"""CricFloatApp — wires the overlay to the ScoreService and auto-refreshes.

Interactions:
  * click body  -> open the match page in Chrome
  * dropdown    -> pin a different match, refresh immediately
  * close       -> quit the app

Auto-refresh (Phase 3): a repeating NSTimer (owned by the small `_Poller`
NSObject trampoline) kicks off a background fetch; the network call runs off
the main thread so the UI never stutters, and the result is pushed back to the
main thread to update the window. The interval adapts — fast while a match is
live, slow when idle.
"""

from __future__ import annotations

import subprocess
import threading

import Cocoa
import objc

from . import config
from .service import ScoreService, ServiceResult
from .ui.menu_bar import MenuBar
from .ui.overlay_window import OverlayWindow
from .ui.render import render_card


def open_in_chrome(url: str) -> None:
    if not url:
        return
    try:
        subprocess.Popen(["open", "-a", "Google Chrome", url])
    except Exception:
        subprocess.Popen(["open", url])


def _menu_bar_text(match) -> str:
    """A compact glanceable score for the menu-bar item, e.g. 'WI 90/1'. Empty
    string => the menu bar falls back to its 🏏 icon (no match / not live)."""
    if match is None or not match.is_live:
        return ""
    batting = next((i for i in match.innings if i.is_batting), None)
    if batting is None or batting.runs is None:
        return ""
    w = "" if batting.wickets is None or batting.wickets >= 10 else f"/{batting.wickets}"
    return f"{batting.team} {batting.runs}{w}"


def _marshal(obj, selector, arg):
    """Run `selector` on `obj` on the main thread in COMMON run-loop modes, so the
    UI update fires even while a menu-bar menu is open (event-tracking mode). The
    plain performSelectorOnMainThread uses default mode only, which stalls during
    menu tracking — that's why a hidden widget's score froze and a menu 'Refresh
    now' click was swallowed while the menu was up. Module-level (not a method) so
    PyObjC doesn't treat it as an Objective-C selector."""
    obj.performSelectorOnMainThread_withObject_waitUntilDone_modes_(
        selector, arg, False, [Cocoa.NSRunLoopCommonModes])


