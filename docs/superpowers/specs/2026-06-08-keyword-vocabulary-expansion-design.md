# Design: Research-grounded keyword/concept vocabulary expansion

**Date:** 2026-06-08
**Branch:** `keyword-vocabulary-expansion`
**Status:** Awaiting spec review

This document is both the design spec **and** the committed evidence doc. Every
added term is listed with its target criterion, sign, and the recency-weighted
evidence score behind it.

---

## 1. Goal

Extend the amount of vocabulary the deterministic ranker picks up for each
criterion, grounded in research on Shopify/DTC ecommerce ideas with **actual
recent results** (2025–2026 favored). Add only vocabulary that is genuinely
**new** (not already covered by `ranker.py` raw lists or `concepts.py`), so the
ranker *advances* (catches more real signal) without *disrupting* the calibrated
model.

Non-goals: re-architecting the scoring math; re-weighting the 12 criteria
(unless substantial evidence demands it — see §9, conclusion: it does not);
adding the AI-scan layer into scoring (out of scope).

## 2. Quantification rubric (how good/bad keywords are quantified)

There is no labelled thesis→revenue dataset, and the model is intentionally
rule-based and auditable, so "quantify" means a transparent **evidence score**
per candidate term, not a learned regression coefficient:

```
score = evidence_strength (1-3) x recency (1-3)          range 1-9
  strength: 3 = quantified outcome / enforced regulation / hard adoption number
            2 = clear cross-source consensus
            1 = single or weak source, or hype-adjacent
  recency:  3 = 2025-2026
            2 = 2024
            1 = 2023 or older
sign:  GOOD (+) tied to traction/revenue;  BAD (-) tied to saturation/failure/commoditization
```

**Inclusion threshold:** include a term only if `score >= 4` (reasonably strong
AND reasonably recent).

**Placement rule:**
- `score >= 6` and fits an existing concept -> add as a concept **trigger** (bounded `+5`).
- high-signal GOOD term deserving a stronger pull -> **also** add to a `ranker.py` raw list (`+6/+8`). ("Both layers.")
- genuinely new theme -> a **new named concept** wired to the right criteria.
- BAD crowded market -> a new `SATURATED_CATEGORY` (density calibrated to evidence).
- BAD pattern/phrase -> a **negative** concept trigger or negative raw keyword.

**False-positive guard:** every trigger is checked to be unambiguous under
substring matching on lowercased `title + one_liner + example_customer + wedge`.
Ambiguous short tokens are excluded on purpose (see §8).

## 3. Where the vocabulary lives (recap of approved approach)

- **Concept layer (`concepts.py`) is the primary home** — bounded `+5/-5`, inspectable via "concepts fired".
- **`ranker.py` raw lists** get a curated handful of high-signal terms for stronger pull ("both layers").
- **`SATURATED_CATEGORIES`** gets new crowded categories + an incumbent refresh.
- **No weight re-tune** (§9).

---

## 4. New positive concepts (concepts.py)

Each is a `Concept(name, triggers)` added to `CONCEPTS`, then wired into
`CRITERION_CONCEPTS` under the listed criteria as `positive`.

### 4.1 `profit_analytics_pain` -> buyer_pain, roi_visibility
Triggers:
`"contribution margin"`, `"net margin"`, `"blended mer"`, `"marketing efficiency ratio"`,
`"cac payback"`, `"per-sku profitability"`,
`"sku-level profit"`, `"cogs sync"`, `"blended cac"`, `"true profitability"`
- Sign GOOD. Score 9 (strength 3 x recency 3).
- Evidence: profitability replaced ROAS as the DTC north-star in 2025-26; median DTC CAC $130-156 (2026); Shopify "Cost per item" excludes freight/duty so true landed cost is a documented gap. Sources: Northbeam "Cost of Growth" 2025; StoreHero DTC profitability guide 2026; Luca ecommerce margins 2026; Saras Analytics 2025.

### 4.2 `returns_abuse_pain` -> buyer_pain, defensibility
Triggers:
`"return fraud"`, `"return abuse"`, `"serial returner"`, `"wardrobing"`, `"bracketing"`,
`"returnless refund"`, `"empty box"`, `"refund fraud"`, `"return policy abuse"`, `"return rate scoring"`
- Sign GOOD. Score 9.
- Evidence: $103B fraudulent returns 2024; 11% of shoppers are serial returners; scored from merchant-owned order/return history (so it also strengthens defensibility). Sources: Loop Returns State of Returns Fraud 2024-25; Chargeflow Return Fraud 2026; Signifyd 2025.

