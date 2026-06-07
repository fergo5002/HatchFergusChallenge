# Keyword Vocabulary Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the deterministic ranker's vocabulary (concept layer + raw keyword lists + saturated categories) with research-backed 2025-26 ecommerce terms, so it catches more real signal without disrupting the calibrated model.

**Architecture:** Pure additive data changes in two modules. New `Concept` entries and trigger additions in `hatch_ranker/concepts.py` (bounded +5/-5 each), 10 new `SATURATED_CATEGORIES`, an incumbent-string refresh, and ~16 high-signal raw keywords in `hatch_ranker/ranker.py`. No weight re-tune, no interface change. Behaviour is locked by new tests and validated by a before/after re-rank of the committed 50-thesis corpus.

**Tech Stack:** Python 3, stdlib `unittest`. Source of truth for all terms/evidence: `docs/superpowers/specs/2026-06-08-keyword-vocabulary-expansion-design.md`.

---

## File Structure

- **Modify** `hatch_ranker/concepts.py` — add 8 concepts to `CONCEPTS`; add triggers to 7 existing concepts; wire new positives/negatives into `CRITERION_CONCEPTS`; add 10 entries to `SATURATED_CATEGORIES`; refresh 3 incumbent strings.
- **Modify** `hatch_ranker/ranker.py` — add ~16 raw keywords across `buyer_pain`, `roi_visibility`, `buildability`, `defensibility`.
- **Create** `tests/test_vocabulary_expansion.py` — behaviour + guard tests.
- **Create** `scripts/impact_diff.py` — diff two `ranking.json` files by ref.
- **Create** `docs/2026-06-08-keyword-expansion-impact.md` — committed before/after delta report (refs + numbers + newly-fired triggers only; no thesis text).

Conventions to follow (from existing code):
- Concept = `Concept("name", ("trigger one", "trigger two", ...))` in `CONCEPTS`.
- Triggers are lowercase; matching is `trigger in normalize(text)` (substring).
- Wire a concept by adding its name to `CRITERION_CONCEPTS[criterion]["positive"|"negative"]`.
- Raw criterion functions take already-normalized lowercase text.

---

## Task 1: Capture the pre-change baseline ranking

**Files:** none modified (generates git-ignored `outputs/`).

- [ ] **Step 1: Confirm the source corpus exists**

Run: `python -c "import pathlib; p=pathlib.Path(r'C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv'); print('OK', p.exists())"`
Expected: `OK True`

- [ ] **Step 2: Generate the BEFORE snapshot with current code**

Run:
```
python -m hatch_ranker.cli --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" --out-dir outputs/expansion_before
```
Expected: prints "Ranked 50 theses." and writes `outputs/expansion_before/ranking.json`.

- [ ] **Step 3: No commit** (`outputs/` is git-ignored; this snapshot is local-only). Proceed.

---

## Task 2: Add the 5 cash-velocity-side positive concepts

**Files:**
- Test: `tests/test_vocabulary_expansion.py`
- Modify: `hatch_ranker/concepts.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vocabulary_expansion.py`:
```python
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

    def test_regulatory_2025_fires_on_buyer_pain(self) -> None:
        text = "handles gpsr responsible person and european accessibility act wcag 2.1 audits"
        self.assertIn("regulatory_2025_pain", fired(text, "buyer_pain"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_vocabulary_expansion.CashVelocityConceptTests -v`
Expected: FAIL — fired lists do not contain the new concept names (concepts not defined yet).

- [ ] **Step 3: Add the 5 concepts to `CONCEPTS`**

