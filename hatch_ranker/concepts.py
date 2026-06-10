"""Concept-anchor layer for the Hatch ranker.

The keyword scorer in `ranker.py` is brittle to vocabulary drift: a new thesis
written with synonyms can collapse every criterion back to its baseline. The
concept layer adds robustness without sacrificing determinism or
inspectability.

For each criterion we declare a small set of *concepts* (groups of related
phrases that mean the same operational thing). A thesis fires a concept when
any phrase in its trigger set appears in the normalized text. The criterion
score is then adjusted by:

    +5 per fired positive concept (capped at 5)
    -5 per fired negative concept (capped at 3)

The adjustment is added to the keyword score and clamped to [0, 100]. When no
concepts fire, the adjustment is 0 and the keyword score is unchanged. When
the thesis uses unfamiliar vocabulary but its underlying *idea* still maps
onto familiar concepts, the concept layer keeps the score honest.

Saturated-category detection lives in this module too: each saturated
category is itself a concept with a hardcoded density [0, 1] used by the
ranker's trap pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from hatch_ranker.matching import phrase_in


@dataclass(frozen=True)
class Concept:
    name: str
    triggers: tuple[str, ...]


CONCEPTS: dict[str, Concept] = {
    # ----- Buyer pain concepts -----
    "refund_return_pain": Concept(
        "refund_return_pain",
        (
            "refund", "refunded", "refunding", "return", "exchange",
            "chargeback", "claim back", "money back", "send back",
            "ship back", "restock fee",
        ),
    ),
    "churn_cancel_pain": Concept(
        "churn_cancel_pain",
        (
            "churn", "cancel", "cancellation", "lapsed", "unsubscribe",
            "downgrade", "win-back", "winback", "save the cancel",
            "save-the-cancel", "involuntary churn",
        ),
    ),
    "support_volume_pain": Concept(
        "support_volume_pain",
        (
            "support tickets", "helpdesk", "wismo", "where is my order",
            "customer service", "email volume", "inbox", "dms", "direct message",
            "complaint", "complaints", "ticket", "tickets",
        ),
    ),
    "inventory_oos_pain": Concept(
        "inventory_oos_pain",
        (
            "out of stock", "oos", "back in stock", "back-in-stock",
            "stockout", "low stock", "restock", "restocking", "preorder",
            "pre-order", "waitlist", "wishlist",
        ),
    ),
    "failed_payment_pain": Concept(
        "failed_payment_pain",
        (
            "failed payment", "failed-payment", "dunning", "card declined",
            "billing failure", "involuntary churn", "recovery sequence",
            "retry", "payment retry",
        ),
    ),
    "compliance_filing_pain": Concept(
        "compliance_filing_pain",
        (
            "recall", "regulator", "regulatory", "compliance", "sales tax",
            "sales-tax", "nexus", "vat", "epr", "filing", "permit",
            "audit", "certification", "inspection", "lot id", "batch id",
            "proof trail",
        ),
    ),
    "margin_profit_pain": Concept(
        "margin_profit_pain",
        (
            "margin", "p&l", "profit", "below cost", "losing money",
            "cogs", "fees", "commission", "marketplace fees", "storage fees",
            "ad spend", "cac", "ltv", "settlement",
        ),
    ),
    "catalog_quality_pain": Concept(
        "catalog_quality_pain",
        (
            "broken links", "missing images", "missing alt", "duplicate meta",
            "catalog health", "listing quality", "404", "out of policy",
            "listing fixes", "duplicate titles",
        ),
    ),
    "wholesale_b2b_pain": Concept(
        "wholesale_b2b_pain",
        (
            "wholesale", "b2b", "stockist", "stockists", "retailer",
            "retailers", "faire", "moq", "tiered pricing", "net 30",
            "net-30", "purchase order",
        ),
    ),
    "supplier_ops_pain": Concept(
        "supplier_ops_pain",
        (
            "supplier", "supplier reliability", "late deliveries", "defect",
            "moq creep", "po history", "vendor", "fulfillment",
            "packaging", "damage rate", "damage refunds", "dim weight",
        ),
    ),

    # ----- Cash-velocity-side positive concepts -----
    "profit_analytics_pain": Concept(
        "profit_analytics_pain",
        (
            "contribution margin", "net margin", "blended mer",
            "marketing efficiency ratio", "cac payback", "per-sku profitability",
            "sku-level profit", "cogs sync", "blended cac", "true profitability",
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
    "eu_regulatory_pain": Concept(
        "eu_regulatory_pain",
        (
            "gpsr", "gpsr responsible person", "european accessibility act",
            "eaa compliance", "wcag 2.1", "accessibility audit",
            "consent mode v2", "consent management platform",
        ),
    ),

    # ----- ROI visibility concepts -----
    "measurable_revenue_lift": Concept(
        "measurable_revenue_lift",
        (
            "recover", "recovered", "recovery", "lift", "uplift",
            "increase", "increased", "boost conversion", "convert",
            "conversion rate", "aov", "ltv", "repeat purchase",
            "reorder rate", "reactivation", "reactivation sequence",
        ),
    ),
    "measurable_cost_save": Concept(
        "measurable_cost_save",
        (
            "reduce cost", "save cost", "cut cost", "lower fees",
            "fewer refunds", "less waste", "expected savings",
            "lower dim", "fewer chargebacks", "save margin",
            "returnless refund", "deflect returns", "lower return rate",
        ),
    ),
    "aesthetic_no_metric": Concept(
        "aesthetic_no_metric",
        (
            "beautiful", "moment", "share card", "brand aesthetic",
            "designer", "delight", "aesthetic", "stories-ready",
        ),
    ),

    # ----- Setup friction concepts -----
    "low_setup_native": Concept(
        "low_setup_native",
        (
            "one-click", "one click", "30-minute", "30 minute",
            "theme app extension", "widget", "csv", "native shopify",
            "metafield", "drag-and-drop", "drag and drop", "plug into",
            "embed code", "snippet", "auto-publish",
        ),
    ),
    "high_setup_uploads": Concept(
        "high_setup_uploads",
        (
            "merchant uploads", "connected ad account", "merchant defines",
            "voice clone", "voice-clone", "live stream", "multi-step setup",
            "manual upload", "supplier list", "stockist list",
            "experience level", "perk calendar", "founder voice",
        ),
    ),

    # ----- Build complexity concepts -----
    "standard_shopify_build": Concept(
        "standard_shopify_build",
        (
            "shopify admin api", "shopify orders api", "shopify orders",
            "webhook", "theme app extension", "metafield", "liquid",
            "product catalog", "embed widget", "ingest", "csv import",
            "rules", "rule engine",
        ),
    ),
    "hard_realtime_ai_build": Concept(
        "hard_realtime_ai_build",
        (
            "real-time", "near-real-time", "realtime", "live video",
            "live-video", "live stream", "voice clone", "voice-clone",
            "voice questions", "voice answer", "3d mesh", "ar try-on",
            "ar try on", "diffusion", "generative 3d", "size recommendation",
            "voice commerce", "conversational checkout", "real-time voice",
        ),
    ),
    "platform_gated_build": Concept(
        "platform_gated_build",
        (
            "checkout extension", "checkout block", "checkout extensions",
            "cart transform", "shopify functions", "shopify pos",
            "pos return", "shopify payouts", "account updater",
            "visa/mc account",
            "agentic checkout protocol", "universal commerce protocol", "checkout kit",
        ),
    ),
    "third_party_integration_dep": Concept(
        "third_party_integration_dep",
        (
            "recharge", "klaviyo", "postscript", "gorgias", "yotpo",
            "loop", "faire", "meta ads manager", "ad account",
            "carrier tracking", "stripe billing", "shopify email",
            "octane",
        ),
    ),

    # ----- Data access concepts -----
    "merchant_owns_data": Concept(
        "merchant_owns_data",
        (
            "shopify orders", "product catalog", "store's collections",
            "store's customers", "merchant's own data", "merchant data",
            "first-party", "first party", "store-specific",
        ),
    ),
    "thin_data_required": Concept(
        "thin_data_required",
        (
            "co-purchase", "image embeddings", "review photos",
            "open timestamps", "behavioral profile", "exchange data",
            "sold-order data", "historical 90", "last-90", "90-day",
            "exchange history",
        ),
    ),

    # ----- Operational simplicity concepts -----
    "approval_workflow": Concept(
        "approval_workflow",
        (
            "approve", "approval", "decline", "draft", "review before",
            "before sending", "before publishing", "human in the loop",
            "human-in-the-loop", "wizard", "fix list", "queue",
            "morning fix",
        ),
    ),
    "autonomous_irreversible": Concept(
        "autonomous_irreversible",
        (
            "zero human", "closed-loop", "closed loop", "auto-resolves",
            "automatically re-prices", "automatically reprices",
            "auto-replies", "fully autonomous", "price mutation",
            "automatic refund", "automatic message", "speaks for the",
            "autonomous buying agent", "auto-issues refunds",
        ),
    ),

    # ----- Buyer / market signal concepts -----
    "specific_vertical_buyer": Concept(
        "specific_vertical_buyer",
        (
            "apparel", "fashion", "beauty", "skincare", "supplements",
            "wellness", "footwear", "pet", "home", "homeware",
            "jewellery", "jewelry", "candles", "food", "beverage",
            "cpg", "lifestyle",
        ),
    ),
    "small_merchant_buyer": Concept(
        "small_merchant_buyer",
        (
            "sub-$500k", "sub $500k", "sub-$1m", "sub $1m", "$50k",
            "small merchant", "solo founder", "first-time", "sub-",
            "under $",
        ),
    ),
    "mid_market_buyer": Concept(
        "mid_market_buyer",
        (
            "$500k-$5m", "$500k-$10m", "$1m-$5m", "$1m-$10m", "$2m+",
            "$5m+", "mid-market", "mid market", "$200k-$3m",
            "$200k-$2m", "$500k-$2m",
        ),
    ),
    "marketplace_seller_buyer": Concept(
        "marketplace_seller_buyer",
        (
            "amazon seller", "amazon sellers", "marketplace-first",
            "marketplace sellers", "walmart seller", "etsy seller",
            "ebay seller", "gmv", "marketplace gmv",
        ),
    ),

    # ----- Expansion concepts -----
    "recurring_pain_event": Concept(
        "recurring_pain_event",
        (
            "every order", "every return", "every failed payment",
            "every subscriber", "every customer", "every batch",
            "nightly", "daily", "monthly", "per-customer", "per-sku",
            "per-order", "per customer", "every night",
        ),
    ),
    "adjacent_workflow_surface": Concept(
        "adjacent_workflow_surface",
        (
            "dashboard", "command center", "workflow", "rules engine",
            "queue", "inbox", "calendar", "scorecard",
            "audit log", "profile", "fix list", "drafts",
        ),
    ),

    # ----- Differentiation / defensibility concepts -----
    "unique_first_party_data": Concept(
        "unique_first_party_data",
        (
            "merchant's own data", "per-customer", "per-sku", "per-store",
            "first-party signals", "store-specific", "category-normalized",
            "brand-specific", "the store's", "this merchant's",
        ),
    ),
    "incumbent_clone_signal": Concept(
        "incumbent_clone_signal",
        (
            "1/10th", "1/10 the price", "priced at $19", "$19/mo",
            "$19/month", "flat monthly", "flat €", "flat eur",
            "lite version", "cheaper than", "alternative to",
            "$29/mo vs", "$79/mo", "no per-",
            "drop-in replacement", "fraction of the price", "fraction of the cost",
        ),
    ),
    "novelty_consumer_behavior": Concept(
        "novelty_consumer_behavior",
        (
            "mystery", "guess the", "share your haul", "share card",
            "animated card", "gift-wrap", "live-video shopping",
            "live video shopping", "gamified", "blind discount",
            "blind flash",
            "spin to win", "spin-to-win", "wheel of fortune",
        ),
    ),

    # ----- Viability / company-side positive concepts -----
    "inventory_forecast_signal": Concept(
        "inventory_forecast_signal",
        (
            "sell-through rate", "reorder point", "days of supply",
            "safety stock", "stockout prediction", "demand forecast",
            "demand planning", "dead stock", "excess inventory",
        ),
    ),
    "agentic_ready_data": Concept(
        "agentic_ready_data",
        (
            "agentic-ready", "agentic ready", "product data completeness",
            "answer engine optimization", "generative engine optimization",
            "ai shopping agent", "agentic storefront",
        ),
    ),
    "zero_party_data": Concept(
        "zero_party_data",
        (
            "zero-party data", "zero party data", "declared preferences",
            "post-purchase survey", "consent mode v2", "quiz responses",
        ),
    ),
}


# Map each criterion to its positive- and negative-firing concepts.
CRITERION_CONCEPTS: dict[str, dict[str, tuple[str, ...]]] = {
    "buyer_pain": {
        "positive": (
            "refund_return_pain", "churn_cancel_pain", "support_volume_pain",
            "inventory_oos_pain", "failed_payment_pain",
            "compliance_filing_pain", "margin_profit_pain",
            "catalog_quality_pain", "wholesale_b2b_pain",
            "supplier_ops_pain",
            "profit_analytics_pain", "returns_abuse_pain",
            "cross_border_duty_pain", "eu_regulatory_pain",
        ),
        "negative": ("novelty_consumer_behavior", "aesthetic_no_metric"),
    },
    "roi_visibility": {
        "positive": (
            "measurable_revenue_lift", "measurable_cost_save",
            "profit_analytics_pain", "post_purchase_revenue",
            "cross_border_duty_pain",
        ),
        "negative": ("aesthetic_no_metric", "novelty_consumer_behavior"),
    },
    "buyer_clarity": {
        "positive": ("specific_vertical_buyer", "mid_market_buyer", "marketplace_seller_buyer"),
        "negative": ("small_merchant_buyer",),
    },
    "low_setup_friction": {
        "positive": ("low_setup_native",),
        "negative": ("high_setup_uploads",),
    },
    "market_access": {
        "positive": ("mid_market_buyer", "specific_vertical_buyer", "marketplace_seller_buyer"),
        "negative": ("small_merchant_buyer",),
    },
    "buildability": {
        "positive": ("standard_shopify_build",),
        "negative": ("hard_realtime_ai_build", "platform_gated_build"),
    },
    "platform_access": {
        "positive": ("standard_shopify_build", "merchant_owns_data", "agentic_ready_data"),
        "negative": ("platform_gated_build", "third_party_integration_dep"),
    },
    "data_access": {
        "positive": ("merchant_owns_data", "inventory_forecast_signal", "agentic_ready_data", "zero_party_data"),
        "negative": ("thin_data_required",),
    },
    "operational_simplicity": {
        "positive": ("approval_workflow",),
        "negative": ("autonomous_irreversible",),
    },
    "expansion_surface": {
        "positive": (
            "recurring_pain_event", "adjacent_workflow_surface",
            "post_purchase_revenue", "inventory_forecast_signal",
        ),
        "negative": ("novelty_consumer_behavior",),
    },
    "differentiation": {
        "positive": ("unique_first_party_data", "zero_party_data"),
        "negative": ("incumbent_clone_signal",),
    },
    "defensibility": {
        "positive": (
            "unique_first_party_data", "recurring_pain_event",
            "returns_abuse_pain", "zero_party_data",
        ),
        "negative": ("incumbent_clone_signal",),
    },
}


# Pain domains a v1 wedge can credibly attack. Firing many of these at once
# is the signature of an unfocused thesis or keyword-stuffed text.
# Derived from CRITERION_CONCEPTS["buyer_pain"]["positive"] to guarantee sync.
PAIN_CONCEPT_NAMES: frozenset[str] = frozenset(CRITERION_CONCEPTS["buyer_pain"]["positive"])


def fired_pain_concepts(text: str) -> list[str]:
    """Sorted names of distinct pain-domain concepts that fire on the text."""

    return sorted(
        name for name in PAIN_CONCEPT_NAMES if _concept_fires(text, CONCEPTS[name])
    )


POSITIVE_WEIGHT = 5.0
NEGATIVE_WEIGHT = 5.0
POSITIVE_CAP = 5
NEGATIVE_CAP = 3


def concept_adjustment(text: str, criterion: str) -> tuple[float, list[str]]:
    """Return the bounded adjustment a criterion should add to its keyword
    score, and the list of fired concept names (negatives prefixed with ``-``).

    The output is in the range [-15, +25] when configured with the default
    weights, so blending against a keyword score that lives in [0, 100] keeps
    final criterion scores stable.
    """

    config = CRITERION_CONCEPTS.get(criterion)
    if not config:
        return 0.0, []

    fired_positive = [
        name for name in config.get("positive", ())
        if _concept_fires(text, CONCEPTS[name])
    ]
    fired_negative = [
        name for name in config.get("negative", ())
        if _concept_fires(text, CONCEPTS[name])
    ]

    adjustment = min(len(fired_positive), POSITIVE_CAP) * POSITIVE_WEIGHT
    adjustment -= min(len(fired_negative), NEGATIVE_CAP) * NEGATIVE_WEIGHT

    fired_labels = list(fired_positive) + [f"-{name}" for name in fired_negative]
    return adjustment, fired_labels


def _concept_fires(text: str, concept: Concept) -> bool:
    return any(phrase_in(text, trigger) for trigger in concept.triggers)


# ---------------------------------------------------------------------------
# Saturated-category detection (improvement B). Each entry is a category that
# Shopify-app-store evaluators routinely flag as "crowded with strong
# incumbents". The density value [0, 1] reflects how saturated the category
# is, calibrated against the 2025/2026 app-store landscape.
# ---------------------------------------------------------------------------


SATURATED_CATEGORIES: dict[str, dict[str, object]] = {
    "back_in_stock_unified_demand": {
        "triggers": (
            "back-in-stock", "back in stock", "restock", "restocking",
            "notify me", "waitlist", "wishlist", "demand inbox",
        ),
        "density": 0.90,
        "label": "back-in-stock / wishlist / preorder",
        "incumbents": "Klaviyo, Back in Stock Alerts, Notify Me, Restock Rocket, Stocky",
    },
    "abandoned_cart_recovery": {
        "triggers": (
            "abandoned cart", "cart abandonment", "cart recovery",
            "abandon flow",
        ),
        "density": 0.95,
        "label": "abandoned-cart recovery",
        "incumbents": "Klaviyo, Recart, Shopify Email",
    },
    "reviews_widget": {
        "triggers": (
            "review widget", "reviews app", "star ratings", "ugc reviews",
            "photo reviews", "pagerank reviews", "first 5 reviews",
        ),
        "density": 0.95,
        "label": "reviews widget",
        "incumbents": "Yotpo, Judge.me, Stamped, Loox, Okendo",
    },
    "loyalty_referral_dashboard": {
        "triggers": (
            "loyalty tier", "loyalty points", "referral program",
            "rewards program", "loyalty x referral", "loyalty +",
        ),
        "density": 0.85,
        "label": "loyalty / referral",
        "incumbents": "Smile.io, Yotpo Loyalty, LoyaltyLion",
    },
    "subscription_billing_recovery": {
        "triggers": (
            "subscription billing", "subscribe & save", "subscribe and save",
            "subscription save",
        ),
        "density": 0.85,
        "label": "subscribe-and-save",
        "incumbents": "Recharge, Skio, Stay AI, Loop, Appstle (plus Shopify native Subscriptions)",
    },
    "helpdesk_tickets": {
        "triggers": (
            "helpdesk", "macros", "canned responses", "ticket queue",
            "support tickets", "auto-resolves tickets",
        ),
        "density": 0.90,
        "label": "helpdesk / tickets",
        "incumbents": "Gorgias (native AI agent), Zendesk, Tidio, Re:amaze",
    },
    "sms_marketing": {
        "triggers": (
            "sms marketing", "sms blast", "sms campaigns", "per-message sms",
            "sms flows",
        ),
        "density": 0.85,
        "label": "SMS marketing",
        "incumbents": "Postscript, Attentive, Klaviyo SMS (Yotpo/SMSBump exited Dec 2025; assets to Attentive)",
    },
    "email_marketing_blast": {
        "triggers": (
            "email marketing", "email automations", "klaviyo flow",
            "shopify email", "send-time intelligence", "send-time",
        ),
        "density": 0.85,
        "label": "email marketing",
        "incumbents": "Klaviyo, Omnisend, Mailchimp, Shopify Email",
    },
    "product_recommendation_quiz": {
        "triggers": (
            "product recommendation quiz", "recommendation quiz",
            "fit quiz", "goal quiz", "ingredient quiz",
        ),
        "density": 0.75,
        "label": "PDP recommendation quiz",
        "incumbents": "Octane AI, Visely, Shop Quiz, Prehook",
    },
    "ad_creative_generator": {
        "triggers": (
            "ad creative", "ad creatives", "ad variants", "meta ads",
            "tiktok ad", "static ad", "feed ads",
        ),
        "density": 0.75,
        "label": "AI ad-creative generator",
        "incumbents": "AdCreative.ai, Pencil, Creatify",
    },
    "occasion_marketing": {
        "triggers": (
            "occasion marketing", "mother's day", "birthday email",
            "shop by recipient", "occasion stack",
        ),
        "density": 0.60,
        "label": "occasion marketing",
        "incumbents": "Klaviyo segments, Birdsend",
    },
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
        "triggers": ("returns portal", "returns management", "self-service returns", "rma portal"),
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
        "triggers": ("shipping protection", "package protection", "shipping insurance"),
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
        "triggers": ("frequently bought together", "product recommendation engine", "cross-sell app", "related products app"),
        "density": 0.85,
        "label": "product recommendation engine",
        "incumbents": "Rebuy, LimeSpot, Frequently Bought Together, Wiser",
    },
}


@dataclass(frozen=True)
class SaturationHit:
    name: str
    density: float
    label: str
    incumbents: str


def detect_saturation(text: str) -> SaturationHit | None:
    """Return the highest-density saturated category that fires on the thesis
    text, or ``None`` if no saturated category matches."""

    best: SaturationHit | None = None
    for name, data in SATURATED_CATEGORIES.items():
        triggers = data["triggers"]
        if any(phrase_in(text, trigger) for trigger in triggers):  # type: ignore[union-attr]
            hit = SaturationHit(
                name=name,
                density=float(data["density"]),  # type: ignore[arg-type]
                label=str(data["label"]),
                incumbents=str(data["incumbents"]),
            )
            if best is None or hit.density > best.density:
                best = hit
    return best
