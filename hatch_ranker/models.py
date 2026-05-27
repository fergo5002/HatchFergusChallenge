from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Thesis:
    """A raw startup thesis in the challenge format."""

    ref: str
    title: str
    one_liner: str
    example_customer: str
    wedge: str
    is_new: bool = False
    source_index: int = 0

    @property
    def text(self) -> str:
        return " ".join(
            part
            for part in (
                self.title,
                self.one_liner,
                self.example_customer,
                self.wedge,
            )
            if part
        )


@dataclass(frozen=True)
class Trap:
    name: str
    penalty: float
    reason: str


@dataclass
class Scorecard:
    ref: str
    title: str
    final_score: float
    rank: int = 0
    cash_velocity: float = 0.0
    v1_viability: float = 0.0
    company_potential: float = 0.0
    viability_cap: float = 100.0
    criteria: dict[str, float] = field(default_factory=dict)
    traps: list[Trap] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    rationale: str = ""
    smallest_v1: str = ""
    evidence: list[str] = field(default_factory=list)
    thesis: Thesis | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "ref": self.ref,
            "title": self.title,
            "score": round(self.final_score, 2),
            "cash_velocity": round(self.cash_velocity, 2),
            "v1_viability": round(self.v1_viability, 2),
            "company_potential": round(self.company_potential, 2),
            "viability_cap": round(self.viability_cap, 2),
            "criteria": {key: round(value, 2) for key, value in self.criteria.items()},
            "traps": [
                {
                    "name": trap.name,
                    "penalty": round(trap.penalty, 2),
                    "reason": trap.reason,
                }
                for trap in self.traps
            ],
            "tags": self.tags,
            "rationale": self.rationale,
            "smallest_v1": self.smallest_v1,
            "evidence": self.evidence,
            "is_new": bool(self.thesis and self.thesis.is_new),
        }
