from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from statistics import mean

from hatch_ranker.concepts import (
    CRITERION_CONCEPTS,
    SaturationHit,
    concept_adjustment,
    detect_saturation,
    fired_pain_concepts,
)
from hatch_ranker.matching import any_phrase, count_phrases
from hatch_ranker.models import Scorecard, Thesis, Trap

# Calibration (2026-06-10): across 8 DOMAIN_TEMPLATES + 50-thesis real corpus + REAL-1
# fixture, the highest legitimate criteria-at-85+ count is 4 (two real-corpus theses).
# The orphan-keyword attack (GAME-3) scores 5 at this threshold — below the principled
# floor of max(4+2, 7)=7, so that specific attack is a residual (see docs/superpowers/
# plans/2026-06-10-ranker-hardening.md §4c for the documented ceiling).
RUBRIC_SATURATION_THRESHOLD = 7


@dataclass(frozen=True)
class RevenueRange:
    low: float | None
    high: float | None


class Ranker:
    """Deterministic ranking engine for 10-week startup survivability.

    The model intentionally combines ordinary weighted criteria with caps and
    trap penalties. That keeps a huge but unbuildable idea from winning on
    market size alone.
    """

    def rank(self, theses: list[Thesis]) -> list[Scorecard]:
        cards = [self.score(thesis) for thesis in theses]
        cards.sort(key=lambda card: (-card.final_score, card.thesis.source_index if card.thesis else 0))
        for index, card in enumerate(cards, start=1):
            card.rank = index
        annotate_tiers(cards)
        return cards

    def score(self, thesis: Thesis) -> Scorecard:
        text = normalize(thesis.text)
        customer_text = normalize(thesis.example_customer)
        revenue = parse_revenue_range(thesis.example_customer)
        tags = infer_tags(text, customer_text)

        # Step 1: keyword-based criteria (the original rubric)
        keyword_criteria = {
            "buyer_pain": buyer_pain(text),
            "roi_visibility": roi_visibility(text),
            "buyer_clarity": buyer_clarity(thesis, revenue),
            "low_setup_friction": low_setup_friction(text),
            "market_access": market_access(customer_text, revenue),
            "buildability": buildability(text),
            "platform_access": platform_access(text, customer_text),
            "data_access": data_access(text, customer_text, revenue),
            "operational_simplicity": operational_simplicity(text),
            "expansion_surface": expansion_surface(text),
            "differentiation": differentiation(text),
            "defensibility": defensibility(text),
        }

        # Step 2: concept-anchor blend (improvement A)
        criteria: dict[str, float] = {}
        fired_concepts: dict[str, list[str]] = {}
        for name, keyword_score in keyword_criteria.items():
            adjustment, fired = concept_adjustment(text, name)
            criteria[name] = clamp(keyword_score + adjustment)
            fired_concepts[name] = fired

        cash_velocity = weighted_average(
            (
                (criteria["buyer_pain"], 0.30),
                (criteria["roi_visibility"], 0.28),
                (criteria["buyer_clarity"], 0.16),
                (criteria["low_setup_friction"], 0.14),
                (criteria["market_access"], 0.12),
            )
        )
        v1_viability = weighted_average(
            (
                (criteria["buildability"], 0.40),
                (criteria["platform_access"], 0.22),
                (criteria["data_access"], 0.18),
                (criteria["operational_simplicity"], 0.20),
            )
        )
        company_potential = weighted_average(
            (
                (criteria["expansion_surface"], 0.40),
                (criteria["differentiation"], 0.26),
                (criteria["defensibility"], 0.20),
                (criteria["market_access"], 0.14),
            )
        )

        traps = identify_traps(text, customer_text, revenue, criteria)

        pain_domains = fired_pain_concepts(text)
        if len(pain_domains) >= 4:
            # 4-5 domains = penalty-only scope warning; >= 6 = cap applied below,
            # since no coherent single wedge spans six pain domains.
            overflow = len(pain_domains) - 3
            labels = [name.removesuffix("_pain").replace("_", " ") for name in pain_domains]
            traps.append(
                Trap(
                    "unfocused wedge",
                    round(min(4.0 * overflow, 16.0), 1),
                    (
                        f"The thesis spans {len(pain_domains)} pain areas "
                        f"({', '.join(labels)}); a 10-week v1 has to win one wedge "
                        "first, so breadth this wide is a scope risk."
                    ),
                )
            )

        # Measured on the project's own fixtures: the most verbose legitimate thesis
        # fires 8 distinct positive concepts; adversarial stuffers fire 18+; threshold
        # 10 leaves a 1-concept margin (9 is safe, 10 trips).
        distinct_positives = {
            name
            for names in fired_concepts.values()
            for name in names
            if not name.startswith("-")
        }
        if len(distinct_positives) >= 10:
            overflow = len(distinct_positives) - 9
            traps.append(
                Trap(
                    "stuffed vocabulary",
                    round(min(4.0 * overflow, 16.0), 1),
                    (
                        f"The text fires {len(distinct_positives)} distinct positive signals "
                        "across the rubric; the most credible focused theses fire fewer than "
                        "ten, so this reads as keyword stuffing rather than one buildable wedge."
                    ),
                )
            )

        high_criteria = sorted(name for name, value in criteria.items() if value >= 85)
        if len(high_criteria) >= RUBRIC_SATURATION_THRESHOLD:
            overflow = len(high_criteria) - (RUBRIC_SATURATION_THRESHOLD - 1)
            traps.append(
                Trap(
                    "rubric saturation",
                    round(min(4.0 * overflow, 16.0), 1),
                    (
                        f"{len(high_criteria)} of 12 criteria score 85+ simultaneously; "
                        "real wedges have weak spots, so across-the-board excellence reads "
                        "as text optimized for the rubric rather than a buildable plan."
                    ),
                )
            )

        # Step 3: saturated-category trap + cap (improvement B)
        saturation_hit = detect_saturation(text)
        if saturation_hit is not None:
            traps.append(_saturated_category_trap(saturation_hit, criteria))

        viability_cap = compute_viability_cap(criteria, traps, pain_domain_count=len(pain_domains))
        if saturation_hit is not None:
            viability_cap = _apply_saturation_cap(viability_cap, saturation_hit)

        raw_score = weighted_average(
            (
                (cash_velocity, 0.48),
                (v1_viability, 0.36),
                (company_potential, 0.16),
            )
        )
        penalty = sum(trap.penalty for trap in traps)
        final_score = clamp(min(raw_score, viability_cap) - penalty, 0, 100)

        saturation_payload: dict[str, object] = {}
        if saturation_hit is not None:
            saturation_payload = {
                "name": saturation_hit.name,
                "label": saturation_hit.label,
                "density": round(saturation_hit.density, 2),
                "incumbents": saturation_hit.incumbents,
            }

        card = Scorecard(
            ref=thesis.ref,
            title=thesis.title,
            final_score=final_score,
            cash_velocity=cash_velocity,
            v1_viability=v1_viability,
            company_potential=company_potential,
            viability_cap=viability_cap,
            criteria=criteria,
            traps=traps,
            tags=tags,
            thesis=thesis,
            fired_concepts=fired_concepts,
            saturation=saturation_payload,
        )
        card.rationale = make_rationale(card)
        card.smallest_v1 = smallest_sellable_v1(card)
        card.evidence = make_evidence(thesis, card, revenue)
        return card


