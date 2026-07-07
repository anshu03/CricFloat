"""Turn a MatchScore into the structured fields the overlay renders.

The overlay is a scorecard: a header line, one row per team (name + score),
a status chip, and a summary line. `render_card` produces a `CardView` with
all of those pre-formatted so the window code stays dumb.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..providers import MatchScore
from ..service import ServiceResult


@dataclass
class TeamRow:
    name: str
    score: str  # "191/6" or "366" or "yet to bat"
    overs: str  # "19.0" or "a.o. 110.0" or ""
    emphasis: bool  # True for the team to visually highlight
    batting: bool = False  # currently batting (live) — gets a ● marker


@dataclass
class DetailRow:
    """One line in the expanded detail: a name on the left, its figure on the
    right. `kind` is 'bat' | 'bowl' | 'note' (styling hint)."""

    name: str
    figure: str  # "42* (30)" for a batsman, "3-24 (4)" for a bowler
    kind: str = "bat"
    on_strike: bool = False


@dataclass
class CardView:
    header: str  # "2ND T20I · MANCHESTER"
    chip: str  # "LIVE" | "FINAL" | "UPCOMING"
    live: bool
    rows: list[TeamRow] = field(default_factory=list)
    summary: str = ""
    note: str = ""  # optional 2nd summary line, e.g. "Match delayed by rain"
    url: str = ""  # match page to open on click
    # Expanded detail: batsmen (one per line) then the bowler, each name+figure.
    detail: list = field(default_factory=list)  # list[DetailRow]
    has_detail: bool = False  # True if this is a live match (chevron shows)
    balls: list = field(default_factory=list)  # list[Ball] for the recent-balls strip


_STATE_CHIP = {"in": "LIVE", "post": "ENDED", "pre": "UPCOMING"}


def _is_india(team: str) -> bool:
    t = (team or "").upper()
    return t == "IND" or t.startswith("IND") or t.startswith("IN-")


def _header(m: MatchScore) -> str:
    """A short 'FORMAT · VENUE' line pulled from the ESPN description blurb.

    description looks like: "2nd T20I, India tour of England at Manchester, ..."
    We take the segment before the first comma (the format) and the venue after
    the last ' at '.
    """
    desc = m.description or m.short_name
    fmt = desc.split(",")[0].strip()
    # For a live Test, the day ("Day 3") is more useful than the venue.
    if m.session:
        return f"{fmt} · {m.session}".upper()
    venue = ""
    if " at " in desc:
        venue = desc.split(" at ")[-1].split(",")[0].strip()
    line = f"{fmt} · {venue}" if venue else fmt
    return line.upper()


def _normalize_overs(overs: float) -> float:
    """Roll a completed over up to the next whole one. Cricket overs use .1–.5
    for balls into the current over, so a 6th ball completes it: 38.6 -> 39.0.
    ESPN sometimes reports the '.6' form instead of rolling over; fix it here."""
    whole = int(overs)
    ball = round((overs - whole) * 10)
    if ball >= 6:
        return float(whole + 1)
    return overs


def _fmt_overs(overs) -> str:
    """Overs as a compact string: drop a trailing '.0' (a completed over) so
    142.0 -> '142', but keep mid-over fractions like '9.5'. A '.6' rolls up
    (38.6 -> '39')."""
    if overs is None:
        return ""
    overs = _normalize_overs(float(overs))
    if float(overs) == int(overs):
        return str(int(overs))
    return str(overs)


def _fmt_overs_str(overs: str) -> str:
    """Like _fmt_overs but for a string overs value (the bowler figure). Rolls a
    '.6' up (38.6 -> '39'); leaves anything non-numeric untouched."""
    try:
        return _fmt_overs(float(overs))
    except (TypeError, ValueError):
        return str(overs)


def _team_rows(m: MatchScore) -> list[TeamRow]:
    live = m.is_live
    rows: list[TeamRow] = []
    for inn in m.innings:
        india = _is_india(inn.team)
        batting = live and inn.is_batting
        # In a live match highlight whoever's batting; otherwise highlight India.
        emphasis = batting if live else india
        if inn.runs is None:
            rows.append(TeamRow(inn.team, "yet to bat", "", emphasis, batting))
            continue
        # Tests: show the multi-innings aggregate ("366 & 209/5"), no overs.
        if inn.aggregate:
            rows.append(TeamRow(inn.team, inn.aggregate, "", emphasis, batting))
            continue
        if inn.wickets is not None and inn.wickets >= 10:
            # All out: score is just the runs (no /10); overs stays numeric so
            # the overs column aligns with other rows.
            score = str(inn.runs)
        else:
            w = "" if inn.wickets is None else f"/{inn.wickets}"
            score = f"{inn.runs}{w}"
        overs = _fmt_overs(inn.overs)
        rows.append(TeamRow(inn.team, score, overs, emphasis, batting))
    return rows


def _balls_left(overs: float | None, max_overs: float | None) -> int | None:
    """Balls remaining in a limited-overs innings. Overs use .1-.5 notation
    (7.5 = 7 overs 5 balls), so convert to balls before subtracting."""
    if overs is None or max_overs is None:
        return None
    def to_balls(o: float) -> int:
        whole = int(o)
        return whole * 6 + round((o - whole) * 10)
    left = to_balls(max_overs) - to_balls(overs)
    return left if left > 0 else None


def _summary_line(m) -> str:
    """State-aware summary: chase equation, 'batting first', or Test trail/lead.

    Falls back to ESPN's own summary when we can't do better."""
    espn = m.summary or m.status_detail

    if not m.is_live:
        return espn

    batting = next((i for i in m.innings if i.is_batting), None)

    # Chase: the batting side has a target -> "need X in Y balls · target Z".
    if batting is not None and batting.target and batting.runs is not None:
        need = batting.target - batting.runs
        balls = _balls_left(batting.overs, batting.max_overs)
        if need > 0:
            line = f"{batting.team} need {need}"
            if balls:
                line += f" in {balls}"
            return f"{line} · target {batting.target}"

    # First innings, opponent yet to bat -> "X batting first".
    yet_to_bat = any(i.runs is None for i in m.innings)
    if batting is not None and yet_to_bat and batting.runs is not None:
        base = espn if espn and "won toss" in espn.lower() else f"{batting.team} batting first"
        if batting.overs is not None:
            return f"{base} · {_fmt_overs(batting.overs)} ov"
        return base

    return espn


def render_card(result: ServiceResult, players=None) -> CardView:
    m = result.match
    if m is None:
        return CardView(header="CRICFLOAT", chip="", live=False,
                        summary="No India match right now")

    summary = _summary_line(m)
    if result.stale:
        summary = f"{summary} · stale"

    detail = []
    balls = []
    if players is not None:
        for b in players.batsmen:
            star = "*" if b.on_strike else ""
            detail.append(DetailRow(name=b.name, figure=f"{b.runs}{star} ({b.balls})",
                                    kind="bat", on_strike=b.on_strike))
        if players.bowler:
            bw = players.bowler
            ov = f" ({_fmt_overs_str(bw.overs)})" if bw.overs else ""
            detail.append(DetailRow(name=bw.name,
                                    figure=f"{bw.wickets}-{bw.conceded}{ov}",
                                    kind="bowl"))
        balls = players.balls

    # An interruption note (rain, bad light…) becomes a 2nd summary line, but
    # only when it isn't already what the summary itself says.
    note = m.status_note or ""
    if note and note.strip().lower() in summary.strip().lower():
        note = ""

    return CardView(
        header=_header(m),
        chip=_STATE_CHIP.get(m.state, m.status_detail.upper()),
        live=m.is_live,
        rows=_team_rows(m),
        summary=summary,
        note=note,
        url=m.url,
        detail=detail,
        has_detail=m.is_live,
        balls=balls,
    )
