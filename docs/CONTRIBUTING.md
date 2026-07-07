# Contributing to CricFloat

Contributions are very welcome! Please read this and
[ARCHITECTURE.md](ARCHITECTURE.md) first — the ESPN provider has non-obvious
invariants.

## Ground rules

1. Keep changes focused; match the surrounding code style (defensive parsing,
   dumb UI, background-only network).
2. If you touch data parsing, verify against `check_scores.py` and, where
   possible, the fixtures (below).
3. If you touch the UI, include a before/after screenshot in the PR.
4. **Respect the [anti-staleness guards](ARCHITECTURE.md#the-anti-staleness-design)**
   before changing the ESPN provider.

**Status:** the core widget is complete — data layer, floating window, adaptive
polling, menu-bar item, remembered position, and a `.app` build (below) all work.

**Good first issues:** theming / colors (a configurable accent), launch-at-login,
additional data providers, and a real test suite.

## Building the `.app` (release)

CricFloat bundles into a standalone, double-clickable macOS app with
[py2app](https://py2app.readthedocs.io/):

```bash
pip install py2app
python setup.py py2app
```

The app lands at **`dist/CricFloat.app`** — double-click to run, or drag it to
`/Applications`. It's a menu-bar accessory (`LSUIElement`), so there's no Dock
icon; look for the 🏏 in the menu bar.

**To cut a release:** zip the app and attach it to a [GitHub Release](https://github.com/anshu03/CricFloat/releases)
(that's the standard way to distribute a Mac app — GitHub Packages is for
dependency registries, not downloadable apps):

```bash
cd dist && ditto -c -k --keepParent CricFloat.app CricFloat.zip
```

> **Note on unsigned apps:** the build isn't code-signed or notarized, so on
> first launch macOS Gatekeeper will warn. Users right-click the app → **Open**,
> or run `xattr -dr com.apple.quarantine CricFloat.app`. Signing/notarization
> (needs an Apple Developer account) is a future improvement.

## Running the data layer without the UI

`check_scores.py` exercises the full provider chain and prints results — great
for verifying data parsing without launching the window:

```bash
python check_scores.py          # full ScoreService chain, once
python check_scores.py --espn   # ESPN provider only
python check_scores.py --loop   # poll continuously, like the real widget
```

## Offline testing with fixtures

`cricfloat/fixtures/` contains a real captured ESPN scorepanel response (a live
women's T20 World Cup run chase), useful for parsing tests when no suitable live
match exists. It deliberately exercises the trickiest cases (linescore mirror
entries, an embedded chase target, a women's-international class id):

```python
from cricfloat.fixtures import load_sample
matches = load_sample()   # parses through the real provider, offline
```

## Verifying UI changes

The widget renders to an off-screen bitmap, so you can screenshot it
programmatically without a display session — handy for checking layout changes.
See the render-to-PNG pattern (`cacheDisplayInRect_toBitmapImageRep_`). A crash
leaves a report in `~/Library/Logs/DiagnosticReports/python*.ips`.

## Code conventions

- **Keep the UI dumb.** Formatting decisions belong in `render.py` (which returns
  a `CardView`); `overlay_window.py` should only *lay out* what it's given.
- **PyObjC gotchas.** On an `NSObject` subclass, every method is treated as an
  Objective-C selector — helper methods with multiple positional args must be
  module-level functions (see `menu_bar.py`'s `_menu_item`) or PyObjC raises a
  `BadPrototypeError`. Keep plain-Python classes (`CricFloatApp`) separate from
  `NSObject` trampolines (`_Poller`).
- **Never block the main thread on the network.** Fetches run on background
  threads; only `current()` (a cache read) may be called on the main thread.

## Troubleshooting

**`ModuleNotFoundError: No module named 'Cocoa'`** — PyObjC isn't installed (or
you're not in the venv where it is). Run `pip install -r requirements.txt` with
Python 3.10+ active.

**`TypeError` about `str | None` / syntax errors on startup** — you're running
Python 3.9 or the system `python3`. CricFloat needs **3.10+** (`python --version`).

**The widget doesn't appear** — it opens top-right by default. If you'd
previously dragged it to a display that's no longer connected, it should
auto-rescue on the next screen change, or you can clear the saved position:
```bash
defaults delete <your-app-domain> CricFloatWindowOriginX 2>/dev/null
defaults delete <your-app-domain> CricFloatWindowOriginY 2>/dev/null
```
(Run as a plain script, the domain is typically your Python binary; once packaged
as a `.app` it's the bundle id.)

**The score looks a little behind ESPNcricinfo.com** — expected; ESPN's public
API lags their website's real-time (blocked) endpoint. See the caveat in
[ARCHITECTURE.md](ARCHITECTURE.md#the-anti-staleness-design).

**No matches showing** — there may genuinely be no live cricket right now. Run
`python check_scores.py` to confirm the data layer sees matches.
