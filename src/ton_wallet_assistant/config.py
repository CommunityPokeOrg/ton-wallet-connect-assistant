"""Runtime configuration for the wallet-connect assistant.

Configuration is resolved from (highest precedence first):

1. Command-line flags (see ``cli.py`` / ``__main__.py``)
2. Environment variables
3. A JSON config file (``~/.config/ton-wallet-assistant/config.json`` on Linux,
   ``%APPDATA%\\ton-wallet-assistant\\config.json`` on Windows)

Environment variables
---------------------
``TON_WALLET_ASSISTANT_MANIFEST_URL``
    HTTPS URL of the app's ``tonconnect-manifest.json``. Required for real
    TonConnect sessions; without it the app starts in demo mode.
``TON_WALLET_ASSISTANT_DEMO``
    ``1``/``true`` forces demo mode even if a manifest URL is configured.
``TON_WALLET_ASSISTANT_DEMO_NETWORK``
    ``mainnet`` (default) or ``testnet`` — the network the demo wallet
    pretends to be on.

No secret ever belongs in this configuration. TonConnect never requires API
keys or private keys on the dApp side; the session keypair is generated
ephemerally per session by ``pytonconnect``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "ton-wallet-connect-assistant"

ENV_MANIFEST_URL = "TON_WALLET_ASSISTANT_MANIFEST_URL"
ENV_DEMO = "TON_WALLET_ASSISTANT_DEMO"
ENV_DEMO_NETWORK = "TON_WALLET_ASSISTANT_DEMO_NETWORK"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys_platform() == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


def sys_platform() -> str:
    import sys

    return sys.platform


def _config_file() -> Path:
    return config_dir() / "config.json"


def _load_file_config(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _env_flag(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class AppConfig:
    """Resolved application configuration."""

    manifest_url: str | None
    demo_mode: bool
    demo_network: str
    storage_path: Path
    config_path: Path

    @property
    def real_connect_available(self) -> bool:
        return bool(self.manifest_url) and not self.demo_mode

    @classmethod
    def resolve(
        cls,
        *,
        manifest_url: str | None = None,
        demo: bool | None = None,
        demo_network: str | None = None,
        env: dict | None = None,
        file_config: dict | None = None,
    ) -> AppConfig:
        env = os.environ if env is None else env
        file_config = _load_file_config(_config_file()) if file_config is None else file_config

        manifest_url = (
            manifest_url
            or env.get(ENV_MANIFEST_URL)
            or file_config.get("manifest_url")
            or None
        )
        if demo is None:
            demo = _env_flag(env.get(ENV_DEMO)) or bool(file_config.get("demo"))
        demo_network = (
            demo_network
            or env.get(ENV_DEMO_NETWORK)
            or file_config.get("demo_network")
            or "mainnet"
        )
        if demo_network not in ("mainnet", "testnet"):
            demo_network = "mainnet"

        # Without a manifest URL there is nothing a real wallet can verify the
        # dApp against, so the app must run in demo mode.
        if not manifest_url:
            demo = True

        cfg_dir = config_dir()
        return cls(
            manifest_url=manifest_url,
            demo_mode=demo,
            demo_network=demo_network,
            storage_path=cfg_dir / "tonconnect-session.json",
            config_path=_config_file(),
        )
