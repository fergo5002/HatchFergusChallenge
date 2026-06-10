from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any

from hatch_ranker.io import REQUIRED_FIELDS
from hatch_ranker.models import Thesis


MAX_FIELD_CHARS = 20_000


@dataclass(frozen=True)
class ValidationIssue:
    index: int
    ref: str
    field: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "ref": self.ref,
            "field": self.field,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class ValidationResult:
    theses: list[Thesis]
    issues: list[ValidationIssue]
    total_records: int

    @property
    def skipped_count(self) -> int:
        invalid_indexes = {
            issue.index
            for issue in self.issues
            if issue.severity == "error" and issue.index >= 0
        }
        return len(invalid_indexes)


def load_raw_records(path: str | Path) -> list[Any]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Input file not found: {source}")

    if source.suffix.lower() == ".json":
        payload = json.loads(_read_text(source))
        if isinstance(payload, dict):
            if "theses" in payload:
                payload = payload["theses"]
            elif "items" in payload:
                payload = payload["items"]
        if not isinstance(payload, list):
            raise ValueError(f"JSON input must be a list, or an object with theses/items: {source}")
        return list(payload)

    if source.suffix.lower() == ".csv":
        raw = _read_text(source)
        return [dict(row) for row in csv.DictReader(StringIO(raw))]

    raise ValueError(f"Unsupported input file type: {source.suffix}. Use .csv or .json.")


def validate_records(
    records: list[Any],
    *,
    is_new: bool = False,
    start_index: int = 0,
    max_field_chars: int = MAX_FIELD_CHARS,
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    theses: list[Thesis] = []
    seen_refs: set[str] = set()

    for offset, record in enumerate(records):
        index = start_index + offset
        if not isinstance(record, dict):
            issues.append(
                ValidationIssue(index, "", "_record", "error", f"Record is {type(record).__name__}, not an object.")
            )
            continue

        normalized = _normalize_record(record)
        ref = normalized.get("ref", "")
        record_issues: list[ValidationIssue] = []

        for field in REQUIRED_FIELDS:
            if field not in normalized:
                record_issues.append(ValidationIssue(index, ref, field, "error", "Missing required field."))
                continue
            original_value = _find_original_value(record, field)
            value = normalized[field]
            if original_value is None:
                record_issues.append(ValidationIssue(index, ref, field, "error", "Field is null."))
            elif not isinstance(original_value, str):
                record_issues.append(
                    ValidationIssue(index, ref, field, "error", f"Field is {type(original_value).__name__}, not string.")
                )
            elif not value:
                record_issues.append(ValidationIssue(index, ref, field, "error", "Field is empty."))
            elif len(value) > max_field_chars:
                record_issues.append(
                    ValidationIssue(
                        index,
                        ref,
                        field,
                        "warning",
                        f"Field is very large ({len(value)} chars); ranking will continue.",
                    )
                )

        if ref and ref in seen_refs:
            record_issues.append(ValidationIssue(index, ref, "ref", "error", "Duplicate ref."))

        issues.extend(record_issues)
        if any(issue.severity == "error" for issue in record_issues):
            continue

        if not ref:
            ref = f"ROW-{index + 1:06d}"
        seen_refs.add(ref)
        theses.append(
            Thesis(
                ref=ref,
                title=normalized["title"],
                one_liner=normalized["one_liner"],
                example_customer=normalized["example_customer"],
                wedge=normalized["wedge"],
                is_new=is_new,
                source_index=index,
            )
        )

    return ValidationResult(theses=theses, issues=issues, total_records=len(records))


def write_validation_issues(issues: list[ValidationIssue], path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", newline="", encoding="utf-8") as handle:
        fieldnames = ["index", "ref", "field", "severity", "message"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue.to_dict())


def _read_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text()


def _normalize_record(record: dict[Any, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in record.items():
        clean_key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        normalized[clean_key] = "" if value is None else str(value).strip()
    return normalized


def _find_original_value(record: dict[Any, Any], normalized_key: str) -> Any:
    for key, value in record.items():
        clean_key = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        if clean_key == normalized_key:
            return value
    return None