def rank_theses(theses: list[Thesis]) -> list[Scorecard]:
    return Ranker().rank(theses)


# ---------------------------------------------------------------------------
# Improvement B: saturated-category trap + cap
# ---------------------------------------------------------------------------


def _saturated_category_trap(hit: SaturationHit, criteria: dict[str, float]) -> Trap:
    has_strong_differentiation = (
        criteria.get("differentiation", 0) >= 70
        or criteria.get("defensibility", 0) >= 70
    )
    base_penalty = (hit.density - 0.5) * 10  # 0.7 -> 2, 0.85 -> 3.5, 0.95 -> 4.5
    penalty = round(base_penalty * (0.5 if has_strong_differentiation else 1.0), 1)
    if penalty < 0:
        penalty = 0
    reason = (
        f"Crowded category ({hit.label}). Strong incumbents already present: "
        f"{hit.incumbents}. The wedge must do more than re-bundle them."
    )
    return Trap("saturated category", penalty, reason)


def _apply_saturation_cap(cap: float, hit: SaturationHit) -> float:
    if hit.density >= 0.85:
        return min(cap, 72)
    if hit.density >= 0.70:
        return min(cap, 78)
    return cap


# ---------------------------------------------------------------------------
# Improvement C: percentile + tier annotation
# ---------------------------------------------------------------------------