class _Poller(Cocoa.NSObject):
    """NSObject trampoline: owns the NSTimer and does main-thread marshalling.

    Kept separate from CricFloatApp so that class can stay a plain Python object
    (PyObjC would otherwise treat every method as an Objective-C selector)."""

    def initWithApp_(self, app):  # noqa: N802
        self = objc.super(_Poller, self).init()
        if self is not None:
            self._app = app
            self._timer = None
            self._fetching = False
        return self

    def start(self):
        self.tick_(None)

    def schedule_(self, interval):  # noqa: N802
        if self._timer is not None:
            self._timer.invalidate()
        # Create the timer and add it to the run loop in COMMON modes (not just
        # the default mode). Otherwise, while the menu-bar menu is open — which
        # puts the run loop into event-tracking mode — a default-mode timer
        # pauses, so the score stops updating and a menu "Refresh now" click can
        # be swallowed until tracking ends.
        self._timer = Cocoa.NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            float(interval), self, "tick:", None, False)
        Cocoa.NSRunLoop.currentRunLoop().addTimer_forMode_(
            self._timer, Cocoa.NSRunLoopCommonModes)

    def tick_(self, timer):  # noqa: N802 — NSTimer selector
        if self._fetching:
            self.schedule_(5.0)
            return
        self._fetching = True
        threading.Thread(target=self._fetch_bg, daemon=True).start()

    def _fetch_bg(self):
        # NOTE: _fetching is cleared in apply_ (main thread). If anything here
        # raises, apply_ never runs and _fetching would stay True forever, wedging
        # all future polls behind the `if self._fetching` guard. So guarantee a
        # main-thread reset+reschedule even on failure.
        try:
            result = self._app.service.refresh()
            # When the widget is HIDDEN, only the score shows (in the menu bar),
            # so skip the extra per-match summary + playbyplay calls (batsmen,
            # bowler, balls). The scorepanel `refresh()` above already has the
            # score. This drops ~3 of the ~4 requests per cycle while hidden.
            if self._app.widget_visible():
                self._app.fetch_players_for(result.match)
            _marshal(self, "apply:", result)
        except Exception:
            _marshal(self, "fetchFailed:", None)

    def fetchFailed_(self, _):  # noqa: N802 — main-thread selector
        # A background fetch blew up. Clear the in-flight flag so polling resumes,
        # drop the spinner, and reschedule the next tick.
        self._fetching = False
        self._app.end_loading()
        self.schedule_(config.POLL_INTERVAL_IDLE)

    def refresh_now(self):
        """Trigger a full fresh fetch immediately (manual refresh button),
        cancelling the pending timer. The regular tick then reschedules."""
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None
        self.tick_(None)

    def fetch_players_now(self):
        """Fetch players for the currently selected match off the main thread,
        then re-render. Used for instant feedback right after a selection."""
        threading.Thread(target=self._players_bg, daemon=True).start()

    def _players_bg(self):
        # The match LIST is already current (the poll refreshes it); we only need
        # the selected match to fetch its players for. Use current() (cached list,
        # no extra list fetch); fetch_players_for does the per-match network call.
        try:
            result = self._app.service.current()
            self._app.fetch_players_for(result.match)
            _marshal(self, "applyPlayers:", result)
        except Exception:
            _marshal(self, "applyPlayersFailed:", None)

    def applyPlayersFailed_(self, _):  # noqa: N802 — main-thread selector
        self._app.end_loading()

    def applyPlayers_(self, result):  # noqa: N802 — main-thread selector
        # Post-selection load finished — hide the spinner (if it was shown).
        self._app.end_loading()
        self._app.render(result)

    def apply_(self, result):  # noqa: N802 — main-thread selector
        self._fetching = False
        # Only the FIRST load hides the spinner; routine refreshes are silent.
        self._app.end_loading()
        self._app.render(result)
        self.schedule_(self._app.service.next_interval(result))

    def stop(self):
        if self._timer is not None:
            self._timer.invalidate()
            self._timer = None


