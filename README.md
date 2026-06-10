# Hatch105 Build Challenge Ranker

This repo contains a deterministic Python ranking engine for the Hatch105 build challenge.

The angle is **10-week revenue survivability**: rank each thesis by whether a three-person Hatch team can ship a credible v1, sell it quickly, and still have a path to a real company. The model is intentionally not a simple weighted average. It uses visible criteria plus caps and trap penalties so that a huge but unbuildable idea cannot win on market size alone.

> Note: this GitHub repo is public, so the confidential challenge theses and generated thesis-level outputs are intentionally ignored by git. Run the tool against the local challenge files.

## Quick Start

```powershell
cd C:\Dev\HatchFergusChallenge
python -m hatch_ranker.cli --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" --out-dir outputs
```

The command writes:

- `outputs/ranking.csv`
- `outputs/ranking.json`
- `outputs/ranking.md`

For the live rerank, save the 5 new theses in the same CSV or JSON format, then append them:

```powershell
python -m hatch_ranker.cli `
  --input "C:\Users\oreil\Documents\Hatch105 Build Challenge\candidate_theses.csv" `
  --append "C:\path\to\live_theses.csv" `
  --out-dir outputs-live
```

## Local UI

Run the browser UI when you want to paste, replace, append, and rerank JSON lists interactively:

```powershell
python -m hatch_ranker.web --port 8765
```

Then open `http://127.0.0.1:8765`. The UI accepts the same JSON shape as the CLI: a list of thesis objects, or an object with `theses` or `items`. Appended ideas are kept in browser local storage and marked as new while the combined list is reranked.

To enable the optional AI edge-case scan, add `GROQ_API_KEY` to a local `.env` file before starting the UI. The scan runs only when you click the button, sends the current ranked cards in one batched request, and returns short risk/opportunity observations for cases the fixed rulebook may miss. Optionally set `AI_SCAN_TOKEN` to require an `X-Scan-Token` header on `/api/ai-scan` (recommended for public deployments).

## Model

The algorithm scores each thesis across three groups:

1. **Cash velocity**: buyer pain, ROI visibility, buyer clarity, setup friction, and market access.
2. **V1 viability**: buildability, platform access, data access, and operational simplicity.
3. **Company potential**: expansion surface, differentiation, defensibility, and repeatability.

Then it applies trap handling:

- **Technical swamp**: 3D, live video, real-time voice, or brittle AI quality promises.
- **Platform gate**: checkout/POS/deep platform surfaces that may be gated or slow to ship.
- **Trust mutation**: products that auto-change prices, message customers, or speak for the merchant before trust is earned.
- **Novelty demand**: ideas that require new consumer behavior before ROI is obvious.
- **Cheap clone**: wedges that are mostly price arbitrage against incumbents.
- **Thin data**: target customers may not have enough data for the promised model.
- **Platform depth**: deep API surfaces on a single platform that may be gated or change without notice.
- **Platform breadth**: the wedge spans too many platforms simultaneously for a 10-week v1.
- **Marketplace platform**: marketplace-first ideas where account health or policy risk cap the ceiling.
- **Compliance scope**: regulatory filing, recall, or cross-border duty work that requires specialist sign-off.
- **Unclear first sale**: no credible description of who pays, for what, on day one.
- **Saturated category**: a crowded market with named incumbents and no differentiated wedge.
- **Unfocused wedge**: 4+ distinct pain domains — too wide for one 10-week v1.
- **Stuffed vocabulary**: 10+ distinct positive signals fired — reads as keyword stuffing, not one buildable wedge.
- **Rubric saturation**: 5+ of 12 criteria at 85+ simultaneously — real wedges have weak spots.

Matching is word-boundary based with light negation handling (see hatch_ranker/matching.py) so substring artifacts ("vat" in "private") cannot score, and revenue bands require an explicit currency symbol ($, €, £).

Tiers are Top Tier / Strong / Watch / Lagging / Trap, percentile-calibrated against the actual corpus; "Trap" requires an actual trap.

The final score is:

```text
cash_velocity      = weighted criteria around fast paid learning
v1_viability       = weighted criteria around shipping and operational risk
company_potential  = weighted criteria around expansion and durability

raw_score = 0.48 * cash_velocity + 0.36 * v1_viability + 0.16 * company_potential
final_score = min(raw_score, viability_cap) - trap_penalties
```

The cap matters. If buildability, data access, platform access, or operational simplicity is weak, the idea cannot float to the top just because the market is large.

## Testing

```powershell
python -m unittest discover -s tests
```

## Stress Testing

Use the stress harness when you want to throw thousands of private or synthetic ideas at the ranker:

```powershell
python -m hatch_ranker.stress `
  --input data/private/ideas.json `
  --out-dir outputs/stress `
  --target-size 10000 `
  --seed 105
```

Stress mode validates records, skips only invalid ones after logging them, expands the corpus with deterministic adversarial theses, ranks the valid set, and writes:

- `stress_summary.json`
- `validation_issues.csv`
- `ranking.json`
- `ranking.csv`
- `ranking.md`
- `ranking_audit.md`

The audit flags suspicious outcomes instead of pretending every ranking is right: severe-trap ideas in the top 5%, no-trap ideas in the bottom 5%, compliance/platform-heavy ideas without caps, non-DTC ideas with DTC-specific rationale, duplicate-title clusters, and domain coverage.

## Why This Angle

The challenge is not asking for the biggest theoretical startup. It is asking what a Hatch team can actually stand up, get to revenue within 10 weeks, and expand into something durable. This model is designed to make those judgment calls repeatable and inspectable, including when new theses are added live.