### 4.3 `post_purchase_revenue` -> roi_visibility, expansion_surface
Triggers:
`"post-purchase upsell"`, `"post purchase upsell"`, `"order bump"`, `"thank-you page"`,
`"thank you page"`, `"post-purchase survey"`, `"store credit"`, `"subscription pause"`,
`"skip delivery"`, `"win-back sequence"`, `"reactivation sequence"`
- Sign GOOD. Score 8-9.
- Evidence: Checkout Extensibility opened the thank-you/order-status page to all plans (Aug 2025); order bumps/post-purchase offers convert 4-12% with 10-30% AOV lift; pause/skip saves ~25% of would-be churners. Sources: Shopify changelog 2025; Aftersell/Zipify 2025; Churnkey State of Retention 2025.
- NOTE: `"post-purchase upsell"` and `"order bump"` are intentionally **also**
  saturated-category triggers (§6.1). Net effect = real lever, but capped unless
  differentiation is strong. This mirrors how `back-in-stock` is treated today.

### 4.4 `cross_border_duty_pain` -> buyer_pain, roi_visibility
Triggers:
`"landed cost"`, `"de minimis"`, `"import duties"`, `"customs duty"`, `"duty drawback"`,
`"tariff"`, `"hts code"`, `"ioss"`, `"import tax"`, `"cross-border duty"`
- Sign GOOD. Score 9.
- Evidence: US de minimis ($800) suspended for China-origin Feb 2025, ended globally Aug 29 2025; EU removing the EUR150 duty exemption from Jul 2026; every parcel now needs HTS + brokerage. Sources: CNBC Aug 2025; Easyship Section 321 guide 2025; Avalara EU 2026 blog Nov 2025.

### 4.5 `eu_regulatory_pain` -> buyer_pain
Triggers:
`"gpsr"`, `"gpsr responsible person"`, `"european accessibility act"`, `"eaa compliance"`,
`"wcag 2.1"`, `"accessibility audit"`, `"consent mode v2"`, `"consent management platform"`
- Sign GOOD. Score 8-9.
- Evidence: GPSR enforced Dec 13 2024 (non-EU sellers need an EU Responsible Person); EAA enforced Jun 28 2025 (WCAG 2.1 AA for checkout, fines to EUR900k); Google Consent Mode v2 enforcement from Jul 2025. Shopify has no native fix. Sources: Shopify Help Center GPSR; TestParty EAA guide 2025; Pandectes Consent Mode v2 2025.
- NOTE: these correctly **also** trip the existing `compliance scope` trap
  (penalty + cap), encoding "real pain, but watch regulated-infra scope creep".

### 4.6 `inventory_forecast_signal` -> data_access, expansion_surface
Triggers:
`"sell-through rate"`, `"reorder point"`, `"days of supply"`, `"safety stock"`,
`"stockout prediction"`, `"demand forecast"`, `"demand planning"`, `"dead stock"`, `"excess inventory"`
- Sign GOOD. Score 7-8.
- Evidence: buildable from owned Shopify orders; AI forecasting cuts stockouts up to 75% and excess inventory 20-40%. Distinct from existing OOS *pain*. Sources: Prediko 2025; ECOSIRE 2025.

### 4.7 `agentic_ready_data` -> platform_access, data_access
Triggers:
`"agentic-ready"`, `"agentic ready"`, `"product data completeness"`, `"answer engine optimization"`,
`"generative engine optimization"`, `"ai shopping agent"`, `"agentic storefront"`
- Sign GOOD. Score 7-8.
- Evidence: Shopify auto-enrolled millions of stores into AI/agentic storefronts (2026); the *buildable, merchant-owned* half is structured product-data quality / feed optimization (vs. the platform-owned checkout protocols, which are BAD — §7). Sources: Shopify "Agentic-Ready Product Data" 2026; BigCommerce GEO 2026; Amsive AEO 2025.

### 4.8 `zero_party_data` -> data_access, differentiation, defensibility
Triggers:
`"zero-party data"`, `"zero party data"`, `"declared preferences"`, `"post-purchase survey"`,
`"consent mode v2"`, `"quiz responses"`
- Sign GOOD. Score 7-8.
- Evidence: post-cookie first-party/zero-party data is a durable, merchant-owned moat; post-purchase "how did you hear about us" surveys are now standard attribution. Sources: Triple Whale PPS docs 2025; Analyzify first-party data 2025.

---

## 5. Additions to existing positive/negative concepts