In `hatch_ranker/concepts.py`, inside the `CONCEPTS` dict (after the existing buyer-pain concepts block, before the ROI block is fine), add:
```python
    "profit_analytics_pain": Concept(
        "profit_analytics_pain",
        (
            "contribution margin", "net margin", "blended mer",
            "marketing efficiency ratio", "cac payback", "payback period",
            "landed cost", "per-sku profitability", "sku-level profit",
            "cogs sync", "blended cac", "true profitability",
        ),
    ),
    "returns_abuse_pain": Concept(
        "returns_abuse_pain",
        (
            "return fraud", "return abuse", "serial returner", "wardrobing",
            "bracketing", "returnless refund", "empty box", "refund fraud",
            "return policy abuse", "return rate scoring",
        ),
    ),
    "post_purchase_revenue": Concept(
        "post_purchase_revenue",
        (
            "post-purchase upsell", "post purchase upsell", "order bump",
            "thank-you page", "thank you page", "post-purchase survey",
            "store credit", "subscription pause", "skip delivery",
            "win-back sequence", "reactivation sequence",
        ),
    ),
    "cross_border_duty_pain": Concept(
        "cross_border_duty_pain",
        (
            "landed cost", "de minimis", "import duties", "customs duty",
            "duty drawback", "tariff", "hts code", "ioss", "import tax",
            "cross-border duty",
        ),
    ),
    "regulatory_2025_pain": Concept(
        "regulatory_2025_pain",
        (
            "gpsr", "responsible person", "european accessibility act",
            "eaa compliance", "wcag 2.1", "accessibility audit",
            "consent mode", "consent management platform",
        ),
    ),
```

- [ ] **Step 4: Wire them into `CRITERION_CONCEPTS`**

Edit these existing entries in `CRITERION_CONCEPTS` to append the new names to their `positive` tuples:
- `buyer_pain.positive` → append `"profit_analytics_pain", "returns_abuse_pain", "cross_border_duty_pain", "regulatory_2025_pain"`
- `roi_visibility.positive` → append `"profit_analytics_pain", "post_purchase_revenue", "cross_border_duty_pain"`
- `expansion_surface.positive` → append `"post_purchase_revenue"`
- `defensibility.positive` → append `"returns_abuse_pain"`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest tests.test_vocabulary_expansion.CashVelocityConceptTests -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```
git add hatch_ranker/concepts.py tests/test_vocabulary_expansion.py
git commit -m "Add cash-velocity-side positive concepts (profit, returns-abuse, post-purchase, duty, regulatory)"
```

---

## Task 3: Add the 3 viability/company-side positive concepts

**Files:**
- Test: `tests/test_vocabulary_expansion.py`
- Modify: `hatch_ranker/concepts.py`

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/test_vocabulary_expansion.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_vocabulary_expansion.ViabilityConceptTests -v`
Expected: FAIL — concepts not defined.

- [ ] **Step 3: Add the 3 concepts to `CONCEPTS`**

```python
    "inventory_forecast_signal": Concept(
        "inventory_forecast_signal",
        (
            "sell-through rate", "reorder point", "days of supply",
            "safety stock", "stockout prediction", "demand forecast",
            "demand planning", "dead stock", "overstock",
        ),
    ),
    "agentic_ready_data": Concept(
        "agentic_ready_data",
        (
            "agentic-ready", "agentic ready", "product data completeness",
            "answer engine optimization", "generative engine optimization",
            "feed optimization", "ai shopping agent", "agentic storefront",
        ),
    ),
    "zero_party_data": Concept(
        "zero_party_data",
        (
            "zero-party data", "zero party data", "declared preferences",
            "post-purchase survey", "consent mode", "quiz responses",
        ),
    ),
```

- [ ] **Step 4: Wire into `CRITERION_CONCEPTS`**

Append to existing `positive` tuples:
- `data_access.positive` → append `"inventory_forecast_signal", "agentic_ready_data", "zero_party_data"`
- `expansion_surface.positive` → append `"inventory_forecast_signal"`
- `platform_access.positive` → append `"agentic_ready_data"`
- `differentiation.positive` → append `"zero_party_data"`
- `defensibility.positive` → append `"zero_party_data"`

- [ ] **Step 5: Run to verify pass**

Run: `python -m unittest tests.test_vocabulary_expansion.ViabilityConceptTests -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```
git add hatch_ranker/concepts.py tests/test_vocabulary_expansion.py
git commit -m "Add viability/company-side positive concepts (forecast, agentic-ready, zero-party)"
```

---

## Task 4: Add triggers to existing concepts (positive + negative)

