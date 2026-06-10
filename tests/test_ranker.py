from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from hatch_ranker.io import load_theses
from hatch_ranker.ranker import Ranker, parse_revenue_range


class RankerTests(unittest.TestCase):
    def test_revenue_range_parser_handles_common_bands(self) -> None:
        revenue = parse_revenue_range("US DTC brands, $500K-$5M")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 500_000)
        self.assertEqual(revenue.high, 5_000_000)

        sub = parse_revenue_range("DTC brands, sub-$500K")
        self.assertIsNotNone(sub)
        self.assertEqual(sub.low, 0)
        self.assertEqual(sub.high, 500_000)

        open_ended = parse_revenue_range("DTC brands, $5M+")
        self.assertIsNotNone(open_ended)
        self.assertEqual(open_ended.low, 5_000_000)
        self.assertIsNone(open_ended.high)

    def test_loader_accepts_csv_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            csv_path = root / "theses.csv"
            json_path = root / "theses.json"
            row = {
                "ref": "T-01",
                "title": "Restock Hub",
                "one_liner": "Wishlist + back-in-stock + preorder unified",
                "example_customer": "US apparel DTC brands, $200K-$3M",
                "wedge": "One PDP widget chooses Save, Notify, or Pre-order from inventory state.",
            }
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            json_path.write_text(json.dumps([row]), encoding="utf-8")

            self.assertEqual(load_theses(csv_path)[0].title, "Restock Hub")
            self.assertEqual(load_theses(json_path)[0].ref, "T-01")

    def test_practical_revenue_wedge_beats_technical_swamp(self) -> None:
        practical = {
            "ref": "P-01",
            "title": "Catalog Guard",
            "one_liner": "Catalog health agent for Shopify stores",
            "example_customer": "US DTC brands, $500K-$5M",
            "wedge": "Crawls product catalog every night for broken links, missing images, zero-inventory products, and prices below cost; sends a morning fix list with one-click bulk fixes.",
        }
        swamp = {
            "ref": "S-01",
            "title": "Live AR Founder",
            "one_liner": "Realtime voice and AR try-on for every PDP",
            "example_customer": "apparel DTC brands, $100K-$5M",
            "wedge": "Generative 3D mesh, drape-capable AR try-on, and realtime founder voice answers shopper questions with zero human input.",
        }
        theses = [load_thesis_dict(practical), load_thesis_dict(swamp)]
        ranked = Ranker().rank(theses)

        self.assertEqual(ranked[0].ref, "P-01")
        self.assertLess(ranked[1].viability_cap, ranked[0].viability_cap)
        self.assertTrue(ranked[1].traps)

    def test_appended_theses_are_marked_new(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.json"
            live = root / "live.json"
            base.write_text(
                json.dumps(
                    [
                        {
                            "ref": "B-01",
                            "title": "B2B Portal",
                            "one_liner": "B2B pricing in 30 minutes",
                            "example_customer": "US DTC brands, $500K-$5M",
                            "wedge": "CSV import, tiered pricing, MOQ, and invoice links.",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            live.write_text(
                json.dumps(
                    [
                        {
                            "ref": "N-01",
                            "title": "Novelty Discount",
                            "one_liner": "Mystery discount game",
                            "example_customer": "DTC brands, $50K-$500K",
                            "wedge": "Customers guess an answer to unlock a random discount.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            theses = load_theses(base)
            theses.extend(load_theses(live, is_new=True, start_index=len(theses)))
            ranked = Ranker().rank(theses)

            self.assertEqual(len(ranked), 2)
            self.assertEqual(sum(1 for card in ranked if card.thesis and card.thesis.is_new), 1)

    def test_marketplace_thesis_is_not_explained_as_dtc_only(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "M-01",
                "title": "MarginMap",
                "one_liner": "SKU-level profit truth for Amazon and Etsy sellers",
                "example_customer": "Marketplace-first sellers doing $250K-$5M GMV",
                "wedge": "Pulls marketplace fees, refunds, storage, shipping, returns, promos, and COGS into a SKU P&L.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("marketplace", card.tags)
        self.assertNotIn("DTC buyer", card.rationale)

    def test_compliance_thesis_gets_explicit_scope_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "C-01",
                "title": "RecallReady",
                "one_liner": "Recall and incident-response OS for consumables brands",
                "example_customer": "Supplements and pet food brands, $500K-$10M",
                "wedge": "Creates recall-ready regulator packets, affected customer lists, and proof trails from batch IDs and complaints.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("compliance", card.tags)
        self.assertTrue(any(trap.name == "compliance scope" for trap in card.traps))

    def test_permit_and_regulatory_language_gets_compliance_scope_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "C-02",
                "title": "HealthPermit Copilot",
                "one_liner": "Drafting assistant for renewal filing and inspection prep",
                "example_customer": "Restaurants and commissary kitchens, $100K-$10M",
                "wedge": "Drafts renewal filing, violation fixes, staff certification, permit checklists, and inspection prep from local requirements.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("compliance", card.tags)
        self.assertTrue(any(trap.name == "compliance scope" for trap in card.traps))

    def test_multi_channel_marketplace_language_gets_platform_breadth_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "M-02",
                "title": "PromoStack Copilot",
                "one_liner": "Discount-stack monitor across marketplaces and shops",
                "example_customer": "Brands selling on Shopify, Amazon, TikTok Shop, Faire, and wholesale portals, $300K-$8M",
                "wedge": "Connects coupon rules, marketplace promos, affiliate codes, wholesale terms, ad calendars, and order exports.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("marketplace", card.tags)
        self.assertTrue(any(trap.name == "platform breadth" for trap in card.traps))

    def test_shopify_dtc_alone_does_not_get_platform_breadth_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "P-01",
                "title": "ListingGuard",
                "one_liner": "Catalog health agent for Shopify stores",
                "example_customer": "DTC brands, $100K-$5M",
                "wedge": "Crawls a Shopify store catalog nightly and sends a fix list for broken product images.",
            }
        )
        card = Ranker().score(thesis)

        self.assertFalse(any(trap.name == "platform breadth" for trap in card.traps))

    def test_marketplace_policy_surface_gets_light_platform_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "M-03",
                "title": "AccountHealth Copilot",
                "one_liner": "Drafting assistant for listing fixes and appeal evidence",
                "example_customer": "Marketplace-first brands and aggregators, $500K-$25M GMV",
                "wedge": "Drafts listing fixes, appeal evidence, buyer responses, and shipping defect triage from account health dashboards, policy emails, and listing edits.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("marketplace", card.tags)
        self.assertTrue(any(trap.name == "marketplace platform" for trap in card.traps))

    def test_multiple_marketplace_platform_names_get_platform_breadth_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "M-05",
                "title": "FeeLeak Copilot",
                "one_liner": "Drafting assistant for marketplace fee disputes",
                "example_customer": "Amazon, Walmart, eBay, and Etsy sellers doing $250K-$10M GMV",
                "wedge": "Drafts fee disputes from settlement files, ad spend, referral fees, storage charges, refunds, shipping labels, and COGS.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("marketplace", card.tags)
        self.assertTrue(any(trap.name == "platform breadth" for trap in card.traps))

    def test_generic_marketplace_customer_does_not_lower_platform_access(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "M-04",
                "title": "ClaimEvidence Signal",
                "one_liner": "Early-warning monitor for claims without proof",
                "example_customer": "consumer brands, suppliers, hospitality groups, and marketplaces, $500K-$50M",
                "wedge": "Links each public claim to evidence and flags missing support before publishing.",
            }
        )
        card = Ranker().score(thesis)

        self.assertIn("marketplace", card.tags)
        self.assertGreaterEqual(card.criteria["platform_access"], 70)
        self.assertFalse(any(trap.name == "marketplace platform" for trap in card.traps))


class FalsePositiveRegressionTests(unittest.TestCase):
    def test_innocent_words_do_not_trigger_compliance_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "FP-01",
                "title": "Private Label Insights",
                "one_liner": "An innovative dashboard to elevate private label brands",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Built by a serial entrepreneur; shows each product detail page conversion.",
            }
        )
        card = Ranker().score(thesis)
        self.assertFalse(any(trap.name == "compliance scope" for trap in card.traps))
        self.assertNotIn("compliance", card.tags)

    def test_email_alone_does_not_get_ai_tag(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "FP-02",
                "title": "Email Digest",
                "one_liner": "A weekly email digest of store changes",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Sends a templated email summary of catalog changes every Monday.",
            }
        )
        card = Ranker().score(thesis)
        self.assertNotIn("ai", card.tags)

    def test_negated_setup_burden_is_not_penalized(self) -> None:
        with_negation = load_thesis_dict(
            {
                "ref": "FP-03",
                "title": "Hands-Off Sync",
                "one_liner": "Catalog sync with no manual upload needed",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Reads the product catalog directly; no manual upload, no merchant uploads.",
            }
        )
        without_mention = load_thesis_dict(
            {
                "ref": "FP-04",
                "title": "Hands-Off Sync",
                "one_liner": "Catalog sync that just works",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Reads the product catalog directly.",
            }
        )
        scored_neg = Ranker().score(with_negation)
        scored_plain = Ranker().score(without_mention)
        self.assertGreaterEqual(
            scored_neg.criteria["low_setup_friction"],
            scored_plain.criteria["low_setup_friction"],
        )


    def test_restocking_thesis_still_hits_saturation_trap(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "FP-05",
                "title": "Restocking Alerts",
                "one_liner": "Restocking alerts for sold-out products",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Watches inventory and emails shoppers when restocking happens.",
            }
        )
        card = Ranker().score(thesis)
        self.assertTrue(any(trap.name == "saturated category" for trap in card.traps))

    def test_supplier_poses_is_not_an_ops_penalty(self) -> None:
        thesis = load_thesis_dict(
            {
                "ref": "FP-06",
                "title": "Delay Radar",
                "one_liner": "Flags when the supplier poses a delay risk",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Reads shipping notices and flags when the supplier poses a delay risk early.",
            }
        )
        baseline = load_thesis_dict(
            {
                "ref": "FP-07",
                "title": "Delay Radar",
                "one_liner": "Flags supplier delay risk",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "Reads shipping notices and flags delay risk early.",
            }
        )
        scored = Ranker().score(thesis)
        scored_baseline = Ranker().score(baseline)
        self.assertEqual(
            scored.criteria["operational_simplicity"],
            scored_baseline.criteria["operational_simplicity"],
        )


def load_thesis_dict(record):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "one.json"
        path.write_text(json.dumps([record]), encoding="utf-8")
        return load_theses(path)[0]


class StuffingDefenseTests(unittest.TestCase):
    STUFFED = {
        "ref": "GAME-1",
        "title": "Merchant Profit Recovery Dashboard",
        "one_liner": (
            "Recovers revenue and margin from failed payments, returns, dunning, "
            "churn and refund leakage with visible ROI"
        ),
        "example_customer": "US apparel and beauty DTC brands on Shopify, $500K-$5M",
        "wedge": (
            "One-click native Shopify theme app extension widget with CSV import reads "
            "shopify orders and product catalog via webhook and metafield rules; approval "
            "queue drafts fixes the merchant approves; nightly per-sku per-customer "
            "dashboard from the merchant's own data shows recovered revenue, expected "
            "savings, contribution margin, aov, reorder and conversion lift, with "
            "a profit truth scorecard, morning fix list and one-click bulk fixes."
        ),
    }
    FOCUSED = {
        "ref": "REAL-1",
        "title": "Failed Payment Recovery",
        "one_liner": "Recovers failed subscription payments for Shopify brands",
        "example_customer": "US DTC subscription brands, $500K-$5M",
        "wedge": (
            "A failed-payment webhook listener sends a three-step recovery email "
            "sequence and reports dollars recovered each week."
        ),
    }

    NON_PAIN_STUFFED = {
        "ref": "GAME-2",
        "title": "Merchant Margin Copilot",
        "one_liner": (
            "Recovers revenue from failed payments with contribution margin, cac payback, "
            "and per-sku profitability lift for true profitability"
        ),
        "example_customer": "US apparel and beauty mid-market DTC brands on Shopify, $500K-$5M",
        "wedge": (
            "One-click native shopify theme app extension widget with csv import, webhook "
            "and metafield rules reads shopify orders and the product catalog; approval "
            "queue with human in the loop drafts fixes; nightly per-customer dashboard from "
            "the merchant's own data and zero-party data post-purchase survey; demand "
            "forecast and reorder point safety stock; agentic-ready product data "
            "completeness; post-purchase upsell store credit recovery; "
            "category-normalized first-party signals in one dashboard command center."
        ),
    }

    def test_stuffed_thesis_gets_unfocused_wedge_trap(self) -> None:
        card = Ranker().score(load_thesis_dict(self.STUFFED))
        self.assertTrue(any(trap.name == "unfocused wedge" for trap in card.traps))

    def test_stuffed_thesis_ranks_below_focused_thesis(self) -> None:
        cards = Ranker().rank(
            [load_thesis_dict(self.FOCUSED), load_thesis_dict(self.STUFFED)]
        )
        self.assertEqual(cards[0].ref, "REAL-1")

    def test_three_pain_domains_do_not_trigger_the_trap(self) -> None:
        card = Ranker().score(
            load_thesis_dict(
                {
                    "ref": "OK-1",
                    "title": "Margin Truth",
                    "one_liner": "SKU-level profit control for marketplace sellers",
                    "example_customer": "Amazon and Etsy sellers doing $250K-$5M GMV",
                    "wedge": (
                        "Pulls fees, ads, returns, storage, shipping, refunds, and COGS "
                        "into a SKU P&L, then drafts kill, raise, or reprice actions."
                    ),
                }
            )
        )
        self.assertFalse(any(trap.name == "unfocused wedge" for trap in card.traps))


    def test_non_pain_stuffer_gets_stuffed_vocabulary_trap(self) -> None:
        card = Ranker().score(load_thesis_dict(self.NON_PAIN_STUFFED))
        self.assertTrue(any(trap.name == "stuffed vocabulary" for trap in card.traps))

    def test_non_pain_stuffer_ranks_below_focused_thesis(self) -> None:
        cards = Ranker().rank(
            [load_thesis_dict(self.FOCUSED), load_thesis_dict(self.NON_PAIN_STUFFED)]
        )
        self.assertEqual(cards[0].ref, "REAL-1")

    KEYWORD_STUFFED = {
        "ref": "GAME-3",
        "title": "Ops Copilot",
        "one_liner": "Operations dashboard for Shopify brands",
        "example_customer": "US DTC brands, $500K-$5M",
        "wedge": (
            "Pulls the Shopify Orders API and the product catalog, tracks inventory "
            "state and profit truth, and applies rules to generate checklists, exports, "
            "and negotiation briefs for the buyer. It also handles subscription pause "
            "and upsell offers. Zero curation and no customer portal to maintain."
        ),
    }

    JOINT_BUDGET_STUFFED = {
        "ref": "GAME-4",
        "title": "Failed Payment Recovery",
        "one_liner": (
            "A webhook listener reads Shopify orders and the product catalog, "
            "joins store's collections with historical cohort retention, and "
            "computes contribution margin and reorder point for each style."
        ),
        "example_customer": "US DTC brands, $500K-$5M",
        "wedge": (
            "Merchants work from one unified native screen with rules, checklists, "
            "loyalty data they can migrate in, and exports for their accountant."
        ),
    }

    def test_residual_attacks_stay_under_ceiling(self) -> None:
        # The strongest known under-all-budgets attacks (see plan Amendments, Task
        # 4c/4d). The ceiling is the measured residual bound; if a vocabulary or
        # threshold change pushes either fixture above it, recalibrate the breadth
        # budgets before trusting the ranking.
        for fixture in (self.KEYWORD_STUFFED, self.JOINT_BUDGET_STUFFED):
            card = Ranker().score(load_thesis_dict(fixture))
            self.assertLessEqual(
                card.final_score, 82.0, f"{fixture['ref']} broke the residual ceiling"
            )

    def test_joint_budget_attack_gets_rubric_saturation_penalty(self) -> None:
        card = Ranker().score(load_thesis_dict(self.JOINT_BUDGET_STUFFED))
        self.assertTrue(any(trap.name == "rubric saturation" for trap in card.traps))

    def test_extreme_stuffers_are_trapped_by_rubric_saturation(self) -> None:
        for fixture in (self.STUFFED, self.NON_PAIN_STUFFED):
            card = Ranker().score(load_thesis_dict(fixture))
            self.assertTrue(
                any(trap.name == "rubric saturation" for trap in card.traps),
                f"{fixture['ref']} should trip rubric saturation",
            )

    def test_no_legitimate_template_gets_rubric_saturation(self) -> None:
        from hatch_ranker.stress import DOMAIN_TEMPLATES

        for index, template in enumerate(DOMAIN_TEMPLATES):
            record = dict(template, ref=f"TPL-{index}")
            card = Ranker().score(load_thesis_dict(record))
            self.assertFalse(
                any(trap.name == "rubric saturation" for trap in card.traps),
                f"{template['title']} wrongly flagged as rubric saturation",
            )

    def test_legit_broad_compliance_wedge_is_not_called_stuffed(self) -> None:
        recall_ledger = load_thesis_dict(
            {
                "ref": "LEGIT-1",
                "title": "Recall Ledger",
                "one_liner": "Recall readiness for regulated consumables brands",
                "example_customer": "Supplements and pet food brands, $500K-$10M",
                "wedge": (
                    "Builds regulator packets, affected customer lists, lot-level proof "
                    "trails, refund workflows, and retailer notices from batch IDs, "
                    "supplier COAs, complaints, and orders."
                ),
            }
        )
        card = Ranker().score(recall_ledger)
        self.assertFalse(any(trap.name == "stuffed vocabulary" for trap in card.traps))
        for trap in card.traps:
            self.assertNotIn("stuffed", trap.reason)


class MoneyParserTests(unittest.TestCase):
    def test_durations_and_distances_are_not_revenue(self) -> None:
        self.assertIsNone(parse_revenue_range("ships in 3 months"))
        self.assertIsNone(parse_revenue_range("set up in 5 minutes"))
        self.assertIsNone(parse_revenue_range("within 10 km radius"))

    def test_comma_amounts_parse_fully(self) -> None:
        revenue = parse_revenue_range("Operators doing $1,500K-$2.75M")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 1_500_000)
        self.assertEqual(revenue.high, 2_750_000)

    def test_pound_symbol_is_supported(self) -> None:
        revenue = parse_revenue_range("UK brands doing £500K-£5M")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 500_000)

    def test_spelled_out_million_parses(self) -> None:
        revenue = parse_revenue_range("brands doing $1.5 million ARR")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 1_500_000)

    def test_bare_under_does_not_zero_the_floor(self) -> None:
        revenue = parse_revenue_range("under 10 minutes setup, brands doing $2M")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 2_000_000)

    def test_full_digit_amounts_parse(self) -> None:
        revenue = parse_revenue_range("US DTC brands, $500,000-$5,000,000")
        self.assertIsNotNone(revenue)
        self.assertEqual(revenue.low, 500_000)
        self.assertEqual(revenue.high, 5_000_000)