| Existing concept | New triggers | Sign | Score |
|---|---|---|---|
| `measurable_cost_save` | `"returnless refund"`, `"deflect returns"`, `"lower return rate"` | + | 8 |
| `measurable_revenue_lift` | `"reactivation"`, `"reactivation sequence"` | + | 7 |
| `incumbent_clone_signal` | `"alternative to"`, `"drop-in replacement"`, `"fraction of the price"`, `"fraction of the cost"`, `"undercut"` | - | 8 |
| `autonomous_irreversible` | `"autonomous buying agent"`, `"auto-issues refunds"`, `"agentic checkout"`, `"fully autonomous"` | - | 8 |
| `hard_realtime_ai_build` | `"voice commerce"`, `"conversational checkout"`, `"real-time voice"` | - | 7 |
| `platform_gated_build` | `"agentic checkout protocol"`, `"universal commerce protocol"`, `"checkout kit"` | - | 7 |
| `novelty_consumer_behavior` | `"spin to win"`, `"spin-to-win"`, `"wheel of fortune"` | - | 7 |

---

## 6. New saturated categories (concepts.py `SATURATED_CATEGORIES`)

These change rankings by design (they cap + penalize crowded ideas). Approved
to add all 10. Density calibrated against the existing scale (reviews/abandoned
cart = 0.95; helpdesk/back-in-stock = 0.90).

| name | density | triggers (exact) | incumbents |
|---|---|---|---|
| `post_purchase_upsell` | 0.88 | `"post-purchase upsell"`, `"thank-you page upsell"`, `"order bump"`, `"one-click upsell"`, `"reconvert"` | ReConvert, AfterSell, Zipify OCU, Rebuy, Honeycomb |
| `page_builder` | 0.90 | `"page builder"`, `"landing page builder"`, `"drag-and-drop page"`, `"pagefly"`, `"gempages"` | PageFly, GemPages, Shogun, Replo, EComposer |
| `returns_portal` | 0.85 | `"returns portal"`, `"returns management"`, `"self-service returns"`, `"rma portal"`, `"return label"` | Loop Returns, AfterShip Returns, Happy Returns, ReturnGO |
| `order_tracking_page` | 0.88 | `"order tracking page"`, `"branded tracking"`, `"shipment tracking page"`, `"parcel tracking"`, `"order lookup page"` | AfterShip, ParcelPanel, Tracktor, 17TRACK |
| `ai_chatbot_support` | 0.88 | `"ai chatbot"`, `"ai support agent"`, `"conversational ai"`, `"support chatbot"`, `"ai concierge"` | Tidio Lyro, Gorgias AI, Intercom Fin, Re:amaze |
| `shipping_protection` | 0.82 | `"shipping protection"`, `"package protection"`, `"shipping insurance"`, `"order protection"` | Route, Navidium, ShipInsure, Seel, Guide |
| `popup_email_capture` | 0.85 | `"email capture popup"`, `"exit-intent popup"`, `"exit intent popup"`, `"newsletter popup"`, `"spin to win"` | Privy, OptiMonk, Justuno, Klaviyo Forms |
| `seo_optimizer` | 0.85 | `"seo app"`, `"seo optimizer"`, `"meta tag optimizer"`, `"auto meta tags"`, `"seo audit"` | Yoast SEO, Plug In SEO, Booster SEO, SearchPie, TinyIMG |
| `server_side_tracking` | 0.82 | `"server-side tracking"`, `"server side tracking"`, `"conversions api"`, `"server-side pixel"`, `"first-party pixel"` | Elevar, Trackify, DataCops (now matched by free Meta CAPI / Google Tag Gateway / Shopify native) |
| `product_reco_engine` | 0.85 | `"frequently bought together"`, `"product recommendation engine"`, `"cross-sell app"`, `"upsell app"`, `"related products app"` | Rebuy, LimeSpot, Frequently Bought Together, Wiser |

Evidence (all 2025-26, strength 2-3): Medium "Don't Build These Shopify Apps" 2025; Craftberry App Store stats 2025 (reviews & upsell are the deepest review pools); StoreCensus most-uninstalled 2025; DataCops Meta CAPI free 2026; ShipAid/centousapps shipping-protection 2025; Wisepops/OptiMonk popup roundups 2026; the4 order-tracking & SEO roundups 2025.

## 6.1 Saturation note on dual-listed terms
`post-purchase upsell` / `order bump` (also in §4.3) and `returns` (the abuse
concept §4.2 vs the generic *portal* triggers here) are deliberately split so a
**differentiated** wedge scores its real upside while a **generic** "build a
returns portal / upsell app" trips saturation.

## 7. Incumbent refresh (string-only, no score change)

