from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from hatch_ranker.io import write_outputs
from hatch_ranker.models import Scorecard, Thesis
from hatch_ranker.ranker import Ranker, normalize
from hatch_ranker.validation import (
    ValidationIssue,
    load_raw_records,
    validate_records,
    write_validation_issues,
)


SEVERE_TRAPS = {
    "technical swamp",
    "platform gate",
    "platform depth",
    "trust mutation",
}

PLATFORM_TRAPS = {"platform breadth", "platform depth", "platform gate", "marketplace platform"}


DOMAIN_TEMPLATES: list[dict[str, str]] = [
    {
        "title": "Recall Ledger",
        "one_liner": "Recall readiness for regulated consumables brands",
        "example_customer": "Supplements and pet food brands, $500K-$10M",
        "wedge": "Builds regulator packets, affected customer lists, lot-level proof trails, refund workflows, and retailer notices from batch IDs, supplier COAs, complaints, and orders.",
    },
    {
        "title": "Margin Truth",
        "one_liner": "SKU-level profit control for marketplace sellers",
        "example_customer": "Amazon, Walmart, and Etsy sellers doing $250K-$5M GMV",
        "wedge": "Pulls fees, ads, returns, storage, shipping, promos, refunds, and COGS into a SKU P&L, then drafts kill, raise, or reprice actions.",
    },
    {
        "title": "Pack Bench",
        "one_liner": "Packaging cost and damage-rate simulator",
        "example_customer": "Fragile goods and homeware DTC brands, $500K-$10M",
        "wedge": "Models product dimensions, carrier mix, breakage history, void-fill inches, DIM weight, and damage refunds before a merchant buys packaging.",
    },
    {
        "title": "Sales Tax Scout",
        "one_liner": "Sales-tax nexus monitor before full Avalara pain",
        "example_customer": "US DTC and marketplace sellers, $100K-$2M",
        "wedge": "Watches Shopify, Amazon, Etsy, and Stripe sales by state, alerts near nexus thresholds, and exports registration checklists, filing calendars, and accountant-ready summaries.",
    },
    {
        "title": "Vendor Score",
        "one_liner": "Supplier reliability scorecard from PO history",
        "example_customer": "Small retailers and DTC brands with 5-50 recurring suppliers, $500K-$10M",
        "wedge": "Reads POs, invoices, shipping notices, late deliveries, defect notes, and email threads to score lateness, fill rate, price drift, MOQ creep, and defect rate.",
    },
    {
        "title": "Cold Chain Watch",
        "one_liner": "Exception dashboard for temperature-sensitive shipments",
        "example_customer": "Food, beverage, and skincare brands, $250K-$5M",
        "wedge": "Combines carrier events, sensor exports, refunds, and complaints to flag shipments likely to spoil before customers complain.",
    },
    {
        "title": "Wholesale Switchboard",
        "one_liner": "B2B reorder portal for independent stockists",
        "example_customer": "Home, beauty, and apparel brands, $500K-$5M",
        "wedge": "Imports retailer lists, sends reorder links, applies MOQ and tier pricing rules, and tracks which stockists are slipping before a rep notices.",
    },
    {
        "title": "Everything AI Autopilot",
        "one_liner": "Realtime 3D voice checkout pricing agent",
        "example_customer": "DTC brands, $50K-$10M",
        "wedge": "Generates 3D mesh AR try-ons, answers checkout questions in a cloned founder voice, re-prices SKUs with closed-loop mutations, and auto-resolves tickets with zero human input.",
    },
]


