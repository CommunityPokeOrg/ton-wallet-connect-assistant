"""Chain-backend interface + value types for balances, assets, and history."""

from __future__ import annotations

import abc
from dataclasses import dataclass


def nano_to_ton(nano: int | float) -> float:
    return nano / 1_000_000_000


def ton_to_nano(amount: str | float) -> int:
    """Parse a decimal TON amount string to nanotons. Raises ValueError."""
    text = str(amount).strip()
    if not text:
        raise ValueError("empty amount")
    if text.startswith("-") or "+" in text:
        raise ValueError("invalid amount")
    whole, dot, frac = text.partition(".")
    if not whole:
        whole = "0"
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise ValueError(f"invalid amount {amount!r}")
    if len(frac) > 9:
        raise ValueError("too many decimals (max 9)")
    return int(whole) * 1_000_000_000 + int(frac.ljust(9, "0") or 0)


def format_ton(nano: int | float) -> str:
    value = nano_to_ton(nano)
    text = f"{value:,.4f}".rstrip("0").rstrip(".")
    return text if "." in text or value == 0 else text


def format_units(raw: int, decimals: int, max_frac: int = 4) -> str:
    """Format a raw asset amount using its decimals."""
    text = f"{raw / 10**decimals:,.{max_frac}f}".rstrip("0").rstrip(".")
    return text or "0"


@dataclass(frozen=True)
class JettonBalance:
    symbol: str
    name: str
    balance: str  # human-readable, already decimal-adjusted
    address: str  # jetton master address
    image_url: str = ""
    decimals: int = 9
    raw_balance: int = 0  # raw units; 0 means unknown
    wallet_address: str = ""  # owner's jetton wallet (needed to send)


@dataclass(frozen=True)
class Nft:
    name: str
    address: str
    collection: str = ""
    image_url: str = ""
    description: str = ""


@dataclass(frozen=True)
class TxRecord:
    tx_hash: str
    timestamp: int
    direction: str  # "in" | "out"
    amount_nano: int  # raw units of `asset` (nanotons for TON)
    counterparty: str  # friendly or raw address
    comment: str = ""
    status: str = "confirmed"  # confirmed | pending | failed
    asset: str = "TON"
    asset_decimals: int = 9
    fee_nano: int | None = None  # network fee, when known
    sender: str = ""  # friendly sender address (for details view)
    recipient: str = ""  # friendly recipient address

    @property
    def amount_ton(self) -> float:
        return nano_to_ton(self.amount_nano)

    @property
    def formatted_amount(self) -> str:
        return format_units(self.amount_nano, self.asset_decimals)


class ChainError(Exception):
    pass


class ChainClient(abc.ABC):
    """Read/write access to the TON blockchain for one account."""

    @abc.abstractmethod
    async def get_balance(self, address: str) -> int:
        """Return TON balance in nanotons."""

    @abc.abstractmethod
    async def get_jettons(self, address: str) -> list[JettonBalance]:
        """Return jetton balances for the account."""

    async def get_nfts(self, address: str) -> list[Nft]:
        """Return NFTs owned by the account (empty by default)."""
        return []

    @abc.abstractmethod
    async def get_history(self, address: str, limit: int = 25) -> list[TxRecord]:
        """Recent transfer history, newest first."""

    @abc.abstractmethod
    async def send(
        self,
        mnemonic: list[str],
        wallet_version: str,
        destination: str,
        amount_nano: int,
        comment: str = "",
    ) -> str:
        """Sign and broadcast a TON transfer. Returns the tx hash."""

    async def send_jetton(
        self,
        mnemonic: list[str],
        wallet_version: str,
        jetton: JettonBalance,
        destination: str,
        amount_units: int,
        comment: str = "",
    ) -> str:
        """Sign and broadcast a jetton transfer. Returns the tx hash."""
        raise ChainError("Jetton transfers not supported by this backend")

    @abc.abstractmethod
    async def close(self) -> None: ...