- `sms_marketing.incumbents` -> "Postscript, Attentive, Klaviyo SMS (Yotpo/SMSBump exited Dec 2025; assets to Attentive)"
- `subscription_billing_recovery.incumbents` -> "Recharge, Skio, Stay AI, Loop, Appstle (plus Shopify native Subscriptions)"
- `helpdesk_tickets.incumbents` -> "Gorgias (native AI agent), Zendesk, Tidio, Re:amaze"

## 8. Deliberate exclusions (false-positive safety)

Not added, despite appearing in research, because substring matching would
mis-fire on good ideas. Documented so reviewers know it was a choice, not a miss:
- bare `"ai"`, `"ai-powered"` (appears in many strong theses)
- bare `"boost aov"` / `"aov"` as a penalty (`aov` is a positive signal elsewhere)
- bare `"seo"` (matches unrelated tokens; we use `"seo app"`/`"seo optimizer"` instead)
- bare `"capi"` (substring of "capital" etc.; we use `"conversions api"`)
- bare `"chatbot"` / `"duty"` (we use `"ai chatbot"` / `"import duties"`,`"customs duty"`)

## 9. Weight re-tune decision: NONE

The research overwhelmingly *reinforces* the existing criteria balance —
measurable ROI, merchant-owned data, standard Shopify build, human-in-the-loop —
rather than arguing any of the 12 weights are mis-set. Per the approved rule
("only re-tune if substantial evidence"), there is **no** substantial evidence to
move the weights, so cash/v1/company weights and all per-criterion weights stay
exactly as they are. The one strong *structural* 2025-26 signal ("ideas Shopify
nativized / clone positioning") is captured as **vocabulary** (saturated
categories + `incumbent_clone_signal`), which is the model's existing vehicle for
that risk, not a weight change.

## 10. `ranker.py` raw high-signal additions ("both layers")

Curated, score >= 6, reinforced beyond the bounded concept layer:

| function | new positive (+) | new negative (-) |
|---|---|---|
| `buyer_pain` (+8) | `"return fraud"`, `"landed cost"`, `"de minimis"`, `"tariff"` | (none) |
| `roi_visibility` (+8) | `"contribution margin"`, `"returnless refund"`, `"store credit"`, `"duty drawback"` | (none) |
| `buildability` (+6 / -8) | `"reorder point"`, `"post-purchase survey"` | `"voice commerce"`, `"conversational checkout"` |
| `defensibility` (+8 / -7) | `"cohort retention"`, `"zero-party data"` | `"alternative to"`, `"drop-in replacement"` |

## 11. Testing plan

New `tests/test_vocabulary_expansion.py`:
1. **Fires-on-right-criterion:** for each new concept, a thesis containing one trigger raises the mapped criterion above its baseline and lists the concept in `fired_concepts`.
2. **Negative concepts subtract:** clone/autonomous/voice triggers lower their mapped criterion.
3. **New saturated categories detected:** `detect_saturation` returns the expected hit for one trigger of each new category; `Ranker().rank` adds the `saturated category` trap and applies the cap.
4. **No duplicate / no-bare-token guard:** assert no new trigger duplicates another trigger *within the same concept* (cross-concept reuse and concept<->raw reinforcement are allowed by design, matching existing code), and assert the excluded bare tokens (§8) appear in no trigger set.
5. **Boundedness:** a thesis stuffed with many new positive triggers cannot exceed the existing concept cap (criterion still <= 100; concept adjustment <= +20).
6. Full existing suite (46 tests) stays green.

## 12. Impact validation ("advance, don't disrupt")

Before/after on the committed corpus:
- Re-rank `outputs/original_50_current` (and `v2_original_50`) with the new vocabulary.
- Produce a diff report: for each thesis, rank delta, score delta, and which new concepts/saturated categories fired.
- Expectation: most ideas move modestly; movement is explainable by a newly-fired concept or saturated category. If any idea swings hard with no explainable trigger, investigate before merging.

## 13. Deliverables

- `concepts.py`: ~8 new concepts, ~7 concept-trigger additions, 10 new saturated categories, 3 incumbent refreshes.
- `ranker.py`: ~16 raw keyword additions (12 positive, 4 negative).
- `tests/test_vocabulary_expansion.py`: guard + behavior tests.
- This document (committed as the evidence doc).
- A short before/after impact report appended here or in `outputs/`.

## 14. Risks & rollback

- **Over-penalizing via saturated categories.** Mitigated by evidence-calibrated densities and the existing "strong differentiation halves the penalty" rule. The before/after report is the gate.
- **Substring false positives.** Mitigated by §8 exclusions and the test in §11.4.
- **Rollback:** all changes are additive data in two files; revert the commit to restore prior behavior. No schema or interface change.