SEVERE_TRAPS_FOR_TIER: frozenset[str] = frozenset(
    {"technical swamp", "platform gate", "trust mutation"}
)


def annotate_tiers(cards: list[Scorecard]) -> None:
    """Mutate cards to add ``percentile`` and ``tier`` fields after ranking.

    Tier bands are calibrated against the corpus actually present, so the tier
    of a thesis can shift when a live rerank changes the population. That is
    the point: a thesis is judged against its peers, not against a hardcoded
    score threshold that may not match the current set.
    """

    n = len(cards)
    if n == 0:
        return
    for card in cards:
        percentile = (n - card.rank + 1) / n * 100
        card.percentile = round(percentile, 1)
        card.tier = _tier_for(card)


def _tier_for(card: Scorecard) -> str:
    if any(trap.name in SEVERE_TRAPS_FOR_TIER for trap in card.traps) and card.final_score < 50:
        return "Trap"
    if card.percentile >= 90:
        return "Top Tier"
    if card.percentile >= 70:
        return "Strong"
    if card.percentile >= 30:
        return "Watch"
    return "Trap"


def buyer_pain(text: str) -> float:
    score = 43
    score += 8 * count_any(
        text,
        (
            "failed-payment",
            "failed payment",
            "dunning",
            "where is my order",
            "wismo",
            "return",
            "refund",
            "out of stock",
            "oos",
            "back-in-stock",
            "preorder",
            "pre-order",
            "wholesale",
            "b2b",
            "broken links",
            "missing images",
            "prices below cost",
            "inventory",
            "supplier",
            "stockists",
            "faire",
            "rising-price",
            "cancel",
            "cancellation",
            "churn",
            "subscription",
            "helpdesk",
            "customer service",
            "support",
            "ticket",
            "tickets",
            "emails/dm",
            "recall",
            "incident-response",
            "compliance",
            "regulator",
            "sales-tax",
            "sales tax",
            "nexus",
            "filing",
            "accountant-ready",
            "losing money",
            "cogs",
            "marketplace fees",
            "storage",
            "damage-rate",
            "breakage",
            "damage refunds",
            "supplier reliability",
            "late deliveries",
            "defect",
            "price drift",
            "moq creep",
            "return fraud",
            "landed cost",
            "de minimis",
            "tariff",
        ),
        cap=5,
    )
    score += 4 * count_any(text, ("aov", "bundle", "upsell", "upselling", "reorder", "reordering", "loyalty", "referral"), cap=3)
    score -= 6 * count_any(text, ("mystery", "guess", "screenshot", "share card", "animated card"), cap=2)
    return clamp(score)


def roi_visibility(text: str) -> float:
    score = 42
    score += 8 * count_any(
        text,
        (
            "recover",
            "recovered",
            "recovery",
            "revenue",
            "margin",
            "commission",
            "saving",
            "refund",
            "payment",
            "paid-ad",
            "ad creative",
            "preorder",
            "pre-order",
            "back-in-stock",
            "below cost",
            "demand",
            "cart",
            "aov",
            "conversion",
            "return",
            "reorder",
            "reordering",
            "support",
            "ticket",
            "tickets",
            "eta",
            "profit",
            "p&l",
            "cogs",
            "fees",
            "storage",
            "losing money",
            "expected savings",
            "damage refunds",
            "lower dim weight",
            "sales-tax",
            "sales tax",
            "nexus",
            "recall",
            "regulator",
            "proof trail",
            "contribution margin",
            "returnless refund",
            "store credit",
            "duty drawback",
        ),
        cap=5,
    )
    score -= 7 * count_any(text, ("social proof", "voice", "share", "beautiful", "moment", "brand aesthetic"), cap=3)
    return clamp(score)


def buyer_clarity(thesis: Thesis, revenue: RevenueRange | None) -> float:
    text = normalize(thesis.example_customer)
    score = 56
    if revenue:
        score += 13
    if contains_any(text, ("apparel", "beauty", "supplements", "skincare", "footwear", "pet", "home")):
        score += 8
    if contains_any(text, ("dtc brands", "shopify", "stores", "marketplace", "sellers", "retailers")):
        score += 5
    if contains_any(text, ("sub-$", "sub $", "$1k-50k")):
        score -= 8
    if contains_any(text, ("$10m", "10m+", "€10m", "£10m")):
        score -= 6
    return clamp(score)


