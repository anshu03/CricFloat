# 🏏 CricFloat

A tiny always-on-top **live cricket score** widget for macOS. It floats above your
windows so you can follow the match without switching to a browser — showing all
current matches (India first), with live batsmen, bowler, and the last 10 balls.

Free ESPN data, **no API key needed**.

> 📸 _Screenshot coming soon — drop an image at `docs/screenshot.png` and
> replace this line with `![CricFloat](docs/screenshot.png)`._

## Features

- 📊 **All matches** — pick any current match from a dropdown; India first.
- 🏏 **Live detail** — batsmen, bowler, and the last 10 balls, on demand.
- 🔔 **Menu-bar score** — glance at the score even with the widget hidden.
- ⚡ **Genuinely live** — refreshes every 10s while a match is on.

## Install

### Option A — Download the app (easiest)

1. Grab **CricFloat.zip** from the [latest release](https://github.com/anshu03/CricFloat/releases), unzip it, and drag **CricFloat.app** to your Applications folder.
2. **First launch only — get past macOS Gatekeeper** (the app is free & open-source but not notarized by Apple, so macOS asks you to confirm):

   > **"Apple could not verify CricFloat is free of malware…"** — this is expected. To open it:
   >
   > 1. Double-click the app once (it gets blocked — that's fine).
   > 2. Open **System Settings → Privacy & Security**.
   > 3. Scroll down to the message about **CricFloat** and click **Open Anyway**, then confirm with Touch ID / password.
   >
   > _Terminal alternative:_ `xattr -dr com.apple.quarantine /Applications/CricFloat.app`

3. After that one-time step, it opens normally. Look for the 🏏 in your menu bar.

### Option B — Run from source

Needs **macOS** and **Python 3.10+**.

```bash
git clone https://github.com/anshu03/CricFloat.git
cd CricFloat
pip install -r requirements.txt
python demo_overlay.py
```

Prefer to build the `.app` yourself? `pip install py2app && python setup.py
py2app` produces `dist/CricFloat.app`. (See
[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md#building-the-app-release) for details.)

## Usage

| Action | How |
|--------|-----|
| Switch match | Click the match name (top-left) |
| Show batsmen & bowler | Click **BATSMEN & BOWLER ▾** |
| Open on ESPNcricinfo | Click `↗` |
| Refresh now | Click `↻` |
| Move it | Drag it — the position is remembered |
| Resize it | 🏏 menu → *Size* → Default / Large (remembered) |
| Hide / show | `✕` hides it; use the 🏏 menu to bring it back |
| Quit | 🏏 menu → *Quit* |

## Configuration

Optional environment variables (defaults shown):

```bash
CRICFLOAT_POLL_LIVE=10    # seconds between refreshes while live
CRICFLOAT_POLL_IDLE=300   # seconds between refreshes when nothing is live
CRICFLOAT_SIZE=default    # initial widget size: default | large
CRICAPI_KEY=              # optional cricapi.com key, used only if ESPN is down
```

## Contributing

PRs welcome! See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for how it works
and **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** to get started (including how
to build the `.app`). Up next: theming and launch-at-login.

## License

[MIT](LICENSE). Uses ESPN's public endpoints for personal, non-commercial use;
not affiliated with ESPN, ESPNcricinfo, or CricAPI.