HOSTILE_SNIPPETS = [
    'pipes | commas, quotes "inside", and CRLF\r\nsecond line',
    "<script>alert('rank')</script> markdown | table breaker",
    "Unicode stress: café, naïve, €250K, emoji-like text, en-dash – em-dash —",
    "No revenue band here, just vague enterprise ambition and vibes.",
    "$1,500K-$2.75M malformed-ish money with commas and decimals",
    "sub-$500K plus $5M+ contradictory revenue language",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hatch-stress",
        description="Brute-force robustness and quality-audit harness for the Hatch thesis ranker.",
    )
    parser.add_argument("--input", "-i", required=True, help="Private .json or .csv file of ideas to stress.")
    parser.add_argument("--out-dir", "-o", default="outputs/stress", help="Directory for stress reports.")
    parser.add_argument("--target-size", type=int, default=10_000, help="Target number of valid ranked records.")
    parser.add_argument("--seed", type=int, default=105, help="Deterministic synthetic generation seed.")
    parser.add_argument("--top", type=int, default=250, help="Rows to include in ranking.md.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=60.0,
        help="Soft performance budget recorded in the summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_stress(
        input_path=Path(args.input),
        out_dir=Path(args.out_dir),
        target_size=args.target_size,
        seed=args.seed,
        top_n=args.top,
        max_seconds=args.max_seconds,
    )
    print(f"Stress ranked {result['counts']['ranked']} valid records.")
    print(f"Wrote {Path(args.out_dir) / 'stress_summary.json'}")
    print(f"Wrote {Path(args.out_dir) / 'ranking_audit.md'}")
    if result["invariant_errors"]:
        print(f"Invariant errors: {len(result['invariant_errors'])}")
        return 1
    if result["timings"]["total_seconds"] > args.max_seconds:
        print(f"Performance budget exceeded: {result['timings']['total_seconds']:.2f}s > {args.max_seconds:.2f}s")
        return 1
    return 0


