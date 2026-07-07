# 🏏 CricFloat

**An always-on-top live cricket score widget for macOS.** A small, translucent
scorecard that floats above all your windows — across every Space and over
fullscreen apps — so you can keep an eye on the match without alt-tabbing to a
browser. Built for cricket fans, with a soft spot for following India.

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

- **All matches, not just India** — pick any current international or domestic
  match from a dropdown; India matches are surfaced first.
- **Live batsmen, bowler, and the last 10 balls** — expandable on demand.
- **Genuinely live** — polls every 10 seconds while a match is on, with
  aggressive anti-staleness so a wicket never flickers away.
- **Stays out of your way** — a menu-bar item lets you hide/show the widget or
  read the score at a glance; the widget remembers where you dragged it.

CricFloat pulls from ESPN's free public cricket endpoints — **no API key
required** to get started.

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Using the widget](#using-the-widget)
- [Configuration](#configuration)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Data sources & the anti-staleness design](#data-sources--the-anti-staleness-design)
- [Developer guide](#developer-guide)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [FAQ](#faq)
- [License](#license)

---

## Features

**Score & match**
- Floating, borderless, translucent HUD panel — always on top, on every Space,
  and over fullscreen apps.
- A **dark scrim** keeps text readable on light *or* dark desktops.
- **All current matches** in a themed dropdown, grouped **LIVE / FINISHED /
  UPCOMING**, India first (🇮🇳 flag), scrollable when the list is long.
- State-aware **summary line**: chase equation (`WI need 84 · target 633`),
  "batting first · overs", or a Test trail/lead. Rain/bad-light interruptions
  show as a second line (e.g. *"Match delayed by rain"*).
- Test matches show the multi-innings aggregate (`549/9d & 3/1`) and the current
  day (`2ND TEST · DAY 4`); limited-overs show the single innings with overs.
- The **batting team** is highlighted; the non-batting team is dimmed so your
  eye lands on the live innings.

**Live detail (expandable)**
- Current **batsmen** with runs/balls (striker marked `*`) and the current
  **bowler**'s figures, from ESPN's per-match `summary` endpoint.
- The **last 10 deliveries** as colored tiles — dot (gray), 1–3 (blue), four
  (green), six (purple), wicket (red), extras like `wd`/`nb` (amber) — with a
  divider at each over boundary.
- Toggle the detail open/closed with the **BATSMEN & BOWLER ▾** section button.

**Menu bar**
- A 🏏 status-bar item showing the **live score at a glance** (e.g. `🏏 ENG 158/4`).
- **Show / Hide** the widget, **Refresh now**, and **Quit** from its menu.
- When hidden, CricFloat keeps the menu-bar score updated but skips the heavier
  per-match fetches (saving ~¾ of the network traffic).

**Quality-of-life**
- **Remembers its position** — reopens where you last dragged it.
- **Screen-change safe** — if you unplug a monitor or change resolution and the
  widget would be stranded off-screen, it snaps back into view.
- **Hover tooltips** above the widget explain every button.
- **Click-to-open** the full match on ESPNcricinfo (`↗` button).
- A **loading spinner** only on first load and after switching matches — routine
  refreshes update silently.

---

## Requirements

- **macOS** (uses AppKit via PyObjC — this is a native macOS app).
- **Python 3.10 or newer.** The code uses `X | None` type syntax; Python 3.9 and
  the system `python3` **will not work**.
- Two Python packages (installed below): [`httpx`](https://www.python-httpx.org/)
  and [`pyobjc-framework-Cocoa`](https://pyobjc.readthedocs.io/).

> **Tip:** Use a version manager like [pyenv](https://github.com/pyenv/pyenv) to
> get Python 3.10+ without touching your system Python.

---

## Quick start

```bash
# 1. Clone
git clone <your-repo-url> cricfloat
cd cricfloat

# 2. (Recommended) create a virtual environment with Python 3.10+
python3.10 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run it
python demo_overlay.py
```

The widget appears in the top-right of your screen and starts fetching. Press
`Ctrl-C` in the terminal (or use the menu-bar **Quit**) to stop it.

That's it — **no API key needed** for the default ESPN data source.

---

## Using the widget

| Action | How |
|--------|-----|
| **Switch match** | Click `◂ <match name>` (top-left) to open the dropdown |
| **See batsmen & bowler** | Click **BATSMEN & BOWLER ▾** to expand |
| **Open on ESPNcricinfo** | Click the `↗` button (opens in Chrome) |
| **Refresh now** | Click the `↻` button, or menu bar → *Refresh now* |
| **Move the widget** | Drag it anywhere — the position is remembered |
| **Hide the widget** | Click `✕`, or menu bar → *Hide widget* |
| **Show it again** | Menu bar (🏏) → *Show widget* |
| **Quit** | Menu bar (🏏) → *Quit CricFloat* |

The `✕` **hides** the widget (it doesn't quit) — the menu bar is the app's
persistent home. Every button also shows a tooltip above the widget on hover.

---

## Configuration

All settings live in [`cricfloat/config.py`](cricfloat/config.py) and are
**environment-variable overridable** — no code edits needed.

| Env var | Default | Meaning |
|---------|---------|---------|
| `CRICAPI_KEY` | *(empty)* | Enables the CricAPI fallback provider (see below) |
| `CRICFLOAT_POLL_LIVE` | `10` | Seconds between polls while a match is live |
| `CRICFLOAT_POLL_IDLE` | `300` | Seconds between polls when nothing is live |
| `CRICFLOAT_HTTP_TIMEOUT` | `12` | Per-request network timeout (seconds) |

Example:

```bash
# Poll every 15s instead of 10, and enable the fallback provider
CRICFLOAT_POLL_LIVE=15 CRICAPI_KEY="your-free-key" python demo_overlay.py
```

### Optional: the CricAPI fallback

CricFloat uses ESPN as its primary source (free, no key). If you want a backup
source for the rare case ESPN is unreachable, get a free key from
[cricapi.com](https://cricapi.com) and set `CRICAPI_KEY`. It's only hit when
ESPN fails, to stay inside the free ~100-requests/day budget. **This is entirely
optional** — the app works fully without it.

The remembered window position is stored in macOS user defaults under the keys
`CricFloatWindowOriginX` / `CricFloatWindowOriginY`.

---

## How it works

CricFloat has three layers, cleanly separated:

```
┌────────────────────────────────────────────────────────────┐
│  UI  (cricfloat/ui/)                                        │
│  overlay_window.py · dropdown_panel.py · menu_bar.py ·      │
│  render.py · loader.py                                      │
│         ▲ set_card(CardView)          │ callbacks           │
│         │                             ▼                     │
├────────────────────────────────────────────────────────────┤
│  App  (cricfloat/app.py)                                    │
│  CricFloatApp wires UI ↔ data; _Poller runs the NSTimer     │
│  loop and marshals background fetches to the main thread    │
│         ▲ ServiceResult / LivePlayers  │ refresh()          │
│         │                              ▼                     │
├────────────────────────────────────────────────────────────┤
│  Data  (cricfloat/service.py + cricfloat/providers/)        │
│  ScoreService picks the match; ESPN/CricAPI providers fetch │
└────────────────────────────────────────────────────────────┘
```

**The refresh loop.** A repeating `NSTimer` (owned by a small `_Poller` NSObject)
fires on an adaptive interval — 10s while any match is live, 300s when idle. Each
tick spawns a **background thread** so the network call never blocks the UI; the
result is marshaled back to the main thread to update the window. The interval,
spinner, and per-match detail fetch are all handled here.

**Threading & safety.** Because a routine poll and a "fetch now" (after you
switch matches) can overlap, the code is careful:
- Per-match detail is published as a **single atomic `(match_id, players)`
  tuple**, so a render never pairs one match's players with another's id.
- `ScoreService.refresh()` runs its network fetch **outside** its lock, so the
  main-thread `current()` (a cache read used to decide whether to show a spinner)
  never blocks on a slow request.
- The ESPN provider serializes its per-match cache bookkeeping with a lock and
  prunes entries for matches that leave the feed (bounded memory).

**Rendering.** `render.py` turns a `MatchScore` (+ optional `LivePlayers`) into a
plain `CardView` — pre-formatted team rows, summary, chip, balls, and detail
lines — so `overlay_window.py` stays a "dumb" view that just lays out the card.

---

## Project layout

```
cricfloat/
├── config.py                 # poll intervals, CricAPI key, timeouts (env-overridable)
├── service.py                # ScoreService: provider chain, selection, cache, staleness
├── app.py                    # CricFloatApp + _Poller: wires UI ↔ data, runs the loop
├── providers/
│   ├── base.py               # MatchScore / InningsLine / LivePlayers models + Provider ABC
│   ├── espn.py               # primary provider (site.api.espn.com) + anti-staleness guards
│   └── cricapi.py            # fallback provider (cricapi.com), optional
├── ui/
│   ├── overlay_window.py     # the floating always-on-top NSWindow (the bulk of the UI)
│   ├── dropdown_panel.py     # the themed match-picker dropdown
│   ├── menu_bar.py           # the 🏏 NSStatusItem menu-bar item
│   ├── render.py             # MatchScore -> CardView (display formatting)
│   └── loader.py             # the loading spinner
└── fixtures/                 # saved sample API responses for offline testing

demo_overlay.py               # ← run this: launches the full widget
check_scores.py               # data-layer smoke test (no UI)
requirements.txt              # httpx + pyobjc-framework-Cocoa
```

### Key files at a glance

| File | What it does |
|------|--------------|
| [`app.py`](cricfloat/app.py) | Entry point logic — `CricFloatApp` and the `_Poller` refresh loop. Start here to understand control flow. |
| [`providers/espn.py`](cricfloat/providers/espn.py) | Where the ESPN JSON is parsed and where all the anti-staleness guards live. The most subtle file. |
| [`ui/overlay_window.py`](cricfloat/ui/overlay_window.py) | The widget itself: layout, dragging, hiding, tooltips, position memory, screen-rescue. |
| [`render.py`](cricfloat/ui/render.py) | Pure formatting — easiest place to tweak how things are displayed. |
| [`service.py`](cricfloat/service.py) | Provider chain + which match is shown + staleness flagging. |

---

## Data sources & the anti-staleness design

CricFloat reads from three **free, public, undocumented** ESPN endpoints:

| Endpoint | Provides |
|----------|----------|
| `.../cricket/scorepanel` | All current matches + scores (the dropdown & score rows) |
| `.../cricket/{league}/summary?event={id}` | Batsmen, bowler, **and** the authoritative score for the selected match |
| `.../cricket/{league}/playbyplay?event={id}` | Ball-by-ball commentary (the last-10-balls strip) |

Because these are undocumented and update at slightly different rates, a lot of
care went into never showing **stale or inconsistent** data. If you're extending
the ESPN provider, understand these guards first:

- **Cache-buster + `no-cache` headers** on every request bypass ESPN's ~10s CDN
  cache, so we always get their freshest snapshot.
- **Single source of truth for the selected match** — the score, batsmen, and
  bowler all come from the *same* `summary` response, so they can never disagree
  with each other.
- **Monotonic ball guard** — each delivery has a match-wide `sequence` integer.
  A snapshot whose newest ball is *older* than what's shown is rejected, so a
  just-shown wicket can't vanish on the next poll.
- **Score-regression guard** — runs/wickets/overs are clamped so a stale
  scorepanel can't make the score go backwards within an innings (keyed by ESPN's
  innings `period`, so a genuine new innings still restarts cleanly).
- **First-load vs. refresh** — the last-good cache is only served *after* a
  successful fetch, so a failed first load shows an empty widget rather than
  fabricated data.

> ⚠️ **Caveat:** ESPN's public `site.api.espn.com` trails the ESPNcricinfo
> website (which uses a real-time endpoint that's Cloudflare-blocked for
> non-browser clients). CricFloat closes the *cacheable* part of that gap, but a
> small residual lag is ESPN's own and can't be fixed client-side.

---

## Developer guide

### Run the data layer without the UI

`check_scores.py` exercises the full provider chain and prints results — great
for verifying data parsing without launching the window:

```bash
python check_scores.py          # full ScoreService chain, once
python check_scores.py --espn   # ESPN provider only
python check_scores.py --loop   # poll continuously, like the real widget
```

### Offline testing with fixtures

`cricfloat/fixtures/` contains a real captured ESPN scorepanel response (a live
women's T20 World Cup run chase), useful for parsing tests when no suitable live
match exists. It deliberately exercises the trickiest cases (linescore mirror
entries, an embedded chase target, a women's-international class id):

```python
from cricfloat.fixtures import load_sample
matches = load_sample()   # parses through the real provider, offline
```

### Verifying UI changes

The widget renders to an off-screen bitmap, so you can screenshot it
programmatically without a display session — handy for checking layout changes.
See the render-to-PNG pattern used throughout development
(`cacheDisplayInRect_toBitmapImageRep_`). A crash leaves a report in
`~/Library/Logs/DiagnosticReports/python*.ips`.

### Code conventions

- **Keep the UI dumb.** Formatting decisions belong in `render.py` (which returns
  a `CardView`); `overlay_window.py` should only *lay out* what it's given.
- **PyObjC gotchas.** On an `NSObject` subclass, every method is treated as an
  Objective-C selector — helper methods with multiple positional args must be
  module-level functions (see `menu_bar.py`'s `_menu_item`) or PyObjC raises a
  `BadPrototypeError`. Keep plain-Python classes (`CricFloatApp`) separate from
  `NSObject` trampolines (`_Poller`).
- **Never block the main thread on the network.** Fetches run on background
  threads; only `current()` (a cache read) may be called on the main thread.
- **Respect the anti-staleness guards** — see the section above before touching
  the ESPN provider.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'Cocoa'`**
PyObjC isn't installed (or you're not in the venv where it is). Run
`pip install -r requirements.txt` with Python 3.10+ active.

**`TypeError` about `str | None` / syntax errors on startup**
You're running Python 3.9 or the system `python3`. CricFloat needs **3.10+**.
Check with `python --version`.

**The widget doesn't appear**
It opens top-right by default. If you'd previously dragged it to a display that's
no longer connected, it should auto-rescue on the next screen change — or delete
the saved position with:
```bash
defaults delete <your-app-domain> CricFloatWindowOriginX 2>/dev/null
defaults delete <your-app-domain> CricFloatWindowOriginY 2>/dev/null
```
(When run as a plain script the domain is typically your Python binary; once
packaged as a `.app` it's the bundle id.)

**The score looks a little behind ESPNcricinfo.com**
Expected — see the caveat under [anti-staleness](#data-sources--the-anti-staleness-design).
ESPN's public API lags their website's real-time (blocked) endpoint.

**No matches showing**
There may genuinely be no live/current cricket right now. Run
`python check_scores.py` to confirm the data layer sees matches.

---

## Roadmap

- [x] **Phase 1** — Data layer: provider chain (ESPN + CricAPI), match selection, caching.
- [x] **Phase 2** — Floating always-on-top borderless `NSWindow` (PyObjC).
- [x] **Phase 3** — Poll loop → render → window, adaptive interval, background fetches.
- [x] **Phase 4** — Menu-bar toggle/quit ✅, remembered position ✅ · *colors/theming (in progress)*.
- [ ] **Phase 5** — Package as a double-clickable `.app` (py2app) + optional launch-at-login.

Ideas welcome — see [Contributing](#contributing).

---

## Contributing

Contributions are very welcome! A few pointers:

1. **Read the [Developer guide](#developer-guide)** and the
   [anti-staleness section](#data-sources--the-anti-staleness-design) first —
   the ESPN provider has non-obvious invariants.
2. Keep changes focused; match the surrounding code style (defensive parsing,
   dumb UI, background-only network).
3. If you touch data parsing, verify against `check_scores.py` and, where
   possible, the fixtures.
4. If you touch the UI, include a before/after screenshot in the PR.

Good first issues: theming/colors (Phase 4), py2app packaging (Phase 5),
additional data providers, and a real test suite.

---

## FAQ

**Is this only for India matches?**
No — it shows all current matches. India matches are just sorted first and
auto-selected by default. Pick any match from the dropdown.

**Does it need an API key?**
No. ESPN's public endpoints need no key. The CricAPI fallback is optional.

**Does it work on Windows/Linux?**
No — it's a native macOS app (AppKit/PyObjC). The *data layer*
(`providers/`, `service.py`) is pure Python and portable, but the UI is macOS-only.

**Why does the `✕` not quit the app?**
It hides the widget; the menu bar is the persistent home. Quit from the 🏏 menu.
This lets you tuck the widget away during a screen-share and bring it back.

**How much network does it use?**
While a match is live and the widget is shown, ~4 small requests every 10s. When
hidden it drops to ~1 request (score only). Idle (nothing live): one request
every 5 minutes.

**Is my data private?**
CricFloat talks only to ESPN (and CricAPI if you enable it). No analytics, no
accounts, nothing stored except your window position.

---

## License

_No license file is included yet._ Before open-sourcing, add a `LICENSE` (MIT is
a common, permissive choice for projects like this) and update this section.

> **Note:** CricFloat uses ESPN's undocumented public endpoints for personal,
> non-commercial use. Respect their service — keep poll intervals reasonable and
> don't hammer the API. This project is not affiliated with or endorsed by ESPN,
> ESPNcricinfo, or CricAPI.
