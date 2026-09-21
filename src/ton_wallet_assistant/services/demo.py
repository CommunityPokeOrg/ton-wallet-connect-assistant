"""Demo wallet backend — no network, no keys, clearly fake.

The demo backend simulates the TonConnect handshake end-to-end so the UI can be
exercised without a manifest URL or a real wallet:

* ``connect()`` returns a ``demo://`` universal link and a scannable QR payload
  that no real wallet will accept (the scheme is not registered anywhere).
* After ``connect_delay`` seconds it emits a CONNECTED event with a randomly
  generated, well-formed wallet address on the configured demo network.
* ``disconnect()`` resets the session.

Everything it produces is labelled "Demo" so it can never be mistaken for a
real wallet connection.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from urllib.parse import quote

from ..models import ConnectedAccount, ConnectionState, ServiceEvent, WalletOption
from .base import WalletService

DEMO_WALLET = WalletOption(
    name="Demo Wallet",
    app_name="demo-wallet",
    universal_url="demo://wallet.demo/ton-connect",
    about_url="",
    platforms=("windows", "linux", "macos", "ios", "android"),
    raw={"app_name": "demo-wallet", "name": "Demo Wallet"},
)


class DemoWalletService(WalletService):
    def __init__(self, network: str = "mainnet", connect_delay: float = 1.5) -> None:
        super().__init__()
        self.network = network
        self.connect_delay = connect_delay
        self._account: ConnectedAccount | None = None
        self._pending_task: asyncio.Task | None = None
        self._session_id = ""

    async def list_wallets(self) -> list[WalletOption]:
        return [DEMO_WALLET]

    async def connect(self, wallet: WalletOption) -> str:
        await self._cancel_pending()
        self._session_id = uuid.uuid4().hex
        request = {
            "manifestUrl": "demo://wallet.demo/manifest.json",
            "items": [{"name": "ton_addr"}],
        }
        link = (
            f"{wallet.universal_url}?v=2&id={self._session_id}"
            f"&r={quote(json.dumps(request, separators=(',', ':')))}"
        )
        self._pending_task = asyncio.ensure_future(self._simulate_approval(wallet))
        return link

    async def restore(self) -> bool:
        return self._account is not None

    async def disconnect(self) -> None:
        await self._cancel_pending()
        if self._account is not None:
            self._account = None
            self._emit(ServiceEvent(state=ConnectionState.DISCONNECTED))

    async def close(self) -> None:
        await self._cancel_pending()

    async def _cancel_pending(self) -> None:
        if self._pending_task is not None:
            self._pending_task.cancel()
            try:
                await self._pending_task
            except asyncio.CancelledError:
                pass
            self._pending_task = None

    async def _simulate_approval(self, wallet: WalletOption) -> None:
        try:
            await asyncio.sleep(self.connect_delay)
        except asyncio.CancelledError:
            raise
        account_id = secrets.token_bytes(32)
        raw_address = f"0:{account_id.hex()}"
        self._account = ConnectedAccount.from_raw_address(
            raw_address,
            network=self.network,
            wallet_app="Demo Wallet",
            public_key=secrets.token_bytes(32).hex(),
            device_platform="demo",
        )
        self._emit(
            ServiceEvent(
                state=ConnectionState.CONNECTED,
                account=self._account,
                wallet_name=wallet.name,
            )
        )
