"""Single Vercel Python entrypoint for all dynamic routes.

Vercel's Python builder runs one handler per project; this dispatches
POST /api/rank and POST /api/ai-scan to the existing payload functions in
`hatch_ranker.web` so behaviour matches the local `hatch-ui` server.

Static assets (index.html, styles.css, app.js) are served from `public/`
by Vercel's static handler before requests reach this entrypoint.
"""
from __future__ import annotations

import json
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hatch_ranker.web import (  # noqa: E402
    ai_scan_payload,
    rank_payload,
    root_issue,
    _error_response,
)

MAX_REQUEST_BYTES = 2_000_000


class handler(BaseHTTPRequestHandler):
    server_version = "HatchRankerVercel/0.1"

    def do_GET(self) -> None:
        # Static assets are served by Vercel before reaching here. If a
        # GET arrives we return a small JSON health response.
        route = urlparse(self.path).path
        if route in {"/api", "/api/", "/api/health"}:
            self._send_json(HTTPStatus.OK, {"ok": True, "service": "hatch-ranker"})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        if route not in {"/api/rank", "/api/ai-scan"}:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Not found"})
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

    def _send_json(self, status, body: dict) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._cors_headers()
        self.end_headers()
        self.wfile.write(data)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format: str, *args) -> None:
        return
