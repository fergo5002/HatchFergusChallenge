# Ranker Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Hatch ranking engine resistant to keyword gaming and free of demonstrated false-positive scoring bugs, so every score survives adversarial review.

**Architecture:** Replace raw substring matching with a single word-boundary + negation-aware matching module that all matchers (keyword lists, concepts, saturation, compliance) route through. Add an "unfocused wedge" trap that detects keyword/scope stuffing via pain-domain concept counts. Fix the money parser, a dead scoring branch, doc drift, and the misleading "Trap" tier label.

**Tech Stack:** Python 3.14 stdlib only (re, unittest). No new dependencies.

**Review evidence (2026-06-10, all empirically confirmed on current code):**

- A keyword-stuffed incoherent thesis scores **94.7 vs 71.9** for a genuinely focused idea after two iterations of trap-word avoidance (defeatability proof).
- `parse_revenue_range("ships in 3 months")` → $3M revenue band; `"within 10 km radius"` → $10K; `"$1,500K"` reads as $500K.
- Compliance-scope trap (−4 penalty, cap 78) fires on "private label", "innovative", "elevate", "entrepreneur" ("vat"/"epr" substrings).
- `roi_visibility` +8 for "details" ("eta"); `support_volume_pain` fires on "shopify admin api" ("dm"); clone-signal fires on "elite"/"polite" ("lite"); `third_party_integration_dep` fires on "closed-loop" ("loop"); `smallest_sellable_v1` matches "po" inside "support".
- Negation blindness: "no manual upload needed" fires `high_setup_uploads`.
- `market_access` 82-branch is dead code (the 78 `low >= 100_000` branch precedes and subsumes `low >= 500_000`).
- Doc drift: `concepts.py` docstring says +4/cap range [−15, +20]; code is `POSITIVE_WEIGHT = 5.0` → [−15, +25]; `io.py` markdown says "+/- 20".
- Bottom 30% of any corpus is labelled "Trap" even with zero traps.

---

### Task 1: Word-boundary + negation matching module

**Files:**
- Create: `hatch_ranker/matching.py`
- Test: `tests/test_matching.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_matching.py
from __future__ import annotations

import unittest

from hatch_ranker.matching import phrase_in


class PhraseInTests(unittest.TestCase):
    def test_whole_word_positives_still_match(self) -> None:
        self.assertTrue(phrase_in("merchants lose money on returns", "return"))   # plural
        self.assertTrue(phrase_in("back-in-stock alerts", "back-in-stock"))       # hyphen phrase
        self.assertTrue(phrase_in("brands doing under $500k", "under $"))         # currency tail
        self.assertTrue(phrase_in("an ai chatbot for support", "ai"))
        self.assertTrue(phrase_in("ai-powered drafting", "ai"))                   # right hyphen ok
        self.assertTrue(phrase_in("priced at $19/mo flat", "$19/mo"))
        self.assertTrue(phrase_in("sees the sku p&l nightly", "p&l"))

    def test_substring_false_positives_are_blocked(self) -> None:
        self.assertFalse(phrase_in("the details page", "eta"))
        self.assertFalse(phrase_in("shopify admin api", "dm"))
        self.assertFalse(phrase_in("elite merchants only", "lite"))
        self.assertFalse(phrase_in("a polite reminder", "lite"))
        self.assertFalse(phrase_in("closed-loop analytics", "loop"))              # left hyphen blocked
        self.assertFalse(phrase_in("a support portal", "po"))
        self.assertFalse(phrase_in("private label brands", "vat"))
        self.assertFalse(phrase_in("a serial entrepreneur", "epr"))
        self.assertFalse(phrase_in("send branded emails", "ai"))

    def test_negated_phrases_do_not_fire(self) -> None:
        self.assertFalse(phrase_in("no manual upload needed", "manual upload"))
        self.assertFalse(phrase_in("works without a regulator packet", "regulator packet"))
        self.assertFalse(phrase_in("zero merchant uploads required", "merchant uploads"))
        self.assertTrue(phrase_in("builds the regulator packet nightly", "regulator packet"))

    def test_negation_only_looks_at_nearby_words(self) -> None:
        # Negator more than 3 words back does not suppress the match.
        self.assertTrue(
            phrase_in("not only that, it also drafts the regulator packet", "regulator packet")
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_matching -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hatch_ranker.matching'`

