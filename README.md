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

Needs **macOS** and **Python 3.10+**.

```bash
git clone https://github.com/anshu03/CricFloat.git
cd CricFloat
pip install -r requirements.txt
python demo_overlay.py
```

The widget appears in the top-right and starts fetching. Quit from the 🏏
menu-bar item, or press `Ctrl-C`.

## Usage

| Action | How |
|--------|-----|
| Switch match | Click the match name (top-left) |
| Show batsmen & bowler | Click **BATSMEN & BOWLER ▾** |
| Open on ESPNcricinfo | Click `↗` |
| Refresh now | Click `↻` |
| Move it | Drag it — the position is remembered |
| Hide / show | `✕` hides it; use the 🏏 menu to bring it back |
| Quit | 🏏 menu → *Quit* |

## Configuration

Optional environment variables (defaults shown):

```bash
CRICFLOAT_POLL_LIVE=10    # seconds between refreshes while live
CRICFLOAT_POLL_IDLE=300   # seconds between refreshes when nothing is live
CRICAPI_KEY=              # optional cricapi.com key, used only if ESPN is down
```

## Contributing

PRs welcome! See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for how it works
and **[docs/CONTRIBUTING.md](docs/CONTRIBUTING.md)** to get started. Roadmap: the
core widget is done — up next is theming and packaging as a `.app`.

## License

[MIT](LICENSE). Uses ESPN's public endpoints for personal, non-commercial use;
not affiliated with ESPN, ESPNcricinfo, or CricAPI.
