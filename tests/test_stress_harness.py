from __future__ import annotations

import csv
import json
import math
import random
import tempfile
import unittest
from pathlib import Path

from hatch_ranker.io import load_theses, write_outputs
from hatch_ranker.models import Thesis
from hatch_ranker.ranker import Ranker, parse_revenue_range
from hatch_ranker.stress import (
    check_invariants,
    generate_synthetic_records,
    run_stress,
    scorecards_hash,
)
from hatch_ranker.validation import load_raw_records, validate_records


class StressHarnessTests(unittest.TestCase):
    def test_loader_accepts_json_root_variants_and_rejects_malformed_root(self) -> None:
        row = sample_record("R-01")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = root / "ideas.csv"
            list_path = root / "list.json"
            theses_path = root / "theses.json"
            items_path = root / "items.json"
            bad_path = root / "bad.json"
            csv_path.write_text(
                "\ufeffref,title,one_liner,example_customer,wedge,extra\n"
                "CSV-01,CSV Idea,CSV one liner,\"DTC brands, $500K-$5M\",CSV wedge,ignored\n",
                encoding="utf-8",
            )
            list_path.write_text(json.dumps([row]), encoding="utf-8")
            theses_path.write_text(json.dumps({"theses": [row]}), encoding="utf-8")
            items_path.write_text(json.dumps({"items": [row]}), encoding="utf-8")
            bad_path.write_text(json.dumps({"ideas": [row]}), encoding="utf-8")

            self.assertEqual(load_theses(csv_path)[0].ref, "CSV-01")
            self.assertEqual(load_theses(list_path)[0].ref, "R-01")
            self.assertEqual(load_theses(theses_path)[0].ref, "R-01")
            self.assertEqual(load_theses(items_path)[0].ref, "R-01")
            with self.assertRaises(ValueError):
                load_raw_records(bad_path)

    def test_validator_catches_bad_records_and_keeps_warning_records(self) -> None:
        records = [
            sample_record("OK-01"),
            {"ref": "MISS-01", "title": "Missing field", "one_liner": "No wedge", "example_customer": "DTC, $1M"},
            {"ref": "NULL-01", "title": "Null", "one_liner": "Null wedge", "example_customer": "DTC, $1M", "wedge": None},
            {"ref": "TYPE-01", "title": "Wrong type", "one_liner": 123, "example_customer": "DTC, $1M", "wedge": "Test"},
            {"ref": "EMPTY-01", "title": "", "one_liner": "Empty", "example_customer": "DTC, $1M", "wedge": "Test"},
            sample_record("OK-01"),
            {**sample_record("WARN-01"), "wedge": "huge " * 5},
        ]

        result = validate_records(records, max_field_chars=10)

        self.assertEqual(len(result.theses), 2)
        messages = [issue.message for issue in result.issues]
        self.assertIn("Missing required field.", messages)
        self.assertIn("Field is null.", messages)
        self.assertIn("Field is int, not string.", messages)
        self.assertIn("Field is empty.", messages)
        self.assertIn("Duplicate ref.", messages)
        self.assertTrue(any(issue.severity == "warning" for issue in result.issues))

    def test_revenue_parser_handles_more_formats_without_crashing(self) -> None:
        cases = [
            "EU retailers doing EUR 250K-2M",
            "Marketplace sellers, $1.5M+ GMV",
            "Operators doing $1,500K-$2.75M",
            "No clear revenue band",
            "DTC brands, €250K-€2M",
        ]

        for case in cases:
            revenue = parse_revenue_range(case)
            if revenue is not None:
                self.assertTrue(revenue.low is None or revenue.low >= 0)
                self.assertTrue(revenue.high is None or revenue.high >= 0)

    def test_outputs_round_trip_with_hostile_text(self) -> None:
        thesis = Thesis(
            ref="PIPE-01",
            title='Pipe | Quote " Title',
            one_liner="Line one\nLine two",
            example_customer="DTC brands, $500K-$5M",
            wedge="<b>HTML-ish</b> commas, pipes | and unicode café",
        )
        cards = Ranker().rank([thesis])

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            write_outputs(cards, out, top_n=1)
            self.assertEqual(json.loads((out / "ranking.json").read_text(encoding="utf-8"))[0]["ref"], "PIPE-01")
            with (out / "ranking.csv").open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["ref"], "PIPE-01")
            markdown = (out / "ranking.md").read_text(encoding="utf-8")
            self.assertIn("Pipe \\| Quote", markdown)

    def test_synthetic_records_rank_without_invariant_errors(self) -> None:
        source = [Thesis(**sample_thesis_kwargs("BASE-01"))]
        raw = generate_synthetic_records(source, 250, seed=105)
        result = validate_records(raw)
        cards = Ranker().rank(result.theses)

        self.assertFalse(check_invariants(cards, result.theses, scorecards_hash(cards), scorecards_hash(Ranker().rank(result.theses))))
        self.assertEqual(len(cards), 250)
        for card in cards:
            self.assertTrue(math.isfinite(card.final_score))
            self.assertGreaterEqual(card.final_score, 0)
            self.assertLessEqual(card.final_score, 100)

    def test_scores_are_stable_when_input_order_changes(self) -> None:
        raw = generate_synthetic_records([], 120, seed=106)
        result = validate_records(raw)
        first_cards = Ranker().rank(result.theses)
        shuffled = list(result.theses)
        random.Random(106).shuffle(shuffled)
        second_cards = Ranker().rank(shuffled)

        first_by_ref = {card.ref: card.to_dict()["criteria"] for card in first_cards}
        second_by_ref = {card.ref: card.to_dict()["criteria"] for card in second_cards}
        self.assertEqual(first_by_ref, second_by_ref)

    def test_stress_runner_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "ideas.json"
            out_dir = root / "stress"
            input_path.write_text(json.dumps([sample_record("SRC-01")]), encoding="utf-8")

            summary = run_stress(input_path=input_path, out_dir=out_dir, target_size=200, seed=107, top_n=25)

            self.assertEqual(summary["counts"]["ranked"], 200)
            self.assertFalse(summary["invariant_errors"])
            for filename in (
                "stress_summary.json",
                "validation_issues.csv",
                "ranking.json",
                "ranking.csv",
                "ranking.md",
                "ranking_audit.md",
            ):
                self.assertTrue((out_dir / filename).exists(), filename)


def sample_record(ref: str) -> dict[str, str]:
    return {
        "ref": ref,
        "title": "Margin Monitor",
        "one_liner": "SKU-level profit truth for sellers",
        "example_customer": "Marketplace and DTC sellers, $250K-$5M",
        "wedge": "Pulls fees, shipping, returns, COGS, and refunds into a live SKU P&L with approval-first actions.",
    }


def sample_thesis_kwargs(ref: str) -> dict[str, object]:
    record = sample_record(ref)
    return {**record, "is_new": False, "source_index": 0}


if __name__ == "__main__":
    unittest.main()
