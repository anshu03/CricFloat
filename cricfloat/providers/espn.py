"""Primary provider: ESPNcricinfo's public site.api.espn.com scorepanel.

Free, no API key. Undocumented, so this is defensive: any schema surprise
results in a skipped event rather than a crash, and total failure returns None
so the ScoreService can fall back to CricAPI.
"""

from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from .base import (
    Ball,
    Batsman,
    Bowler,
    InningsLine,
    LivePlayers,
    MatchScore,
    Provider,
)

SCOREPANEL_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/scorepanel"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/{league}/summary"
PLAYBYPLAY_URL = "https://site.api.espn.com/apis/site/v2/sports/cricket/{league}/playbyplay"


def _int(v) -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return 0


def _ball_outcome(ball: dict) -> tuple[str, str]:
    """One delivery -> (symbol, kind). kind is one of: dot, run, four, six,
    wicket, wide, noball, bye — used for both the label and the color."""
    pt = (ball.get("playType", {}) or {}).get("description", "").lower()
    runs = ball.get("scoreValue", 0) or 0

    if "wicket" in pt or pt == "out":
        return "W", "wicket"
    if "wide" in pt:
        # A wide can concede extra runs (e.g. "5 wides"): show "wd" or "N+wd".
        return ("wd" if runs <= 1 else f"{runs - 1}wd"), "wide"
    if "no ball" in pt or "no-ball" in pt or "noball" in pt:
        return ("nb" if runs <= 1 else f"{runs - 1}nb"), "noball"
    if "bye" in pt:  # byes / leg-byes
        return (f"{runs}b" if runs else "b"), "bye"
    if "four" in pt or runs == 4:
        return "4", "four"
    if "six" in pt or runs == 6:
        return "6", "six"
    if runs == 0:
        return ".", "dot"
    return str(runs), "run"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.espncricinfo.com/",
}

# ESPN's summary endpoint is edge-cached for ~10s (Cache-Control: max-age=10),
# so two polls inside that window can get an identical stale body. These headers
# + a unique cache-buster param on each request force past the edge cache so we
# always get ESPN's freshest available snapshot.
_NOCACHE_HEADERS = {**_HEADERS, "Cache-Control": "no-cache", "Pragma": "no-cache"}


def _cache_buster() -> dict:
    """A unique query param so each request bypasses any intermediary cache."""
    return {"_": str(int(time.time() * 1000))}

# Match teams whose abbreviation/name indicates India (covers IND, IND-A,
# IND19, IN-AW, INDIA...). We match on the ESPN abbreviation prefix.
_INDIA_TOKENS = ("IND", "IN-A", "IN-W")


def _is_india(abbr: str, name: str) -> bool:
    a = (abbr or "").upper()
    n = (name or "").upper()
    if any(a.startswith(t) for t in _INDIA_TOKENS):
        return True
    return n == "INDIA" or n.startswith("INDIA ")


