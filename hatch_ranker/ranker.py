from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from statistics import mean

from hatch_ranker.models import Scorecard, Thesis, Trap


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
        return cards

    def score(self, thesis: Thesis) -> Scorecard:
        text = normalize(thesis.text)
        customer_text = normalize(thesis.example_customer)
        revenue = parse_revenue_range(thesis.example_customer)
        tags = infer_tags(text, customer_text)

        criteria = {
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
        viability_cap = compute_viability_cap(criteria, traps)
        raw_score = weighted_average(
            (
                (cash_velocity, 0.48),
                (v1_viability, 0.36),
                (company_potential, 0.16),
            )
        )
        penalty = sum(trap.penalty for trap in traps)
        final_score = clamp(min(raw_score, viability_cap) - penalty, 0, 100)

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
        )
        card.rationale = make_rationale(card)
        card.smallest_v1 = smallest_sellable_v1(card)
        card.evidence = make_evidence(thesis, card, revenue)
        return card


def rank_theses(theses: list[Thesis]) -> list[Scorecard]:
    return Ranker().rank(theses)


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
            "15% commission",
            "cancel",
            "churn",
            "subscription",
            "helpdesk",
            "customer service",
            "support",
            "ticket",
            "tickets",
            "emails/dm",
        ),
        cap=5,
    )
    score += 4 * count_any(text, ("aov", "bundle", "upsell", "reorder", "loyalty", "referral"), cap=3)
    score -= 6 * count_any(text, ("mystery", "guess", "screenshot", "share card", "animated card"), cap=2)
    return clamp(score)


def roi_visibility(text: str) -> float:
    score = 42
    score += 8 * count_any(
        text,
        (
            "recover",
            "recovered",
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
            "support",
            "ticket",
            "tickets",
            "eta",
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
    if contains_any(text, ("dtc brands", "shopify", "stores")):
        score += 5
    if contains_any(text, ("sub-$", "sub $", "$1k-50k")):
        score -= 8
    if contains_any(text, ("$10m", "10m+")):
        score -= 6
    if contains_any(text, ("reptile", "lingerie")):
        score -= 5
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
            "zero curation",
            "no customer portal",
            "plug into",
            "drag-and-drop",
            "native shopify",
            "morning fix list",
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
        elif high and high <= 5_000_000 and low >= 100_000:
            score = 78
        elif high and high <= 5_000_000 and low >= 500_000:
            score = 82
        elif high and high >= 10_000_000:
            score = 64
        elif not high and low >= 500_000:
            score = 66
    if contains_any(customer_text, ("dtc brands", "shopify")):
        score += 5
    if contains_any(customer_text, ("reptile", "lingerie")):
        score -= 9
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
    if contains_any(customer_text, ("$50k", "$100k", "sub-$500k", "sub $500k")) and contains_any(
        text, ("checkout extension", "checkout block", "checkout extensions")
    ):
        score -= 12
    if contains_any(text, ("theme app extension", "metafield", "liquid", "shopify email", "shopify orders")):
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
            "supplier pos",
            "cash",
            "commission",
            "payouts",
            "closed-loop",
            "auto-resolves",
            "zero human",
            "re-prices",
            "price mutation",
        ),
        cap=4,
    )
    return clamp(score)


def expansion_surface(text: str) -> float:
    score = 52
    score += 9 * count_any(
        text,
        (
            "demand inbox",
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
            "demand inbox",
            "zero javascript",
            "zero external javascript",
            "actual",
            "approval",
            "approve",
            "migrate",
            "native",
            "rules",
            "queue-and-drip",
            "product is locked",
            "no customer portal",
        ),
        cap=5,
    )
    score -= 7 * count_any(
        text,
        (
            "1/10th",
            "priced at",
            "$19/mo",
            "flat monthly",
            "flat eur",
            "flat €",
            "killing octane",
            "gorgiaslite",
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
            "demand inbox",
            "merchant's own data",
            "category-normalized",
            "dashboard",
            "rules",
            "historical",
            "90-day",
            "customer profile",
            "stockists",
            "supplier",
            "catalog every night",
        ),
        cap=5,
    )
    score -= 7 * count_any(text, ("static ads", "ad creatives", "gift-wrap", "animated card", "mystery discount"), cap=4)
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
    if contains_any(text, ("cart transform", "shopify functions", "shopify pos", "shopify payouts", "visa/mc account updater")):
        traps.append(
            Trap(
                "platform depth",
                8,
                "The wedge leans on deeper platform APIs or third-party rails that may slow a first release.",
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
    if contains_any(text, ("1/10th", "$19/mo", "flat monthly", "killing octane", "gorgiaslite")):
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


def compute_viability_cap(criteria: dict[str, float], traps: list[Trap]) -> float:
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
        positives.append("reachable mid-market DTC buyer")
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
    if contains_any(text, ("inventory", "supplier", "po")):
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
    evidence.append(
        "Inferred: scores are from the thesis text only; no deep market research was used."
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
        ("conversion", ("cart", "checkout", "aov", "bundle", "quiz", "pdp", "social proof")),
        ("retention", ("subscription", "reorder", "replenishment", "loyalty", "churn", "cancel")),
        ("returns", ("return", "refund", "exchange", "resale")),
        ("support", ("helpdesk", "where is my order", "wismo", "ticket")),
        ("inventory", ("inventory", "supplier", "stock", "back-in-stock", "preorder", "pre-order")),
        ("b2b", ("wholesale", "b2b", "stockists", "faire")),
        ("marketing", ("email", "sms", "ad creative", "meta", "tiktok", "occasion")),
        ("ai", ("ai", "gpt", "llm", "embedding", "diffusion", "vision")),
    )
    for tag, needles in checks:
        if contains_any(text, needles):
            tags.append(tag)
    if contains_any(customer_text, ("sub-$500k", "sub $500k", "$50k")):
        tags.append("small-merchant")
    return tags


def parse_revenue_range(text: str) -> RevenueRange | None:
    normalized = normalize(text)
    amounts = [
        money_to_number(match.group(1), match.group(2))
        for match in re.finditer(r"(?:[$€]\s*)?(\d+(?:\.\d+)?)\s*([km])", normalized)
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


def money_to_number(amount: str, suffix: str) -> float:
    number = float(amount)
    multiplier = 1_000 if suffix.lower() == "k" else 1_000_000
    return number * multiplier


def contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def count_any(text: str, needles: tuple[str, ...], *, cap: int) -> int:
    count = sum(1 for needle in needles if needle in text)
    return min(count, cap)


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
