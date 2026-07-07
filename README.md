# 🏏 CricFloat

**An always-on-top live cricket score widget for macOS.** A small, translucent
scorecard that floats above all your windows — across every Space and over
fullscreen apps — so you can follow the match without alt-tabbing to a browser.
Shows all current matches (India first), pulling from ESPN's free public
endpoints — **no API key required**.

<!-- Add a screenshot/GIF here once you have one:
![CricFloat](docs/screenshot.png)
-->

```
┌─────────────────────────────────┐
│ ◂ WI v SL                ● LIVE ✕│
│ 2ND TEST · DAY 4            ↻  ↗ │
│ WI            90/1          9.5  │
│ SL            549/9         142  │
│ WI trail by 84                  │
│ [1][4][·][6] | [W][2][4] | [·][6]│
│         BATSMEN & BOWLER  ▾      │
└─────────────────────────────────┘
```

## Features

- **All matches, not just India** — pick any current international or domestic
  match from a themed dropdown (grouped LIVE / FINISHED / UPCOMING, India first).
- **Live detail on demand** — expand to see current batsmen (striker marked `*`),
  the bowler's figures, and the **last 10 deliveries** as color-coded tiles.
- **Genuinely live** — polls every 10s while a match is on, with aggressive
  anti-staleness so a wicket never flickers away.
- **Menu-bar item** — glance at the score up top (`🏏 ENG 158/4`); hide/show the
  widget or quit from its menu.
- **Stays out of your way** — remembers where you dragged it, snaps back if a
  monitor is unplugged, hover tooltips explain every button, and it fades to a
  quiet dark HUD that reads on light or dark desktops.

## Requirements

- **macOS** (native AppKit app via PyObjC).
- **Python 3.10+** — the code uses `X | None` type syntax; Python 3.9 and the
  system `python3` **will not work**. ([pyenv](https://github.com/pyenv/pyenv) is
  an easy way to get 3.10+.)

## Quick start

```bash
git clone https://github.com/anshu03/CricFloat.git
cd CricFloat

python3.10 -m venv .venv && source .venv/bin/activate   # recommended
pip install -r requirements.txt

python demo_overlay.py
```

The widget appears top-right and starts fetching. Quit from the menu bar (🏏), or
`Ctrl-C` in the terminal.

## Using the widget

| Action | How |
|--------|-----|
| Switch match | Click `◂ <match name>` (top-left) |
| See batsmen & bowler | Click **BATSMEN & BOWLER ▾** |
| Open on ESPNcricinfo | Click `↗` |
| Refresh now | Click `↻`, or menu bar → *Refresh now* |
| Move the widget | Drag it — the position is remembered |
| Hide / show | `✕` hides it; menu bar (🏏) → *Show widget* brings it back |
| Quit | Menu bar (🏏) → *Quit CricFloat* |

The `✕` **hides** the widget — the menu bar is the app's persistent home.

## Configuration

Settings live in [`cricfloat/config.py`](cricfloat/config.py) and are all
**environment-variable overridable**:

| Env var | Default | Meaning |
|---------|---------|---------|
| `CRICFLOAT_POLL_LIVE` | `10` | Seconds between polls while a match is live |
| `CRICFLOAT_POLL_IDLE` | `300` | Seconds between polls when nothing is live |
| `CRICFLOAT_HTTP_TIMEOUT` | `12` | Per-request network timeout (seconds) |
| `CRICAPI_KEY` | *(empty)* | Optional [CricAPI](https://cricapi.com) key — a fallback source, only used if ESPN is unreachable |

```bash
CRICFLOAT_POLL_LIVE=15 python demo_overlay.py
```

## Project layout

```
cricfloat/
├── config.py          # poll intervals, key, timeouts (env-overridable)
├── service.py         # ScoreService: provider chain, selection, cache
├── app.py             # CricFloatApp + _Poller: wires UI ↔ data, runs the loop
├── providers/         # espn.py (primary) · cricapi.py (fallback) · base.py (models)
├── ui/                # overlay_window · dropdown_panel · menu_bar · render · loader
└── fixtures/          # saved API responses for offline testing

demo_overlay.py        # ← run this: launches the full widget
check_scores.py        # data-layer smoke test (no UI)
```

Want the deeper picture? See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for
the layered design, threading model, and the anti-staleness guards.

## Roadmap

- [x] **Phase 1** — Data layer: provider chain (ESPN + CricAPI), selection, caching.
- [x] **Phase 2** — Floating always-on-top borderless `NSWindow` (PyObjC).
- [x] **Phase 3** — Poll loop → render → window, adaptive interval, background fetches.
- [x] **Phase 4** — Menu-bar toggle/quit ✅, remembered position ✅ · *colors/theming (in progress)*.
- [ ] **Phase 5** — Package as a double-clickable `.app` (py2app) + launch-at-login.

## Contributing

Contributions welcome — see **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** for
the developer guide, offline testing, code conventions, and troubleshooting.

## License

Released under the [MIT License](LICENSE) — free to use, modify, and
redistribute; just keep the copyright notice.

> CricFloat uses ESPN's undocumented public endpoints for personal,
> non-commercial use. Keep poll intervals reasonable. Not affiliated with or
> endorsed by ESPN, ESPNcricinfo, or CricAPI.
