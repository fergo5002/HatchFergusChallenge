"""Tests for the v2 algorithm improvements: concept-anchor blend,
saturated-category trap, and tier system.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hatch_ranker.concepts import (
    SATURATED_CATEGORIES,
    concept_adjustment,
    detect_saturation,
)
from hatch_ranker.io import load_theses
from hatch_ranker.ranker import Ranker


def _load_thesis(record):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "one.json"
        path.write_text(json.dumps([record]), encoding="utf-8")
        return load_theses(path)[0]


class ConceptAnchorTests(unittest.TestCase):
    def test_concept_adjustment_is_positive_when_pain_concepts_fire(self) -> None:
        text = "out of stock pain, refund volume, customer service ticket queue"
        adjustment, fired = concept_adjustment(text, "buyer_pain")
        self.assertGreater(adjustment, 0)
        self.assertIn("refund_return_pain", fired)
        self.assertIn("inventory_oos_pain", fired)

    def test_concept_adjustment_penalizes_aesthetic_roi(self) -> None:
        text = "beautiful share card and brand aesthetic moment"
        adjustment, fired = concept_adjustment(text, "roi_visibility")
        self.assertLess(adjustment, 0)
        self.assertTrue(any(name.startswith("-aesthetic_no_metric") for name in fired))

    def test_concept_adjustment_returns_zero_when_no_concepts_match(self) -> None:
        text = "lorem ipsum dolor sit amet with no relevant vocabulary"
        adjustment, fired = concept_adjustment(text, "buyer_pain")
        self.assertEqual(adjustment, 0)
        self.assertEqual(fired, [])

    def test_concept_layer_lifts_synonym_drift_thesis(self) -> None:
        """A new-language thesis with no original keywords should still get
        credit when its underlying concepts fire."""

        synonym = _load_thesis(
            {
                "ref": "SYN-A",
                "title": "ClaimRescue",
                "one_liner": "Warranty claim deflection for kitchenware brands",
                "example_customer": "US homeware DTC brands, $500K-$5M",
                "wedge": (
                    "Reads every refund and exchange against a rules engine, "
                    "drafts a credit-or-replace decision the merchant approves "
                    "from a queue, recovers margin nightly per-customer."
                ),
            }
        )
        card = Ranker().score(synonym)
        self.assertGreater(card.criteria["buyer_pain"], 60)
        self.assertGreater(card.criteria["roi_visibility"], 55)
        self.assertTrue(card.fired_concepts["buyer_pain"])

    def test_score_records_fired_concepts_for_inspectability(self) -> None:
        thesis = _load_thesis(
            {
                "ref": "C-A",
                "title": "Catalog Guard",
                "one_liner": "Nightly catalog audit",
                "example_customer": "DTC brands, $200K-$3M",
                "wedge": "Crawls Shopify catalog, finds broken links and missing images, drafts fix list, approval queue.",
            }
        )
        card = Ranker().score(thesis)
        self.assertIn("catalog_quality_pain", card.fired_concepts["buyer_pain"])
        self.assertIn("approval_workflow", card.fired_concepts["operational_simplicity"])


class SaturationTrapTests(unittest.TestCase):
    def test_saturated_back_in_stock_is_detected(self) -> None:
        hit = detect_saturation(
            "one widget for back-in-stock, wishlist, and preorder"
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit.name, "back_in_stock_unified_demand")

    def test_no_saturation_for_catalog_health(self) -> None:
        hit = detect_saturation(
            "nightly catalog audit, broken links, missing alt text, fix list"
        )
        self.assertIsNone(hit)

    def test_saturation_trap_caps_otherwise_strong_thesis(self) -> None:
        thesis = _load_thesis(
            {
                "ref": "H-49-CLONE",
                "title": "Restock OS",
                "one_liner": "Wishlist + back-in-stock + preorder unified",
                "example_customer": "US apparel/footwear DTC brands, $200K-$3M",
                "wedge": (
                    "One PDP widget auto-chooses between Save / Notify / "
                    "Pre-order based on inventory state, turning three apps "
                    "merchants pay for separately into a unified demand inbox."
                ),
            }
        )
        card = Ranker().score(thesis)
        self.assertTrue(any(trap.name == "saturated category" for trap in card.traps))
        self.assertLessEqual(card.viability_cap, 72)

    def test_saturation_does_not_fire_on_compliance_thesis(self) -> None:
        thesis = _load_thesis(
            {
                "ref": "RC-1",
                "title": "Recall Ledger",
                "one_liner": "Recall and incident-response OS for consumables brands",
                "example_customer": "Supplements and pet food brands, $500K-$10M",
                "wedge": "Regulator packets, affected customer lists, proof trails from batch IDs.",
            }
        )
        card = Ranker().score(thesis)
        self.assertFalse(any(trap.name == "saturated category" for trap in card.traps))

    def test_strong_differentiation_halves_saturation_penalty(self) -> None:
        """When differentiation/defensibility is strong, the penalty is
        halved (the trap still fires but the merchant has earned a wedge)."""

        regular = _load_thesis(
            {
                "ref": "S-WEAK",
                "title": "Restock Clone",
                "one_liner": "Back-in-stock notifier",
                "example_customer": "DTC brands, $200K-$3M",
                "wedge": "Send a back in stock email.",
            }
        )
        diff = _load_thesis(
            {
                "ref": "S-STRONG",
                "title": "Restock Clone",
                "one_liner": "Back-in-stock notifier with merchant's own per-customer demand model",
                "example_customer": "DTC brands, $200K-$3M",
                "wedge": (
                    "Builds per-customer per-sku demand inbox from the store's "
                    "own first-party order history with category-normalized "
                    "rules nightly."
                ),
            }
        )
        weak_card = Ranker().score(regular)
        strong_card = Ranker().score(diff)
        weak_pen = next(t.penalty for t in weak_card.traps if t.name == "saturated category")
        strong_pen = next(t.penalty for t in strong_card.traps if t.name == "saturated category")
        self.assertLess(strong_pen, weak_pen)


class TierAnnotationTests(unittest.TestCase):
    def test_tier_top_strong_watch_trap_after_rank(self) -> None:
        theses = []
        for index in range(20):
            theses.append(
                _load_thesis(
                    {
                        "ref": f"T-{index:02d}",
                        "title": f"Thesis {index}",
                        "one_liner": "Pain and ROI" if index < 10 else "vague aesthetic moment",
                        "example_customer": "US DTC brands, $500K-$5M" if index < 10
                            else "DTC brands, sub-$500K",
                        "wedge": (
                            "Recovers refund volume, dunning failed-payment, csv import, one-click."
                            if index < 10
                            else "share card animated card mystery discount."
                        ),
                    }
                )
            )
        cards = Ranker().rank(theses)
        self.assertEqual(cards[0].rank, 1)
        self.assertEqual(cards[-1].rank, len(cards))
        for card in cards:
            self.assertIn(card.tier, {"Top Tier", "Strong", "Watch", "Trap"})
        self.assertEqual(cards[0].tier, "Top Tier")
        self.assertGreaterEqual(cards[0].percentile, 90)

    def test_severe_trap_with_low_score_forces_trap_tier(self) -> None:
        swamp = _load_thesis(
            {
                "ref": "SW-01",
                "title": "AR Voice Founder",
                "one_liner": "Realtime AR + voice clone for every PDP",
                "example_customer": "DTC brands, $100K-$5M",
                "wedge": "Generative 3D mesh, drape AR try-on, voice clone, zero human in the loop.",
            }
        )
        cards = Ranker().rank([swamp])
        # severe trap + low score overrides percentile, even when alone
        self.assertEqual(cards[0].tier, "Trap")

        # Now with a mixed set
        practical = _load_thesis(
            {
                "ref": "PR-01",
                "title": "Catalog Guard",
                "one_liner": "Catalog audit",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Crawls catalog nightly, drafts fix list, approval queue, one-click fixes.",
            }
        )
        cards = Ranker().rank([practical, swamp])
        self.assertEqual(cards[0].ref, "PR-01")
        self.assertEqual(cards[0].tier, "Top Tier")
        # The swamp card is at percentile 50 in a 2-card corpus, so tier is
        # Watch unless severe trap drags it down. Since final_score is low
        # (well below 50) AND it has technical swamp, expect Trap tier.
        self.assertEqual(cards[1].tier, "Trap")


if __name__ == "__main__":
    unittest.main()
