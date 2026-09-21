"""Headless Python SDK — use the wallet core and TonConnect without the GUI.

Quick start (demo mode — fully offline, no real keys/network):

    import asyncio
    from ton_wallet_assistant.sdk import TonWalletSDK

    async def main():
        sdk = await TonWalletSDK.demo()
        print(sdk.account.friendly_bounceable, await sdk.get_balance())
        await sdk.send_ton("UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ", "1.5")
        await sdk.close()

    asyncio.run(main())

Real mode (creates/uses the encrypted keystore on disk):

    sdk = TonWalletSDK(network="mainnet", manifest_url="https://example.com/manifest.json")
    words, account = await sdk.create_wallet(password="s3cret")     # show words once for backup
    sdk.unlock("s3cret")
    await sdk.send_ton("EQ…", "0.1", comment="hi")

Security: the mnemonic/keys are never logged or returned after wallet
creation; signing material is unlocked in memory only until ``lock()`` or
``close()``. Demo mode never touches the network.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .companion import PairingManager
from .companion.protocol import TonConnectLinkDetails, TransferDetails
from .config import AppConfig
from .models import ConnectedAccount, ConnectionState, ServiceEvent, WalletOption
from .wallet.account import (
    DEFAULT_VERSION,
    SUPPORTED_VERSIONS,
    WalletAccount,
    derive_account,
    generate_mnemonic,
    validate_mnemonic,
)
from .wallet.chain import (
    ChainError,
    JettonBalance,
    Nft,
    TxRecord,
    format_ton,
    format_units,
    ton_to_nano,
)
from .wallet.jettons import build_jetton_transfer_body, jetton_amount_to_units

if TYPE_CHECKING:
    from collections.abc import Callable

    from .services.base import WalletService
    from .wallet.chain import ChainClient
    from .wallet.keystore import Keystore

DEFAULT_FORWARD_TON_NANO = 50_000_000  # 0.05 TON notification for jetton sends


class TonConnectClient:
    """Async wrapper over a WalletService backend (real TonConnect or demo).

    Provides the dApp-side session lifecycle: list wallets, request a
    connection (returns a universal link), wait for approval, inspect the
    pending state, disconnect, and restore a previous session.
    """

    def __init__(self, service: WalletService) -> None:
        self._service = service
        self._events: asyncio.Queue[ServiceEvent] = asyncio.Queue()
        self._account: ConnectedAccount | None = None
        self._state = ConnectionState.DISCONNECTED
        self._error = ""
        service.set_event_callback(self._handle_event)

    # ------------------------------------------------------------- events

    def _handle_event(self, event: ServiceEvent) -> None:
        self._state = event.state
        if event.account is not None:
            self._account = event.account
        if event.error:
            self._error = event.error
        self._events.put_nowait(event)

    def on_event(self, callback: Callable[[ServiceEvent], None]) -> None:
        """Register an additional consumer for service events."""
        self._service.set_event_callback(lambda e: (self._handle_event(e), callback(e)))

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def connected(self) -> bool:
        return self._state is ConnectionState.CONNECTED and self._account is not None

    @property
    def pending(self) -> bool:
        """True while a connection request awaits wallet approval."""
        return self._state is ConnectionState.AWAITING_CONFIRMATION

    @property
    def account(self) -> ConnectedAccount | None:
        return self._account

    @property
    def last_error(self) -> str:
        return self._error

    # ---------------------------------------------------------- lifecycle

    async def list_wallets(self) -> list[WalletOption]:
        return await self._service.list_wallets()

    async def request_connection(self, wallet: WalletOption) -> str:
        """Start a connect request; returns the universal link/QR payload."""
        link = await self._service.connect(wallet)
        self._state = ConnectionState.AWAITING_CONFIRMATION
        return link

    async def wait_for_connection(self, timeout: float = 120.0) -> ConnectedAccount:
        """Block until the wallet approves (or rejects/errors)."""
        while True:
            event = await asyncio.wait_for(self._events.get(), timeout=timeout)
            if event.state is ConnectionState.CONNECTED and event.account is not None:
                return event.account
            if event.state is ConnectionState.ERROR:
                raise ChainError(event.error or "connection failed")

    async def disconnect(self) -> None:
        await self._service.disconnect()
        self._account = None
        self._state = ConnectionState.DISCONNECTED

    async def restore(self) -> bool:
        return await self._service.restore()

    async def close(self) -> None:
        await self._service.close()


class TonWalletSDK:
    """Headless facade over the wallet core, chain backends, and TonConnect.

    Args:
        network: ``"mainnet"`` (default) or ``"testnet"``.
        demo: run fully offline with fabricated data (no keys, no network).
        data_dir: directory for the keystore + TonConnect session file.
            Defaults to the app config dir (~/.config/ton-wallet-connect-assistant).
        tonapi_key: optional tonapi.io API key for higher read rate limits.
        manifest_url: public HTTPS URL of the app's tonconnect-manifest.json.
            Required for real TonConnect connections; without it the
            TonConnect client runs a clearly-labelled demo backend.
    """

    def __init__(
        self,
        *,
        network: str = "mainnet",
        demo: bool = False,
        data_dir: str | Path | None = None,
        tonapi_key: str | None = None,
        manifest_url: str | None = None,
        connect_delay: float = 1.5,
    ) -> None:
        if network not in ("mainnet", "testnet"):
            raise ValueError(f"unsupported network {network!r}")
        self.network = network
        self.demo = demo

        config = AppConfig.resolve(
            manifest_url=manifest_url,
            demo=demo,
            network=network,
            env=os.environ,
            file_config={},
        )
        if data_dir is not None:
            import dataclasses

            config_dir = Path(data_dir)
            config_dir.mkdir(parents=True, exist_ok=True)
            config = dataclasses.replace(config, storage_path=config_dir / "tonconnect-session.json")

        from .session import keystore_path
        from .wallet.keystore import Keystore

        self.config = config
        self.keystore: Keystore | None = None if demo else Keystore(keystore_path(config, network))
        self._account: WalletAccount | None = None
        self._words: list[str] | None = None  # decrypted mnemonic while unlocked

        self._chain: ChainClient
        if demo:
            from .services.demo import DemoWalletService
            from .wallet.demo import DemoChainClient

            self._chain = DemoChainClient(network)
            service: WalletService = DemoWalletService(network=network, connect_delay=connect_delay)
        else:
            from .services.tonconnect import TonConnectService
            from .wallet.tonapi import TonApiClient

            self._chain = TonApiClient(network, api_key=tonapi_key or os.environ.get("TONAPI_KEY"))
            if manifest_url:
                service = TonConnectService(manifest_url, config.storage_path)
            else:
                from .services.demo import DemoWalletService

                # No manifest configured -> TonConnect side stays in demo mode
                # (the chain backend is still real).
                service = DemoWalletService(network=network, connect_delay=connect_delay)
        self.tonconnect = TonConnectClient(service)

        # Mobile companion pairing bridge (not bound until start_pairing()).
        self.pairing = PairingManager(demo=demo, network=network)
        self.pairing.transfer_handler = self._pairing_transfer
        self.pairing.connect_handler = self._pairing_connect

    # ------------------------------------------------------------ demo

    @classmethod
    async def demo(cls, network: str = "mainnet", **kwargs) -> TonWalletSDK:
        """Create a demo SDK instance: random throwaway account, fake chain."""
        sdk = cls(network=network, demo=True, **kwargs)
        await sdk._ensure_demo_account()
        return sdk

    async def _ensure_demo_account(self) -> WalletAccount:
        if self._account is None:
            self._account = await derive_account(generate_mnemonic(), network=self.network)
        return self._account

    # ------------------------------------------------- wallet lifecycle

    @property
    def has_keystore(self) -> bool:
        return self.keystore is not None and self.keystore.exists

    @property
    def account(self) -> WalletAccount | None:
        """The derived account (address + public key). None until set up."""
        return self._account

    @property
    def address(self) -> str:
        """Friendly bounceable address; empty string if no account yet."""
        return self._account.friendly_bounceable if self._account else ""

    @property
    def is_unlocked(self) -> bool:
        return self.demo or self._words is not None

    async def create_wallet(
        self, password: str, wallet_version: str = DEFAULT_VERSION
    ) -> tuple[list[str], WalletAccount]:
        """Create a new wallet. Returns ``(words, account)`` — show the words
        once for backup; afterwards they live only in the encrypted keystore.
        """
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        if self.has_keystore:
            raise RuntimeError("keystore already exists — delete it first or use unlock()")
        words = generate_mnemonic()
        account = await derive_account(words, network=self.network, wallet_version=wallet_version)
        self.keystore.create(
            words, password, wallet_version=wallet_version,
            network=self.network, address_hint=account.friendly_bounceable,
        )
        self._account = account
        self._words = list(words)
        return words, account

    async def import_wallet(
        self, words: list[str], password: str, wallet_version: str = DEFAULT_VERSION
    ) -> WalletAccount:
        """Import an existing 24-word mnemonic into the encrypted keystore."""
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        if self.has_keystore:
            raise RuntimeError("keystore already exists — delete it first or use unlock()")
        words = validate_mnemonic(words)
        account = await derive_account(words, network=self.network, wallet_version=wallet_version)
        self.keystore.create(
            words, password, wallet_version=wallet_version,
            network=self.network, address_hint=account.friendly_bounceable,
        )
        self._account = account
        self._words = list(words)
        return account

    async def unlock_and_derive(self, password: str) -> WalletAccount:
        """Unlock the keystore with ``password`` and derive the account."""
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        self._words = self.keystore.unlock(password)  # raises WrongPasswordError
        meta = self.keystore.meta()
        self._account = await derive_account(
            self._words, network=meta.network, wallet_version=meta.wallet_version
        )
        return self._account

    def reveal_mnemonic(self, password: str) -> list[str]:
        """Return the recovery phrase. Sensitive — caller must not log/store it."""
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        return self.keystore.unlock(password)

    def lock(self) -> None:
        """Forget the decrypted mnemonic (keystore file remains encrypted)."""
        if self._words is not None:
            for i in range(len(self._words)):
                self._words[i] = "\x00" * 8
            self._words = None
        if self.keystore is not None and self.keystore.is_unlocked:
            self.keystore.lock()

    def change_password(self, old_password: str, new_password: str) -> None:
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        self.keystore.change_password(old_password, new_password)

    def delete_wallet(self, password: str) -> None:
        """Verify the password then delete the keystore file."""
        if self.keystore is None:
            raise RuntimeError("demo SDK has no keystore")
        self.keystore.unlock(password)  # raises on wrong password
        self.keystore.delete()
        self.lock()
        self._account = None

    # -------------------------------------------------------------- reads

    def _address(self) -> str:
        if self._account is None:
            raise RuntimeError("no wallet yet — create/import/unlock first")
        return self._account.friendly_bounceable

    async def get_balance(self) -> int:
        """TON balance in nanotons."""
        return await self._chain.get_balance(self._address())

    async def get_balance_ton(self) -> str:
        return format_ton(await self.get_balance())

    async def get_jettons(self) -> list[JettonBalance]:
        return await self._chain.get_jettons(self._address())

    async def get_nfts(self) -> list[Nft]:
        return await self._chain.get_nfts(self._address())

    async def get_history(self, limit: int = 25) -> list[TxRecord]:
        return await self._chain.get_history(self._address(), limit=limit)

    # -------------------------------------------------------------- sends

    def _mnemonic_for_signing(self) -> list[str]:
        if self.demo:
            return []  # demo backend ignores signing material
        if not self._words:
            raise RuntimeError("wallet is locked — call unlock_and_derive() first")
        return list(self._words)

    async def send_ton(self, destination: str, amount: str | float | int, comment: str = "") -> str:
        """Sign and broadcast a TON transfer. ``amount`` is decimal TON
        (str/float) or nanotons (int). Returns the broadcast marker/tx hash."""
        amount_nano = amount if isinstance(amount, int) else ton_to_nano(str(amount))
        return await self._chain.send(
            self._mnemonic_for_signing(),
            self._account.wallet_version if self._account else DEFAULT_VERSION,
            destination,
            amount_nano,
            comment,
        )

    async def send_jetton(
        self,
        asset: str | JettonBalance,
        destination: str,
        amount: str | float | int,
        comment: str = "",
    ) -> str:
        """Sign and broadcast a jetton transfer (TEP-74).

        ``asset`` is a symbol (e.g. "USDT") or a ``JettonBalance`` from
        ``get_jettons()``. ``amount`` is decimal units of that jetton
        (str/float) or raw units (int).
        """
        jetton = await self._resolve_jetton(asset)
        amount_units = (
            amount if isinstance(amount, int) else jetton_amount_to_units(str(amount), jetton.decimals)
        )
        return await self._chain.send_jetton(
            self._mnemonic_for_signing(),
            self._account.wallet_version if self._account else DEFAULT_VERSION,
            jetton,
            destination,
            amount_units,
            comment,
        )

    async def _resolve_jetton(self, asset: str | JettonBalance) -> JettonBalance:
        if isinstance(asset, JettonBalance):
            return asset
        symbol = asset.upper()
        for j in await self.get_jettons():
            if j.symbol.upper() == symbol:
                return j
        raise ChainError(f"no jetton balance for {asset!r} in this wallet")

    # ------------------------------------------------- companion pairing

    async def start_pairing(self, *, host: str = "0.0.0.0", port: int = 0) -> str:
        """Start the LAN companion bridge and return the pairing URL to show
        (QR-encode it for the phone). The bridge is token-gated; payloads are
        validated and queued — nothing is signed or forwarded until
        ``approve_pairing_request`` is called.
        """
        self.pairing.host = host
        self.pairing.port = port
        return await self.pairing.start()

    async def stop_pairing(self) -> None:
        await self.pairing.stop()

    @property
    def pairing_url(self) -> str:
        return self.pairing.pairing_url

    def pairing_pending(self) -> list:
        """Pending (non-expired) requests relayed from the phone."""
        return self.pairing.pending_requests()

    def pairing_requests(self):
        """Async iterator yielding each incoming relayed request."""
        return self.pairing.requests()

    async def approve_pairing_request(self, request_id: str, password: str | None = None) -> str:
        """Approve a relayed request and execute it.

        ``ton://transfer`` payloads are signed + broadcast via the keystore
        (unlocks first if ``password`` is given and the wallet is locked).
        TonConnect universal links are forwarded to the local wallet app
        (in demo mode they are only recorded). Returns the result text.
        """
        if password is not None and not self.demo and self.keystore is not None:
            if not self.is_unlocked:
                await self.unlock_and_derive(password)
        return await self.pairing.approve(request_id)

    def reject_pairing_request(self, request_id: str) -> None:
        self.pairing.reject(request_id)

    async def _pairing_transfer(self, request) -> str:
        details: TransferDetails = request.payload
        if details.jetton:
            match = next((j for j in await self.get_jettons() if j.address == details.jetton), None)
            if match is None:
                raise ChainError(f"no jetton balance for master {details.jetton}")
            if details.amount_nano is None:
                raise ChainError("ton:// link does not specify an amount")
            return await self.send_jetton(match, details.address, details.amount_nano, comment=details.comment)
        if details.amount_nano is None:
            raise ChainError("ton:// link does not specify an amount")
        return await self.send_ton(details.address, details.amount_nano, comment=details.comment)

    async def _pairing_connect(self, request) -> str:
        details: TonConnectLinkDetails = request.payload
        if self.demo:
            return f"demo: universal link for {details.wallet_host} accepted (not opened)"
        import webbrowser

        webbrowser.open(details.url)
        return f"forwarded universal link to wallet app ({details.wallet_host})"

    # ------------------------------------------------- low-level building

    @staticmethod
    def build_transfer_body(comment: str):
        """Comment cell for a plain TON transfer (op-0 text payload)."""
        from pytoniq_core import begin_cell

        if not comment.strip():
            raise ValueError("empty comment")
        return begin_cell().store_uint(0, 32).store_snake_string(comment.strip()).end_cell()

    @staticmethod
    def build_jetton_transfer(destination: str, amount_units: int, response_address: str,
                              comment: str = "", forward_ton_nano: int = DEFAULT_FORWARD_TON_NANO):
        """Construct a TEP-74 jetton-transfer message body (offline)."""
        return build_jetton_transfer_body(
            destination=destination,
            amount_units=amount_units,
            response_address=response_address,
            forward_ton_amount=forward_ton_nano,
            comment=comment,
        )

    # -------------------------------------------------------------- misc

    async def close(self) -> None:
        self.lock()
        await self.pairing.stop()
        await self._chain.close()
        await self.tonconnect.close()

    async def __aenter__(self) -> TonWalletSDK:
        if self.demo:
            await self._ensure_demo_account()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


__all__ = [
    "DEFAULT_FORWARD_TON_NANO",
    "PairingManager",
    "SUPPORTED_VERSIONS",
    "ChainError",
    "ConnectedAccount",
    "ConnectionState",
    "JettonBalance",
    "Nft",
    "ServiceEvent",
    "TonConnectClient",
    "TonWalletSDK",
    "TxRecord",
    "WalletAccount",
    "WalletOption",
    "format_ton",
    "format_units",
    "ton_to_nano",
]
