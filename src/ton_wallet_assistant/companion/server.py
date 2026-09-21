"""LAN companion bridge — a tiny HTTP server the phone's browser talks to.

Routes (all except ``GET /p/<token>`` require the pairing token):

* ``GET /p/<token>`` — mobile scanner page (camera + manual paste).
* ``GET /api/health`` — liveness.
* ``POST /api/relay`` — submit a scanned payload (JSON:
  ``{"payload": str, "nonce": str, "ts": int}``).
* ``GET /api/requests/<id>`` — request status for mobile polling.

The token is embedded in the pairing URL path; every API call must present it
via the ``X-Pairing-Token`` header (or the ``?token=`` query for GETs the page
performs). Requests without it get 403 — never payload data.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .protocol import new_pairing_token
from .scanner_page import SCANNER_PAGE_HTML

MAX_BODY = 32 * 1024


class CompanionServer:
    """Threaded HTTP server bound to the LAN (or loopback in demo)."""

    def __init__(self, manager, *, host: str = "0.0.0.0", port: int = 0) -> None:
        self.manager = manager
        self.token = new_pairing_token()
        self._httpd = ThreadingHTTPServer((host, port), _make_handler(self))
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self._httpd.server_address[0]

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def check_token(self, handler: BaseHTTPRequestHandler) -> bool:
        token = handler.headers.get("X-Pairing-Token", "")
        if not token:
            qs = parse_qs(urlparse(handler.path).query)
            token = qs.get("token", [""])[0]
        return token == self.token


def _json(handler: BaseHTTPRequestHandler, status: int, data: dict) -> None:
    body = json.dumps(data).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _make_handler(server: CompanionServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TonWalletCompanion/0.1"

        # -- helpers -----------------------------------------------------

        def _auth(self) -> bool:
            if not server.check_token(self):
                _json(self, 403, {"error": "invalid or missing pairing token"})
                return False
            return True

        def _client_ip(self) -> str:
            return self.client_address[0]

        # -- routes ------------------------------------------------------

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path

            if path.startswith("/p/"):
                token = path[len("/p/"):].split("/")[0]
                if token != server.token:
                    self.send_response(404)
                    self.end_headers()
                    return
                demo = parse_qs(parsed.query).get("demo") == ["1"]
                html = SCANNER_PAGE_HTML.replace("__TOKEN__", server.token).replace(
                    "__DEMO__", "true" if demo or server.manager.demo else "false"
                )
                body = html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return

            if path == "/api/health":
                _json(self, 200, {"ok": True})
                return

            if path.startswith("/api/requests/"):
                if not self._auth():
                    return
                req_id = path.rsplit("/", 1)[-1]
                status = server.manager.status_for(req_id)
                if status is None:
                    _json(self, 404, {"error": "unknown request"})
                else:
                    _json(self, 200, status)
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path != "/api/relay":
                self.send_response(404)
                self.end_headers()
                return
            if not self._auth():
                return
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                _json(self, 415, {"error": "expected application/json"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                _json(self, 413, {"error": "bad body size"})
                return
            try:
                data = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                _json(self, 400, {"error": "invalid JSON"})
                return
            try:
                ts = float(data.get("ts"))
            except (TypeError, ValueError):
                _json(self, 400, {"error": "missing ts"})
                return
            try:
                result = server.manager.submit_from_thread(
                    origin_ip=self._client_ip(),
                    raw_payload=str(data.get("payload", "")),
                    nonce=str(data.get("nonce", "")),
                    ts=ts,
                )
            except Exception as exc:
                _json(self, 500, {"error": str(exc)})
                return
            if "error" in result:
                _json(self, 422, result)
            else:
                _json(self, 202, result)

        def log_message(self, fmt, *args):  # quiet; the app log owns UX
            pass

    return Handler