**Files:**
- Test: `tests/test_vocabulary_expansion.py`
- Modify: `hatch_ranker/concepts.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_vocabulary_expansion.ExistingConceptAdditionTests -v`
Expected: FAIL — new triggers not present.

- [ ] **Step 3: Append triggers to the listed existing concepts in `CONCEPTS`**

- `measurable_cost_save`: add `"returnless refund", "deflect returns", "lower return rate"`
- `measurable_revenue_lift`: add `"reactivation", "reactivation sequence"`
- `incumbent_clone_signal`: add `"alternative to", "drop-in replacement", "fraction of the price", "fraction of the cost", "undercut"`
- `autonomous_irreversible`: add `"autonomous buying agent", "auto-issues refunds", "agentic checkout", "fully autonomous"`
- `hard_realtime_ai_build`: add `"voice commerce", "conversational checkout", "real-time voice"`
- `platform_gated_build`: add `"agentic checkout protocol", "universal commerce protocol", "checkout kit"`
- `novelty_consumer_behavior`: add `"spin to win", "spin-to-win", "wheel of fortune"`

- [ ] **Step 4: Run to verify pass**

Run: `python -m unittest tests.test_vocabulary_expansion.ExistingConceptAdditionTests -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```
git add hatch_ranker/concepts.py tests/test_vocabulary_expansion.py
git commit -m "Extend existing concepts with new positive/negative triggers"
```

---

## Task 5: Add 10 new saturated categories

**Files:**
- Test: `tests/test_vocabulary_expansion.py`
- Modify: `hatch_ranker/concepts.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_vocabulary_expansion.SaturatedCategoryTests -v`
Expected: FAIL — categories not defined.

- [ ] **Step 3: Add 10 entries to `SATURATED_CATEGORIES`**

In `hatch_ranker/concepts.py`, add to the `SATURATED_CATEGORIES` dict:
```python
    "post_purchase_upsell": {
        "triggers": ("post-purchase upsell", "thank-you page upsell", "order bump", "one-click upsell", "reconvert"),
        "density": 0.88,
        "label": "post-purchase upsell",
        "incumbents": "ReConvert, AfterSell, Zipify OCU, Rebuy, Honeycomb",
    },
    "page_builder": {
        "triggers": ("page builder", "landing page builder", "drag-and-drop page", "pagefly", "gempages"),
        "density": 0.90,
        "label": "page builder",
        "incumbents": "PageFly, GemPages, Shogun, Replo, EComposer",
    },
    "returns_portal": {
        "triggers": ("returns portal", "returns management", "self-service returns", "rma portal", "return label"),
        "density": 0.85,
        "label": "returns portal",
        "incumbents": "Loop Returns, AfterShip Returns, Happy Returns, ReturnGO",
    },
    "order_tracking_page": {
        "triggers": ("order tracking page", "branded tracking", "shipment tracking page", "parcel tracking", "order lookup page"),
        "density": 0.88,
        "label": "order tracking page",
        "incumbents": "AfterShip, ParcelPanel, Tracktor, 17TRACK",
    },
    "ai_chatbot_support": {
        "triggers": ("ai chatbot", "ai support agent", "conversational ai", "support chatbot", "ai concierge"),
        "density": 0.88,
        "label": "AI chatbot / support agent",
        "incumbents": "Tidio Lyro, Gorgias AI, Intercom Fin, Re:amaze",
    },
    "shipping_protection": {
        "triggers": ("shipping protection", "package protection", "shipping insurance", "order protection"),
        "density": 0.82,
        "label": "shipping / package protection",
        "incumbents": "Route, Navidium, ShipInsure, Seel, Guide",
    },
    "popup_email_capture": {
        "triggers": ("email capture popup", "exit-intent popup", "exit intent popup", "newsletter popup", "spin to win"),
        "density": 0.85,
        "label": "popup / email capture",
        "incumbents": "Privy, OptiMonk, Justuno, Klaviyo Forms",
    },
    "seo_optimizer": {
        "triggers": ("seo app", "seo optimizer", "meta tag optimizer", "auto meta tags", "seo audit"),
        "density": 0.85,
        "label": "SEO optimizer",
        "incumbents": "Yoast SEO, Plug In SEO, Booster SEO, SearchPie, TinyIMG",
    },
    "server_side_tracking": {
        "triggers": ("server-side tracking", "server side tracking", "conversions api", "server-side pixel", "first-party pixel"),
        "density": 0.82,
        "label": "server-side tracking / CAPI",
        "incumbents": "Elevar, Trackify, DataCops (now matched by free Meta CAPI / Google Tag Gateway / Shopify native)",
    },
    "product_reco_engine": {
        "triggers": ("frequently bought together", "product recommendation engine", "cross-sell app", "upsell app", "related products app"),
        "density": 0.85,
        "label": "product recommendation engine",
        "incumbents": "Rebuy, LimeSpot, Frequently Bought Together, Wiser",
    },
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m unittest tests.test_vocabulary_expansion.SaturatedCategoryTests -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```
git add hatch_ranker/concepts.py tests/test_vocabulary_expansion.py
git commit -m "Add 10 new saturated categories (2025-26 crowded app markets)"
```

