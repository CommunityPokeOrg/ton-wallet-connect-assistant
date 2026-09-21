"""PairingManager — owns the companion HTTP bridge and the approval
state machine shared by the GUI, SDK, and tests.

Threading model: the HTTP server runs on its own thread; all request
mutations are funnelled onto the asyncio loop that called ``start()`` via
``loop.call_soon_threadsafe``. Consumers either await the ``requests``
async iterator or poll ``pending_requests()`` (both thread-safe to read).
"""

from __future__ import annotations

import asyncio
import secrets
import socket
import threading
import time
from typing import TYPE_CHECKING

from .protocol import (
    PayloadKind,
    RelayedRequest,
    RequestState,
    TonConnectLinkDetails,
    TransferDetails,
    new_nonce,
    parse_payload,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def _lan_ip() -> str:
    """Best-effort local LAN IP for the pairing URL."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("192.0.2.1", 80))  # no traffic actually sent
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "127.0.0.1"


class PairingManager:
    """Coordinates the LAN companion bridge and incoming request approvals."""

    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 0,
        demo: bool = False,
        network: str = "mainnet",
    ) -> None:
        self.host = host
        self.port = port
        self.demo = demo
        self.network = network
        self.token = ""
        self._server = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: int | None = None
        self._requests: dict[str, RelayedRequest] = {}
        self._lock = threading.Lock()
        self._incoming: asyncio.Queue[RelayedRequest] = asyncio.Queue()
        self.transfer_handler: Callable[[RelayedRequest], Awaitable[str]] | None = None
        self.connect_handler: Callable[[RelayedRequest], Awaitable[str]] | None = None

    # ------------------------------------------------------------- server

    async def stop(self) -> None:
        if self._server is not None:
            self._server.stop()
            self._server = None

    @property
    def running(self) -> bool:
        return self._server is not None

    @property
    def pairing_url(self) -> str:
        if not self._server:
            return ""
        host = "127.0.0.1" if self.host in ("127.0.0.1", "localhost") else _lan_ip()
        demo_q = "?demo=1" if self.demo else ""
        return f"http://{host}:{self.port}/p/{self.token}{demo_q}"

    # ----------------------------------------------------- request intake

    def submit_from_thread(self, *, origin_ip: str, raw_payload: str, nonce: str, ts: float) -> dict:
        """Entry point for the HTTP thread. Validates, queues, returns status dict."""
        if self._loop is None:
            raise RuntimeError("manager not started")
        from .protocol import ReplayError, ValidationError

        # Nonce/replay check must happen on the io loop (single-threaded there).
        result: dict = {}
        done = threading.Event()

        def _process() -> None:
            nonlocal result
            try:
                self._nonces.check(nonce, ts)
                kind, payload = parse_payload(raw_payload)
                req = RelayedRequest(
                    request_id=secrets.token_hex(8),
                    kind=kind,
                    payload=payload,
                    origin_ip=origin_ip,
                )
                with self._lock:
                    self._requests[req.request_id] = req
                self._incoming.put_nowait(req)
                result = {"id": req.request_id, "state": req.state.value}
            except (ValidationError, ReplayError) as exc:
                result = {"error": str(exc)}
            done.set()

        if threading.get_ident() == self._loop_thread:
            _process()  # already on the io loop — run inline to avoid deadlock
        else:
            self._loop.call_soon_threadsafe(_process)
            done.wait(timeout=5)
        return result

    _nonces = None  # set in start()

    async def submit_local(self, raw_payload: str, *, origin: str = "local") -> str:
        """Trusted local intake (embedded webview, CLI, tests) — runs on the
        io loop, skips the nonce/replay check that guards the HTTP endpoint.
        Does not require the bridge server to be running."""
        kind, payload = parse_payload(raw_payload)
        req = RelayedRequest(
            request_id=secrets.token_hex(8),
            kind=kind,
            payload=payload,
            origin_ip=origin,
        )
        with self._lock:
            self._requests[req.request_id] = req
        self._incoming.put_nowait(req)
        return req.request_id

    async def start(self) -> str:  # noqa: F811 — redefined to init NonceTracker on the loop
        if self._server is not None:
            return self.pairing_url
        self._loop = asyncio.get_running_loop()
        self._loop_thread = threading.get_ident()
        from .protocol import NonceTracker

        self._nonces = NonceTracker()
        from .server import CompanionServer

        self._server = CompanionServer(self, host=self.host, port=self.port)
        self._server.start()
        self.port = self._server.port
        self.token = self._server.token
        return self.pairing_url

    # ------------------------------------------------------- request view

    def pending_requests(self) -> list[RelayedRequest]:
        """Current pending (non-expired) requests — safe to call from any thread."""
        now = time.time()
        with self._lock:
            for req in self._requests.values():
                if req.state is RequestState.PENDING and req.expired(now):
                    req.state = RequestState.EXPIRED
            return [r for r in self._requests.values() if r.state is RequestState.PENDING]

    def all_requests(self) -> list[RelayedRequest]:
        with self._lock:
            return list(self._requests.values())

    def get(self, request_id: str) -> RelayedRequest | None:
        with self._lock:
            return self._requests.get(request_id)

    def status_for(self, request_id: str) -> dict | None:
        req = self.get(request_id)
        if req is None:
            return None
        now = time.time()
        if req.state is RequestState.PENDING and req.expired(now):
            req.state = RequestState.EXPIRED
        return req.as_dict()

    # -------------------------------------------------------- approvals

    async def requests(self):
        """Async iterator yielding each incoming request (for SDK/headless use)."""
        while True:
            yield await self._incoming.get()

    async def approve(self, request_id: str) -> str:
        """Mark a request approved and run its handler. Returns the result.

        ``transfer_handler`` / ``connect_handler`` must be set by the caller
        (SDK wires them to the chain backend + keystore).
        """
        req = self.get(request_id)
        if req is None:
            raise KeyError(f"unknown request {request_id}")
        if req.state is not RequestState.PENDING:
            raise RuntimeError(f"request is {req.state.value}, not pending")
        if req.expired():
            req.state = RequestState.EXPIRED
            raise RuntimeError("request expired")

        req.state = RequestState.APPROVED
        handler = (
            self.transfer_handler
            if req.kind is PayloadKind.TON_TRANSFER
            else self.connect_handler
        )
        if handler is None:
            req.state = RequestState.FAILED
            req.error = "no handler configured for this request type"
            raise RuntimeError(req.error)
        try:
            req.result = await handler(req)
            req.state = RequestState.COMPLETED
        except Exception as exc:
            req.state = RequestState.FAILED
            req.error = str(exc)
            raise
        return req.result

    def reject(self, request_id: str) -> None:
        req = self.get(request_id)
        if req is None:
            raise KeyError(f"unknown request {request_id}")
        if req.state is RequestState.PENDING:
            req.state = RequestState.REJECTED


__all__ = [
    "PairingManager",
    "PayloadKind",
    "RelayedRequest",
    "RequestState",
    "TonConnectLinkDetails",
    "TransferDetails",
    "new_nonce",
    "parse_payload",
]