class MarketAccessBandTests(unittest.TestCase):
    def test_mid_market_premium_band_is_reachable(self) -> None:
        from hatch_ranker.ranker import market_access, RevenueRange

        premium = market_access("US DTC brands", RevenueRange(500_000, 5_000_000))
        standard = market_access("US DTC brands", RevenueRange(100_000, 5_000_000))
        self.assertGreater(premium, standard)


class OverfitVocabularyTests(unittest.TestCase):
    def test_vertical_nouns_do_not_change_buyer_clarity(self) -> None:
        base = {
            "ref": "V-1",
            "title": "Restock Alerts",
            "one_liner": "Back-in-stock alerts",
            "example_customer": "US DTC brands, $500K-$5M",
            "wedge": "A PDP widget sends restock alerts.",
        }
        niche = dict(base, ref="V-2", example_customer="US lingerie DTC brands, $500K-$5M")
        plain = Ranker().score(load_thesis_dict(base))
        scored_niche = Ranker().score(load_thesis_dict(niche))
        self.assertEqual(
            plain.criteria["buyer_clarity"], scored_niche.criteria["buyer_clarity"]
        )
        self.assertEqual(
            plain.criteria["market_access"], scored_niche.criteria["market_access"]
        )


class InputRobustnessTests(unittest.TestCase):
    def test_csv_with_multiline_quoted_field_loads_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "multiline.csv"
            path.write_text(
                'ref,title,one_liner,example_customer,wedge\n'
                'T-01,Restock Hub,"Line one\nline two","US DTC brands, $500K-$5M",Widget\n',
                encoding="utf-8",
            )
            theses = load_theses(path)
            self.assertEqual(len(theses), 1)
            self.assertIn("line two", theses[0].one_liner)

    def test_cli_skips_duplicate_refs_across_append(self) -> None:
        from hatch_ranker.cli import main

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base = root / "base.json"
            live = root / "live.json"
            out = root / "out"
            row = {
                "ref": "B-01",
                "title": "B2B Portal",
                "one_liner": "B2B pricing in 30 minutes",
                "example_customer": "US DTC brands, $500K-$5M",
                "wedge": "CSV import and tiered pricing.",
            }
            base.write_text(json.dumps([row]), encoding="utf-8")
            live.write_text(json.dumps([row]), encoding="utf-8")  # same ref appended
            exit_code = main(
                ["--input", str(base), "--append", str(live), "--out-dir", str(out)]
            )
            self.assertEqual(exit_code, 0)
            ranking = json.loads((out / "ranking.json").read_text(encoding="utf-8"))
            refs = [card["ref"] for card in ranking]
            self.assertEqual(len(refs), len(set(refs)), "duplicate refs reached output")


if __name__ == "__main__":
    unittest.main()