def run_stress(
    *,
    input_path: Path,
    out_dir: Path,
    target_size: int = 10_000,
    seed: int = 105,
    top_n: int = 250,
    max_seconds: float = 60.0,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    start_total = time.perf_counter()

    loaded_at = time.perf_counter()
    raw_source = load_raw_records(input_path)
    timings["load_seconds"] = elapsed_since(loaded_at)

    validated_at = time.perf_counter()
    source_result = validate_records(raw_source)
    timings["source_validation_seconds"] = elapsed_since(validated_at)

    generated_at = time.perf_counter()
    needed = max(0, target_size - len(source_result.theses))
    synthetic_valid = generate_synthetic_records(source_result.theses, needed, seed=seed)
    synthetic_invalid = generate_invalid_records(seed=seed)
    raw_synthetic = synthetic_valid + synthetic_invalid
    timings["generation_seconds"] = elapsed_since(generated_at)

    synthetic_validated_at = time.perf_counter()
    synthetic_result = validate_records(raw_synthetic, start_index=len(raw_source))
    timings["synthetic_validation_seconds"] = elapsed_since(synthetic_validated_at)

    synthetic_used = synthetic_result.theses[:needed] if needed else []
    theses = source_result.theses + synthetic_used

    ranked_at = time.perf_counter()
    cards = Ranker().rank(theses)
    timings["ranking_seconds"] = elapsed_since(ranked_at)

    determinism_at = time.perf_counter()
    ranking_hash = scorecards_hash(cards)
    second_hash = scorecards_hash(Ranker().rank(list(theses)))
    timings["determinism_seconds"] = elapsed_since(determinism_at)

    invariant_errors = check_invariants(cards, theses, ranking_hash, second_hash)

    write_at = time.perf_counter()
    write_outputs(cards, out_dir, top_n=top_n)
    issues = source_result.issues + synthetic_result.issues
    write_validation_issues(issues, out_dir / "validation_issues.csv")
    audit = build_audit(cards, issues)
    (out_dir / "ranking_audit.md").write_text(audit, encoding="utf-8")
    timings["write_seconds"] = elapsed_since(write_at)

    timings["total_seconds"] = elapsed_since(start_total)

    summary = build_summary(
        input_path=input_path,
        seed=seed,
        target_size=target_size,
        max_seconds=max_seconds,
        timings=timings,
        raw_source_count=len(raw_source),
        source_result=source_result,
        raw_synthetic_count=len(raw_synthetic),
        synthetic_result=synthetic_result,
        synthetic_used_count=len(synthetic_used),
        cards=cards,
        ranking_hash=ranking_hash,
        invariant_errors=invariant_errors,
        issues=issues,
    )
    (out_dir / "stress_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return summary


def generate_synthetic_records(base_theses: list[Thesis], count: int, *, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    records: list[dict[str, str]] = []
    bases = base_theses or [
        Thesis(
            ref="BASE-000",
            title="Baseline Idea",
            one_liner="Operational savings dashboard for merchants",
            example_customer="DTC and marketplace sellers, $250K-$5M",
            wedge="Finds costly mistakes and drafts approval-first fixes.",
            source_index=0,
        )
    ]

    for idx in range(count):
        if base_theses and idx % 7 == 0:
            base = bases[idx % len(bases)]
            record = {
                "title": base.title,
                "one_liner": base.one_liner,
                "example_customer": base.example_customer,
                "wedge": base.wedge,
            }
        else:
            record = dict(DOMAIN_TEMPLATES[idx % len(DOMAIN_TEMPLATES)])

        ref = f"SYN-{idx + 1:06d}"
        if idx % 251 == 0:
            record["title"] = "Duplicate Cluster Thesis"
        else:
            record["title"] = f"{record['title']} Stress {idx + 1:06d}"

        if idx % 11 == 0:
            record["wedge"] = f"{record['wedge']} {HOSTILE_SNIPPETS[(idx // 11) % len(HOSTILE_SNIPPETS)]}"
        if idx % 17 == 0:
            record["example_customer"] = rng.choice(
                [
                    "Brands doing $500K-$5M",
                    "Marketplace sellers, $1.5M+ GMV",
                    "US DTC brands, sub-$500K",
                    "EU retailers doing €250K-€2M",
                    "No clear revenue band",
                    "Operators doing $1,500K-$2.75M with mixed channels",
                ]
            )
        if idx % 29 == 0:
            record["one_liner"] = " ".join(
                [
                    record["one_liner"],
                    "recall checkout extension platform gate zero human 3D mesh profit truth supplier reliability",
                ]
            )
        if idx % 37 == 0:
            record["wedge"] = "No meaningful wedge. Vague AI for everyone with no buyer, no ROI, and no setup detail."

        record["ref"] = ref
        records.append(record)

    return records


def generate_invalid_records(*, seed: int) -> list[Any]:
    rng = random.Random(seed)
    huge = "oversize " * 3_000
    return [
        "not an object",
        {"ref": "BAD-001", "title": "", "one_liner": "Missing title", "example_customer": "DTC, $1M", "wedge": "Test"},
        {"ref": "BAD-002", "title": "Null Wedge", "one_liner": "Null field", "example_customer": "DTC, $1M", "wedge": None},
        {"ref": "BAD-003", "title": "Non String", "one_liner": 123, "example_customer": "DTC, $1M", "wedge": "Test"},
        {"ref": "BAD-004", "title": "Missing customer", "one_liner": "Bad shape", "wedge": "Test"},
        {"ref": "SYN-000001", "title": "Duplicate Ref", "one_liner": "Dup", "example_customer": "DTC, $1M", "wedge": "Test"},
        {
            "ref": f"WARN-{rng.randint(1, 999):03d}",
            "title": "Huge But Valid",
            "one_liner": "Very large wedge should warn, not fail",
            "example_customer": "DTC brands, $500K-$5M",
            "wedge": huge,
        },
    ]


def check_invariants(
    cards: list[Scorecard],
    theses: list[Thesis],
    ranking_hash: str,
    second_hash: str,
) -> list[str]:
    errors: list[str] = []
    if len(cards) != len(theses):
        errors.append(f"Expected {len(theses)} scorecards, got {len(cards)}.")

    ranks = [card.rank for card in cards]
    if ranks != list(range(1, len(cards) + 1)):
        errors.append("Ranks are not contiguous from 1..N.")

    refs = [card.ref for card in cards]
    if len(refs) != len(set(refs)):
        errors.append("Duplicate refs reached ranked output.")

    if ranking_hash != second_hash:
        errors.append("Determinism hash changed between identical runs.")

    for card in cards:
        scores = [
            card.final_score,
            card.cash_velocity,
            card.v1_viability,
            card.company_potential,
            card.viability_cap,
            *card.criteria.values(),
        ]
        for score in scores:
            if not isinstance(score, (int, float)) or not math.isfinite(score):
                errors.append(f"{card.ref} has non-finite score {score!r}.")
                break
            if score < 0 or score > 100:
                errors.append(f"{card.ref} has out-of-range score {score!r}.")
                break
    return errors


def scorecards_hash(cards: list[Scorecard]) -> str:
    payload = json.dumps([card.to_dict() for card in cards], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_summary(
    *,
    input_path: Path,
    seed: int,
    target_size: int,
    max_seconds: float,
    timings: dict[str, float],
    raw_source_count: int,
    source_result,
    raw_synthetic_count: int,
    synthetic_result,
    synthetic_used_count: int,
    cards: list[Scorecard],
    ranking_hash: str,
    invariant_errors: list[str],
    issues: list[ValidationIssue],
) -> dict[str, Any]:
    severity_counts = Counter(issue.severity for issue in issues)
    issue_message_counts = Counter(issue.message for issue in issues)
    return {
        "input": str(input_path),
        "seed": seed,
        "target_size": target_size,
        "max_seconds": max_seconds,
        "counts": {
            "raw_source": raw_source_count,
            "source_valid": len(source_result.theses),
            "source_skipped": source_result.skipped_count,
            "raw_synthetic": raw_synthetic_count,
            "synthetic_valid": len(synthetic_result.theses),
            "synthetic_used": synthetic_used_count,
            "synthetic_skipped": synthetic_result.skipped_count,
            "ranked": len(cards),
            "validation_issues": len(issues),
        },
        "timings": {key: round(value, 6) for key, value in timings.items()},
        "ranking_hash": ranking_hash,
        "invariant_errors": invariant_errors,
        "issue_counts": {
            "by_severity": dict(sorted(severity_counts.items())),
            "top_messages": dict(issue_message_counts.most_common(10)),
        },
        "score_distribution": score_distribution(cards),
        "top_refs": [card.ref for card in cards[:10]],
        "bottom_refs": [card.ref for card in cards[-10:]],
    }


def build_audit(cards: list[Scorecard], issues: list[ValidationIssue]) -> str:
    top_window = max(1, math.ceil(len(cards) * 0.05)) if cards else 0
    bottom_window = top_window
    top_cards = cards[:25]
    bottom_cards = cards[-25:]
    source_cards = [card for card in cards if not card.ref.startswith("SYN-")]
    source_top_cards = source_cards[:25]
    source_bottom_cards = source_cards[-25:]

    high_trap = [
        card
        for card in cards[:top_window]
        if any(trap.name in SEVERE_TRAPS for trap in card.traps)
    ]
    low_no_trap = [card for card in cards[-bottom_window:] if not card.traps]
    non_dtc_bad_rationale = [
        card
        for card in cards
        if ("marketplace" in card.tags or "operations" in card.tags or "compliance" in card.tags)
        and "DTC buyer" in card.rationale
    ]
    compliance_without_cap = [
        card
        for card in cards
        if "compliance" in card.tags
        and not any(trap.name == "compliance scope" for trap in card.traps)
    ]
    platform_without_cap = [
        card
        for card in cards
        if ("marketplace" in card.tags or _contains_platform_text(card))
        and not any(trap.name in PLATFORM_TRAPS for trap in card.traps)
        and card.criteria.get("platform_access", 100) < 70
    ]

    title_clusters = duplicate_title_clusters(cards)
    domain_counts = Counter(tag for card in cards for tag in card.tags)
    issue_counts = Counter(issue.message for issue in issues)

    lines = [
        "# Hatch Ranker Stress Audit",
        "",
        f"Ranked records: {len(cards)}",
        f"Validation issues: {len(issues)}",
        "",
        "## Score Distribution",
        "",
        markdown_dict(score_distribution(cards)),
        "",
        "## Domain Coverage",
        "",
        markdown_dict(dict(domain_counts.most_common())),
        "",
        "## Top 25",
        "",
        markdown_cards(top_cards),
        "",
        "## Original Input Top 25",
        "",
        markdown_cards(source_top_cards),
        "",
        "## Bottom 25",
        "",
        markdown_cards(bottom_cards),
        "",
        "## Original Input Bottom 25",
        "",
        markdown_cards(source_bottom_cards),
        "",
        "## Suspicious: Severe Traps In Top 5%",
        "",
        markdown_cards(high_trap),
        "",
        "## Suspicious: No-Trap Ideas In Bottom 5%",
        "",
        markdown_cards(low_no_trap),
        "",
        "## Suspicious: Non-DTC Ideas With DTC-Specific Rationale",
        "",
        markdown_cards(non_dtc_bad_rationale),
        "",
        "## Suspicious: Compliance Ideas Without Compliance Scope Trap",
        "",
        markdown_cards(compliance_without_cap),
        "",
        "## Suspicious: Platform-Heavy Ideas Without Platform Trap",
        "",
        markdown_cards(platform_without_cap),
        "",
        "## Duplicate Title Clusters",
        "",
        markdown_clusters(title_clusters),
        "",
        "## Top Validation Issue Messages",
        "",
        markdown_dict(dict(issue_counts.most_common(20))),
        "",
    ]
    return "\n".join(lines)


def markdown_cards(cards: list[Scorecard]) -> str:
    if not cards:
        return "_None._"
    lines = [
        "| Rank | Ref | Title | Score | Traps | Tags | Rationale |",
        "|---:|---|---|---:|---|---|---|",
    ]
    for card in cards:
        traps = ", ".join(trap.name for trap in card.traps) or "-"
        tags = ", ".join(card.tags) or "-"
        lines.append(
            f"| {card.rank} | {escape_md(card.ref)} | {escape_md(card.title)} | {card.final_score:.1f} | {escape_md(traps)} | {escape_md(tags)} | {escape_md(card.rationale)} |"
        )
    return "\n".join(lines)


def markdown_clusters(clusters: dict[str, list[str]]) -> str:
    if not clusters:
        return "_None._"
    lines = ["| Normalized title | Refs |", "|---|---|"]
    for title, refs in sorted(clusters.items(), key=lambda item: (-len(item[1]), item[0]))[:25]:
        lines.append(f"| {escape_md(title)} | {escape_md(', '.join(refs[:20]))} |")
    return "\n".join(lines)


def markdown_dict(values: dict[str, Any]) -> str:
    if not values:
        return "_None._"
    lines = ["| Metric | Value |", "|---|---:|"]
    for key, value in values.items():
        lines.append(f"| {escape_md(str(key))} | {escape_md(str(value))} |")
    return "\n".join(lines)


def score_distribution(cards: list[Scorecard]) -> dict[str, float | int | None]:
    if not cards:
        return {
            "count": 0,
            "min": None,
            "p10": None,
            "median": None,
            "mean": None,
            "p90": None,
            "max": None,
        }
    scores = sorted(card.final_score for card in cards)
    return {
        "count": len(scores),
        "min": round(scores[0], 3),
        "p10": round(percentile(scores, 0.10), 3),
        "median": round(statistics.median(scores), 3),
        "mean": round(statistics.fmean(scores), 3),
        "p90": round(percentile(scores, 0.90), 3),
        "max": round(scores[-1], 3),
    }


def percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def duplicate_title_clusters(cards: list[Scorecard]) -> dict[str, list[str]]:
    clusters: dict[str, list[str]] = defaultdict(list)
    for card in cards:
        clusters[normalize(card.title)].append(card.ref)
    return {title: refs for title, refs in clusters.items() if len(refs) > 1}


def escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def elapsed_since(start: float) -> float:
    return time.perf_counter() - start


def _contains_platform_text(card: Scorecard) -> bool:
    text = normalize(card.thesis.text if card.thesis else "")
    return any(word in text for word in ("checkout", "shopify functions", "pos", "amazon", "walmart", "etsy", "stripe"))


if __name__ == "__main__":
    raise SystemExit(main())
