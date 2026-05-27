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

## Why This Angle

The challenge is not asking for the biggest theoretical startup. It is asking what a Hatch team can actually stand up, get to revenue within 10 weeks, and expand into something durable. This model is designed to make those judgment calls repeatable and inspectable, including when new theses are added live.
