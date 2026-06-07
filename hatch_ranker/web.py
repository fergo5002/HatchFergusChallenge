from __future__ import annotations

import argparse
import json
import mimetypes
import os
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from typing import Any
from urllib.parse import urlparse

from hatch_ranker.ai_scan import AIScanError, load_env_file, scan_cards
from hatch_ranker.io import REQUIRED_FIELDS
from hatch_ranker.models import Scorecard, Thesis
from hatch_ranker.ranker import Ranker
from hatch_ranker.validation import ValidationIssue, validate_records


MAX_REQUEST_BYTES = 2_000_000
STATIC_PACKAGE = "hatch_ranker.web_static"


def extract_records(payload: Any) -> list[Any]:
    """Return thesis records from the JSON roots supported by the CLI."""

    if isinstance(payload, list):
        return list(payload)
    if isinstance(payload, dict):
        for key in ("theses", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return list(value)
        raise ValueError("JSON object must contain a list under 'theses' or 'items'.")
    raise ValueError("JSON payload must be a list, or an object with 'theses' or 'items'.")


def rank_payload(payload: Any) -> tuple[int, dict[str, Any]]:
    try:
        records = extract_records(payload)
    except ValueError as exc:
        return _error_response(HTTPStatus.BAD_REQUEST, [root_issue(str(exc))])

    result = validate_records(records)
    errors = [issue for issue in result.issues if issue.severity == "error"]
    if errors:
        return _error_response(HTTPStatus.BAD_REQUEST, result.issues)

    theses = _apply_record_metadata(result.theses, records)
    cards = Ranker().rank(theses)
    return HTTPStatus.OK, {
        "ok": True,
        "count": len(cards),
        "required_fields": list(REQUIRED_FIELDS),
        "issues": [issue.to_dict() for issue in result.issues],
        "ranking": [_card_to_web_dict(card) for card in cards],
    }


def root_issue(message: str) -> ValidationIssue:
    return ValidationIssue(-1, "", "_json", "error", message)


def ai_scan_payload(payload: Any) -> tuple[int, dict[str, Any]]:
    """Run the AI edge-case scan and return a JSON-ready response."""

    if isinstance(payload, dict):
        cards = payload.get("ranking") or payload.get("cards") or payload.get("items")
    else:
        cards = payload
    if not isinstance(cards, list) or not cards:
        return int(HTTPStatus.BAD_REQUEST), {
            "ok": False,
            "observations": [],
            "error": "Send a 'ranking' or 'cards' array from the most recent /api/rank response.",
        }

    try:
        observations = scan_cards(cards)
    except AIScanError as exc:
        return int(HTTPStatus.BAD_GATEWAY), {
            "ok": False,
            "observations": [],
            "error": str(exc),
        }

    return int(HTTPStatus.OK), {
        "ok": True,
        "count": len(observations),
        "observations": [
            {"ref": obs.ref, "kind": obs.kind, "note": obs.note}
            for obs in observations
        ],
    }


def _error_response(status: HTTPStatus, issues: list[ValidationIssue]) -> tuple[int, dict[str, Any]]:
    return int(status), {
        "ok": False,
        "count": 0,
        "required_fields": list(REQUIRED_FIELDS),
        "issues": [issue.to_dict() for issue in issues],
        "ranking": [],
    }


def _apply_record_metadata(theses: list[Thesis], records: list[Any]) -> list[Thesis]:
    marked: list[Thesis] = []
    for thesis in theses:
        source = records[thesis.source_index] if 0 <= thesis.source_index < len(records) else {}
        marked.append(replace(thesis, is_new=_record_is_new(source)))
    return marked


def _record_is_new(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    value = record.get("is_new", record.get("isNew", False))
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "new", "appended"}
    return bool(value)


def _card_to_web_dict(card: Scorecard) -> dict[str, Any]:
    data = card.to_dict()
    raw_score = (
        0.48 * card.cash_velocity
        + 0.36 * card.v1_viability
        + 0.16 * card.company_potential
    )
    trap_penalty = sum(trap.penalty for trap in card.traps)
    capped_score = min(raw_score, card.viability_cap)
    data["score_logic"] = {
        "weights": {
            "cash_velocity": 0.48,
            "v1_viability": 0.36,
            "company_potential": 0.16,
        },
        "raw_score": round(raw_score, 2),
        "capped_score": round(capped_score, 2),
        "trap_penalty": round(trap_penalty, 2),
        "formula": "final = min(raw score, viability cap) - trap penalties",
    }
    if card.thesis:
        data["source"] = {
            "one_liner": card.thesis.one_liner,
            "example_customer": card.thesis.example_customer,
            "wedge": card.thesis.wedge,
        }
    return data


class HatchRankerRequestHandler(BaseHTTPRequestHandler):
    server_version = "HatchRankerUI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        if route in {"/", "/index.html"}:
            self._serve_static("index.html")
            return
        if route in {"/styles.css", "/app.js"}:
            self._serve_static(route.lstrip("/"))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route not in {"/api/rank", "/api/ai-scan"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            payload = self._read_json_body()
        except ValueError as exc:
            status, body = _error_response(HTTPStatus.BAD_REQUEST, [root_issue(str(exc))])
            self._send_json(status, body)
            return

        if route == "/api/rank":
            status, body = rank_payload(payload)
        else:
            status, body = ai_scan_payload(payload)
        self._send_json(status, body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def _read_json_body(self) -> Any:
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header.") from exc
        if length <= 0:
            raise ValueError("Request body is empty.")
        if length > MAX_REQUEST_BYTES:
            raise ValueError(f"Request body is too large. Limit is {MAX_REQUEST_BYTES} bytes.")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("Request body must be UTF-8 JSON.") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}.") from exc

    def _serve_static(self, name: str) -> None:
        try:
            data = resources.files(STATIC_PACKAGE).joinpath(name).read_bytes()
        except (FileNotFoundError, ModuleNotFoundError):
            self.send_error(HTTPStatus.NOT_FOUND, "Static asset not found")
            return

        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hatch-ui",
        description="Serve the local Hatch105 ranker UI.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Defaults to 127.0.0.1.")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Defaults to 8765.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file()
    address = (args.host, args.port)
    server = ThreadingHTTPServer(address, HatchRankerRequestHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"Serving Hatch Ranker UI at {url}")
    if os.environ.get("GROQ_API_KEY"):
        print("AI edge-case scan: enabled (GROQ_API_KEY found).")
    else:
        print("AI edge-case scan: disabled (set GROQ_API_KEY in .env to enable).")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Hatch Ranker UI.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
