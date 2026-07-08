"""py2app build script — bundles CricFloat into a double-clickable macOS .app.

Build a standalone app:

    pip install py2app
    python setup.py py2app

The finished app is at  dist/CricFloat.app  — double-click to run, or drag it to
/Applications. See docs/CONTRIBUTING.md for the full release flow.
"""

from setuptools import setup

APP = ["main.py"]

# Bundled Info.plist keys.
PLIST = {
    "CFBundleName": "CricFloat",
    "CFBundleDisplayName": "CricFloat",
    "CFBundleIdentifier": "com.cricfloat.app",
    "CFBundleVersion": "1.0.0",
    "CFBundleShortVersionString": "1.0.0",
    # Accessory app: no Dock icon, menu-bar only (matches ActivationPolicyAccessory).
    "LSUIElement": True,
    # Talks to ESPN over HTTPS; no ATS exceptions needed, but be explicit.
    "NSHumanReadableCopyright": "MIT License",
}

OPTIONS = {
    # Bundle the whole package so all submodules ship.
    "packages": ["cricfloat"],
    # PyObjC frameworks CricFloat imports.
    "includes": ["Cocoa", "objc", "httpx"],
    "plist": PLIST,
    # Smaller, cleaner bundle.
    "optimize": 2,
    # App icon (cricket ball on green). Regenerate with tools/make_icon.py.
    "iconfile": "docs/CricFloat.icns",
}

setup(
    app=APP,
    name="CricFloat",
    version="1.0.0",
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
