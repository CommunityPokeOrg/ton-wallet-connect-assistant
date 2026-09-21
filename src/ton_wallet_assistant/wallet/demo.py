"""Demo chain backend — fabricated balances/history/NFTs, simulated sends.

Everything here is fake: no network, no real addresses, no keys. Demo sends
append a synthetic pending record so the UI flow can be exercised end-to-end.
"""

from __future__ import annotations

import secrets
import time

from ..address_utils import raw_to_friendly
from .chain import ChainClient, ChainError, JettonBalance, Nft, TxRecord, ton_to_nano


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
                fee_nano=ton_to_nano("0.005"),
            )
            for i in range(8)
        ]
        self._jettons = [
            JettonBalance(
                symbol="dUSD", name="Demo USD", balance="1,250.5",
                address=_fake_address(), decimals=6, raw_balance=1_250_500_000,
                wallet_address=_fake_address(),
            ),
            JettonBalance(
                symbol="DEMO", name="Demo Token", balance="9,999",
                address=_fake_address(), decimals=9, raw_balance=9_999_000_000_000,
                wallet_address=_fake_address(),
            ),
        ]
        self._nfts = [
            Nft(
                name="Whales Club #42", address=_fake_address(),
                collection="Whales Club", description="Demo collectible",
            ),
            Nft(
                name="demo.ton", address=_fake_address(),
                collection="TON DNS", description="Demo domain",
            ),
            Nft(
                name="NotCoin Voucher #7", address=_fake_address(),
                collection="NotCoin", description="Demo voucher",
            ),
        ]

    async def get_balance(self, address: str) -> int:
        return self._balance

    async def get_jettons(self, address: str) -> list[JettonBalance]:
        return list(self._jettons)

    async def get_nfts(self, address: str) -> list[Nft]:
        return list(self._nfts)

    async def get_history(self, address: str, limit: int = 25) -> list[TxRecord]:
        return self._history[:limit]

    async def send(self, mnemonic, wallet_version, destination, amount_nano, comment="") -> str:
        if amount_nano > self._balance:
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

    async def send_jetton(self, mnemonic, wallet_version, jetton, destination, amount_units, comment="") -> str:
        held = next((j for j in self._jettons if j.symbol == jetton.symbol), None)
        if held is None:
            raise ChainError(f"Demo wallet holds no {jetton.symbol}")
        if amount_units > held.raw_balance:
            raise ChainError(f"Insufficient demo {jetton.symbol} balance")
        remaining = held.raw_balance - amount_units
        decimals = held.decimals
        new_balance = f"{remaining / 10**decimals:,.4f}".rstrip("0").rstrip(".")
        self._jettons[self._jettons.index(held)] = JettonBalance(
            symbol=held.symbol, name=held.name, balance=new_balance,
            address=held.address, decimals=decimals, raw_balance=remaining,
            wallet_address=held.wallet_address,
        )
        tx_hash = secrets.token_hex(32)
        self._history.insert(
            0,
            TxRecord(
                tx_hash=tx_hash,
                timestamp=int(time.time()),
                direction="out",
                amount_nano=amount_units,
                counterparty=destination,
                comment=comment,
                status="pending",
                asset=held.symbol,
                asset_decimals=decimals,
            ),
        )
        return tx_hash

    async def close(self) -> None:
        return None
