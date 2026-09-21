"""Demo chain backend — fabricated balances/history, simulated sends.

Everything here is fake: no network, no real addresses, no keys. Demo sends
append a synthetic pending record so the UI flow can be exercised end-to-end.
"""

from __future__ import annotations

import secrets
import time

from ..address_utils import raw_to_friendly
from .chain import ChainClient, JettonBalance, TxRecord, ton_to_nano


def _fake_address() -> str:
    return raw_to_friendly(f"0:{secrets.token_bytes(32).hex()}", bounceable=False)


class DemoChainClient(ChainClient):
    def __init__(self, network: str = "mainnet") -> None:
        self.network = network
        self._balance = ton_to_nano("42.1337")
        self._history: list[TxRecord] = [
            TxRecord(
                tx_hash=secrets.token_hex(32),
                timestamp=int(time.time()) - 3600 * (i + 1),
                direction="in" if i % 3 else "out",
                amount_nano=ton_to_nano(f"{1.5 + i * 0.25:.4f}"),
                counterparty=_fake_address(),
                comment=["coffee", "", "demo payout", ""][i % 4],
            )
            for i in range(8)
        ]
        self._jettons = [
            JettonBalance(symbol="dUSD", name="Demo USD", balance="1,250.5", address=_fake_address()),
            JettonBalance(symbol="DEMO", name="Demo Token", balance="9,999", address=_fake_address()),
        ]

    async def get_balance(self, address: str) -> int:
        return self._balance

    async def get_jettons(self, address: str) -> list[JettonBalance]:
        return list(self._jettons)

    async def get_history(self, address: str, limit: int = 25) -> list[TxRecord]:
        return self._history[:limit]

    async def send(self, mnemonic, wallet_version, destination, amount_nano, comment="") -> str:
        if amount_nano > self._balance:
            from .chain import ChainError

            raise ChainError("Insufficient demo balance")
        self._balance -= amount_nano
        tx_hash = secrets.token_hex(32)
        self._history.insert(
            0,
            TxRecord(
                tx_hash=tx_hash,
                timestamp=int(time.time()),
                direction="out",
                amount_nano=amount_nano,
                counterparty=destination,
                comment=comment,
                status="pending",
            ),
        )
        return tx_hash

    async def close(self) -> None:
        return None