- [ ] **Step 3: Write the implementation**

```python
# hatch_ranker/matching.py
"""Word-boundary phrase matching with light negation handling.

Every matcher in the ranker (keyword lists, concept triggers, saturation
triggers, compliance keywords) routes through ``phrase_in`` so the whole
engine shares one defensible definition of "the thesis says X":

* A needle matches only at word boundaries, so "vat" no longer fires on
  "private" and "eta" no longer fires on "details".
* A trailing optional plural (``s``/``es``) keeps "return" matching
  "returns" the way the old substring matcher did.
* A hyphen immediately before the match blocks it ("closed-loop" must not
  fire the "loop" brand trigger), but a hyphen after is allowed so
  "ai-powered" still fires "ai".
* A negator within the three words before the match suppresses it, so
  "no manual upload needed" stops firing the high-setup trigger.
"""

from __future__ import annotations

import re
from functools import lru_cache

NEGATORS = frozenset(
    {
        "no", "not", "without", "zero", "never",
        "avoid", "avoids", "avoiding",
        "eliminate", "eliminates", "replaces",
    }
)

_NEGATION_WINDOW_WORDS = 3
_WINDOW_CHARS = 40


def phrase_in(text: str, needle: str) -> bool:
    """True when ``needle`` appears as a whole word/phrase and is not negated."""

    if not needle:
        return False
    for match in _compiled(needle).finditer(text):
        if not _negated(text, match.start()):
            return True
    return False


def count_phrases(text: str, needles: tuple[str, ...], *, cap: int) -> int:
    count = sum(1 for needle in needles if phrase_in(text, needle))
    return min(count, cap)


def any_phrase(text: str, needles: tuple[str, ...]) -> bool:
    return any(phrase_in(text, needle) for needle in needles)


@lru_cache(maxsize=8192)
def _compiled(needle: str) -> re.Pattern[str]:
    escaped = re.escape(needle)
    left = r"(?<![\w$€-])" if needle[0].isalnum() else ""
    if needle[-1].isalpha():
        right = r"(?:e?s)?(?!\w)"
    elif needle[-1].isdigit():
        right = r"(?!\w)"
    else:
        right = ""
    return re.compile(left + escaped + right)


def _negated(text: str, start: int) -> bool:
    window = text[max(0, start - _WINDOW_CHARS):start]
    words = re.findall(r"[a-z][\w'-]*", window)
    return any(word in NEGATORS for word in words[-_NEGATION_WINDOW_WORDS:])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_matching -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add hatch_ranker/matching.py tests/test_matching.py
git commit -m "feat: word-boundary + negation phrase matcher"
```

---

### Task 2: Route every matcher through the new module

**Files:**
- Modify: `hatch_ranker/ranker.py:1097-1103` (`contains_any`, `count_any`)
- Modify: `hatch_ranker/concepts.py:507-508` (`_concept_fires`), `concepts.py:690-706` (`detect_saturation`)
- Test: `tests/test_ranker.py` (add regression tests)

- [ ] **Step 1: Write the failing regression tests**

Append to `tests/test_ranker.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ranker -v`
Expected: the three new tests FAIL (compliance trap fires on "private/innovative/elevate/entrepreneur"; "ai" tag fires on "email"; negated uploads penalized). All pre-existing tests still pass.

- [ ] **Step 3: Swap the matcher implementations**

In `hatch_ranker/ranker.py`, add the import and replace the two helpers (keep the names so all 40+ call sites stay untouched):

```python
# add to imports at top of ranker.py
from hatch_ranker.matching import any_phrase, count_phrases
```

```python
# replace the existing contains_any / count_any definitions
def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any_phrase(text, needles)


def count_any(text: str, needles: tuple[str, ...], *, cap: int) -> int:
    return count_phrases(text, needles, cap=cap)
```

In `hatch_ranker/concepts.py`, add the import and replace `_concept_fires` and the trigger check inside `detect_saturation`:

```python
# add to imports at top of concepts.py
from hatch_ranker.matching import phrase_in
```