def low_setup_friction(text: str) -> float:
    score = 60
    score += 7 * count_any(
        text,
        (
            "one-click",
            "30-minute",
            "30 minute",
            "theme app extension",
            "widget",
            "csv",
            "plug into",
            "drag-and-drop",
            "native shopify",
            "checklists",
            "calendar",
            "exports",
        ),
        cap=4,
    )
    score -= 7 * count_any(
        text,
        (
            "merchant uploads",
            "connected ad account",
            "define",
            "perk calendar",
            "voice-clone",
            "voice clone",
            "live stream",
            "supplier",
            "stockists",
            "3 product photos",
            "front, back, side",
            "experience level",
            "regulator packet",
            "registration",
            "messy inbox",
            "email threads",
        ),
        cap=5,
    )
    return clamp(score)


def market_access(customer_text: str, revenue: RevenueRange | None) -> float:
    score = 62
    if revenue:
        low = revenue.low or 0
        high = revenue.high
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
    if contains_any(customer_text, ("dtc brands", "shopify", "marketplace", "sellers", "retailers")):
        score += 5
    if contains_any(customer_text, ("sub-$500k", "sub $500k", "sub-$1m", "sub $1m")):
        score -= 6
    return clamp(score)


def buildability(text: str) -> float:
    score = 62
    score += 6 * count_any(
        text,
        (
            "widget",
            "theme app extension",
            "shopify admin api",
            "webhook",
            "metafield",
            "liquid",
            "csv",
            "rules",
            "dashboard",
            "crawler",
            "product catalog",
            "shopify orders",
            "one-click",
            "queue",
            "bulk fixes",
            "scorecard",
            "checklists",
            "exports",
            "calendar",
            "reorder point",
            "post-purchase survey",
        ),
        cap=5,
    )
    score -= 8 * count_any(
        text,
        (
            "3d mesh",
            "drape",
            "ar try-on",
            "realtime api",
            "real-time",
            "near-real-time",
            "live-video",
            "voice questions",
            "voice-clone",
            "voice clone",
            "closed-loop",
            "diffusion",
            "generative 3d",
            "size recommendation",
            "exchange data",
            "computer vision",
            "auto-resolves",
            "zero human",
            "messy inbox",
            "email threads",
            "regulator packet",
            "voice commerce",
            "conversational checkout",
        ),
        cap=6,
    )
    return clamp(score)


def platform_access(text: str, customer_text: str) -> float:
    score = 76
    score -= 12 * count_any(
        text,
        (
            "checkout extension",
            "checkout block",
            "checkout extensions",
            "cart transform",
            "shopify functions",
            "shopify payouts",
            "pos return",
            "shopify pos",
            "visa/mc account updater",
            "meta ads manager",
            "faire",
            "recharge",
            "carrier tracking",
            "postscript",
            "klaviyo",
        ),
        cap=4,
    )
    if contains_any(text, PLATFORM_ACCESS_KEYWORDS):
        score -= 8
    if contains_any(customer_text, ("$50k", "$100k", "sub-$500k", "sub $500k")) and contains_any(
        text, ("checkout extension", "checkout block", "checkout extensions")
    ):
        score -= 12
    if contains_any(text, ("theme app extension", "metafield", "liquid", "shopify email", "shopify orders", "exports")):
        score += 7
    return clamp(score)


def data_access(text: str, customer_text: str, revenue: RevenueRange | None) -> float:
    score = 72
    score += 4 * count_any(text, ("product catalog", "shopify orders", "store's collections", "inventory state"), cap=3)
    score -= 6 * count_any(
        text,
        (
            "last-90-day",
            "co-purchase",
            "image embeddings",
            "review photos",
            "open timestamps",
            "supplier",
            "stockists",
            "carrier tracking",
            "competitor",
            "exchange data",
            "sold-order",
            "behavioral profile",
            "supplier coas",
            "batch ids",
            "lot-level",
            "messy inbox",
            "email threads",
            "invoices",
            "shipping notices",
        ),
        cap=6,
    )
    if revenue and revenue.high and revenue.high <= 500_000 and contains_any(text, ("co-purchase", "exchange data", "sold-order")):
        score -= 10
    if contains_any(customer_text, ("sub-$500k", "sub $500k")) and contains_any(text, ("historical", "last-90-day", "open timestamps")):
        score -= 6
    return clamp(score)


