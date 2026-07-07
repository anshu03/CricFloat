"""Saved sample API responses, for reference and offline testing.

`espn_scorepanel_sample.json` is a real capture of the ESPN scorepanel endpoint
(https://site.api.espn.com/apis/site/v2/sports/cricket/scorepanel), trimmed to a
single event: the live **ENG-W v AUS-W** Women's T20 World Cup final — an active
run chase. It's a good reference because it exercises the trickiest parsing:

  * `linescores` mirror entries (isBatting:false) that carry the OPPONENT's
    overs — the reason per-team overs must come from the isBatting:true entry;
  * the chase target embedded in the flat `score` string
    ("38/1 (3.4/20 ov, target 151)"), not in the linescores;
  * `internationalClassId: "10"` marking a women's international (non-domestic).

Use `load_sample()` to parse it through the real provider offline, e.g. in tests
or when the live feed has no suitable match.
"""

from __future__ import annotations

import json
from pathlib import Path

_DIR = Path(__file__).parent
ESPN_SCOREPANEL_SAMPLE = _DIR / "espn_scorepanel_sample.json"


def load_espn_scorepanel() -> dict:
    """Return the saved scorepanel JSON as a dict."""
    with open(ESPN_SCOREPANEL_SAMPLE) as f:
        return json.load(f)


def load_sample():
    """Parse the saved sample through the real ESPN provider (offline).

    Returns a list[MatchScore]. Handy in tests or to demo the widget without a
    live match."""
    from ..providers import ESPNProvider

    return ESPNProvider().parse_scorepanel(load_espn_scorepanel())
