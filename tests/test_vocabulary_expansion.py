from __future__ import annotations

import unittest

from hatch_ranker.concepts import (
    CONCEPTS,
    CRITERION_CONCEPTS,
    SATURATED_CATEGORIES,
    concept_adjustment,
    detect_saturation,
)
from hatch_ranker.models import Thesis
from hatch_ranker.ranker import (
    Ranker,
    buyer_pain,
    buildability,
    defensibility,
    roi_visibility,
)


def fired(text: str, criterion: str) -> list[str]:
    return concept_adjustment(text, criterion)[1]


def adjustment(text: str, criterion: str) -> float:
    return concept_adjustment(text, criterion)[0]


class CashVelocityConceptTests(unittest.TestCase):
    def test_profit_analytics_fires_on_buyer_pain_and_roi(self) -> None:
        text = "tracks contribution margin and blended mer with cac payback per channel"
        self.assertIn("profit_analytics_pain", fired(text, "buyer_pain"))
        self.assertIn("profit_analytics_pain", fired(text, "roi_visibility"))
        self.assertGreater(adjustment(text, "roi_visibility"), 0)

    def test_returns_abuse_fires_on_buyer_pain_and_defensibility(self) -> None:
        text = "scores serial returner and wardrobing patterns to flag return fraud"
        self.assertIn("returns_abuse_pain", fired(text, "buyer_pain"))
        self.assertIn("returns_abuse_pain", fired(text, "defensibility"))

    def test_post_purchase_revenue_fires_on_roi_and_expansion(self) -> None:
        text = "adds an order bump and a post-purchase upsell on the thank-you page"
        self.assertIn("post_purchase_revenue", fired(text, "roi_visibility"))
        self.assertIn("post_purchase_revenue", fired(text, "expansion_surface"))

    def test_cross_border_duty_fires_on_buyer_pain_and_roi(self) -> None:
        text = "shows landed cost and de minimis duties with hts code lookup"
        self.assertIn("cross_border_duty_pain", fired(text, "buyer_pain"))
        self.assertIn("cross_border_duty_pain", fired(text, "roi_visibility"))

    def test_eu_regulatory_fires_on_buyer_pain(self) -> None:
        text = "handles gpsr responsible person and european accessibility act wcag 2.1 audits"
        self.assertIn("eu_regulatory_pain", fired(text, "buyer_pain"))


if __name__ == "__main__":
    unittest.main()
