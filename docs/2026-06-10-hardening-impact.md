# Ranker Hardening Impact (before -> after)

Before = pre-branch main (75fdd56), regenerated 2026-06-10 in a clean worktree (the older
`outputs/original_50_current` snapshot predates the v2 concept layer and was NOT used).
After = `ranker-hardening` branch head. Generated with `scripts/impact_diff.py`; causal
traces below produced with `scripts/trace_movers.py`. Refs and numbers only — no thesis text.

## Summary

- **Top 3 unchanged** (H-19, H-39, H-29). 38/50 shifted rank; max move 13 places.
- **Zero real theses** fire any of the three new breadth traps (unfocused wedge,
  stuffed vocabulary, rubric saturation) — they exist purely as anti-gaming armor.
- Stress harness: 10,000 records, no invariant errors, 19.8s (budget 60s).
- The matcher prefilter was verified score-neutral: rerunning the corpus with and
  without it produces byte-identical ranking.json.

## Hand review of movers > 3 places

Every large move traces to an intended fix, not collateral damage:

- **H-40 (28→15), H-06 (16→7)**: lost a false `platform breadth` trap (cap 82→92) that
  substring matching had pinned on them; small roi_visibility shifts from removed
  false keywords. Both were under-ranked before.
- **H-22 (10→22)**: buyer_pain −26 / expansion −18 — it had been collecting
  `failed_payment_pain` and `wholesale_b2b_pain` credit from substring artifacts
  (bare "po"-class needles). The pain credit was never real.
- **H-24 (19→11)**: lost the false `compliance scope` trap — the headline "vat"/"epr"
  substring bug ("private", "elevate", "innovative", "entrepreneur").
- **H-04 (15→20), H-37 (21→25), H-21 (23→27)**: stopped firing `wholesale_b2b_pain`
  via the removed bare-"po" trigger; modest deserved drops.
- **H-02 (13→18)**: keyword-level false positives removed ("eta"-class hits plus
  fingerprint vocabulary) across roi/friction/differentiation/defensibility.
- **H-20 (48→44)**: lost a false `unclear first sale` trap after buildability false
  negatives were fixed; still bottom-tier.
- **H-08 (4→8)**: lost spurious `refund_return_pain` / `measurable_revenue_lift`
  credit (roi_visibility −21) — words it used incidentally, not its actual wedge.

Rows sorted by absolute rank movement.

| Ref | Rank b->a | dRank | dScore | Newly fired |
|---|---|---:|---:|---|
| H-40 | 28->15 | +13 | +3.92 | - |
| H-22 | 10->22 | -12 | -5.66 | - |
| H-06 | 16->7 | +9 | +6.26 | - |
| H-24 | 19->11 | +8 | +2.56 | - |
| H-04 | 15->20 | -5 | -2.09 | - |
| H-02 | 13->18 | -5 | -2.09 | - |
| H-37 | 21->25 | -4 | -0.72 | - |
| H-21 | 23->27 | -4 | -2.60 | - |
| H-20 | 48->44 | +4 | +9.62 | - |
| H-08 | 4->8 | -4 | -5.56 | - |
| H-44 | 38->41 | -3 | -1.01 | - |
| H-33 | 33->30 | +3 | +2.27 | - |
| H-14 | 30->33 | -3 | -2.06 | - |
| H-50 | 18->16 | +2 | +1.10 | - |
| H-42 | 43->45 | -2 | -0.72 | - |
| H-32 | 47->49 | -2 | -0.18 | - |
| H-31 | 41->39 | +2 | +0.00 | - |
| H-28 | 46->48 | -2 | +0.00 | - |
| H-26 | 8->10 | -2 | -2.58 | - |
| H-15 | 27->29 | -2 | -1.48 | - |
| H-10 | 49->47 | +2 | +7.00 | - |
| H-49 | 6->5 | +1 | +0.00 | - |
| H-48 | 20->19 | +1 | +0.00 | - |
| H-46 | 44->43 | +1 | +0.81 | - |
| H-43 | 24->23 | +1 | +0.00 | - |
| H-41 | 37->36 | +1 | +2.96 | - |
| H-38 | 5->4 | +1 | -0.14 | - |
| H-35 | 25->24 | +1 | +0.00 | - |
| H-34 | 22->21 | +1 | -0.29 | - |
| H-30 | 31->32 | -1 | +0.00 | - |
| H-25 | 11->12 | -1 | -0.72 | - |
| H-18 | 7->6 | +1 | +0.72 | - |
| H-13 | 36->37 | -1 | +0.00 | - |
| H-12 | 39->38 | +1 | +0.00 | - |
| H-11 | 32->31 | +1 | +0.47 | - |
| H-09 | 45->46 | -1 | +0.00 | - |
| H-05 | 29->28 | +1 | -0.67 | - |
| H-01 | 12->13 | -1 | +0.00 | - |
| H-47 | 34->34 | +0 | -0.72 | - |
| H-45 | 17->17 | +0 | +0.00 | - |
| H-39 | 2->2 | +0 | -3.78 | - |
| H-36 | 26->26 | +0 | -1.08 | - |
| H-29 | 3->3 | +0 | -2.81 | - |
| H-27 | 14->14 | +0 | +0.00 | - |
| H-23 | 35->35 | +0 | +0.00 | - |
| H-19 | 1->1 | +0 | -3.65 | - |
| H-17 | 40->40 | +0 | -0.72 | - |
| H-16 | 42->42 | +0 | -0.72 | - |
| H-07 | 9->9 | +0 | -0.98 | - |
| H-03 | 50->50 | +0 | +0.00 | - |

**38/50 theses changed rank.** Max move: 13 places.
