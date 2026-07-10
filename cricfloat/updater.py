"""Self-update from GitHub Releases.

Checks the repo's latest release, and — when running as a packaged .app — can
download the new build and swap the running app in place, then relaunch.

Flow (all the risky bits are isolated here):
  1. check_for_update()  -> queries GitHub's releases/latest, compares versions.
  2. download_update()   -> downloads the release's CricFloat.zip to a temp dir.
  3. install_and_relaunch() -> unzips, strips the Gatekeeper quarantine flag, and
     hands off to a DETACHED shell script that waits for this app to quit,
     replaces the .app bundle, and relaunches it. (An app can't overwrite itself
     while running, so the swap must happen from an outside process.)

Because the app is unsigned, the downloaded build would otherwise be
re-quarantined by macOS; the installer strips that flag so the updated app opens
without the Gatekeeper prompt again.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import tempfile
from dataclasses import dataclass

import Cocoa
import httpx

from . import __version__

# GitHub repo to check. Uses the public API (no token needed for public repos).
GITHUB_OWNER = "anshu03"
GITHUB_REPO = "CricFloat"
_LATEST_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_ASSET_NAME = "CricFloat.zip"
_TIMEOUT = 20.0


@dataclass
class Release:
    version: str          # normalized, e.g. "1.2.0"
    tag: str              # raw tag, e.g. "v1.2.0"
    notes: str            # release body (markdown)
    asset_url: str        # browser download URL for CricFloat.zip
    html_url: str         # the release page (fallback if no asset)


# ---- version helpers -------------------------------------------------------

def current_version() -> str:
    """The running app's version: the bundle's CFBundleShortVersionString when
    packaged, else the package __version__ (dev / script mode)."""
    info = Cocoa.NSBundle.mainBundle().infoDictionary() or {}
    return info.get("CFBundleShortVersionString") or __version__


def app_bundle_path() -> str | None:
    """Absolute path to the running .app bundle, or None if run as a script."""
    path = Cocoa.NSBundle.mainBundle().bundlePath()
    return path if path and path.endswith(".app") else None


def _parse(v: str) -> tuple:
    """'v1.2.0' / '1.2' -> (1, 2, 0) for comparison; unknown parts -> 0."""
    v = (v or "").lstrip("vV").split("-")[0].split("+")[0]
    parts = []
    for chunk in v.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(candidate: str, current: str) -> bool:
    return _parse(candidate) > _parse(current)


# ---- 1. check --------------------------------------------------------------

def check_for_update() -> Release | None:
    """Return a Release if the latest GitHub release is newer than the running
    version; None if up to date or the check failed. Runs on a background thread
    (network) — never call from the main thread."""
    try:
        resp = httpx.get(_LATEST_URL, timeout=_TIMEOUT,
                         headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    if not tag or not is_newer(tag, current_version()):
        return None
    asset_url = ""
    for asset in data.get("assets", []) or []:
        if asset.get("name") == _ASSET_NAME:
            asset_url = asset.get("browser_download_url", "")
            break
    return Release(
        version=tag.lstrip("vV"),
        tag=tag,
        notes=data.get("body", "") or "",
        asset_url=asset_url,
        html_url=data.get("html_url", ""),
    )


# ---- 2. download -----------------------------------------------------------

def download_update(release: Release) -> str | None:
    """Download the release's CricFloat.zip to a temp file; return its path (or
    None on failure). Background thread only."""
    if not release.asset_url:
        return None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="cricfloat-update-")
        zip_path = os.path.join(tmp_dir, _ASSET_NAME)
        with httpx.stream("GET", release.asset_url, timeout=_TIMEOUT,
                          follow_redirects=True) as r:
            r.raise_for_status()
            with open(zip_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
        return zip_path
    except Exception:
        return None


# ---- 3. install + relaunch -------------------------------------------------

def install_and_relaunch(zip_path: str) -> bool:
    """Unzip the update, de-quarantine it, and launch a detached script that
    waits for this app to quit, swaps the bundle, and relaunches. Returns True
    if the handoff started (the caller should then quit the app).

    Only works when running from a real .app bundle."""
    bundle = app_bundle_path()
    if not bundle or not os.path.exists(zip_path):
        return False

    work = os.path.dirname(zip_path)
    extract_dir = os.path.join(work, "extracted")
    try:
        os.makedirs(extract_dir, exist_ok=True)
        # ditto preserves the .app's structure/metadata better than unzip.
        subprocess.run(["ditto", "-x", "-k", zip_path, extract_dir],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        return False

    new_app = os.path.join(extract_dir, "CricFloat.app")
    if not os.path.isdir(new_app):
        return False

    # Strip the "downloaded from the internet" quarantine so the updated app
    # opens without the Gatekeeper prompt (the app is unsigned).
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", new_app],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pid = os.getpid()
    parent = os.path.dirname(bundle.rstrip("/"))  # where the .app lives
    log = os.path.join(work, "swap.log")
    script = os.path.join(work, "swap.sh")
    # Wait for THIS process to exit, then atomically replace the bundle and
    # relaunch. The new app is moved to a sibling of the old bundle first, so the
    # final temp-dir cleanup can't race the copy. Every step is logged.
    with open(script, "w") as f:
        f.write(f"""#!/bin/bash
exec >>{_q(log)} 2>&1
echo "swap: waiting for pid {pid} to exit"
for i in $(seq 1 60); do
    kill -0 {pid} 2>/dev/null || break
    sleep 0.5
done
echo "swap: app exited; staging new bundle next to the old one"
mkdir -p {_q(parent)}
STAGED={_q(parent)}/.CricFloat.new
rm -rf "$STAGED"
ditto {_q(new_app)} "$STAGED" || {{ echo "swap: ditto stage FAILED"; exit 1; }}
echo "swap: swapping in place"
rm -rf {_q(bundle)}
mv "$STAGED" {_q(bundle)} || {{ echo "swap: mv FAILED"; exit 1; }}
xattr -dr com.apple.quarantine {_q(bundle)} 2>/dev/null
echo "swap: relaunching"
open {_q(bundle)}
echo "swap: done; cleaning up"
rm -rf {_q(work)}
""")
    os.chmod(script, 0o755)
    # Detach so it outlives this app when we quit.
    subprocess.Popen(["/bin/bash", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return True


def _q(path: str) -> str:
    """Shell-quote a path for the swap script."""
    return "'" + path.replace("'", "'\\''") + "'"
