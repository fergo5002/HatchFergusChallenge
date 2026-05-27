from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from hatch_ranker.models import Scorecard, Thesis


REQUIRED_FIELDS = ("ref", "title", "one_liner", "example_customer", "wedge")


def load_theses(path: str | Path, *, is_new: bool = False, start_index: int = 0) -> list[Thesis]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input file not found: {source}")

    if source.suffix.lower() == ".json":
        records = _load_json_records(source)
    elif source.suffix.lower() == ".csv":
        records = _load_csv_records(source)
    else:
        raise ValueError(f"Unsupported input file type: {source.suffix}. Use .csv or .json.")

    theses: list[Thesis] = []
    for offset, record in enumerate(records):
        clean = _normalize_record(record)
        if not any(clean.values()):
            continue
        missing = [field for field in REQUIRED_FIELDS if field not in clean]
        if missing:
            raise ValueError(f"{source} row {offset + 1} is missing fields: {', '.join(missing)}")
        theses.append(
            Thesis(
                ref=clean["ref"] or f"ROW-{start_index + offset + 1:03d}",
                title=clean["title"],
                one_liner=clean["one_liner"],
                example_customer=clean["example_customer"],
                wedge=clean["wedge"],
                is_new=is_new,
                source_index=start_index + offset,
            )
        )
    return theses


def write_outputs(scorecards: Iterable[Scorecard], out_dir: str | Path, *, top_n: int = 50) -> None:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    cards = list(scorecards)
    _write_json(cards, output / "ranking.json")
    _write_csv(cards, output / "ranking.csv")
    _write_markdown(cards, output / "ranking.md", top_n=top_n)


def _load_json_records(path: Path) -> list[dict[str, object]]:
    raw = _read_text(path)
    payload = json.loads(raw)
    if isinstance(payload, dict):
        if "theses" in payload:
            payload = payload["theses"]
        elif "items" in payload:
            payload = payload["items"]
    if not isinstance(payload, list):
        raise ValueError(f"JSON input must be a list of thesis objects: {path}")
    return [item for item in payload if isinstance(item, dict)]


def _load_csv_records(path: Path) -> list[dict[str, object]]:
    raw = _read_text(path)
    rows = csv.DictReader(raw.splitlines())
    return [dict(row) for row in rows]


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text()


def _normalize_record(record: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in record.items():
        clean_key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        if value is None:
            clean_value = ""
        else:
            clean_value = str(value).strip()
        normalized[clean_key] = clean_value
    return normalized


def _write_json(cards: list[Scorecard], path: Path) -> None:
    path.write_text(
        json.dumps([card.to_dict() for card in cards], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_csv(cards: list[Scorecard], path: Path) -> None:
    fieldnames = [
        "rank",
        "ref",
        "title",
        "score",
        "cash_velocity",
        "v1_viability",
        "company_potential",
        "viability_cap",
        "tags",
        "traps",
        "rationale",
        "is_new",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for card in cards:
            row = card.to_dict()
            writer.writerow(
                {
                    "rank": row["rank"],
                    "ref": row["ref"],
                    "title": row["title"],
                    "score": row["score"],
                    "cash_velocity": row["cash_velocity"],
                    "v1_viability": row["v1_viability"],
                    "company_potential": row["company_potential"],
                    "viability_cap": row["viability_cap"],
                    "tags": "; ".join(row["tags"]),
                    "traps": "; ".join(trap["name"] for trap in row["traps"]),
                    "rationale": row["rationale"],
                    "is_new": row["is_new"],
                }
            )


def _write_markdown(cards: list[Scorecard], path: Path, *, top_n: int) -> None:
    visible = cards[:top_n]
    lines = [
        "# Hatch105 Thesis Ranking",
        "",
        "Algorithm: 10-week revenue survivability ranker.",
        "",
        "The score is deterministic and inspectable. It rewards quick revenue learning, buildable v1 scope, and long-term company surface, then applies caps/penalties for hidden traps.",
        "",
        "## Criteria",
        "",
        "- Cash velocity: buyer pain, ROI visibility, buyer clarity, setup friction, and target-market accessibility.",
        "- V1 viability: buildability, platform access, data access, and operational simplicity.",
        "- Company potential: expansion surface, differentiation, repeatability, and defensibility.",
        "- Trap handling: severe technical, platform, trust, data, novelty, and clone risks cap or penalize the final score.",
        "",
        "## Ranking",
        "",
        "| Rank | Ref | Title | Score | Cash | V1 | Company | Traps | Rationale |",
        "|---:|---|---|---:|---:|---:|---:|---|---|",
    ]
    for card in visible:
        traps = ", ".join(trap.name for trap in card.traps) or "-"
        lines.append(
            "| {rank} | {ref} | {title} | {score:.1f} | {cash:.1f} | {v1:.1f} | {company:.1f} | {traps} | {rationale} |".format(
                rank=card.rank,
                ref=_escape_md(card.ref),
                title=_escape_md(card.title),
                score=card.final_score,
                cash=card.cash_velocity,
                v1=card.v1_viability,
                company=card.company_potential,
                traps=_escape_md(traps),
                rationale=_escape_md(card.rationale),
            )
        )

    lines.extend(["", "## Top 3 Rationale", ""])
    for card in cards[:3]:
        lines.extend(
            [
                f"### {card.rank}. {card.ref} - {card.title}",
                "",
                card.rationale,
                "",
                f"Smallest sellable v1: {card.smallest_v1}",
                "",
                "Evidence/assumptions:",
            ]
        )
        lines.extend(f"- {item}" for item in card.evidence)
        lines.append("")

    new_cards = [card for card in cards if card.thesis and card.thesis.is_new]
    if new_cards:
        lines.extend(["## New Thesis Landing Notes", ""])
        for card in new_cards:
            lines.append(
                f"- Rank {card.rank}: {card.ref} - {card.title}. {card.rationale}"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
