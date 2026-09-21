"""Experimental Telegram Mini App/WebApp bridge for desktop wallets.

The bridge deliberately has no Node.js runtime dependency. It can open a TMA or
TonConnect web app in the user's browser, and optionally expose a tiny local
HTTP callback endpoint for URL/deep-link handoff. QWebEngine integration is
kept optional so the core package remains usable without Qt WebEngine.
"""

from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable


@dataclass(frozen=True)
class MiniAppLaunch:
    url: str
    title: str = "Telegram Mini App"


class TelegramWebAppShim:
    """Small SDK-compatible state shim for apps loaded outside Telegram."""

    def __init__(self, init_data: str = "") -> None:
        self.initData = init_data
        self.initDataUnsafe: dict[str, object] = {}
        self._events: dict[str, list[Callable[..., None]]] = {}

    def onEvent(self, event: str, callback: Callable[..., None]) -> None:
        self._events.setdefault(event, []).append(callback)

    def offEvent(self, event: str, callback: Callable[..., None]) -> None:
        if event in self._events and callback in self._events[event]:
            self._events[event].remove(callback)

    def emit(self, event: str, *args: object) -> None:
        for callback in tuple(self._events.get(event, ())):
            callback(*args)

    def ready(self) -> None:
        self.emit("ready")

    def expand(self) -> None:
        self.emit("viewportChanged", True)

    def close(self) -> None:
        self.emit("close")


class TelegramMiniAppBridge:
    """Launch external TMAs and receive TonConnect/deep-link callbacks."""

    def __init__(self, callback: Callable[[str], None] | None = None) -> None:
        self.callback = callback
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @staticmethod
    def build_tma_url(username: str, startapp: str | None = None) -> str:
        username = username.lstrip("@ ").strip()
        if not username or any(ch in username for ch in "/?#"):
            raise ValueError("username must be a Telegram handle")
        url = f"https://t.me/{username}"
        return f"{url}?startapp={urllib.parse.quote(startapp, safe='') }" if startapp else url

    @staticmethod
    def validate_web_url(url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Mini App URL must be an absolute HTTP(S) URL")
        return url

    def launch(self, url: str, *, title: str = "Telegram Mini App") -> MiniAppLaunch:
        launch = MiniAppLaunch(self.validate_web_url(url), title)
        webbrowser.open(launch.url)
        return launch

    def start_callback_server(self) -> str:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                payload = query.get("tonconnect", query.get("url", [self.path]))[0]
                if bridge.callback:
                    bridge.callback(payload)
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}/callback"

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