```python
def _concept_fires(text: str, concept: Concept) -> bool:
    return any(phrase_in(text, trigger) for trigger in concept.triggers)
```

```python
# inside detect_saturation, replace:
#   if any(trigger in text for trigger in triggers):
        if any(phrase_in(text, trigger) for trigger in triggers):  # type: ignore[union-attr]
```

- [ ] **Step 4: Repair vocabulary that legitimately relied on substrings**

Word-boundary matching removes a few intended matches. Make these exact edits:

1. `ranker.py` `buyer_pain` tuple: add `"cancellation"` after `"cancel"` (substring used to catch it).
2. `ranker.py` `infer_tags` retention check: add `"cancellation"` after `"cancel"`.
3. `ranker.py` `smallest_sellable_v1` inventory branch: change `("inventory", "supplier", "po")` to `("inventory", "supplier", "purchase order", "po history", "reorder point")` — bare `"po"` was matching "support"/"portal".
4. `concepts.py` `support_volume_pain` triggers: change `"dm"` to `"dms"` and add `"direct message"` (bare `"dm"` was matching "admin").
5. `concepts.py` `incumbent_clone_signal` triggers: remove `"lite"` and `"killing"`, keep `"lite version"`, `"gorgiaslite"`; add `"-lite"` is NOT needed (left-hyphen is blocked by design — "GorgiasLite" normalizes to one word and is matched by its own trigger).

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (72 pre-existing + new tests). If any pre-existing test fails, the failure is a vocabulary regression — fix it by adding the lost word form to the relevant tuple (as in Step 4), never by weakening `matching.py`.

- [ ] **Step 6: Commit**

```bash
git add hatch_ranker/ranker.py hatch_ranker/concepts.py tests/test_ranker.py
git commit -m "fix: route all matchers through word-boundary engine, kill substring false positives"
```

---

### Task 3: Fix the money parser and the dead market_access branch

**Files:**
- Modify: `hatch_ranker/ranker.py:988-1005` (`parse_revenue_range`), `ranker.py:411-436` (`market_access`)
- Test: `tests/test_ranker.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ranker.py`:

```python
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


class MarketAccessBandTests(unittest.TestCase):
    def test_mid_market_premium_band_is_reachable(self) -> None:
        from hatch_ranker.ranker import market_access, RevenueRange

        premium = market_access("US DTC brands", RevenueRange(500_000, 5_000_000))
        standard = market_access("US DTC brands", RevenueRange(100_000, 5_000_000))
        self.assertGreater(premium, standard)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ranker -v`
Expected: `test_durations_and_distances_are_not_revenue` FAILS (returns $3M/$2M-$5M/$10K bands), `test_comma_amounts_parse_fully` FAILS (low == 500_000), `test_mid_market_premium_band_is_reachable` FAILS (both 78 — the 82 branch is dead).

- [ ] **Step 3: Fix `parse_revenue_range`**

Replace the regex/extraction in `parse_revenue_range` (currency symbol now required — that is the defensible rule: a bare "3 m" is not money):

```python
MONEY_PATTERN = re.compile(r"[$€£]\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([km])\b")


def parse_revenue_range(text: str) -> RevenueRange | None:
    normalized = normalize(text)
    amounts = [
        money_to_number(match.group(1).replace(",", ""), match.group(2))
        for match in MONEY_PATTERN.finditer(normalized)
    ]
    if not amounts:
        return None
    first = amounts[0]
    if contains_any(normalized, ("sub-$", "sub $", "under $", "under ")) and len(amounts) == 1:
        return RevenueRange(0, first)
    if "+" in normalized and len(amounts) == 1:
        return RevenueRange(first, None)
    if len(amounts) == 1:
        return RevenueRange(first, first)
    low = min(amounts[0], amounts[1])
    high = max(amounts[0], amounts[1])
    return RevenueRange(low, high)
```

- [ ] **Step 4: Fix the dead branch in `market_access`**

Reorder so the more specific `low >= 500_000` band is checked first:

