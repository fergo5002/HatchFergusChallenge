"""One-off probe: trace why the big movers moved in the hardening calibration.

Usage:
    python scripts/trace_movers.py outputs/hardening_before/ranking.json outputs/hardening_after/ranking.json H-40 H-22 ...
Prints refs, numbers, traps, and concept names only - no thesis text.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    before = {c["ref"]: c for c in json.load(open(sys.argv[1], encoding="utf-8"))}
    after = {c["ref"]: c for c in json.load(open(sys.argv[2], encoding="utf-8"))}
    for ref in sys.argv[3:]:
        b, a = before[ref], after[ref]
        bt = {t["name"] for t in b["traps"]}
        at = {t["name"] for t in a["traps"]}
        bf = {n for v in b["fired_concepts"].values() for n in v}
        af = {n for v in a["fired_concepts"].values() for n in v}
        crit = {
            k: round(a["criteria"][k] - b["criteria"][k], 1)
            for k in a["criteria"]
            if abs(a["criteria"][k] - b["criteria"][k]) >= 4
        }
        print(f"{ref} rank {b['rank']}->{a['rank']} score {b['score']}->{a['score']} cap {b['viability_cap']}->{a['viability_cap']}")
        print(f"  traps gained {sorted(at - bt)} lost {sorted(bt - at)}")
        print(f"  concepts stopped firing: {sorted(bf - af)}")
        print(f"  concepts newly firing: {sorted(af - bf)}")
        print(f"  criteria moved >=4: {crit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
