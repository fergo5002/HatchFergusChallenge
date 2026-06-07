"""Vercel Python serverless handler for POST /api/rank.

Reuses the deterministic ranker logic from `hatch_ranker.web.rank_payload`
so the Vercel deployment behaves identically to the local `hatch-ui` server.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# Vercel sets the project root as cwd; make sibling packages importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hatch_ranker.web import rank_payload, root_issue, _error_response  # noqa: E402

MAX_REQUEST_BYTES = 2_000_000


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            payload = self._read_json_body()
        except ValueError as exc:
            status, body = _error_response(400, [root_issue(str(exc))])
            self._send_json(status, body)
            return

        status, body = rank_payload(payload)
        self._send_json(status, body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _read_json_body(self):
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
            raise ValueError(
                f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}."
            ) from exc

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args) -> None:
        # Quiet the default stderr logging on Vercel.
        return
