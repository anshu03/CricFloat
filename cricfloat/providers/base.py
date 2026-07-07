"""Provider abstraction + the provider-agnostic MatchScore model.

Every data source (ESPN, CricAPI, ...) returns the same `MatchScore` so the
rest of the app never has to know which provider answered.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Batsman:
    name: str
    runs: int = 0
    balls: int = 0
    on_strike: bool = False

    def line(self) -> str:
        star = "*" if self.on_strike else ""
        return f"{self.name} {self.runs}{star} ({self.balls})"


@dataclass
class Bowler:
    name: str
    wickets: int = 0
    conceded: int = 0
    overs: str = ""

    def line(self) -> str:
        ov = f" ({self.overs})" if self.overs else ""
        return f"{self.name} {self.wickets}-{self.conceded}{ov}"


@dataclass
class Ball:
    """One delivery, for the recent-balls strip."""

    symbol: str  # ".", "1", "4", "6", "W", "wd", "nb", ...
    kind: str = "run"  # dot|run|four|six|wicket|wide|noball|bye — drives color
    over_start: bool = False  # True if this ball begins a new over (draw a gap)


@dataclass
class LivePlayers:
    """Current batsmen + bowler + recent balls for a live match (from ESPN's
    summary + playbyplay endpoints). Empty when not applicable."""

    batsmen: list[Batsman] = field(default_factory=list)
    bowler: Bowler | None = None
    balls: list[Ball] = field(default_factory=list)  # last N deliveries (live)
    top_scorer: str = ""  # "IND Kohli 82 (49)" — finished matches
    top_bowler: str = ""  # "AUS Cummins 3/24" — finished matches
    # Score (innings lines) parsed from the SAME summary response as the
    # batsmen/bowler, so the selected match's score stays consistent with its
    # players instead of drifting against a separately-fetched scorepanel.
    innings: list = field(default_factory=list)  # list[InningsLine]


@dataclass
class InningsLine:
    """One team's innings line, e.g. 'IND 190/7 (19.0 ov)'.

    For Tests, `aggregate` holds the multi-innings string (e.g. '366 & 209')
    and takes precedence over the structured runs/wickets/overs when set.
    """

    team: str  # abbreviation, e.g. "IND"
    runs: int | None = None
    wickets: int | None = None
    overs: float | None = None
    is_batting: bool = False
    aggregate: str | None = None  # Test-only: "366 & 209/5"
    target: int | None = None  # runs to chase (2nd innings only)
    max_overs: float | None = None  # innings length, e.g. 20.0 (limited-overs)
    period: int = 0  # innings number (ESPN linescore period) — distinguishes
    #                  a team's 1st vs 2nd innings for the score-regression guard

    def score_str(self) -> str:
        if self.runs is None:
            return "yet to bat"
        w = "" if self.wickets is None or self.wickets >= 10 else f"/{self.wickets}"
        if self.wickets is not None and self.wickets >= 10:
            w = " all out"
        ov = f" ({self.overs} ov)" if self.overs is not None else ""
        return f"{self.runs}{w}{ov}"


@dataclass
class MatchScore:
    """Provider-agnostic snapshot of a single match."""

    match_id: str
    short_name: str  # "ENG v IND"
    description: str  # league / venue blurb
    state: str  # "pre" | "in" | "post"
    status_detail: str  # "Live", "Stumps", "Final", ...
    summary: str  # human blurb: "India A lead by 175 runs"
    status_note: str = ""  # interruption note, e.g. "Match delayed by rain"
    innings: list[InningsLine] = field(default_factory=list)
    source: str = ""  # which provider produced this (for debugging)
    url: str = ""  # link to the match page (for click-through)
    has_india: bool = False  # any competitor is an India team
    is_international: bool = True  # False for domestic / franchise-league games
    session: str = ""  # multi-day session, e.g. "Day 3" (Tests only)
    league_id: str = ""  # ESPN league id, needed for the summary endpoint

    @property
    def is_live(self) -> bool:
        return self.state == "in"

    @property
    def priority(self) -> int:
        """Sort tier within a group: India (0) → international (1) → domestic (2)."""
        if self.has_india:
            return 0
        return 1 if self.is_international else 2

    @property
    def match_tag(self) -> str:
        """Short match identifier from the description, e.g. '4th T20I' or
        '2nd Test' — used to distinguish same-name matches in the dropdown."""
        seg = (self.description or "").split(",")[0].strip()
        # Keep it only if it looks like a match number (starts with a digit).
        return seg if seg[:1].isdigit() else ""

    def one_liner(self) -> str:
        parts = [f"{i.team} {i.score_str()}" for i in self.innings if i.runs is not None]
        body = "  ".join(parts) if parts else self.short_name
        tail = f" — {self.summary}" if self.summary else f" ({self.status_detail})"
        return f"{body}{tail}"


class Provider(ABC):
    """A cricket data source.

    `fetch_all` returns every current match this provider knows about (for the
    dropdown). Returns [] on failure so ScoreService can fall back.
    """

    name: str = "provider"

    @abstractmethod
    def fetch_all(self) -> list[MatchScore]:  # pragma: no cover - interface
        ...
