"""Telegram client abstraction shared by the real TDLib backend and the demo.

The auth state machine mirrors TDLib's ``updateAuthorizationState``:

    INITIALIZING → WAIT_PHONE → WAIT_CODE → (WAIT_PASSWORD) → READY → CLOSED

All long-running operations are async; incoming TDLib updates are exposed via
``updates()`` (async iterator) and ``on_update`` callbacks.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TelegramAuthState(Enum):
    INITIALIZING = "initializing"
    WAIT_PHONE = "wait_phone"
    WAIT_CODE = "wait_code"
    WAIT_PASSWORD = "wait_password"
    READY = "ready"
    CLOSED = "closed"
    ERROR = "error"


class TelegramError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class TelegramUpdate:
    """A normalized update delivered to listeners."""

    type: str  # e.g. "authorization_state", "new_message", "raw"
    data: dict[str, Any] = field(default_factory=dict)


class TelegramClient(abc.ABC):
    """Async Telegram client interface (dApp-side; user account auth)."""

    def __init__(self) -> None:
        self._auth_state = TelegramAuthState.INITIALIZING
        self._update_queue: asyncio.Queue[TelegramUpdate] = asyncio.Queue()
        self._update_callbacks: list = []
        self._state_callbacks: list = []

    # ------------------------------------------------------------ state

    @property
    def auth_state(self) -> TelegramAuthState:
        return self._auth_state

    @property
    def is_ready(self) -> bool:
        return self._auth_state is TelegramAuthState.READY

    def on_update(self, callback) -> None:
        self._update_callbacks.append(callback)

    def on_auth_state(self, callback) -> None:
        self._state_callbacks.append(callback)

    def _emit_update(self, update: TelegramUpdate) -> None:
        self._update_queue.put_nowait(update)
        for cb in self._update_callbacks:
            cb(update)

    def _set_auth_state(self, state: TelegramAuthState) -> None:
        if state is self._auth_state:
            return
        self._auth_state = state
        self._emit_update(TelegramUpdate("authorization_state", {"state": state.value}))
        for cb in self._state_callbacks:
            cb(state)

    async def updates(self):
        """Async iterator over incoming updates."""
        while True:
            yield await self._update_queue.get()

    # --------------------------------------------------------- operations

    @abc.abstractmethod
    async def start(self) -> TelegramAuthState:
        """Initialize the client and begin receiving updates."""

    @abc.abstractmethod
    async def submit_phone(self, phone: str) -> TelegramAuthState:
        """Submit the phone number (state → WAIT_CODE on success)."""

    @abc.abstractmethod
    async def submit_code(self, code: str) -> TelegramAuthState:
        """Submit the login code (→ READY, or WAIT_PASSWORD if 2FA)."""

    @abc.abstractmethod
    async def submit_password(self, password: str) -> TelegramAuthState:
        """Submit the 2FA password (→ READY)."""

    @abc.abstractmethod
    async def get_chats(self, limit: int = 20) -> list[dict]:
        """List recent chats (dicts with id/title)."""

    @abc.abstractmethod
    async def send_message(self, chat_id: int, text: str) -> dict:
        """Send a text message. Returns the sent message object."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Shut down the client and release resources."""
