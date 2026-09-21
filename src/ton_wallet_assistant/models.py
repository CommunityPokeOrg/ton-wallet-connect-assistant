"""Shared data types for the wallet-connect assistant.

These types are deliberately UI- and backend-agnostic: both the real TonConnect
backend and the demo backend produce/consume them, and the GUI renders them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .address_utils import (
    AddressError,
    network_from_chain,
    parse_raw_address,
    raw_to_friendly,
)


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class WalletOption:
    """A wallet the user can connect through (e.g. Tonkeeper, Telegram Wallet)."""

    name: str
    app_name: str
    universal_url: str = ""
    about_url: str = ""
    image_url: str = ""
    bridge_url: str = ""
    platforms: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_tonconnect(cls, wallet: dict[str, Any]) -> WalletOption:
        bridges = wallet.get("bridge") or []
        sse_bridge = next((b for b in bridges if b.get("type") == "sse"), {})
        return cls(
            name=wallet.get("name") or wallet.get("app_name") or "Unknown wallet",
            app_name=wallet.get("app_name") or wallet.get("name") or "unknown",
            universal_url=wallet.get("universal_url", ""),
            about_url=wallet.get("about_url", ""),
            image_url=wallet.get("image", ""),
            bridge_url=sse_bridge.get("url", ""),
            platforms=tuple(wallet.get("platforms") or ()),
            raw=wallet,
        )

    @property
    def supports_desktop(self) -> bool:
        if not self.platforms:
            return True
        return bool({"windows", "linux", "macos"} & set(self.platforms))


@dataclass(frozen=True)
class ConnectedAccount:
    """The wallet account the user approved for this session."""

    raw_address: str
    friendly_bounceable: str
    friendly_non_bounceable: str
    network: str
    workchain: int
    wallet_app: str = ""
    public_key: str = ""
    device_platform: str = ""

    @property
    def short_address(self) -> str:
        a = self.friendly_bounceable
        return f"{a[:8]}…{a[-6:]}" if len(a) > 16 else a

    @classmethod
    def from_raw_address(
        cls,
        raw_address: str,
        *,
        network: str = "mainnet",
        wallet_app: str = "",
        public_key: str = "",
        device_platform: str = "",
    ) -> ConnectedAccount:
        workchain, _ = parse_raw_address(raw_address)
        test_only = network == "testnet"
        return cls(
            raw_address=raw_address,
            friendly_bounceable=raw_to_friendly(raw_address, bounceable=True, test_only=test_only),
            friendly_non_bounceable=raw_to_friendly(raw_address, bounceable=False, test_only=test_only),
            network=network,
            workchain=workchain,
            wallet_app=wallet_app,
            public_key=public_key,
            device_platform=device_platform,
        )

    @classmethod
    def from_tonconnect(cls, wallet_info: dict[str, Any]) -> ConnectedAccount:
        account = wallet_info.get("account") or {}
        device = wallet_info.get("device") or {}
        raw_address = account.get("address") or ""
        if not raw_address:
            raise AddressError("wallet info contains no account address")
        return cls.from_raw_address(
            raw_address,
            network=network_from_chain(account.get("chain")),
            wallet_app=device.get("app_name") or wallet_info.get("app_name") or "",
            public_key=account.get("public_key") or "",
            device_platform=device.get("platform") or "",
        )


@dataclass(frozen=True)
class ServiceEvent:
    """An event emitted by a wallet backend and consumed by the GUI."""

    state: ConnectionState
    account: ConnectedAccount | None = None
    error: str = ""
    link: str = ""
    wallet_name: str = ""
