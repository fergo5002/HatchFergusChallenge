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


def load_thesis_dict(record):
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "one.json"
        path.write_text(json.dumps([record]), encoding="utf-8")
        return load_theses(path)[0]


if __name__ == "__main__":
    unittest.main()