---

## Task 6: Refresh incumbent strings on existing saturated categories

**Files:** Modify `hatch_ranker/concepts.py` (string-only; no scoring change).

- [ ] **Step 1: Update three `incumbents` strings**

- `sms_marketing.incumbents` → `"Postscript, Attentive, Klaviyo SMS (Yotpo/SMSBump exited Dec 2025; assets to Attentive)"`
- `subscription_billing_recovery.incumbents` → `"Recharge, Skio, Stay AI, Loop, Appstle (plus Shopify native Subscriptions)"`
- `helpdesk_tickets.incumbents` → `"Gorgias (native AI agent), Zendesk, Tidio, Re:amaze"`

- [ ] **Step 2: Run the full suite to confirm nothing broke**

Run: `python -m unittest discover -s tests`
Expected: OK (all tests pass; string change is behaviour-neutral).

- [ ] **Step 3: Commit**

```
git add hatch_ranker/concepts.py
git commit -m "Refresh saturated-category incumbents for 2025-26 (Yotpo exit, native Shopify, Gorgias AI)"
```

---

## Task 7: Add high-signal raw keywords to ranker.py

**Files:**
- Test: `tests/test_vocabulary_expansion.py`
- Modify: `hatch_ranker/ranker.py`

- [ ] **Step 1: Write the failing tests**

Append:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m unittest tests.test_vocabulary_expansion.RawKeywordTests -v`
Expected: FAIL — raw keywords not yet added (negatives in particular won't drop below baseline).

- [ ] **Step 3: Add raw keywords in `hatch_ranker/ranker.py`**

- In `buyer_pain`, add to the first `count_any` positive tuple (the `+8` block): `"return fraud", "landed cost", "de minimis", "tariff"`.
- In `roi_visibility`, add to the `+8` positive tuple: `"contribution margin", "returnless refund", "store credit", "duty drawback"`.
- In `buildability`, add to the `+6` positive tuple: `"reorder point", "post-purchase survey"`; add to the `-8` negative tuple: `"voice commerce", "conversational checkout"`.
- In `defensibility`, add to the `+8` positive tuple: `"cohort retention", "zero-party data"`; add to the `-7` negative tuple: `"alternative to", "drop-in replacement"`.

- [ ] **Step 4: Run to verify pass**

Run: `python -m unittest tests.test_vocabulary_expansion.RawKeywordTests -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```
git add hatch_ranker/ranker.py tests/test_vocabulary_expansion.py
git commit -m "Add high-signal raw keywords to buyer_pain, roi, buildability, defensibility"
```

---

## Task 8: Guard tests (no dupes, no bare tokens, bounded)

**Files:**
- Test: `tests/test_vocabulary_expansion.py`

- [ ] **Step 1: Write the guard tests**

