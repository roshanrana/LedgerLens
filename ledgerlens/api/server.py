from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ledgerlens.api.resources import (
    export_normalized_events,
    get_report,
    list_review_tasks,
    resolve_review_task,
    run_demo,
    run_reconciliation,
)


class LedgerLensAPIHandler(BaseHTTPRequestHandler):
    db_path: str | Path = ".ledgerlens/ledgerlens.db"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json({"status": "ok", "service": "ledgerlens"})
            return
        if parsed.path == "/review/tasks":
            query = parse_qs(parsed.query)
            run_id = _first(query.get("run_id"))
            status = _first(query.get("status"))
            self._json({"review_tasks": list_review_tasks(self.db_path, run_id=run_id, status=status)})
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/events/normalized"):
            run_id = parsed.path.split("/")[2]
            self._text(export_normalized_events(self.db_path, run_id), content_type="application/x-ndjson")
            return
        if parsed.path.startswith("/runs/") and parsed.path.endswith("/report"):
            run_id = parsed.path.split("/")[2]
            self._json(get_report(self.db_path, run_id))
            return
        self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/demo":
            try:
                body = self._read_json()
                payload = run_demo(self.db_path, client_id=body.get("client_id", "acme"))
            except ValueError as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._json(payload, status=HTTPStatus.CREATED)
            return
        if parsed.path == "/runs":
            try:
                body = self._read_json()
                sources = _sources_from_body(body)
                payload = run_reconciliation(
                    self.db_path,
                    client_id=body.get("client_id", "default"),
                    sources=sources,
                )
            except (KeyError, ValueError) as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self._json(payload, status=HTTPStatus.CREATED)
            return
        if parsed.path.startswith("/review/tasks/") and parsed.path.endswith("/resolve"):
            task_id = parsed.path.split("/")[3]
            try:
                body = self._read_json()
                payload = resolve_review_task(
                    self.db_path,
                    task_id,
                    decision=body["decision"],
                    notes=body.get("notes", ""),
                    reviewer=body.get("reviewer", "api"),
                )
            except (KeyError, ValueError) as exc:
                self._json({"error": str(exc)}, status=_error_status(exc))
                return
            self._json(payload)
            return
        self._json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, _format: str, *_args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"malformed JSON: {exc.msg}") from exc

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, payload: str, *, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = payload.encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    class Handler(LedgerLensAPIHandler):
        pass

    Handler.db_path = db_path
    return ThreadingHTTPServer((host, port), Handler)


def serve(db_path: str | Path, host: str = "127.0.0.1", port: int = 8080) -> int:
    server = build_server(db_path, host, port)
    try:
        print(f"LedgerLens API listening on http://{host}:{server.server_port}")
        server.serve_forever()
    except KeyboardInterrupt:
        print("LedgerLens API stopped")
    finally:
        server.server_close()
    return 0


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _sources_from_body(body: dict[str, Any]) -> list[tuple[str, str]]:
    raw_sources = body.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources must be a list")
    sources: list[tuple[str, str]] = []
    for index, item in enumerate(raw_sources, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"sources[{index}] must be an object")
        csv_path = item.get("csv_path")
        profile_path = item.get("profile_path")
        if not isinstance(csv_path, str) or not isinstance(profile_path, str):
            raise ValueError(f"sources[{index}] must include csv_path and profile_path strings")
        sources.append((csv_path, profile_path))
    return sources


def _error_status(exc: Exception) -> HTTPStatus:
    if "already resolved" in str(exc):
        return HTTPStatus.CONFLICT
    return HTTPStatus.BAD_REQUEST
