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


class ViabilityConceptTests(unittest.TestCase):
    def test_inventory_forecast_fires_on_data_access_and_expansion(self) -> None:
        text = "predicts sell-through rate and reorder point with days of supply"
        self.assertIn("inventory_forecast_signal", fired(text, "data_access"))
        self.assertIn("inventory_forecast_signal", fired(text, "expansion_surface"))

    def test_agentic_ready_fires_on_platform_and_data_access(self) -> None:
        text = "improves product data completeness for agentic-ready answer engine optimization"
        self.assertIn("agentic_ready_data", fired(text, "platform_access"))
        self.assertIn("agentic_ready_data", fired(text, "data_access"))

    def test_zero_party_fires_on_data_diff_defensibility(self) -> None:
        text = "collects zero-party data via declared preferences and a post-purchase survey"
        self.assertIn("zero_party_data", fired(text, "data_access"))
        self.assertIn("zero_party_data", fired(text, "differentiation"))
        self.assertIn("zero_party_data", fired(text, "defensibility"))


class ExistingConceptAdditionTests(unittest.TestCase):
    def test_new_cost_save_triggers(self) -> None:
        self.assertIn("measurable_cost_save", fired("issues a returnless refund to deflect returns", "roi_visibility"))

    def test_new_revenue_lift_triggers(self) -> None:
        self.assertIn("measurable_revenue_lift", fired("a reactivation sequence for lapsed buyers", "roi_visibility"))

    def test_clone_signal_negative(self) -> None:
        labels = fired("a drop-in replacement, an alternative to gorgias at a fraction of the price", "differentiation")
        self.assertIn("-incumbent_clone_signal", labels)
        self.assertLess(adjustment("alternative to gorgias at a fraction of the price", "differentiation"), 0)

    def test_voice_build_negative(self) -> None:
        self.assertIn("-hard_realtime_ai_build", fired("voice commerce with conversational checkout", "buildability"))

    def test_autonomous_negative(self) -> None:
        self.assertIn("-autonomous_irreversible", fired("an autonomous buying agent that auto-issues refunds", "operational_simplicity"))

    def test_platform_gated_negative(self) -> None:
        self.assertIn("-platform_gated_build", fired("built on the agentic checkout protocol", "platform_access"))

    def test_novelty_negative(self) -> None:
        self.assertIn("-novelty_consumer_behavior", fired("a spin to win wheel of fortune popup", "roi_visibility"))


class SaturatedCategoryTests(unittest.TestCase):
    EXPECTED = {
        "post-purchase upsell on the thank-you page": "post_purchase_upsell",
        "a drag-and-drop page builder": "page_builder",
        "a self-service returns portal with rma": "returns_portal",
        "a branded order tracking page": "order_tracking_page",
        "an ai chatbot support agent": "ai_chatbot_support",
        "shipping protection at checkout": "shipping_protection",
        "an exit-intent email capture popup": "popup_email_capture",
        "an seo optimizer with auto meta tags": "seo_optimizer",
        "server-side tracking via conversions api": "server_side_tracking",
        "a frequently bought together cross-sell app": "product_reco_engine",
    }

    def test_each_new_category_detected(self) -> None:
        for text, name in self.EXPECTED.items():
            hit = detect_saturation(text)
            self.assertIsNotNone(hit, f"no saturation hit for: {text}")
            self.assertEqual(hit.name, name, f"wrong category for: {text}")

    def test_saturated_category_adds_trap_and_cap(self) -> None:
        thesis = Thesis(
            ref="SAT-1", title="Page Builder Pro",
            one_liner="a drag-and-drop page builder",
            example_customer="US DTC brands, $500k-$5m",
            wedge="a drag-and-drop page builder for landing pages",
        )
        card = Ranker().rank([thesis])[0]
        self.assertTrue(any(t.name == "saturated category" for t in card.traps))


class RawKeywordTests(unittest.TestCase):
    def test_buyer_pain_raw_additions(self) -> None:
        self.assertGreater(buyer_pain("we detect return fraud and compute landed cost on de minimis tariff parcels"), 43)

    def test_roi_raw_additions(self) -> None:
        self.assertGreater(roi_visibility("reports contribution margin, returnless refund savings, store credit, and duty drawback"), 42)

    def test_buildability_raw_positive_and_negative(self) -> None:
        pos = buildability("a reorder point tool with a post-purchase survey")
        neg = buildability("voice commerce with conversational checkout")
        self.assertGreater(pos, 62)
        self.assertLess(neg, 62)

    def test_defensibility_raw_positive_and_negative(self) -> None:
        pos = defensibility("builds a cohort retention model on zero-party data")
        neg = defensibility("a drop-in replacement, an alternative to the leader")
        self.assertGreater(pos, 50)
        self.assertLess(neg, 50)


EXCLUDED_BARE_TOKENS = {"ai", "ai-powered", "boost aov", "seo", "capi", "chatbot", "duty"}


class GuardTests(unittest.TestCase):
    def test_no_duplicate_trigger_within_a_concept(self) -> None:
        for name, concept in CONCEPTS.items():
            self.assertEqual(
                len(concept.triggers), len(set(concept.triggers)),
                f"duplicate trigger inside concept {name}",
            )

    def test_excluded_bare_tokens_are_not_standalone_triggers(self) -> None:
        all_triggers = {t for c in CONCEPTS.values() for t in c.triggers}
        for data in SATURATED_CATEGORIES.values():
            all_triggers.update(data["triggers"])
        for token in EXCLUDED_BARE_TOKENS:
            self.assertNotIn(token, all_triggers, f"excluded bare token present: {token}")

    def test_concept_adjustment_is_bounded(self) -> None:
        text = (
            "contribution margin blended mer cac payback landed cost "
            "returnless refund serial returner order bump store credit"
        )
        self.assertLessEqual(adjustment(text, "roi_visibility"), 25.0)
        self.assertGreaterEqual(adjustment(text, "buildability"), -15.0)

    def test_no_duplicate_trigger_within_a_saturated_category(self) -> None:
        for name, data in SATURATED_CATEGORIES.items():
            triggers = tuple(data["triggers"])
            self.assertEqual(
                len(triggers), len(set(triggers)),
                f"duplicate trigger inside saturated category {name}",
            )

    def test_every_wired_concept_name_exists(self) -> None:
        for criterion, cfg in CRITERION_CONCEPTS.items():
            for name in (*cfg.get("positive", ()), *cfg.get("negative", ())):
                self.assertIn(name, CONCEPTS, f"{criterion} wires unknown concept {name}")


if __name__ == "__main__":
    unittest.main()
