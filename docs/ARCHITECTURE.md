# Architecture

How CricFloat is put together, and the non-obvious design decisions behind it.
Read this before extending the ESPN provider or the refresh loop.

## Three layers

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
result is marshaled back to the main thread to update the window.

> The timer and the main-thread callbacks are registered in
> **`NSRunLoopCommonModes`**, not the default mode. Opening the menu-bar menu
> puts the run loop into event-tracking mode, and default-mode timers/selectors
> pause there — which would freeze the menu-bar score and swallow a menu
> "Refresh now" while the menu is open. Use the common-modes variants
> (`addTimer_forMode_`, `performSelectorOnMainThread_..._modes_`) if you touch
> this code.

**Hidden vs. visible.** While the widget is hidden, the poll fetches **only the
score** (for the menu bar) and skips the heavier per-match `summary`/`playbyplay`
calls. So `_players_entry` is stale while hidden — `render` therefore applies the
summary-sourced score/players **only when visible**, and lets the fresh
scorepanel score flow straight to the menu bar otherwise.

**Rendering.** `render.py` turns a `MatchScore` (+ optional `LivePlayers`) into a
plain `CardView` — pre-formatted team rows, summary, chip, balls, and detail
lines — so `overlay_window.py` stays a "dumb" view that just lays out the card.

## Threading & safety

A routine poll and a "fetch now" (after you switch matches) can overlap, so:

- Per-match detail is published as a **single atomic `(match_id, players)`
  tuple**, so a render never pairs one match's players with another's id.
- `ScoreService.refresh()` runs its network fetch **outside** its lock, so the
  main-thread `current()` (a cache read used to decide whether to show a spinner)
  never blocks on a slow request.
- The ESPN provider serializes its per-match cache bookkeeping with a lock and
  prunes entries for matches that leave the feed (bounded memory).

## Data sources

CricFloat reads from three **free, public, undocumented** ESPN endpoints:

| Endpoint | Provides |
|----------|----------|
| `.../cricket/scorepanel` | All current matches + scores (the dropdown & score rows) |
| `.../cricket/{league}/summary?event={id}` | Batsmen, bowler, **and** the authoritative score for the selected match |
| `.../cricket/{league}/playbyplay?event={id}` | Ball-by-ball commentary (the last-10-balls strip) |

## The anti-staleness design

Because these endpoints are undocumented and update at slightly different rates,
a lot of care went into never showing **stale or inconsistent** data. Understand
these guards before touching the ESPN provider:

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

## Key files

| File | What it does |
|------|--------------|
| [`app.py`](../cricfloat/app.py) | Entry point logic — `CricFloatApp` and the `_Poller` refresh loop. Start here to understand control flow. |
| [`providers/espn.py`](../cricfloat/providers/espn.py) | Where the ESPN JSON is parsed and where all the anti-staleness guards live. The most subtle file. |
| [`ui/overlay_window.py`](../cricfloat/ui/overlay_window.py) | The widget itself: layout, dragging, hiding, tooltips, position memory, screen-rescue. |
| [`render.py`](../cricfloat/ui/render.py) | Pure formatting — easiest place to tweak how things are displayed. |
| [`service.py`](../cricfloat/service.py) | Provider chain + which match is shown + staleness flagging. |
