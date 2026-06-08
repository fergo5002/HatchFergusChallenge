"""Diff two ranking.json files by ref: rank/score deltas + newly-fired triggers.

Usage:
    python scripts/impact_diff.py outputs/expansion_before/ranking.json outputs/expansion_after/ranking.json
Prints a markdown report to stdout (refs + numbers + newly-fired concepts/saturation only; no thesis text).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> dict[str, dict]:
    cards = json.loads(Path(path).read_text(encoding="utf-8"))
    return {c["ref"]: c for c in cards}


def fired_set(card: dict) -> set[str]:
    names: set[str] = set()
    for lst in (card.get("fired_concepts") or {}).values():
        names.update(lst)
    sat = card.get("saturation") or {}
    if sat.get("name"):
        names.add(f"saturated:{sat['name']}")
    for trap in card.get("traps") or []:
        names.add(f"trap:{trap['name']}")
    return names


def main() -> int:
    before, after = load(sys.argv[1]), load(sys.argv[2])
    rows = []
    for ref, a in after.items():
        b = before.get(ref)
        if not b:
            continue
        d_rank = b["rank"] - a["rank"]          # positive = moved up
        d_score = round(a["score"] - b["score"], 2)
        new_fired = sorted(fired_set(a) - fired_set(b))
        rows.append((abs(d_rank), ref, b["rank"], a["rank"], d_rank, d_score, new_fired))
    rows.sort(reverse=True)
    print("# Keyword Expansion Impact (before -> after)\n")
    print(f"Corpus: {len(after)} theses. Rows sorted by absolute rank movement.\n")
    print("| Ref | Rank b->a | dRank | dScore | Newly fired |")
    print("|---|---|---:|---:|---|")
    for _, ref, rb, ra, dr, ds, nf in rows:
        print(f"| {ref} | {rb}->{ra} | {dr:+d} | {ds:+.2f} | {', '.join(nf) or '-'} |")
    moved = sum(1 for r in rows if r[0] != 0)
    print(f"\n**{moved}/{len(rows)} theses changed rank.** "
          f"Max move: {rows[0][0] if rows else 0} places.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
