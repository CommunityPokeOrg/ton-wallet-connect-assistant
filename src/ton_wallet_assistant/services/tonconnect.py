"""Real TonConnect backend, powered by ``pytonconnect``.

Security notes
--------------
* ``pytonconnect`` generates a fresh ed25519 session keypair per connection
  request inside its storage; no private key or mnemonic ever touches this app.
* The only thing the app needs to operate is a public ``manifest_url`` — an
  HTTPS-hosted ``tonconnect-manifest.json`` that wallets display to the user
  when asking for approval. See ``assets/tonconnect-manifest.example.json`` and
  the README for how to publish one.
* Session state is persisted to a local JSON file so a previously approved
  wallet can be restored on the next launch.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from ..models import ConnectedAccount, ConnectionState, ServiceEvent, WalletOption
from .base import WalletService


class TonConnectService(WalletService):
    def __init__(self, manifest_url: str, storage_path: Path) -> None:
        super().__init__()
        from pytonconnect import TonConnect
        from pytonconnect.storage import FileStorage

        storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._connector = TonConnect(manifest_url, storage=FileStorage(str(storage_path)))
        self._connector.on_status_change(self._on_status, self._on_status_error)
        self._last_wallet_name = ""

    async def list_wallets(self) -> list[WalletOption]:
        wallets = await asyncio.to_thread(self._connector.get_wallets)
        options = [WalletOption.from_tonconnect(w) for w in wallets]
        return [w for w in options if w.universal_url and w.supports_desktop] or options

    async def connect(self, wallet: WalletOption) -> str:
        self._last_wallet_name = wallet.name
        return await self._connector.connect(wallet.raw or {"name": wallet.name, "app_name": wallet.app_name})

    async def disconnect(self) -> None:
        with contextlib.suppress(Exception):
            await self._connector.disconnect()

    async def restore(self) -> bool:
        try:
            return bool(await self._connector.restore_connection())
        except Exception as exc:  # corrupted storage, offline bridge, ...
            self._emit(ServiceEvent(state=ConnectionState.ERROR, error=f"Could not restore session: {exc}"))
            return False

    async def close(self) -> None:
        # pytonconnect pauses the SSE listener; there is no explicit close.
        with contextlib.suppress(Exception):
            self._connector.pause_connection()

    @property
    def connected(self) -> bool:
        return bool(self._connector.connected)

    def _on_status(self, wallet_info: Any) -> None:
        if wallet_info:
            try:
                account = ConnectedAccount.from_tonconnect(wallet_info)
            except Exception as exc:
                self._emit(
                    ServiceEvent(state=ConnectionState.ERROR, error=f"Malformed wallet response: {exc}")
                )
                return
            self._emit(
                ServiceEvent(
                    state=ConnectionState.CONNECTED,
                    account=account,
                    wallet_name=account.wallet_app or self._last_wallet_name,
                )
            )
        else:
            self._emit(ServiceEvent(state=ConnectionState.DISCONNECTED))

    def _on_status_error(self, exc: BaseException) -> None:
        self._emit(
            ServiceEvent(
                state=ConnectionState.ERROR,
                error=_friendly_error(exc),
                wallet_name=self._last_wallet_name,
            )
        )


def _friendly_error(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "declined" in lowered or "reject" in lowered:
        return "The wallet declined the connection request."
    if "timeout" in lowered or "timed out" in lowered:
        return "The connection request timed out. Generate a new link and try again."
    if "manifest" in lowered:
        return "The wallet could not fetch the app manifest. Check the manifest URL."
    return text