Append:
```python
EXCLUDED_BARE_TOKENS = {"ai", "ai-powered", "boost aov", "aov", "seo", "capi", "chatbot", "duty"}


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
        # Many positive triggers for one criterion must still respect the cap.
        text = (
            "contribution margin blended mer cac payback landed cost "
            "returnless refund serial returner order bump store credit"
        )
        self.assertLessEqual(adjustment(text, "roi_visibility"), 20.0)
        self.assertGreaterEqual(adjustment(text, "buildability"), -15.0)

    def test_every_wired_concept_name_exists(self) -> None:
        for criterion, cfg in CRITERION_CONCEPTS.items():
            for name in (*cfg.get("positive", ()), *cfg.get("negative", ())):
                self.assertIn(name, CONCEPTS, f"{criterion} wires unknown concept {name}")
```

- [ ] **Step 2: Run to verify the guards pass**

Run: `python -m unittest tests.test_vocabulary_expansion.GuardTests -v`
Expected: PASS (4 tests). If `test_excluded_bare_tokens` fails, a bare token leaked into a trigger — remove/rename it. If `test_every_wired_concept_name_exists` fails, a `CRITERION_CONCEPTS` entry references a typo'd concept name — fix it.

- [ ] **Step 3: Commit**

```
git add tests/test_vocabulary_expansion.py
git commit -m "Add guard tests: no within-concept dupes, no bare tokens, bounded, all wirings valid"
```

---

## Task 9: Full-suite green + before/after impact report

**Files:**
- Create: `scripts/impact_diff.py`
- Create: `docs/2026-06-08-keyword-expansion-impact.md`

- [ ] **Step 1: Run the entire test suite**

Run: `python -m unittest discover -s tests`
Expected: OK — original 46 tests + all new vocabulary tests pass.

- [ ] **Step 2: Generate the AFTER snapshot**

Run:
```
python -m hatch_ranker.cli --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" --out-dir outputs/expansion_after
```
Expected: "Ranked 50 theses."

- [ ] **Step 3: Write the diff script**

Create `scripts/impact_diff.py`:
```python
"""Diff two ranking.json files by ref: rank/score deltas + newly-fired triggers.

Usage:
    python scripts/impact_diff.py outputs/expansion_before/ranking.json outputs/expansion_after/ranking.json
Prints a markdown report to stdout (refs + numbers + newly-fired concepts/saturation only).
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
```

- [ ] **Step 4: Produce the committed impact report**

Run:
```
python scripts/impact_diff.py outputs/expansion_before/ranking.json outputs/expansion_after/ranking.json > docs/2026-06-08-keyword-expansion-impact.md
```
Then open `docs/2026-06-08-keyword-expansion-impact.md` and read it. Verify the "advance, don't disrupt" expectation: every non-trivial rank move has an explaining entry in "Newly fired" (a new concept or saturated category). If any ref moved with an empty "Newly fired" cell, investigate before continuing.

- [ ] **Step 5: Commit**

```
git add scripts/impact_diff.py docs/2026-06-08-keyword-expansion-impact.md
git commit -m "Add impact-diff script and before/after report for vocabulary expansion"
```

---

## Self-Review (completed during planning)

**Spec coverage:** §2 rubric → evidence doc already committed (no code). §4 (8 concepts) → Tasks 2-3. §5 (existing-concept additions) → Task 4. §6 (10 saturated) → Task 5. §7 (incumbent refresh) → Task 6. §8 (exclusions) → Task 8 guard. §9 (no re-tune) → no code by design. §10 (raw additions) → Task 7. §11 (tests) → Tasks 2-8. §12 (impact) → Tasks 1 & 9. §13/§14 → Task 9 + additive-revert. All covered.

**Type/name consistency:** concept names used in `CRITERION_CONCEPTS` wiring (Tasks 2-4) match the `Concept(...)` definitions; saturated category keys (Task 5) match the test `EXPECTED` map (Task 5); raw function names (`buyer_pain`/`roi_visibility`/`buildability`/`defensibility`) match `ranker.py`.

**Note for executor:** cross-concept trigger reuse and concept↔raw reinforcement are intentional ("both layers"); the dedup guard (Task 8) only forbids duplicates *within* a single concept.