```python
        if high and high <= 75_000:
            score = 32
        elif high and high <= 500_000 and low <= 50_000:
            score = 48
        elif high and high <= 1_000_000 and low <= 100_000:
            score = 64
        elif high and high <= 5_000_000 and low >= 500_000:
            score = 82
        elif high and high <= 5_000_000 and low >= 100_000:
            score = 78
        elif high and high >= 10_000_000:
            score = 64
        elif not high and low >= 500_000:
            score = 66
```

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hatch_ranker/ranker.py tests/test_ranker.py
git commit -m "fix: money parser requires currency symbol; un-dead the 82 market band"
```

---

### Task 4: "Unfocused wedge" anti-stuffing trap

**Files:**
- Modify: `hatch_ranker/concepts.py` (add `PAIN_CONCEPT_NAMES`, `fired_pain_concepts`)
- Modify: `hatch_ranker/ranker.py` (`score`, `compute_viability_cap`)
- Test: `tests/test_ranker.py`

The attack this kills: stuff positive vocabulary from many pain domains into one thesis (the confirmed 94.7-point exploit). A three-person team cannot ship a v1 that attacks 4+ distinct pain domains in 10 weeks; either the thesis is unfocused or the text is stuffed. The trap reason names the fired domains, so it is fully explainable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ranker.py`:

```python
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

    def test_stuffed_thesis_gets_unfocused_wedge_trap(self) -> None:
        card = Ranker().score(load_thesis_dict(self.STUFFED))
        self.assertTrue(any(trap.name == "unfocused wedge" for trap in card.traps))

    def test_stuffed_thesis_ranks_below_focused_thesis(self) -> None:
        cards = Ranker().rank(
            [load_thesis_dict(self.FOCUSED), load_thesis_dict(self.STUFFED)]
        )
        self.assertEqual(cards[0].ref, "REAL-1")

    def test_two_pain_domains_do_not_trigger_the_trap(self) -> None:
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ranker.StuffingDefenseTests -v`
Expected: first two tests FAIL (no such trap; GAME-1 outranks REAL-1).

- [ ] **Step 3: Add pain-domain counting to `concepts.py`**

```python
# append to concepts.py, after CRITERION_CONCEPTS

# Pain domains a v1 wedge can credibly attack. Firing many of these at once
# is the signature of an unfocused thesis or keyword-stuffed text.
PAIN_CONCEPT_NAMES: frozenset[str] = frozenset(
    {
        "refund_return_pain", "churn_cancel_pain", "support_volume_pain",
        "inventory_oos_pain", "failed_payment_pain", "compliance_filing_pain",
        "margin_profit_pain", "catalog_quality_pain", "wholesale_b2b_pain",
        "supplier_ops_pain", "profit_analytics_pain", "returns_abuse_pain",
        "cross_border_duty_pain", "eu_regulatory_pain",
    }
)


def fired_pain_concepts(text: str) -> list[str]:
    """Sorted names of distinct pain-domain concepts that fire on the text."""

    return sorted(
        name for name in PAIN_CONCEPT_NAMES if _concept_fires(text, CONCEPTS[name])
    )
```

- [ ] **Step 4: Add the trap and cap in `ranker.py`**

Import `fired_pain_concepts` alongside the existing concepts imports. In `Ranker.score`, immediately after `traps = identify_traps(...)`:

```python
        pain_domains = fired_pain_concepts(text)
        if len(pain_domains) >= 4:
            overflow = len(pain_domains) - 3
            traps.append(
                Trap(
                    "unfocused wedge",
                    round(min(4.0 * overflow, 16.0), 1),
                    (
                        f"The thesis claims {len(pain_domains)} distinct pain domains "
                        f"({', '.join(pain_domains)}); a 10-week v1 can credibly attack "
                        "one or two, so this reads as unfocused scope or stuffed text."
                    ),
                )
            )
```

In `compute_viability_cap`, add to the trap-name cap ladder (between "thin data" and "compliance scope" to keep severity ordering readable):

```python
    if "unfocused wedge" in trap_names:
        cap = min(cap, 72)
```

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS. If `test_two_pain_domains_do_not_trigger_the_trap` fails, the Margin Truth fixture fired ≥4 domains — verify which via `fired_pain_concepts` in a REPL and adjust the threshold only if the fixture genuinely spans ≥4 (it should fire margin_profit + refund_return + supplier_ops at most = 3).

