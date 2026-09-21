"""Broadcast TON transfers through the lite-client protocol (pytoniq).

The transfer is signed locally with the wallet's private key and sent to TON
lite-servers — the same mechanism desktop/mobile wallets use. The private key
is derived from the decrypted mnemonic for the duration of the call only.
"""

from __future__ import annotations

from .account import private_key_from_mnemonic
from .chain import ChainError


class LiteSender:
    """Sends TON transfers via ``pytoniq`` lite-client (no API key needed)."""

    def __init__(self, network: str = "mainnet") -> None:
        self.network = network
        self._client = None

    async def _ensure_client(self):
        if self._client is not None:
            return self._client
        try:
            from pytoniq import LiteClient
        except ImportError as exc:
            raise ChainError("pytoniq is required to send real transactions") from exc
        if self.network == "testnet":
            client = LiteClient.from_testnet_config(ls_i=0, trust_level=2, timeout=15)
        else:
            client = LiteClient.from_mainnet_config(ls_i=0, trust_level=2, timeout=15)
        try:
            await client.connect()
        except Exception as exc:
            raise ChainError(f"Could not connect to TON lite-servers: {exc}") from exc
        self._client = client
        return client

    async def send(
        self,
        mnemonic: list[str],
        wallet_version: str,
        destination: str,
        amount_nano: int,
        comment: str = "",
    ) -> str:
        from ..address_utils import is_friendly_address, is_raw_address

        if not (is_friendly_address(destination) or is_raw_address(destination)):
            raise ChainError("Destination is not a valid TON address")
        if amount_nano <= 0:
            raise ChainError("Amount must be positive")

        client = await self._ensure_client()
        private_key = private_key_from_mnemonic(mnemonic)
        try:
            if wallet_version == "v5r1":
                from pytoniq.contract.wallets import WalletV5R1 as WalletCls

                wallet = await WalletCls.from_private_key(
                    provider=client,
                    private_key=private_key,
                    network_global_id=-3 if self.network == "testnet" else -239,
                )
            else:
                from pytoniq.contract.wallets import WalletV4R2 as WalletCls

                wallet = await WalletCls.from_private_key(provider=client, private_key=private_key)

            body = None
            if comment.strip():
                from pytoniq_core import begin_cell

                body = begin_cell().store_uint(0, 32).store_snake_string(comment.strip()).end_cell()

            await wallet.transfer(destination=destination, amount=amount_nano, body=body)
        except ChainError:
            raise
        except Exception as exc:
            raise ChainError(f"Transfer failed: {exc}") from exc
        finally:
            private_key = b"\x00" * len(private_key)
        # pytoniq's raw_transfer returns the sent message hash context-dependent;
        # surface a best-effort identifier the UI can display.
        return getattr(wallet, "_last_tx_hash", "") or "broadcast"

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None
