"""HTTP server: JSON API under /api plus the static single-page app."""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .store import BadRequest, NotFound, Store

APP_NAME = "n2-daily"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
OFFICIAL_DIR = Path(__file__).resolve().parent.parent / "content" / "official"
OFFICIAL_ASSET_DIRS = ("crops", "raw")
OFFICIAL_ASSET_TYPES = {".png": "image/png", ".mp3": "audio/mpeg"}
RANGE_PATTERN = re.compile(r"^bytes=(\d*)-(\d*)$")

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
        Route("POST", "/api/tests", lambda match, body: (
            store.create_official_test(str(body["official_set"]), str(body.get("official_part")))
            if "official_set" in body else store.create_test(body_int(body, "size")))),
        Route("GET", "/api/official", lambda match, body: store.official_catalog()),
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

    def __init__(self, address, store: Store, idle_timeout: float | None = None, official_dir: Path = OFFICIAL_DIR):
        self.store = store
        self.routes = build_routes(store)
        self.idle_timeout = idle_timeout
        self.official_dir = official_dir
        self.last_activity = time.monotonic()
        super().__init__(address, RequestHandler)
        if idle_timeout:
            threading.Thread(target=self._watch_idle, daemon=True).start()

    def handle_error(self, request, client_address) -> None:
        # Browsers drop idle keep-alive connections and cancel audio range requests; that is not an error.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

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
            if path.startswith("/official/"):
                return self._serve_official_asset(path.removeprefix("/official/"))
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

    def _serve_official_asset(self, relative: str) -> None:
        """Serve official crops and audio (with HTTP Range support so audio can seek)."""
        official_dir = self.server.official_dir
        target = (official_dir / unquote(relative)).resolve()
        allowed = any(target.is_relative_to((official_dir / folder).resolve()) for folder in OFFICIAL_ASSET_DIRS)
        content_type = OFFICIAL_ASSET_TYPES.get(target.suffix.lower())
        if not allowed or content_type is None or not target.is_file():
            return self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        size = target.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            match = RANGE_PATTERN.match(range_header.strip())
            if not match or (not match[1] and not match[2]):
                return self._send_range_not_satisfiable(size)
            if match[1]:
                start = int(match[1])
                end = min(int(match[2]), size - 1) if match[2] else size - 1
            else:
                start = max(size - int(match[2]), 0)
            if start > end or start >= size:
                return self._send_range_not_satisfiable(size)
            status = HTTPStatus.PARTIAL_CONTENT

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "max-age=86400")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with open(target, "rb") as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return  # the browser cancelled the request (normal while seeking)
                remaining -= len(chunk)

    def _send_range_not_satisfiable(self, size: int) -> None:
        self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
        self.send_header("Content-Range", f"bytes */{size}")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
