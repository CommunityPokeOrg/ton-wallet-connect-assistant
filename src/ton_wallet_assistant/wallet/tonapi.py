"""Read-side chain backend: tonapi.io REST (balances, jettons, history)."""

from __future__ import annotations

from typing import Any

from .chain import ChainClient, ChainError, JettonBalance, TxRecord

MAINNET_API = "https://tonapi.io"
TESTNET_API = "https://testnet.tonapi.io"


class TonApiClient(ChainClient):
    """Reads via tonapi.io; sends via the pytoniq lite-client (see sender.py).

    An optional tonapi API key raises rate limits but is not required —
    read endpoints work anonymously at the free tier.
    """

    def __init__(self, network: str = "mainnet", api_key: str | None = None, sender=None) -> None:
        import httpx

        base = TESTNET_API if network == "testnet" else MAINNET_API
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.AsyncClient(base_url=base, headers=headers, timeout=15)
        self.network = network
        self._sender = sender  # lazy LiteSender or compatible

    async def _get(self, path: str, params: dict | None = None) -> Any:
        try:
            resp = await self._http.get(path, params=params)
        except Exception as exc:
            raise ChainError(f"Network error contacting tonapi: {exc}") from exc
        if resp.status_code == 429:
            raise ChainError("Rate limited by tonapi — wait a moment and retry")
        if resp.status_code >= 400:
            raise ChainError(f"tonapi returned HTTP {resp.status_code}")
        return resp.json()

    async def get_balance(self, address: str) -> int:
        data = await self._get(f"/v2/accounts/{address}")
        return int(data.get("balance", 0))

    async def get_jettons(self, address: str) -> list[JettonBalance]:
        data = await self._get(f"/v2/accounts/{address}/jettons", {"currencies": "usd"})
        out = []
        for item in data.get("balances", []):
            jetton = item.get("jetton", {})
            decimals = int(jetton.get("decimals", 9))
            raw_balance = int(item.get("balance", "0"))
            meta = jetton.get("metadata") or {}
            out.append(
                JettonBalance(
                    symbol=jetton.get("symbol") or meta.get("symbol") or "?",
                    name=jetton.get("name") or meta.get("name") or "Jetton",
                    balance=f"{raw_balance / 10**decimals:,.4f}".rstrip("0").rstrip("."),
                    address=item.get("wallet_address", {}).get("address", "")
                    if isinstance(item.get("wallet_address"), dict)
                    else jetton.get("address", ""),
                    image_url=jetton.get("image") or meta.get("image") or "",
                )
            )
        return out

    async def get_history(self, address: str, limit: int = 25) -> list[TxRecord]:
        data = await self._get(
            f"/v2/accounts/{address}/events",
            {"limit": limit, "subject_only": "true"},
        )
        records: list[TxRecord] = []
        for event in data.get("events", []):
            for action in event.get("actions", []):
                rec = _action_to_record(action, address, event.get("event_id", ""))
                if rec is not None:
                    records.append(rec)
        return records[:limit]

    async def send(self, mnemonic, wallet_version, destination, amount_nano, comment="") -> str:
        if self._sender is None:
            from .sender import LiteSender

            self._sender = LiteSender(self.network)
        return await self._sender.send(mnemonic, wallet_version, destination, amount_nano, comment)

    async def close(self) -> None:
        await self._http.aclose()
        if self._sender is not None:
            await self._sender.close()


def _friendly(addr: Any) -> str:
    if not addr:
        return ""
    if isinstance(addr, dict):
        addr = addr.get("address", "")
    try:
        from pytoniq_core import Address

        return Address(str(addr)).to_str(is_user_friendly=True, is_bounceable=False)
    except Exception:
        return str(addr)


def _action_to_record(action: dict, own: str, event_id: str) -> TxRecord | None:
    atype = action.get("type")
    simple = action.get("simple_preview") or {}
    own_friendly = _friendly(own)

    if atype == "TonTransfer":
        t = action.get("TonTransfer", {})
        sender = _friendly(t.get("sender"))
        recipient = _friendly(t.get("recipient"))
        direction = "in" if recipient == own_friendly else "out"
        return TxRecord(
            tx_hash=event_id,
            timestamp=int(action.get("timestamp") or simple.get("timestamp") or 0),
            direction=direction,
            amount_nano=int(t.get("amount", 0)),
            counterparty=sender if direction == "in" else recipient,
            comment=t.get("comment") or "",
            status="confirmed" if action.get("status", "ok") == "ok" else "failed",
        )
    if atype == "JettonTransfer":
        t = action.get("JettonTransfer", {})
        sender = _friendly(t.get("sender"))
        recipient = _friendly(t.get("recipient"))
        direction = "in" if recipient == own_friendly else "out"
        jetton = t.get("jetton") or {}
        decimals = int(jetton.get("decimals", 9))
        try:
            amount = float(t.get("amount", "0")) * 10**decimals
        except (TypeError, ValueError):
            amount = 0
        return TxRecord(
            tx_hash=event_id,
            timestamp=int(action.get("timestamp") or simple.get("timestamp") or 0),
            direction=direction,
            amount_nano=int(amount),
            counterparty=sender if direction == "in" else recipient,
            comment=t.get("comment") or "",
            status="confirmed" if action.get("status", "ok") == "ok" else "failed",
            asset=jetton.get("symbol") or "JETTON",
        )
    return None
