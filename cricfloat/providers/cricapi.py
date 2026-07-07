"""Fallback provider: CricAPI (cricapi.com / cricketdata.org).

Requires a free API key (config.CRICAPI_KEY). Only hit when ESPN fails, to
stay inside the free ~100 req/day budget. Returns None if no key is set.
"""

from __future__ import annotations

import re

import httpx

from .base import InningsLine, MatchScore, Provider

CURRENT_MATCHES_URL = "https://api.cricapi.com/v1/currentMatches"

_INDIA_TOKENS = ("INDIA", "IND")

# CricAPI score inning names look like "India Inning 1"; the flat `r/w/o`
# fields carry runs/wickets/overs.
_SCORE_TEAM_RE = re.compile(r"^(.*?)\s+Inning", re.IGNORECASE)


def _is_india(name: str) -> bool:
    n = (name or "").upper()
    return n == "INDIA" or n.startswith("INDIA ") or n.startswith("IND ") or n == "IND"


class CricAPIProvider(Provider):
    name = "cricapi"

    def __init__(self, api_key: str | None, timeout: float = 12.0) -> None:
        self._api_key = api_key
        self._timeout = timeout

    def fetch_all(self) -> list[MatchScore]:
        if not self._api_key:
            return []
        try:
            resp = httpx.get(
                CURRENT_MATCHES_URL,
                params={"apikey": self._api_key, "offset": 0},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            return []

        if payload.get("status") != "success":
            return []

        matches: list[MatchScore] = []
        for m in payload.get("data", []) or []:
            ms = self._parse_match(m)
            if ms is not None:
                matches.append(ms)

        order = {"in": 0, "post": 1, "pre": 2}
        matches.sort(key=lambda m: (order.get(m.state, 3), m.priority))
        return matches

    def _parse_match(self, m: dict) -> MatchScore | None:
        try:
            teams = m.get("teams", []) or []
            state = self._state(m)
            innings = self._parse_scores(m.get("score", []) or [])
            match_id = str(m.get("id", ""))

            return MatchScore(
                match_id=match_id,
                short_name=" v ".join(teams) if teams else m.get("name", ""),
                description=m.get("name", ""),
                state=state,
                status_detail=m.get("status", ""),
                summary=m.get("status", ""),
                innings=innings,
                source=self.name,
                url=f"https://www.cricapi.com/match/{match_id}" if match_id else "",
                has_india=any(_is_india(t) for t in teams),
            )
        except Exception:
            return None

    def _state(self, m: dict) -> str:
        if m.get("matchEnded"):
            return "post"
        if m.get("matchStarted"):
            return "in"
        return "pre"

    def _parse_scores(self, scores: list[dict]) -> list[InningsLine]:
        out: list[InningsLine] = []
        for s in scores:
            inning = s.get("inning", "")
            match = _SCORE_TEAM_RE.match(inning)
            team = match.group(1).strip() if match else inning
            out.append(
                InningsLine(
                    team=team,
                    runs=int(s["r"]) if isinstance(s.get("r"), (int, float)) else None,
                    wickets=int(s["w"]) if isinstance(s.get("w"), (int, float)) else None,
                    overs=float(s["o"]) if isinstance(s.get("o"), (int, float)) else None,
                )
            )
        return out
