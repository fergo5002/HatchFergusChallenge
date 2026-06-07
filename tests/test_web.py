from __future__ import annotations

import unittest
from unittest.mock import patch

from hatch_ranker.ai_scan import AIScanError, Observation
from hatch_ranker.web import ai_scan_payload, extract_records, rank_payload


def sample_record(ref: str) -> dict[str, str]:
    return {
        "ref": ref,
        "title": "Catalog Guard",
        "one_liner": "Catalog health agent for Shopify stores",
        "example_customer": "DTC brands, $500K-$5M",
        "wedge": "Crawls product catalog every night for broken links, missing images, zero-inventory products, and prices below cost; sends a morning fix list.",
    }


class WebApiTests(unittest.TestCase):
    def test_extract_records_accepts_supported_json_roots(self) -> None:
        row = sample_record("R-01")

        self.assertEqual(extract_records([row]), [row])
        self.assertEqual(extract_records({"theses": [row]}), [row])
        self.assertEqual(extract_records({"items": [row]}), [row])

    def test_rank_payload_returns_ranking_shape(self) -> None:
        status, body = rank_payload([sample_record("R-01")])

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)
        card = body["ranking"][0]
        self.assertEqual(card["rank"], 1)
        self.assertEqual(card["ref"], "R-01")
        self.assertIn("criteria", card)
        self.assertIn("score_logic", card)
        self.assertEqual(card["score_logic"]["weights"]["cash_velocity"], 0.48)
        self.assertIn("source", card)

    def test_rank_payload_marks_appended_records_new(self) -> None:
        base = sample_record("B-01")
        appended = {**sample_record("N-01"), "is_new": True}

        status, body = rank_payload({"items": [base, appended]})

        self.assertEqual(status, 200)
        by_ref = {card["ref"]: card for card in body["ranking"]}
        self.assertFalse(by_ref["B-01"]["is_new"])
        self.assertTrue(by_ref["N-01"]["is_new"])

    def test_rank_payload_reports_duplicate_refs_without_ranking(self) -> None:
        status, body = rank_payload([sample_record("DUP"), sample_record("DUP")])

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["ranking"], [])
        self.assertTrue(any(issue["field"] == "ref" for issue in body["issues"]))

    def test_rank_payload_reports_missing_required_field(self) -> None:
        broken = sample_record("BROKEN")
        del broken["wedge"]

        status, body = rank_payload({"theses": [broken]})

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertTrue(any(issue["field"] == "wedge" for issue in body["issues"]))

    def test_ai_scan_payload_rejects_missing_cards(self) -> None:
        status, body = ai_scan_payload({"ranking": []})

        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertEqual(body["observations"], [])

    def test_ai_scan_payload_returns_observations(self) -> None:
        with patch(
            "hatch_ranker.web.scan_cards",
            return_value=[
                Observation(
                    ref="R-01",
                    kind="risk",
                    note="The wedge implies regulated workflow that the fixed trap list misses.",
                )
            ],
        ) as scan_cards:
            status, body = ai_scan_payload({"ranking": [{"ref": "R-01"}]})

        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["observations"][0]["ref"], "R-01")
        self.assertEqual(body["observations"][0]["kind"], "risk")
        scan_cards.assert_called_once_with([{"ref": "R-01"}])

    def test_ai_scan_payload_reports_scan_error(self) -> None:
        with patch("hatch_ranker.web.scan_cards", side_effect=AIScanError("missing API key")):
            status, body = ai_scan_payload({"ranking": [{"ref": "R-01"}]})

        self.assertEqual(status, 502)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "missing API key")


if __name__ == "__main__":
    unittest.main()
