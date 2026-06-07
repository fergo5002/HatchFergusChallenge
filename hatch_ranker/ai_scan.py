"""Edge-case scanner powered by a hosted LLM.

The deterministic ranker in `ranker.py` is auditable and reproducible but blind
to anything outside its hand-coded vocabulary, trap list, and rubric. This
module exists for those exact gaps. It sends the ranked cards to a Groq-hosted
Llama model in a single batched call and asks the model to flag, per card, at
most two observations that the rule-based ranker is structurally unable to
catch:

    1. Vocabulary blind spots - thesis means the right thing in words the
       keyword/concept lists don't cover.
    2. Hidden traps - real-world risks (vertical-specific compliance, fading
       platform, founder-bandwidth) not in the trap list.
    3. Hidden upside - strengths the rubric undervalues.
    4. Coherence smells - keyword-stuffed, vague, or contradictory wedge.

Output is a flat list of `Observation(ref, kind, note)`. The model is asked to
return strict JSON; we tolerate code fences and stray prose around the JSON
object.

Non-interference contract
-------------------------
This module *advances* the deterministic ranking; it must never *interfere*
with it. Concretely:

* It only reads the ranked cards (via `_summarise_card`) to build the prompt -
  it never mutates them.
* Its only output type is `Observation`, a frozen dataclass with exactly three
  fields (ref, kind, note). It cannot carry a score, rank, tier, or order, so
  nothing it returns can feed back into the score.
* `ranker.py` does not import this module, so scoring is computed and finished
  before any scan can run.

If you extend this module, keep the output advisory-only. Anything that could
re-order or re-score cards belongs in `ranker.py`, behind the auditable rules,
not here. The guards in `tests/test_ai_separation.py` enforce this.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
REQUEST_TIMEOUT_SECONDS = 60
MAX_CARDS_PER_CALL = 50
MAX_OBSERVATIONS_PER_CARD = 2


@dataclass(frozen=True)
class Observation:
    ref: str
    kind: str   # "risk" or "opportunity"
    note: str


class AIScanError(RuntimeError):
    """Raised when the AI scan cannot complete (config, network, parse)."""


def load_env_file(start: Path | None = None) -> None:
    """Best-effort `.env` loader; walks up from CWD or `start` until found."""

    here = Path(start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        env_file = candidate / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
            return


def scan_cards(cards: list[dict[str, Any]]) -> list[Observation]:
    """Send the ranked cards to Groq and return parsed observations.

    Raises AIScanError with a human-readable message on any failure.
    """

    if not cards:
        return []

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise AIScanError(
            "GROQ_API_KEY is not set. Add it to .env or export it before starting the server."
        )
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)

    trimmed = [_summarise_card(card) for card in cards[:MAX_CARDS_PER_CALL]]
    payload = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(trimmed)},
        ],
    }

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        GROQ_API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "hatch-ranker/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            pass
        raise AIScanError(f"Groq API returned HTTP {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise AIScanError(f"Could not reach the Groq API: {exc.reason}.") from exc

    try:
        envelope = json.loads(raw)
        content = envelope["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError) as exc:
        raise AIScanError("Groq API response was not in the expected shape.") from exc

    parsed = _extract_json_object(content)
    items = parsed.get("observations")
    if not isinstance(items, list):
        raise AIScanError("Model output did not contain an 'observations' array.")

    allowed_refs = {
        str(card.get("ref", "")).strip()
        for card in cards
        if isinstance(card, dict) and card.get("ref")
    }
    observations: list[Observation] = []
    seen_per_ref: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref", "")).strip()
        kind = str(item.get("kind", "")).strip().lower()
        note = str(item.get("note", "")).strip()
        if not ref or ref not in allowed_refs or not note:
            continue
        if kind not in {"risk", "opportunity"}:
            kind = "risk"
        if seen_per_ref.get(ref, 0) >= MAX_OBSERVATIONS_PER_CARD:
            continue
        observations.append(Observation(ref=ref, kind=kind, note=note))
        seen_per_ref[ref] = seen_per_ref.get(ref, 0) + 1
    return observations


_SYSTEM_PROMPT = (
    "You are a sceptical product reviewer auditing a deterministic startup-thesis "
    "ranker. The ranker uses keyword matching with hand-tuned weights, so it misses "
    "edge cases: novel vocabulary, vertical-specific traps not in its trap list, "
    "hidden upside the rubric undervalues, and coherence smells (keyword stuffing, "
    "vague wedge, customer/wedge mismatch). Your job is to flag those gaps. "
    "Return strict JSON of the form "
    '{"observations": [{"ref": "H-XX", "kind": "risk"|"opportunity", "note": "<one sentence>"}]}. '
    "Rules: at most two observations per ref; skip a ref entirely if nothing about "
    "it is surprising relative to its tier and score; each note must be a single "
    "sentence of 30 words or fewer; cite the specific aspect of the idea, never "
    "generic advice; never restate the deterministic score, tier, tags, traps, or "
    "absence of traps; never invent facts not present in the thesis text."
)


def _build_user_prompt(summaries: list[dict[str, Any]]) -> str:
    header = (
        "Here are the ranked theses, already scored by the deterministic ranker. "
        "For each, decide if anything material has been missed (risk or "
        "opportunity). Return observations only where it is genuinely worth a "
        "human reviewer's attention.\n\n"
    )
    body = json.dumps(summaries, ensure_ascii=False, indent=2)
    return header + body


def _summarise_card(card: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(card, dict):
        return {
            "ref": "",
            "title": "",
            "rank": "",
            "tier": "",
            "score": "",
            "one_liner": "",
            "example_customer": "",
            "wedge": "",
            "deterministic_traps": [],
            "saturation_label": "",
        }
    source = card.get("source") or {}
    traps = card.get("traps") or []
    trap_names = [t.get("name") for t in traps if isinstance(t, dict) and t.get("name")]
    saturation = card.get("saturation") or {}
    return {
        "ref": card.get("ref"),
        "title": card.get("title"),
        "rank": card.get("rank"),
        "tier": card.get("tier"),
        "score": card.get("score"),
        "one_liner": source.get("one_liner") or "",
        "example_customer": source.get("example_customer") or "",
        "wedge": source.get("wedge") or "",
        "deterministic_traps": trap_names,
        "saturation_label": saturation.get("label") or "",
    }


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = _FENCE_RE.search(text)
    if match:
        try:
            return json.loads(match.group(1))
        except ValueError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except ValueError:
            pass
    raise AIScanError("Could not parse JSON object from model output.")
