"""Demo Telegram client — fully offline simulation of the TDLib auth flow.

Mirrors the real client's state machine without any network access or
credentials: phone → code → (optional password) → ready, with fabricated
chats and incoming-message updates. Clearly labelled demo everywhere.
"""

from __future__ import annotations

import asyncio
import itertools
from typing import Any

from .client import TelegramAuthState, TelegramClient, TelegramError, TelegramUpdate

DEMO_CODE = "12345"  # the demo login code — printed in the UI


class DemoTelegramClient(TelegramClient):
    def __init__(self, *, demo_password: str | None = None) -> None:
        super().__init__()
        self._phone: str | None = None
        self._demo_password = demo_password
        self._chats = [
            {"id": 1, "title": "Wallet (Telegram)", "demo": True},
            {"id": 2, "title": "Tonkeeper Alerts", "demo": True},
            {"id": 3, "title": "TON Community", "demo": True},
        ]
        self._sent: list[dict] = []
        self._id_counter = itertools.count(1000)

    async def start(self) -> TelegramAuthState:
        await asyncio.sleep(0)
        self._emit_update(TelegramUpdate("raw", {"@type": "demoStarted", "demo": True}))
        self._set_auth_state(TelegramAuthState.WAIT_PHONE)
        return self._auth_state

    async def submit_phone(self, phone: str) -> TelegramAuthState:
        phone = phone.strip()
        if not phone or not phone.lstrip("+").isdigit():
            raise TelegramError("invalid phone number", code=400)
        self._phone = phone
        self._set_auth_state(TelegramAuthState.WAIT_CODE)
        return self._auth_state

    async def submit_code(self, code: str) -> TelegramAuthState:
        if self._auth_state is not TelegramAuthState.WAIT_CODE:
            raise TelegramError("no code was requested", code=400)
        if code.strip() != DEMO_CODE:
            raise TelegramError("incorrect code (demo code is 12345)", code=400)
        if self._demo_password is not None:
            self._set_auth_state(TelegramAuthState.WAIT_PASSWORD)
        else:
            self._set_auth_state(TelegramAuthState.READY)
            self._emit_demo_messages()
        return self._auth_state

    async def submit_password(self, password: str) -> TelegramAuthState:
        if self._auth_state is not TelegramAuthState.WAIT_PASSWORD:
            raise TelegramError("no password was requested", code=400)
        if password != self._demo_password:
            raise TelegramError("incorrect password", code=400)
        self._set_auth_state(TelegramAuthState.READY)
        self._emit_demo_messages()
        return self._auth_state

    def _emit_demo_messages(self) -> None:
        for chat in self._chats:
            self._emit_update(
                TelegramUpdate(
                    "new_message",
                    {
                        "chat_id": chat["id"],
                        "text": f"Demo update from {chat['title']} (offline)",
                        "id": next(self._id_counter),
                        "demo": True,
                    },
                )
            )

    async def get_chats(self, limit: int = 20) -> list[dict]:
        if not self.is_ready:
            raise TelegramError("not authenticated", code=401)
        return self._chats[:limit]

    async def send_message(self, chat_id: int, text: str) -> dict:
        if not self.is_ready:
            raise TelegramError("not authenticated", code=401)
        if not any(c["id"] == chat_id for c in self._chats):
            raise TelegramError("unknown chat", code=400)
        msg: dict[str, Any] = {
            "id": next(self._id_counter),
            "chat_id": chat_id,
            "text": text,
            "demo": True,
        }
        self._sent.append(msg)
        self._emit_update(
            TelegramUpdate("new_message", {"chat_id": chat_id, "text": text, "id": msg["id"], "demo": True})
        )
        return msg

    async def resolve_webapp(self, context, **_kwargs) -> dict:
        """Synthetic web app resolution — demo/offline only, clearly marked."""
        if not self.is_ready:
            raise TelegramError("not authenticated", code=401)
        return {
            "url": context.url,
            "query_id": "",
            "method": "demo",
            "demo": True,
        }

    async def close(self) -> None:
        self._set_auth_state(TelegramAuthState.CLOSED)