class CricFloatApp:
    def __init__(self) -> None:
        self.service = ScoreService()
        self.overlay = OverlayWindow()
        self.overlay.on_click = self._on_click
        self.overlay.on_select = self._on_select
        self.overlay.on_close = self._quit          # ✕ quits the app
        self.overlay.on_hide = self._on_hide        # – hides to the menu bar
        self.overlay.on_refresh = self._on_refresh
        # Menu-bar item: a persistent home so the widget can be hidden/shown and
        # the app quit even when the floating window is off-screen or hidden.
        self._menu_bar = MenuBar.alloc().initWithCallbacks_({
            "toggle": self._toggle_widget,
            "refresh": self._on_refresh,
            "quit": self._quit,
        })
        self._widget_visible = True
        self._poller = _Poller.alloc().initWithApp_(self)
        # Per-match detail as a SINGLE (match_id, players) tuple, so publishing
        # and reading it is one atomic attribute access. Keeping the id and the
        # players as two separate fields let overlapping fetch threads (on a match
        # switch) interleave and tag one match's players with another's id — which
        # leaked the old match's batsmen/bowler/balls. None = nothing loaded yet.
        self._players_entry = None  # (match_id, LivePlayers) | None
        # True while we're waiting for INITIAL or post-selection data (spinner
        # shown). Routine 25s refreshes do NOT set this, so they update silently.
        self._loading = False

    def begin_loading(self) -> None:
        self._loading = True
        self.overlay.start_loading()

    def end_loading(self) -> None:
        if self._loading:
            self._loading = False
            self.overlay.stop_loading()

    def start(self) -> None:
        """Show the spinner, load everything once, THEN begin polling."""
        self.begin_loading()
        self._poller.start()

    def fetch_players_for(self, match) -> None:
        """Background-thread call: fetch per-match detail (live players+balls, or
        the top scorer for a finished match) for the selected match.

        Two fetch threads can overlap on a match switch (the post-select fetch
        and a regular poll). We do the network call into a LOCAL, then publish it
        with its owning id as ONE tuple assignment to `_players_entry` — a single
        atomic store — so a reader never sees one match's players paired with
        another match's id (which leaked the old match's data after a switch)."""
        if match is None or match.state == "pre":
            self._players_entry = None
            return
        # ESPN is the primary provider; only it exposes the summary endpoint.
        provider = self.service._providers[0]
        try:
            players = provider.fetch_live_players(match)
            self._players_entry = (match.match_id, players)  # atomic publish
        except Exception:
            self._players_entry = None

    def render(self, result: ServiceResult) -> None:
        selected = self.service.selected_id or (
            result.match.match_id if result.match else None)
        self.overlay.set_matches(result.matches, selected)
        # Attach the per-match detail (batsmen/bowler/balls + its summary-sourced
        # score) ONLY when the widget is visible. While hidden we deliberately
        # skip fetching players, so `_players_entry` is stale — overlaying its
        # innings would clobber the FRESH scorepanel score with an old value (and
        # freeze the menu-bar score). Read the entry once (atomic); require it to
        # belong to the shown match so a just-switched match can't leak old data.
        entry = self._players_entry
        players = None
        if (self._widget_visible and entry is not None and result.match is not None
                and entry[0] == result.match.match_id):
            players = entry[1]
            # The summary carries the score too. Use it so the shown score,
            # batsmen and bowler all come from ONE fetch (no scorepanel drift).
            if players.innings:
                result.match.innings = players.innings
        self.overlay.set_card(render_card(result, players))
        self._menu_bar.set_status(_menu_bar_text(result.match))

    # ---- overlay callbacks --------------------------------------------

    def _on_click(self, url: str) -> None:
        open_in_chrome(url)

    def _on_select(self, match_id: str) -> None:
        self.service.select(match_id)
        # Drop the previous match's detail immediately so a stray render can't
        # show it against the newly selected match.
        self._players_entry = None
        # Read the selected match from cache (no network) so the UI thread never
        # blocks on a fetch here; the real fetch runs in the background below.
        result = self.service.current()
        m = result.match
        if m is not None and m.state in ("in", "post"):
            # Live or finished match has extra detail to fetch (players/balls or
            # top scorer). Show ONLY the spinner, fetch in the background, then
            # render everything in one go. No partial/cached data flashes first.
            self.begin_loading()
            self._poller.fetch_players_now()
        else:
            # Upcoming match — nothing extra to wait for; render immediately.
            self.render(result)

    def _on_refresh(self) -> None:
        # Manual refresh: decide whether to show the spinner from the CACHED
        # current match (no blocking network on the UI thread), then kick off the
        # real fresh fetch in the background.
        m = self.service.current().match
        if m is not None and m.state in ("in", "post"):
            self.begin_loading()
        self._poller.refresh_now()

    def _on_hide(self) -> None:
        # The widget's – button hides it to the menu bar; the app keeps running
        # and the score keeps updating up top. Bring it back via the 🏏 menu.
        self._set_widget_visible(False)

    def widget_visible(self) -> bool:
        return self._widget_visible

    def _toggle_widget(self) -> None:
        self._set_widget_visible(not self._widget_visible)

    def _set_widget_visible(self, visible: bool) -> None:
        self._widget_visible = visible
        if visible:
            self.overlay.show()
            # While hidden we skipped fetching balls/batsmen/bowler, so they're
            # stale — pull a fresh full set now (with the spinner) so the widget
            # shows current detail rather than the last-seen-before-hiding one.
            self._players_entry = None
            m = self.service.current().match
            if m is not None and m.state in ("in", "post"):
                self.begin_loading()
                self._poller.fetch_players_now()
        else:
            self.overlay.hide()
        self._menu_bar.set_widget_visible(visible)

    def _quit(self) -> None:
        self._poller.stop()
        Cocoa.NSApp().terminate_(None)
