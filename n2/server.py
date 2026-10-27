"""HTTP server: JSON API under /api plus the static single-page app."""

from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .store import BadRequest, NotFound, Store

APP_NAME = "n2-daily"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")


class Route:
    def __init__(self, method: str, pattern: str, handler):
        self.method = method
        self.regex = re.compile(f"^{pattern}$")
        self.handler = handler


def build_routes(store: Store) -> list[Route]:
    def body_int(body: dict, field: str) -> int:
        value = body.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise BadRequest(f"{field} must be an integer")
        return value

    return [
        Route("GET", "/api/health", lambda match, body: {"app": APP_NAME, "ok": True}),
        Route("POST", "/api/heartbeat", lambda match, body: {"ok": True}),
        Route("GET", "/api/summary", lambda match, body: store.summary()),
        Route("GET", "/api/settings", lambda match, body: store.settings()),
        Route("PATCH", "/api/settings", lambda match, body: store.update_settings(body)),
        Route("GET", "/api/tests", lambda match, body: store.list_tests()),
        Route("POST", "/api/tests", lambda match, body: store.create_test(body_int(body, "size"))),
        Route("GET", r"/api/tests/(\d+)", lambda match, body: store.get_test(int(match[1]))),
        Route("DELETE", r"/api/tests/(\d+)", lambda match, body: store.delete_test(int(match[1])) or {"ok": True}),
        Route("POST", r"/api/tests/(\d+)/submit", lambda match, body: store.submit_test(
            int(match[1]), body.get("answers") or {}, body.get("seconds"))),
        Route("GET", "/api/cards", lambda match, body: store.list_cards()),
        Route("GET", "/api/cards/keys", lambda match, body: store.card_keys()),
        Route("POST", "/api/cards", lambda match, body: store.add_card(
            body.get("kind"), body.get("data") or {}, body.get("source_question"))),
        Route("DELETE", r"/api/cards/(\d+)", lambda match, body: store.delete_card(int(match[1])) or {"ok": True}),
        Route("GET", "/api/study", lambda match, body: store.study_queue()),
        Route("POST", r"/api/cards/(\d+)/review", lambda match, body: store.review_card(
            int(match[1]), body_int(body, "rating"))),
    ]


class AppServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: Store, idle_timeout: float | None = None):
        self.store = store
        self.routes = build_routes(store)
        self.idle_timeout = idle_timeout
        self.last_activity = time.monotonic()
        super().__init__(address, RequestHandler)
        if idle_timeout:
            threading.Thread(target=self._watch_idle, daemon=True).start()

    def _watch_idle(self) -> None:
        while True:
            time.sleep(5)
            if time.monotonic() - self.last_activity > self.idle_timeout:
                self.shutdown()
                return


class RequestHandler(BaseHTTPRequestHandler):
    server: AppServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # keep the console quiet
        pass

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        self.server.last_activity = time.monotonic()
        path = urlparse(self.path).path
        if not path.startswith("/api/"):
            if method != "GET":
                return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return self._serve_static(path)

        for route in self.server.routes:
            if route.method != method:
                continue
            match = route.regex.match(path)
            if not match:
                continue
            try:
                result = route.handler(match, self._read_body())
            except BadRequest as error:
                return self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except NotFound as error:
                return self._send_json({"error": str(error)}, HTTPStatus.NOT_FOUND)
            return self._send_json(result)
        self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            body = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as error:
            raise BadRequest(f"invalid JSON: {error}") from error
        if not isinstance(body, dict):
            raise BadRequest("body must be a JSON object")
        return body

    def _send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        target = (STATIC_DIR / relative).resolve()
        if not target.is_relative_to(STATIC_DIR) or not target.is_file():
            target = STATIC_DIR / "index.html"
        data = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)