- [ ] **Step 6: Commit**

```bash
git add hatch_ranker/concepts.py hatch_ranker/ranker.py tests/test_ranker.py
git commit -m "feat: unfocused-wedge trap defeats keyword stuffing"
```

---

### Task 5: Remove overfit one-off keywords

**Files:**
- Modify: `hatch_ranker/ranker.py` (`buyer_clarity`, `market_access`, `differentiation`, `identify_traps`)
- Test: `tests/test_ranker.py`

These literals score specific theses from the original 50 and are indefensible in a live rerank ("why does 'lingerie' lose 5 points?" has no principled answer):

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_ranker.OverfitVocabularyTests -v`
Expected: FAIL (niche scores 5 lower on buyer_clarity, 9 lower on market_access).

- [ ] **Step 3: Delete the overfit literals**

1. `buyer_clarity`: delete the `if contains_any(text, ("reptile", "lingerie")): score -= 5` block.
2. `market_access`: delete the `if contains_any(customer_text, ("reptile", "lingerie")): score -= 9` block.
3. `differentiation` negative tuple: remove `"killing octane"`, `"gorgiaslite"`, `"lite"` (keep `"cheaper"`, `"1/10th"`, `"priced at"`, `"$19/mo"`, `"flat monthly"`, `"flat eur"`, `"flat €"` — those are pricing patterns, not thesis fingerprints).
4. `identify_traps` cheap-clone check: change `("1/10th", "$19/mo", "flat monthly", "killing octane", "gorgiaslite")` to `("1/10th", "$19/mo", "flat monthly", "fraction of the price", "drop-in replacement", "cheaper than")`.

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hatch_ranker/ranker.py tests/test_ranker.py
git commit -m "fix: remove thesis-fingerprint keywords from scoring vocabulary"
```

---

### Task 6: Honest tier labels + doc drift

**Files:**
- Modify: `hatch_ranker/ranker.py:207-216` (`_tier_for`)
- Modify: `hatch_ranker/io.py:229-241` (`_tier_summary`), `io.py:166` (concept-blend bullet)
- Modify: `hatch_ranker/concepts.py:1-24` (module docstring), `concepts.py:478-485` (`concept_adjustment` docstring)
- Modify: `hatch_ranker/web_static/app.js:24-27` and `public/app.js:24-27` (TIER_MODIFIERS — files are identical, apply to both)
- Test: `tests/test_v2_features.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_v2_features.py` (match its existing import style):

```python
class TierHonestyTests(unittest.TestCase):
    def test_bottom_percentile_without_traps_is_lagging_not_trap(self) -> None:
        theses = []
        for index in range(10):
            theses.append(
                load_thesis_dict(
                    {
                        "ref": f"T-{index:02d}",
                        "title": f"Catalog Helper {index}",
                        "one_liner": "Catalog fix list for Shopify stores" + " plus" * index,
                        "example_customer": "US DTC brands, $500K-$5M",
                        "wedge": "Nightly catalog audit emails a ranked fix list."
                        + " It also exports a csv." * (index % 3),
                    }
                )
            )
        cards = Ranker().rank(theses)
        for card in cards:
            if card.tier == "Trap":
                self.assertTrue(
                    card.traps, f"{card.ref} labelled Trap with zero traps"
                )
```