class ESPNProvider(Provider):
    name = "espn"

    def __init__(self, timeout: float = 12.0) -> None:
        self._timeout = timeout
        # Last good recent-balls per match — reused if a fetch transiently fails,
        # so the balls strip never lags behind or empties out relative to the
        # score/bowler (they all render as one consistent set).
        self._last_balls: dict[str, list] = {}
        # Monotonic guard: the highest ESPN ball `sequence` (a match-wide int that
        # never resets) we've shown per match. If a fetch's newest ball has a
        # LOWER sequence, ESPN handed us a stale/rolled-back snapshot — we keep the
        # last good balls so a just-shown event (e.g. a wicket) can't disappear.
        self._last_ball_seq: dict[str, int] = {}
        # Last good batsmen+bowler per match. The summary endpoint (their source)
        # can transiently fail or return unparseable data while the balls call
        # succeeds — that used to blank the batsmen/bowler while the strip kept
        # updating. Reusing the last good parse keeps the two in step. Populated
        # only AFTER a successful parse, so a first-load failure still shows
        # nothing (never fabricated data).
        self._last_players: dict[str, tuple] = {}  # mid -> (batsmen, bowler)
        # Score-regression guard: highest (runs, wickets, overs) seen for each
        # team's innings, keyed (match_id, team, period). Runs/wickets only ever
        # climb within an innings, so a scorepanel snapshot showing FEWER for the
        # same period is stale and gets clamped up. A new innings has a new period
        # → its own fresh high-water mark. See _guard_score.
        self._score_high: dict[tuple, tuple] = {}  # (mid, team, period) -> (runs, wkts, overs)
        # A post-select "fetch now" and a regular poll can call into the provider
        # at the same time. The per-match caches above use read-modify-write
        # sequences (esp. the page-count logic in _recent_balls), which two
        # threads could interleave into a wrong result. This lock serializes those
        # stateful sections. Network I/O happens OUTSIDE the lock, so it doesn't
        # serialize the slow part — only the brief cache bookkeeping.
        self._state_lock = threading.Lock()

    def fetch_all(self) -> list[MatchScore]:
        try:
            resp = httpx.get(SCOREPANEL_URL, params=_cache_buster(),
                             headers=_NOCACHE_HEADERS, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        return self.parse_scorepanel(data)

    def parse_scorepanel(self, data: dict) -> list[MatchScore]:
        """Parse a scorepanel response dict into sorted MatchScores.

        Split out from `fetch_all` so the saved fixture (see cricfloat.fixtures)
        can be parsed offline through the exact same logic."""
        matches: list[MatchScore] = []
        for group in data.get("scores", []) or []:
            for event in group.get("events", []) or []:
                ms = self._parse_event(event)
                if ms is not None:
                    self._guard_score(ms)
                    matches.append(ms)

        # Drop per-match cache entries for matches no longer in the feed, so the
        # dicts don't grow without bound over a long-running session.
        self._prune_caches({m.match_id for m in matches})

        # Sort: live first, then finished, then upcoming; India before others.
        order = {"in": 0, "post": 1, "pre": 2}
        matches.sort(key=lambda m: (order.get(m.state, 3), m.priority))
        return matches

    def _prune_caches(self, live_ids: set) -> None:
        """Evict cached balls / players / guards for matches that dropped off the
        feed, keeping the per-match dicts bounded on a long-running widget."""
        with self._state_lock:
            for d in (self._last_balls, self._last_ball_seq, self._last_players):
                for mid in [k for k in d if k not in live_ids]:
                    del d[mid]
            # _score_high is keyed (match_id, team, period).
            for key in [k for k in self._score_high if k[0] not in live_ids]:
                del self._score_high[key]

    def _guard_score(self, ms: MatchScore) -> None:
        """Clamp a stale scorepanel snapshot so a team's live score never goes
        BACKWARDS within an innings. Delegates each innings to _clamp_innings,
        keyed by ESPN's linescore `period` so a genuine new innings restarts its
        own high-water mark. Test aggregates and finished matches are skipped."""
        if not ms.is_live:
            return
        with self._state_lock:
            for inn in ms.innings:
                self._clamp_innings(ms.match_id, inn)

    def _clamp_innings(self, match_id: str, inn) -> None:
        """Clamp one InningsLine's runs/wickets/overs up to the highest seen for
        that (match, team, innings-period). Caller must hold _state_lock. Both the
        scorepanel path and the summary-header path share this, so whichever
        endpoint updates first sets the floor for the other."""
        if inn.aggregate or inn.runs is None:
            return  # Test aggregate or 'yet to bat' — nothing to guard
        key = (match_id, inn.team, inn.period)
        prev = self._score_high.get(key)
        if prev is not None:
            p_runs, p_wkts, p_overs = prev
            if inn.runs < p_runs:
                inn.runs = p_runs
            if inn.wickets is not None and p_wkts is not None \
                    and inn.wickets < p_wkts:
                inn.wickets = p_wkts
            if inn.overs is not None and p_overs is not None \
                    and inn.overs < p_overs:
                inn.overs = p_overs
        self._score_high[key] = (inn.runs, inn.wickets, inn.overs)

    # ---- live players (batsmen / bowler) from the summary endpoint ------

    def fetch_live_players(self, match: MatchScore) -> LivePlayers:
        """Fetch per-match detail for the SELECTED match.

        For a LIVE match: current batsmen + bowler (summary) and the recent
        balls (playbyplay), fetched IN PARALLEL. For a FINISHED match: the top
        scorer (from the summary scorecard) instead of live players/balls.
        Returns empty LivePlayers if not applicable / on error."""
        if not match.league_id or not match.match_id:
            return LivePlayers()

        if match.state == "post":
            data = self._fetch_summary(match)
            if data is None:
                return LivePlayers()
            scorer, bowler = self._top_performers(data)
            return LivePlayers(top_scorer=scorer, top_bowler=bowler)

        if not match.is_live:
            return LivePlayers()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_summary = pool.submit(self._fetch_summary, match)
            f_balls = pool.submit(self._recent_balls, match, 10)
            data = f_summary.result()
            balls = f_balls.result()

        mid = match.match_id
        players = self._parse_players(data) if data is not None else LivePlayers()
        # Parse the SCORE from the same summary response, so the selected match's
        # score, batsmen and bowler all reflect one consistent instant (no drift
        # against the separately-fetched scorepanel).
        if data is not None:
            players.innings = self._innings_from_summary(data, mid)
        with self._state_lock:
            if players.batsmen or players.bowler:
                # Good parse — remember it so a later summary hiccup doesn't blank
                # the batsmen/bowler while the balls strip keeps refreshing.
                self._last_players[mid] = (players.batsmen, players.bowler)
            else:
                # Summary failed or was unparseable this cycle. Reuse the last good
                # batsmen/bowler (if any) so they stay in step with the fresh balls
                # instead of vanishing. Nothing cached (first load) => stays empty.
                cached = self._last_players.get(mid)
                if cached is not None:
                    players.batsmen, players.bowler = cached
        players.balls = balls
        return players

    def _innings_from_summary(self, data: dict, match_id: str) -> list:
        """Parse the innings lines (score) from a summary response's header, using
        the SAME competitor/linescore parsing as the scorepanel. Returns [] on any
        shape surprise so the caller falls back to the scorepanel score."""
        try:
            comp = data["header"]["competitions"][0]
            cls = comp.get("class", {}) or {}
            fmt = (cls.get("eventType") or cls.get("generalClassCard") or "").lower()
            multi = "test" in fmt or "first-class" in fmt
            innings = [self._parse_competitor(c, multi)
                       for c in comp.get("competitors", [])]
            # Same monotonic guard as the scorepanel path, sharing the high-water
            # marks so the two endpoints can't regress each other.
            with self._state_lock:
                for inn in innings:
                    self._clamp_innings(match_id, inn)
            return innings
        except Exception:
            return []

    def _team_abbrevs(self, data: dict) -> dict:
        """Map full team name -> abbreviation from the summary header."""
        out = {}
        try:
            comps = data["header"]["competitions"][0]["competitors"]
            for c in comps:
                t = c.get("team", {})
                if t.get("displayName") and t.get("abbreviation"):
                    out[t["displayName"]] = t["abbreviation"]
        except Exception:
            pass
        return out

    def _top_performers(self, data: dict) -> tuple[str, str]:
        """Best batsman and best bowler of the match, each prefixed with their
        team, e.g. ('BDD Zadran 55 (37)', 'BEAD Shirzad 3/28')."""
        abbr = self._team_abbrevs(data)
        best_bat = None   # (team, name, runs, balls)
        best_bowl = None  # (team, name, wkts, conceded)
        for card in data.get("matchcards", []) or []:
            team = abbr.get(card.get("teamName", ""), card.get("teamName", "?"))
            headline = (card.get("headline") or "").lower()
            for p in card.get("playerDetails", []) or []:
                name = (p.get("playerName") or "?").split()[-1]
                if "bowl" in headline:
                    try:
                        wkts = int(p.get("wickets"))
                    except (TypeError, ValueError):
                        continue
                    conceded = p.get("conceded", "")
                    key = (wkts, -_int(conceded))  # most wkts, fewest runs
                    if best_bowl is None or key > (best_bowl[2], -_int(best_bowl[3])):
                        best_bowl = (team, name, wkts, conceded)
                else:  # batting card
                    try:
                        runs = int(p.get("runs"))
                    except (TypeError, ValueError):
                        continue
                    if best_bat is None or runs > best_bat[2]:
                        best_bat = (team, name, runs, p.get("ballsFaced"))

        top_scorer = ""
        if best_bat:
            balls = f" ({best_bat[3]})" if best_bat[3] else ""
            top_scorer = f"{best_bat[0]} {best_bat[1]} {best_bat[2]}{balls}"
        top_bowler = ""
        if best_bowl:
            top_bowler = f"{best_bowl[0]} {best_bowl[1]} {best_bowl[2]}/{best_bowl[3]}"
        return top_scorer, top_bowler

    def _fetch_summary(self, match: MatchScore) -> dict | None:
        try:
            resp = httpx.get(
                SUMMARY_URL.format(league=match.league_id),
                params={"event": match.match_id, **_cache_buster()},
                headers=_NOCACHE_HEADERS, timeout=self._timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def _commentary_page(self, url: str, event: str, page: int | None) -> dict:
        params = {"event": event, **_cache_buster()}
        if page is not None:
            params["page"] = page
        resp = httpx.get(url, params=params, headers=_NOCACHE_HEADERS,
                         timeout=self._timeout)
        resp.raise_for_status()
        return resp.json().get("commentary") or {}

    def _recent_balls(self, match: MatchScore, n: int = 10) -> list:
        """Last `n` deliveries as Ball objects. Serialized per provider so an
        overlapping poll + post-select fetch can't interleave the page-count /
        monotonic-guard read-modify-writes into a wrong result. The two overlap
        only on the same selected match, so the wait is ~one round-trip."""
        with self._state_lock:
            return self._recent_balls_locked(match, n)

    def _recent_balls_locked(self, match: MatchScore, n: int = 10) -> list:
        """Body of _recent_balls; must be called with _state_lock held.

        Commentary is paginated oldest-first, so the recent balls are on the LAST
        page. We read page 1 for the AUTHORITATIVE pageCount every fetch, then
        pull the true last page (+ the one before, to guarantee >= n balls). This
        keeps the strip from getting pinned behind a stale page (which showed as
        'bowler updates but balls don't')."""
        url = PLAYBYPLAY_URL.format(league=match.league_id)
        mid = match.match_id
        try:
            first = self._commentary_page(url, mid, None)  # page 1 = source of truth
            last = first.get("pageCount") or 1
            if last <= 1:
                pages = [first]
            else:
                pages = [self._commentary_page(url, mid, pg)
                         for pg in (last - 1, last) if pg >= 1]
        except Exception:
            return self._last_balls.get(mid, [])  # keep the last good set on error

        items = []
        for p in pages:
            items += p.get("items") or []
        balls = [b for b in items
                 if isinstance(b.get("over"), dict)
                 and b["over"].get("actual") is not None]
        if not balls:
            return self._last_balls.get(mid, [])

        # Staleness guard via `sequence`: ESPN stamps every delivery with a
        # match-wide monotonic integer that never resets (across overs OR
        # innings). Reject a snapshot whose NEWEST ball is strictly OLDER than the
        # newest we've already shown — that's a rolled-back/stale body, and
        # accepting it would make a just-shown event (e.g. a wicket) disappear.
        # Equal-or-newer is accepted, so the strip never freezes behind the score.
        seq = self._ball_seq(balls[-1])
        last_seq = self._last_ball_seq.get(mid)
        if last_seq is not None and seq is not None and seq < last_seq:
            return self._last_balls.get(mid, [])

        formatted = self._format_balls(balls[-n:])
        self._last_balls[mid] = formatted
        if seq is not None:
            self._last_ball_seq[mid] = seq
        return formatted

    @staticmethod
    def _ball_seq(ball: dict):
        """A delivery's match-wide monotonic order key. Prefer ESPN's `sequence`
        (an int that never resets); fall back to over.actual as a float if it's
        missing (older/other payloads)."""
        seq = ball.get("sequence")
        if seq is not None:
            try:
                return int(seq)
            except (TypeError, ValueError):
                pass
        actual = (ball.get("over", {}) or {}).get("actual")
        if actual is not None:
            try:
                return float(actual)
            except (TypeError, ValueError):
                pass
        return None

    def _over_number(self, ball: dict) -> int:
        """The over a delivery belongs to. Take the integer part of `over.actual`
        straight from the string ('98.4' -> 98) to avoid float rounding, and fall
        back to `over.completed`/`over.number` if present."""
        over = ball.get("over", {}) or {}
        actual = over.get("actual")
        if actual is not None:
            s = str(actual)
            head = s.split(".")[0]
            try:
                # For a ball that completes an over ("98.6"), it still belongs to
                # over 98. Deliveries are numbered 1-6 within head+1 conceptually,
                # but `head` is already the completed-over count, so use head.
                return int(head)
            except ValueError:
                pass
        return -1

    def _format_balls(self, balls: list) -> list:
        out: list[Ball] = []
        prev_over = None
        for b in balls:
            over_num = self._over_number(b)
            # New over starts only when the over number actually increases
            # (guards against equal/regressing values from extras).
            is_start = (prev_over is not None and over_num > prev_over)
            symbol, kind = _ball_outcome(b)
            out.append(Ball(symbol=symbol, kind=kind, over_start=is_start))
            prev_over = over_num if over_num >= 0 else prev_over
        return out

    def _player_name(self, athlete: dict) -> str:
        """Prefer shortName, but fall back to the surname of the full name when
        ESPN leaves shortName empty (happens for some U19/associate players)."""
        short = (athlete.get("shortName") or "").strip()
        if short:
            return short
        full = (athlete.get("displayName") or athlete.get("name") or "").strip()
        return full.split()[-1] if full else "?"

    def _parse_players(self, data: dict) -> LivePlayers:
        batsmen: list[Batsman] = []
        bowler: Bowler | None = None
        try:
            for roster in data.get("rosters", []) or []:
                for p in roster.get("roster", []) or []:
                    if not p.get("active"):
                        continue
                    role = (p.get("activeName") or "").lower()
                    name = self._player_name(p.get("athlete", {}) or {})
                    if "striker" in role:  # "striker" or "non-striker"
                        # Use the BATTING period's stats, not linescores[-1]:
                        # a player who bowled earlier this match has a stale
                        # bowling period that would otherwise leak in.
                        stats = self._role_stats(p, "batting")
                        batsmen.append(Batsman(
                            name=name,
                            runs=_int(stats.get("runs")),
                            balls=_int(stats.get("ballsFaced")),
                            on_strike=(role == "striker"),
                        ))
                    elif role == "current bowler":
                        stats = self._role_stats(p, "bowling")
                        bowler = Bowler(
                            name=name,
                            wickets=_int(stats.get("wickets")),
                            conceded=_int(stats.get("conceded")),
                            overs=stats.get("overs", "") or "",
                        )
            # Striker first.
            batsmen.sort(key=lambda b: not b.on_strike)
        except Exception:
            return LivePlayers()
        return LivePlayers(batsmen=batsmen, bowler=bowler)

    def _period_stats(self, ls: dict) -> dict:
        """Flatten one linescore period's stat name->displayValue map."""
        out: dict = {}
        for cat in ls.get("statistics", {}).get("categories", []) or []:
            for s in cat.get("stats", []) or []:
                out[s.get("name")] = s.get("displayValue")
        return out

    def _role_stats(self, player: dict, role: str) -> dict:
        """Return the stats from the linescore period matching `role`
        ('batting' or 'bowling'). A player can have both a batting and a bowling
        period this match; picking by role avoids showing a batsman's stale
        bowling figures (or vice-versa)."""
        lss = player.get("linescores", []) or []
        picked = []
        for ls in lss:
            st = self._period_stats(ls)
            if role == "batting" and ("ballsFaced" in st or "runs" in st and "battingPosition" in st):
                # A real batting innings has ballsFaced; prefer the one they
                # actually batted in (latest such period).
                if "ballsFaced" in st:
                    picked.append(st)
            elif role == "bowling" and ("conceded" in st or "bowlingPosition" in st):
                if "overs" in st or "conceded" in st:
                    picked.append(st)
        if picked:
            return picked[-1]
        # Fallback: last period (old behaviour) if role detection failed.
        return self._period_stats(lss[-1]) if lss else {}

    def _match_url(self, event: dict) -> str:
        for link in event.get("links", []) or []:
            rel = link.get("rel", [])
            if "desktop" in rel and link.get("href"):
                return link["href"]
        links = event.get("links", []) or []
        return links[0].get("href", "") if links else ""

    def _parse_event(self, event: dict) -> MatchScore | None:
        try:
            comps = event.get("competitions") or []
            if not comps:
                return None
            comp = comps[0]
            competitors = comp.get("competitors") or []

            india_here = any(
                _is_india(c.get("team", {}).get("abbreviation", ""),
                          c.get("team", {}).get("displayName", ""))
                for c in competitors
            )

            status = comp.get("status", {}) or {}
            stype = status.get("type", {}) or {}

            # internationalClassId "0" = domestic/franchise; non-zero = intl.
            cls = comp.get("class", {}) or {}
            intl_id = cls.get("internationalClassId", "0")
            is_intl = str(intl_id) not in ("0", "")

            # Tests / first-class span two innings per team — show the aggregate.
            fmt = (cls.get("eventType") or cls.get("generalClassCard") or "").lower()
            is_multi_innings = "test" in fmt or "first-class" in fmt

            innings = [self._parse_competitor(c, is_multi_innings)
                       for c in competitors]

            # ESPN's status.type has a generic label (`detail`, usually
            # "Live"/"Final") and a SPECIFIC description (`description`, e.g.
            # "Match delayed by rain" for interruption ids like 101). Capture the
            # specific note when it adds info beyond the generic label, so the UI
            # can show it as a second summary line.
            detail = (stype.get("detail") or "").strip()
            description = (stype.get("description") or "").strip()
            status_note = description if description and description != detail else ""

            return MatchScore(
                match_id=str(event.get("id", "")),
                short_name=event.get("shortName", "") or event.get("name", ""),
                description=event.get("description", ""),
                state=stype.get("state", ""),
                status_detail=detail or description,
                summary=status.get("summary", ""),
                status_note=status_note,
                innings=innings,
                source=self.name,
                url=self._match_url(event),
                has_india=india_here,
                is_international=is_intl,
                # Multi-day session ("Day 3") on live Tests; blank otherwise.
                session=status.get("session", "") or "" if is_multi_innings else "",
                league_id=str(event.get("leagueId", "")),
            )
        except Exception:
            return None

    def _parse_competitor(self, c: dict, multi_innings: bool = False) -> InningsLine:
        team = c.get("team", {}) or {}
        abbr = team.get("abbreviation", "") or team.get("shortDisplayName", "?")
        lines = c.get("linescores") or []

        # In ESPN's data each competitor gets a linescore for EVERY period,
        # including mirror/placeholder entries for the opponent's innings. Those
        # mirrors have `isBatting: false` and runs 0, but their `overs` field
        # carries the OPPONENT's over count — which is why both teams showed the
        # same overs. Only entries with `isBatting: true` are this team's real
        # innings.
        own = [ls for ls in lines if ls.get("isBatting")]
        current = own[-1] if own else None

        if current is None:
            # No innings from this team yet — fall back to the flat `score`.
            raw = c.get("score")
            runs = int(raw) if isinstance(raw, str) and raw.isdigit() else None
            return InningsLine(team=abbr, runs=runs)

        runs = current.get("runs")
        wkts = current.get("wickets")
        overs = current.get("overs")
        aggregate = self._aggregate(own) if multi_innings else None
        target, max_overs = self._chase_info(c.get("score", ""))
        return InningsLine(
            team=abbr,
            runs=int(runs) if isinstance(runs, (int, float)) else None,
            wickets=int(wkts) if isinstance(wkts, (int, float)) else None,
            overs=float(overs) if isinstance(overs, (int, float)) else None,
            is_batting=bool(current.get("isCurrent")),
            aggregate=aggregate,
            target=target,
            max_overs=max_overs,
            period=int(current.get("period") or 0),
        )

    def _chase_info(self, score: str):
        """Parse '(7.5/20 ov, target 208)' from the flat score string ->
        (target, max_overs)."""
        target = None
        max_overs = None
        m = re.search(r"target\s+(\d+)", score)
        if m:
            target = int(m.group(1))
        m = re.search(r"/(\d+(?:\.\d+)?)\s*ov", score)
        if m:
            max_overs = float(m.group(1))
        return target, max_overs

    def _aggregate(self, own_innings: list[dict]) -> str:
        """Test aggregate across a team's innings, e.g. '366 & 209/5' or
        '549/9d & 36/0' (with a 'd' for a declared innings)."""
        parts = []
        for ls in own_innings:
            runs = ls.get("runs")
            wkts = ls.get("wickets")
            if runs is None:
                continue
            dec = "d" if "declar" in (ls.get("description", "") or "").lower() else ""
            if isinstance(wkts, (int, float)) and wkts < 10:
                parts.append(f"{runs}/{wkts}{dec}")
            else:  # all out (10) or unknown — show just the runs
                parts.append(f"{runs}{dec}")
        return " & ".join(parts)
