"""Runtime session: account + keystore + chain backend + wallet-connect backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .services.base import WalletService
from .wallet.account import WalletAccount
from .wallet.chain import ChainClient
from .wallet.keystore import Keystore


def keystore_path(config: AppConfig, network: str) -> Path:
    return Path(config.storage_path).parent / f"keystore-{network}.json"


@dataclass
class WalletSession:
    """Everything the wallet UI needs for one unlocked (or demo) account."""

    account: WalletAccount
    chain: ChainClient
    keystore: Keystore | None  # None in demo mode — nothing is persisted
    demo: bool
    connect_service: WalletService  # the TonConnect (dApp-side) backend

    @property
    def locked(self) -> bool:
        return self.keystore is not None and not self.keystore.is_unlocked

    def unlock(self, password: str) -> list[str]:
        if self.keystore is None:
            raise RuntimeError("demo session has no keystore")
        return self.keystore.unlock(password)