def operational_simplicity(text: str) -> float:
    score = 70
    score += 5 * count_any(text, ("approve", "decline", "draft", "fix list", "one-click", "wizard"), cap=4)
    score -= 8 * count_any(
        text,
        (
            "live stream",
            "returns",
            "return label",
            "liquidation",
            "resale",
            "supplier po",
            "cash",
            "commission",
            "payouts",
            "closed-loop",
            "auto-resolves",
            "zero human",
            "re-prices",
            "price mutation",
            "recall",
            "regulator packet",
            "registration",
            "filing calendar",
            "messy inbox",
            "email threads",
        ),
        cap=4,
    )
    return clamp(score)


def expansion_surface(text: str) -> float:
    score = 52
    score += 9 * count_any(
        text,
        (
            "back-in-stock",
            "preorder",
            "wishlist",
            "inventory",
            "supplier",
            "return",
            "resale",
            "subscription",
            "dunning",
            "failed-payment",
            "helpdesk",
            "customer service",
            "b2b",
            "wholesale",
            "catalog health",
            "stockists",
            "loyalty",
            "sku p&l",
            "marketplace",
            "sales-tax",
            "sales tax",
            "nexus",
            "recall",
            "compliance",
            "supplier reliability",
            "damage-rate",
        ),
        cap=5,
    )
    score += 4 * count_any(text, ("dashboard", "profile", "workflow", "queue", "rules"), cap=4)
    score -= 6 * count_any(text, ("banner", "share card", "gift-wrap", "occasion", "mystery", "quiz", "social proof"), cap=4)
    return clamp(score)


def differentiation(text: str) -> float:
    score = 52
    score += 7 * count_any(
        text,
        (
            "unified",
            "one dashboard",
            "approval",
            "approve",
            "migrate",
            "native",
            "rules",
            "proof trail",
        ),
        cap=5,
    )
    score -= 7 * count_any(
        text,
        (
            "1/10th",
            "priced at",
            "$19/mo",
            "$19/month",
            "flat monthly",
            "flat eur",
            "flat €",
            "lite",
            "cheaper",
        ),
        cap=4,
    )
    return clamp(score)


def defensibility(text: str) -> float:
    score = 50
    score += 8 * count_any(
        text,
        (
            "per-customer",
            "per-sku",
            "merchant's own data",
            "category-normalized",
            "dashboard",
            "rules",
            "historical",
            "90-day",
            "customer profile",
            "stockists",
            "supplier",
            "batch ids",
            "lot-level",
            "proof trail",
            "sku p&l",
            "score suppliers",
            "po history",
            "invoices",
            "cohort retention",
            "zero-party data",
        ),
        cap=5,
    )
    score -= 7 * count_any(text, ("static ads", "ad creatives", "gift-wrap", "animated card", "mystery discount", "drop-in replacement", "fraction of the price"), cap=4)
    return clamp(score)


