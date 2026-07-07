"""ScoreService — provider chain, all-matches list, selection, and staleness.

Fetches every current match (ESPN primary, CricAPI fallback), keeps the full
list for the dropdown, and tracks which match the user has selected. If the
user hasn't picked one, it auto-selects the best India match (prefer live).
The last good list is cached, so a transient total failure still shows data
(flagged stale) rather than a blank widget.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from . import config
from .providers import CricAPIProvider, ESPNProvider, MatchScore, Provider


@dataclass
class ServiceResult:
    match: MatchScore | None  # the currently selected match
    matches: list[MatchScore] = field(default_factory=list)  # all, for dropdown
    stale: bool = False  # True when all providers failed (cached value)
    fetched_at: float = 0.0


class ScoreService:
    def __init__(self, providers: list[Provider] | None = None) -> None:
        if providers is None:
            providers = [
                ESPNProvider(timeout=config.HTTP_TIMEOUT),
                CricAPIProvider(config.CRICAPI_KEY, timeout=config.HTTP_TIMEOUT),
            ]
        self._providers = providers
        self._cache: list[MatchScore] = []
        self._cache_at: float = 0.0
        self._selected_id: str | None = None  # user's explicit pick
        # Cache is only served AFTER the first successful fetch. Until then a
        # failure shows an empty widget rather than nothing-yet-cached data —
        # and, by the same flag, we never surface a stale set on the very first
        # frame. Set True the first time any provider returns matches.
        self._had_success: bool = False
        # Serializes overlapping refresh() calls (poll + post-select fetch) so
        # they don't double-hammer the API. NOT held by current(), which reads the
        # cache atomically without blocking on a background network call.
        self._fetch_lock = threading.Lock()

    def select(self, match_id: str | None) -> None:
        """Pin the dropdown selection. None = auto (best India match)."""
        self._selected_id = match_id

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    def current(self) -> ServiceResult:
        """The currently-selected match from the LAST cached list — no network,
        no blocking. For main-thread callers that just need the current
        match/state (e.g. to decide whether to show a spinner). Reads `_cache`
        directly: a list-reference read is atomic in CPython, so it never waits
        on a background refresh's network call.

        NOT flagged stale: the cache is kept current by the poll loop, so this is
        a read of good data, not a failure fallback. Only `refresh()` marks a
        result stale — and only when a live fetch actually failed."""
        return self._result(self._cache, stale=False)

    def refresh(self) -> ServiceResult:
        # The network fetch runs OUTSIDE the lock so a slow call never blocks the
        # main-thread `current()` (which just reads `_cache`). We only lock the
        # brief cache swap. `_fetch_lock` also serializes overlapping refreshes so
        # two poll/post-select threads don't double-hammer the API.
        with self._fetch_lock:
            for provider in self._providers:
                matches = provider.fetch_all()
                if matches:
                    self._cache = matches
                    self._cache_at = time.time()
                    self._had_success = True
                    return self._result(matches, stale=False)

            # Everything failed. Only fall back to the last good list on a REFRESH
            # (i.e. after we've succeeded at least once). On the FIRST load a
            # failure shows an empty widget — never cached data.
            if self._had_success and self._cache:
                return self._result(self._cache, stale=True)
            return self._result([], stale=False)

    def _result(self, matches: list[MatchScore], stale: bool) -> ServiceResult:
        return ServiceResult(
            match=self._pick(matches),
            matches=matches,
            stale=stale,
            fetched_at=self._cache_at,
        )

    def _pick(self, matches: list[MatchScore]) -> MatchScore | None:
        if not matches:
            return None
        if self._selected_id is not None:
            for m in matches:
                if m.match_id == self._selected_id:
                    return m
            # Selected match dropped off the feed — fall back to auto.
        india = [m for m in matches if m.has_india]
        pool = india or matches
        # matches are already sorted live-first; return the top of the pool.
        return pool[0]

    def next_interval(self, result: ServiceResult) -> float:
        # Poll at the LIVE cadence whenever the SELECTED match is live, OR any
        # match in the feed is live — so the menu-bar score stays fresh even when
        # the widget is hidden and even if the currently-selected match isn't the
        # live one. Only go idle when nothing is live at all.
        if result.match is not None and result.match.is_live:
            return config.POLL_INTERVAL_LIVE
        if any(m.is_live for m in result.matches):
            return config.POLL_INTERVAL_LIVE
        return config.POLL_INTERVAL_IDLE
