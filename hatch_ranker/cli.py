from __future__ import annotations

import argparse
from pathlib import Path

from hatch_ranker.io import load_theses, write_outputs
from hatch_ranker.models import Thesis
from hatch_ranker.ranker import Ranker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hatch-rank",
        description="Rank Hatch105 startup theses with a deterministic 10-week revenue survivability model.",
    )
    parser.add_argument(
        "--input",
        "-i",
        required=True,
        help="Path to the base candidate theses file (.csv or .json).",
    )
    parser.add_argument(
        "--append",
        "-a",
        action="append",
        default=[],
        help="Optional extra .csv/.json file to append and rerank, useful for live challenge theses. Can be passed multiple times.",
    )
    parser.add_argument(
        "--out-dir",
        "-o",
        default="outputs",
        help="Directory for ranking.csv, ranking.json, and ranking.md. Defaults to ./outputs.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="How many rows to include in the markdown ranking table. JSON/CSV always include all rows.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    theses = load_theses(args.input, is_new=False)
    start_index = len(theses)
    for append_path in args.append:
        new_theses = load_theses(append_path, is_new=True, start_index=start_index)
        theses.extend(new_theses)
        start_index += len(new_theses)

    seen_refs: set[str] = set()
    unique: list[Thesis] = []
    for thesis in theses:
        if thesis.ref in seen_refs:
            print(f"Skipping duplicate ref {thesis.ref} (source row {thesis.source_index + 1}).")
            continue
        seen_refs.add(thesis.ref)
        unique.append(thesis)
    theses = unique

    cards = Ranker().rank(theses)
    write_outputs(cards, Path(args.out_dir), top_n=args.top)
    print_summary(cards, Path(args.out_dir))
    return 0


def print_summary(cards, out_dir: Path) -> None:
    print(f"Ranked {len(cards)} theses.")
    print(f"Wrote {out_dir / 'ranking.csv'}")
    print(f"Wrote {out_dir / 'ranking.json'}")
    print(f"Wrote {out_dir / 'ranking.md'}")
    print()
    print("Top 5:")
    for card in cards[:5]:
        print(f"{card.rank:>2}. {card.ref:<5} {card.final_score:>5.1f}  {card.title}")

    new_cards = [card for card in cards if card.thesis and card.thesis.is_new]
    if new_cards:
        print()
        print("New thesis landing notes:")
        for card in new_cards:
            print(f"- Rank {card.rank}: {card.ref} ({card.final_score:.1f}) - {card.rationale}")


if __name__ == "__main__":
    raise SystemExit(main())