(Reuse the `load_thesis_dict` helper pattern already present in the test module; if absent, copy it from `tests/test_ranker.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_v2_features -v`
Expected: FAIL — bottom cards have `tier == "Trap"` with empty `traps`.

- [ ] **Step 3: Fix `_tier_for` and the tier summary**

```python
def _tier_for(card: Scorecard) -> str:
    if any(trap.name in SEVERE_TRAPS_FOR_TIER for trap in card.traps) and card.final_score < 50:
        return "Trap"
    if card.percentile >= 90:
        return "Top Tier"
    if card.percentile >= 70:
        return "Strong"
    if card.percentile >= 30:
        return "Watch"
    return "Trap" if card.traps else "Lagging"
```

In `io.py` `_tier_summary`: `tier_order = ("Top Tier", "Strong", "Watch", "Lagging", "Trap")`.

In both `app.js` copies, extend the modifier map (the renderer already falls back to `"unknown"`, this just gives Lagging its own neutral style):

```javascript
  ["Lagging", "watch"],
```

(insert before the `["Trap", "trap"]` entry; reusing the muted "watch" style is fine — no CSS change needed.)

- [ ] **Step 4: Fix the three documentation drifts**

1. `concepts.py` module docstring: change `+4 per fired positive concept (capped at 5)` to `+5 per fired positive concept (capped at 5)`.
2. `concepts.py` `concept_adjustment` docstring: change `[-15, +20]` to `[-15, +25]`.
3. `io.py` markdown bullet: change `adjusted by +/- 20` to `adjusted within [-15, +25]`.

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hatch_ranker/ranker.py hatch_ranker/io.py hatch_ranker/concepts.py hatch_ranker/web_static/app.js public/app.js tests/test_v2_features.py
git commit -m "fix: Lagging tier for trapless bottom percentile; align concept-layer docs with code"
```

---

### Task 7: Input-handling robustness (CSV multiline, CLI duplicate refs)

**Files:**
- Modify: `hatch_ranker/io.py:70-73` (`_load_csv_records`), `hatch_ranker/validation.py:66-68` (CSV branch of `load_raw_records`)
- Modify: `hatch_ranker/cli.py:43-57` (`main`)
- Test: `tests/test_ranker.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_ranker.InputRobustnessTests -v`
Expected: multiline test FAILS (newline lost or row split); duplicate-ref test FAILS (two `B-01` rows in output).

- [ ] **Step 3: Fix CSV loading in both modules**

```python
# io.py — add `import io as io_module` is unnecessary; use StringIO from the io module:
from io import StringIO

def _load_csv_records(path: Path) -> list[dict[str, object]]:
    raw = _read_text(path)
    rows = csv.DictReader(StringIO(raw))
    return [dict(row) for row in rows]
```

```python
# validation.py — same change in load_raw_records:
from io import StringIO
...
    if source.suffix.lower() == ".csv":
        raw = _read_text(source)
        return [dict(row) for row in csv.DictReader(StringIO(raw))]
```

- [ ] **Step 4: Deduplicate refs in the CLI**

In `cli.py` `main`, after loading base + append files, before ranking:

```python
    seen_refs: set[str] = set()
    unique: list = []
    for thesis in theses:
        if thesis.ref in seen_refs:
            print(f"Skipping duplicate ref {thesis.ref} (source row {thesis.source_index + 1}).")
            continue
        seen_refs.add(thesis.ref)
        unique.append(thesis)
    theses = unique
```

- [ ] **Step 5: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add hatch_ranker/io.py hatch_ranker/validation.py hatch_ranker/cli.py tests/test_ranker.py
git commit -m "fix: multiline CSV fields and duplicate refs across --append"
```

---

### Task 8: Calibration run on the real corpus

The vocabulary changes shift scores; this task verifies the shifts are improvements, not regressions. The challenge corpus is local-only (gitignored).

**Files:**
- Create: `outputs/hardening_after/` (gitignored output)
- Create: `docs/2026-06-10-hardening-impact.md`

- [ ] **Step 1: Produce before/after rankings**

```powershell
cd C:\Dev\HatchFergusChallenge
git stash list  # ensure clean tree
python -m hatch_ranker.cli --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" --out-dir outputs/hardening_after
python scripts/impact_diff.py outputs/original_50_current/ranking.json outputs/hardening_after/ranking.json > docs/2026-06-10-hardening-impact.md
```

(`impact_diff.py` takes two positional `ranking.json` paths — before, then after — and prints a markdown report to stdout; the prior impact doc `docs/2026-06-08-keyword-expansion-impact.md` was produced the same way.)

- [ ] **Step 2: Review every rank movement by hand**

For each thesis that moved more than 3 places, read its text and confirm the movement traces to a removed false positive (compliance trap gone, "lite"/"eta"/"dm" hits gone, revenue band corrected) or to a real trap (unfocused wedge). Record one line per mover in the impact doc: ref, old→new rank, cause.

- [ ] **Step 3: Re-run the stress harness**

```powershell
python -m hatch_ranker.stress --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" --out-dir outputs/stress_hardened --target-size 10000 --seed 105
```

Expected: exit 0, no invariant errors, and the audit's "Suspicious" sections should be no worse than `outputs/stress_10k/ranking_audit.md`.

- [ ] **Step 4: Commit the impact doc**

```bash
git add docs/2026-06-10-hardening-impact.md
git commit -m "docs: hardening impact on the 50-thesis corpus"
```

---

### Task 9 (optional, deploy hygiene): AI-scan abuse guard

The Vercel deployment exposes `POST /api/ai-scan` with `Access-Control-Allow-Origin: *` and no rate limit — anyone can burn the Groq key. Skip this task if the deployment is taken down after the challenge.

**Files:**
- Modify: `hatch_ranker/web.py` (`ai_scan_payload`), `api/index.py` (header pass-through)
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

```python
class AiScanTokenTests(unittest.TestCase):
    def test_scan_rejected_without_token_when_token_configured(self) -> None:
        import os
        from hatch_ranker.web import ai_scan_payload

        os.environ["AI_SCAN_TOKEN"] = "secret"
        try:
            status, body = ai_scan_payload({"ranking": [{"ref": "H-01"}]}, token="")
            self.assertEqual(status, 401)
            self.assertFalse(body["ok"])
        finally:
            del os.environ["AI_SCAN_TOKEN"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_web -v`
Expected: FAIL with `TypeError` (no `token` parameter).

- [ ] **Step 3: Implement**

`web.py` — change the signature and add the gate at the top:

```python
def ai_scan_payload(payload: Any, *, token: str = "") -> tuple[int, dict[str, Any]]:
    required = os.environ.get("AI_SCAN_TOKEN", "")
    if required and token != required:
        return 401, {"ok": False, "observations": [], "error": "Missing or invalid scan token."}
    ...
```

(`web.py` already imports `os`.) Update both call sites to pass the header through:

```python
# web.py HatchRankerRequestHandler.do_POST and api/index.py handler.do_POST:
            status, body = ai_scan_payload(payload, token=self.headers.get("X-Scan-Token", ""))
```

And add `X-Scan-Token` to the CORS allowed headers in `api/index.py`:

```python
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Scan-Token")
```

The frontend keeps working with no token set (the gate only activates when `AI_SCAN_TOKEN` is configured in Vercel env).

- [ ] **Step 4: Run the full suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add hatch_ranker/web.py api/index.py tests/test_web.py
git commit -m "feat: optional shared-token gate on /api/ai-scan"
```

---

## Amendments (2026-06-10, post-review)

- **Task 2:** NEGATORS reduced to absence markers only (no/not/without/zero/never); mitigation verbs (avoid/eliminate/replace families) removed — "eliminates churn" is evidence of churn pain, not its absence. Restored word forms lost by the plural-only heuristic (recovery, restocking, near-real-time, $19/month, etc.).
- **Task 3:** MONEY_PATTERN also accepts spelled-out "million" via `(?:illion)?`; bare "under " (no symbol) removed from the floor-zeroing needles.
- **Task 4 (4b):** Added a second breadth trap, "stuffed vocabulary" (>= 10 distinct fired positive concepts -> overflow-scaled penalty + cap 72), because pain-domain counting alone left a 3-domain stuffer scoring 97.6. Unfocused-wedge cap softened: penalty-only at 4-5 pain domains, cap 72 at >= 6; reason reworded to neutral plain English with human-readable domain labels.

---

## Explicitly out of scope (documented decisions, not gaps)

- **Double-counting of evidence** (one phrase can hit a keyword list, a concept, a trap, and a cap): intentional layering — keyword = magnitude, concept = robustness, trap/cap = severity. Defend it as designed redundancy; do not dampen without corpus evidence it misranks.
- **Criterion baselines (43–76) and group weights (0.48/0.36/0.16)**: hand-calibrated judgment encoded as visible constants; changing them is a recalibration project, not a hardening fix.
- **Embedding/LLM scoring**: rejected — determinism and inspectability are the product's defense. The AI scan stays advisory-only behind the existing non-interference contract.
- **Prompt injection via thesis text into the AI scan**: already mitigated (advisory-only output, ref allowlist, no DOM injection in the frontend).
