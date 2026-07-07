"""Phase 1 smoke test: prove the data layer can fetch a live India match.

Usage:
    python check_scores.py          # run the full ScoreService provider chain
    python check_scores.py --espn   # test ESPN provider directly
    python check_scores.py --loop   # poll continuously like the real widget will
"""

from __future__ import annotations

import sys
import time

from cricfloat.providers import ESPNProvider
from cricfloat.service import ScoreService


def show(result) -> None:
    m = result.match
    stale = " [STALE]" if result.stale else ""
    if m is None:
        print("No India match found (all providers empty/failed).")
        return
    print(f"source={m.source}{stale}  state={m.state}  detail={m.status_detail}")
    print(f"  {m.short_name}")
    if m.description:
        print(f"  {m.description}")
    print(f"  >> {m.one_liner()}")


def main() -> None:
    args = set(sys.argv[1:])

    if "--espn" in args:
        matches = ESPNProvider().fetch_all()
        india = [m for m in matches if m.has_india]
        print(f"ESPN direct: {len(matches)} matches, {len(india)} with India")
        for m in (india or matches)[:1]:
            print("  best:", m.one_liner())
        return

    service = ScoreService()

    if "--loop" in args:
        print("Polling (Ctrl-C to stop)...\n")
        while True:
            res = service.refresh()
            print(time.strftime("%H:%M:%S"), end="  ")
            show(res)
            print("-" * 60)
            time.sleep(service.next_interval(res))
        return

    show(service.refresh())


if __name__ == "__main__":
    main()