def identify_traps(
    text: str,
    customer_text: str,
    revenue: RevenueRange | None,
    criteria: dict[str, float],
) -> list[Trap]:
    traps: list[Trap] = []
    if contains_any(
        text,
        (
            "3d mesh",
            "drape-capable",
            "ar try-on",
            "generative 3d",
            "live-video",
            "voice questions",
            "realtime api",
        ),
    ):
        traps.append(
            Trap(
                "technical swamp",
                15,
                "Core promise depends on hard real-time, 3D, or multimedia AI quality inside a 10-week window.",
            )
        )
    if contains_any(text, ("checkout extension", "checkout block", "checkout extensions")):
        penalty = 12
        if contains_any(customer_text, ("$50k", "$100k", "$800k", "sub-$", "sub $")):
            penalty += 5
        traps.append(
            Trap(
                "platform gate",
                penalty,
                "Checkout surfaces can be gated by Shopify plan/API constraints, especially for smaller merchants.",
            )
        )
    if contains_any(
        text,
        (
            "cart transform",
            "shopify functions",
            "shopify pos",
            "shopify payouts",
            "visa/mc account updater",
        ),
    ):
        traps.append(
            Trap(
                "platform depth",
                8,
                "The wedge leans on deeper platform APIs or third-party rails that may slow a first release.",
            )
        )
    if count_channel_mentions(text) >= 2 or count_platform_name_mentions(text) >= 2:
        traps.append(
            Trap(
                "platform breadth",
                5,
                "The first release spans multiple sales channels, so the v1 should start with the thinnest useful ingestion path.",
            )
        )
    elif contains_marketplace_surface_text(text):
        traps.append(
            Trap(
                "marketplace platform",
                5,
                "The wedge depends on marketplace policy, exports, listings, or account-health surfaces that can slow the first release.",
            )
        )
    if contains_compliance_scope_text(text):
        traps.append(
            Trap(
                "compliance scope",
                4,
                "Compliance pain is real, but the v1 must avoid becoming regulated workflow infrastructure before the first sale.",
            )
        )
    if contains_any(
        text,
        (
            "closed-loop",
            "re-prices",
            "price mutation",
            "auto-resolves",
            "zero human",
            "cash via shopify payouts",
        ),
    ):
        penalty = 11
        if contains_any(text, ("where is my order", "wismo", "ticket", "tickets", "carrier tracking")):
            penalty = 7
        traps.append(
            Trap(
                "trust mutation",
                penalty,
                "The product changes prices, messages customers, or speaks for the merchant before it has earned trust.",
            )
        )
    if contains_any(text, ("mystery discount", "guess the", "share your haul", "animated card", "gift-wrap", "live-video shopping")):
        traps.append(
            Trap(
                "novelty demand",
                9,
                "The product asks merchants or shoppers to adopt a new behavior before ROI is obvious.",
            )
        )
    if contains_any(text, ("1/10th", "$19/mo", "$19/month", "flat monthly", "fraction of the price", "drop-in replacement", "cheaper than")):
        traps.append(
            Trap(
                "cheap clone",
                7,
                "The wedge risks being price arbitrage against incumbents rather than a durable workflow advantage.",
            )
        )
    if revenue and revenue.high and revenue.high <= 500_000 and contains_any(text, ("co-purchase", "sold-order", "exchange data", "open timestamps")):
        traps.append(
            Trap(
                "thin data",
                8,
                "The target customer may not have enough historical data for the promised model to work reliably.",
            )
        )
    if criteria["buildability"] < 45 and criteria["roi_visibility"] < 65:
        traps.append(
            Trap(
                "unclear first sale",
                8,
                "Hard to build and not immediately tied to a measurable revenue or cost-saving event.",
            )
        )
    return traps


def compute_viability_cap(
    criteria: dict[str, float], traps: list[Trap], *, pain_domain_count: int = 0
) -> float:
    weak_link = min(
        criteria["buildability"],
        criteria["platform_access"],
        criteria["data_access"],
        criteria["operational_simplicity"],
    )
    cap = clamp(weak_link + 24, 42, 100)
    trap_names = {trap.name for trap in traps}
    if "technical swamp" in trap_names:
        cap = min(cap, 58)
    if "platform gate" in trap_names:
        cap = min(cap, 62)
    if "trust mutation" in trap_names:
        cap = min(cap, 68)
    if "thin data" in trap_names:
        cap = min(cap, 70)
    if "stuffed vocabulary" in trap_names:
        cap = min(cap, 72)
    # 4-5 pain domains = penalty only; >= 6 also caps because no coherent
    # single wedge spans six pain domains.
    if pain_domain_count >= 6:
        cap = min(cap, 72)
    if "rubric saturation" in trap_names:
        cap = min(cap, 72)
    if "compliance scope" in trap_names:
        cap = min(cap, 78)
    if "platform breadth" in trap_names:
        cap = min(cap, 82)
    if "marketplace platform" in trap_names:
        cap = min(cap, 82)
    return cap


def make_rationale(card: Scorecard) -> str:
    c = card.criteria
    positives: list[str] = []
    if c["buyer_pain"] >= 76:
        positives.append("acute merchant pain")
    if c["roi_visibility"] >= 76:
        positives.append("visible ROI")
    if c["buildability"] >= 76:
        positives.append("credible 10-week v1")
    if c["low_setup_friction"] >= 74:
        positives.append("low setup friction")
    if c["expansion_surface"] >= 76:
        positives.append("room to expand beyond the wedge")
    if c["market_access"] >= 76:
        positives.append("reachable mid-market buyer")
    if not positives:
        positives.append("balanced but not exceptional fundamentals")

    rationale = "Scores well on " + ", ".join(positives[:3]) + "."
    if card.traps:
        top_traps = ", ".join(trap.name for trap in card.traps[:2])
        rationale += f" Capped by {top_traps} risk."
    elif card.v1_viability < 68:
        rationale += " Main watch-out is whether the v1 can be simple enough."
    elif card.cash_velocity < 68:
        rationale += " Main watch-out is proving merchants will pay quickly."
    else:
        rationale += " The first paid pilot is easy to describe."
    return rationale


