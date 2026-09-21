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


@dataclass(frozen=True)
class JettonBalance:
    symbol: str
    name: str
    balance: str  # human-readable, already decimal-adjusted
    address: str  # jetton master address
    image_url: str = ""


@dataclass(frozen=True)
class TxRecord:
    tx_hash: str
    timestamp: int
    direction: str  # "in" | "out"
    amount_nano: int
    counterparty: str  # friendly or raw address
    comment: str = ""
    status: str = "confirmed"  # confirmed | pending | failed
    asset: str = "TON"

    @property
    def amount_ton(self) -> float:
        return nano_to_ton(self.amount_nano)


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

    @abc.abstractmethod
    async def close(self) -> None: ...