def smallest_sellable_v1(card: Scorecard) -> str:
    text = normalize(card.thesis.text if card.thesis else "")
    if contains_any(text, ("back-in-stock", "preorder", "pre-order", "wishlist", "demand inbox")):
        return "A Shopify PDP widget that auto-switches between Save, Notify, and Pre-order, plus a merchant demand inbox and one broadcast template."
    if contains_any(text, ("catalog health", "broken links", "missing images", "prices below cost", "catalog every night")):
        return "A nightly catalog audit that emails a ranked fix list and supports two one-click fixes: unpublish zero-inventory products and patch missing image/SEO fields."
    if contains_any(text, ("where is my order", "wismo", "carrier tracking", "customer service")):
        return "A helpdesk/Gmail connected assistant that drafts Shopify order-status replies from carrier data, with human approval before auto-send."
    if contains_any(text, ("wholesale", "b2b", "stockists", "faire")):
        return "A simple B2B ordering portal with CSV import, tiered pricing, MOQ, and branded invite links for the first 10 wholesale buyers."
    if contains_any(text, ("failed-payment", "dunning", "recharge")):
        return "A failed-payment webhook listener that sends a three-step email/SMS recovery sequence and reports dollars recovered."
    if contains_any(text, ("return", "refund", "exchange", "resale")):
        return "A return-intake rules screen that recommends exchange, credit, or resale routing and shows estimated margin impact before any automation."
    if contains_any(text, ("inventory", "supplier", "purchase order", "po history", "reorder point")):
        return "A stock-level watcher that drafts supplier PO emails from reorder rules and requires merchant approval before sending."
    if contains_any(text, ("ad creative", "meta", "tiktok", "creative")):
        return "An approval-first creative generator that exports static ad variants from product photos before attempting direct ad-account launch."
    return "A narrow Shopify app that proves one measurable action for one merchant segment, with approval queues before any irreversible automation."


def make_evidence(thesis: Thesis, card: Scorecard, revenue: RevenueRange | None) -> list[str]:
    evidence = [
        f"Observed: target customer is '{thesis.example_customer}'.",
        f"Observed: wedge is '{thesis.wedge}'.",
    ]
    if revenue:
        high = f"${revenue.high:,.0f}" if revenue.high else "open-ended"
        low = f"${revenue.low:,.0f}" if revenue.low else "$0"
        evidence.append(f"Inferred: stated revenue band is roughly {low} to {high}.")
    if card.saturation:
        evidence.append(
            "Saturation: '{label}' (density {density:.2f}). Incumbents: {incumbents}.".format(
                label=card.saturation["label"],
                density=float(card.saturation["density"]),
                incumbents=card.saturation["incumbents"],
            )
        )
    evidence.append(
        "Inferred: scores are from the thesis text only; verify market claims before commit."
    )
    if card.traps:
        evidence.append(
            "Judgment call: trap penalties applied for "
            + ", ".join(trap.name for trap in card.traps)
            + "."
        )
    else:
        evidence.append("Judgment call: no hard trap was detected by the rulebook.")
    return evidence


def infer_tags(text: str, customer_text: str) -> list[str]:
    tags: list[str] = []
    checks = (
        ("conversion", ("cart", "add-to-cart", "in-cart", "checkout", "aov", "bundle", "quiz", "quizzes", "pdp", "social proof")),
        ("retention", ("subscription", "reorder", "replenishment", "loyalty", "churn", "cancel", "cancellation")),
        ("returns", ("return", "refund", "exchange", "resale")),
        ("support", ("helpdesk", "where is my order", "wismo", "ticket")),
        ("inventory", ("inventory", "supplier", "stock", "restocking", "back-in-stock", "preorder", "pre-order")),
        ("b2b", ("wholesale", "b2b", "stockists", "faire")),
        ("marketing", ("email", "sms", "ad creative", "meta", "tiktok", "occasion")),
        ("ai", ("ai", "gpt", "llm", "embedding", "diffusion", "vision")),
        ("marketplace", MARKETPLACE_TAG_KEYWORDS),
        ("compliance", COMPLIANCE_KEYWORDS),
        ("operations", ("packaging", "damage", "supplier", "po history", "cogs", "p&l")),
    )
    for tag, needles in checks:
        if contains_any(text, needles):
            tags.append(tag)
    if contains_any(customer_text, ("sub-$500k", "sub $500k", "$50k")):
        tags.append("small-merchant")
    return tags


MONEY_PATTERN = re.compile(r"[$€£]\s*(\d+(?:,\d{3})*(?:\.\d+)?)\s*([km])(?:illion)?\b")


def parse_revenue_range(text: str) -> RevenueRange | None:
    normalized = normalize(text)
    amounts = [
        money_to_number(match.group(1).replace(",", ""), match.group(2))
        for match in MONEY_PATTERN.finditer(normalized)
    ]
    if not amounts:
        return None
    first = amounts[0]
    if contains_any(normalized, ("sub-$", "sub $", "under $")) and len(amounts) == 1:
        return RevenueRange(0, first)
    if "+" in normalized and len(amounts) == 1:
        return RevenueRange(first, None)
    if len(amounts) == 1:
        return RevenueRange(first, first)
    low = min(amounts[0], amounts[1])
    high = max(amounts[0], amounts[1])
    return RevenueRange(low, high)


PLATFORM_NAME_KEYWORDS = (
    "amazon",
    "walmart",
    "ebay",
    "etsy",
    "stripe",
    "tiktok shop",
    "tik tok shop",
    "faire",
)


CHANNEL_BREADTH_GROUPS = (
    ("shopify", "dtc", "storefront"),
    ("marketplace", *PLATFORM_NAME_KEYWORDS),
    ("wholesale", "wholesale portal", "b2b", "stockist"),
    ("retail", "retailer", "pop-up", "pop up"),
)


MARKETPLACE_PLATFORM_KEYWORDS = (
    "marketplace-first",
    "marketplace sellers",
    "marketplace limits",
    "marketplace promos",
    "marketplace facilitator",
    "account health",
    "account-health",
    "listing fixes",
    "listing edits",
    "policy emails",
    "appeal evidence",
)


PLATFORM_ACCESS_KEYWORDS = (*PLATFORM_NAME_KEYWORDS, *MARKETPLACE_PLATFORM_KEYWORDS)


MARKETPLACE_TAG_KEYWORDS = ("marketplace", *PLATFORM_NAME_KEYWORDS)


COMPLIANCE_KEYWORDS = (
    "recall",
    "regulator",
    "regulatory",
    "sales-tax",
    "sales tax",
    "nexus",
    "filing",
    "permit",
    "certification",
    "inspection",
    "biosecurity",
    "audit packet",
    "regulator-ready",
    "epr",
    "vat",
    "hazmat",
)


def count_channel_mentions(text: str) -> int:
    if contains_any(text, ("multi-channel", "multichannel", "split across")):
        return 2
    groups = 0
    for group in CHANNEL_BREADTH_GROUPS:
        if contains_any(text, group):
            groups += 1
    return groups


def count_platform_name_mentions(text: str) -> int:
    return count_any(text, PLATFORM_NAME_KEYWORDS, cap=len(PLATFORM_NAME_KEYWORDS))


def contains_marketplace_surface_text(text: str) -> bool:
    return contains_any(text, MARKETPLACE_PLATFORM_KEYWORDS)


def contains_compliance_scope_text(text: str) -> bool:
    return contains_any(text, COMPLIANCE_KEYWORDS)


def money_to_number(amount: str, suffix: str) -> float:
    number = float(amount)
    multiplier = 1_000 if suffix.lower() == "k" else 1_000_000
    return number * multiplier


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any_phrase(text, needles)


def count_any(text: str, needles: tuple[str, ...], *, cap: int) -> int:
    return count_phrases(text, needles, cap=cap)


def weighted_average(values: tuple[tuple[float, float], ...]) -> float:
    numerator = sum(value * weight for value, weight in values)
    denominator = sum(weight for _, weight in values)
    return numerator / denominator


def normalize(value: str) -> str:
    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = cleaned.replace("–", "-").replace("—", "-").replace("’", "'")
    return re.sub(r"\s+", " ", cleaned).lower().strip()


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))
