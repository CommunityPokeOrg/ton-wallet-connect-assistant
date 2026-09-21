"""Telegram client configuration.

Credentials resolve with strict precedence — environment variables,
then the ``"telegram"`` section of ``config.json``, then the built-in
app defaults (``DEFAULT_API_ID`` / ``DEFAULT_API_HASH``):

* ``TELEGRAM_API_ID``    — integer app id
* ``TELEGRAM_API_HASH``  — app hash (never logged; masked in diagnostics)
* ``TELEGRAM_PHONE``     — optional default phone for the auth flow
* ``TDLIB_PATH``         — optional path to the prebuilt libtdjson library
* ``TELEGRAM_TEST_DC``   — ``1``/``true`` to use Telegram test datacenters

Note: the built-in defaults are public app credentials shipped in source
anyone can read them — they are a convenience so the app works out of
the box, not a secret store. Operators should supply their own
api_id/api_hash from https://my.telegram.org via env or config.json.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class TelegramConfigError(Exception):
    """Raised when required Telegram configuration is missing/invalid."""


# Built-in fallback app credentials (supplied by the project owner).
# Public by design — overridden by env vars or config.json when present.
DEFAULT_API_ID = 24715872
DEFAULT_API_HASH = "f20ddb0c4be8968b984e5ac7467034ef"


@dataclass(frozen=True)
class TelegramConfig:
    api_id: int
    api_hash: str
    database_dir: Path
    files_dir: Path
    phone: str | None = None
    tdlib_path: Path | None = None
    use_test_dc: bool = False
    system_language_code: str = "en"
    device_model: str = "Desktop"
    application_version: str = "0.1.0"

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        data_dir: str | Path | None = None,
    ) -> TelegramConfig:
        """Env-only resolution (no config file). Prefer ``resolve()``."""
        return cls.resolve(env=env, file_config={}, data_dir=data_dir)

    @classmethod
    def resolve(
        cls,
        env: dict[str, str] | None = None,
        *,
        file_config: dict | None = None,
        data_dir: str | Path | None = None,
    ) -> TelegramConfig:
        """Resolve configuration: env vars > config file > code defaults.

        ``file_config`` is the parsed ``config.json`` (a ``"telegram"``
        section is read: ``api_id``, ``api_hash``, ``phone``,
        ``tdlib_path``, ``test_dc``). When ``file_config`` is None the
        standard app config file is loaded. Env vars always win; when
        neither env nor file supplies credentials, the built-in
        ``DEFAULT_API_ID``/``DEFAULT_API_HASH`` are used.
        """
        env = os.environ if env is None else env
        if file_config is None:
            from ..config import _config_file, _load_file_config

            file_config = _load_file_config(_config_file())
        section = file_config.get("telegram") or {}

        def pick(env_name: str, key: str) -> str:
            value = env.get(env_name, "").strip()
            if not value:
                value = str(section.get(key, "") or "").strip()
            return value

        api_id = pick("TELEGRAM_API_ID", "api_id")
        api_hash = pick("TELEGRAM_API_HASH", "api_hash")
        if not api_id:
            api_id = str(DEFAULT_API_ID)
        if not api_hash:
            api_hash = DEFAULT_API_HASH
        try:
            api_id_int = int(api_id)
        except ValueError as exc:
            raise TelegramConfigError("TELEGRAM_API_ID/api_id must be an integer") from exc
        if not api_id_int > 0:
            raise TelegramConfigError("TELEGRAM_API_ID/api_id must be a positive integer")
        if not api_hash.strip():
            raise TelegramConfigError("TELEGRAM_API_HASH/api_hash must not be empty")

        base = Path(data_dir) if data_dir else Path(
            env.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "ton-wallet-connect-assistant"
        tdlib_raw = pick("TDLIB_PATH", "tdlib_path")
        test_dc_raw = pick("TELEGRAM_TEST_DC", "test_dc")
        use_test_dc = (
            test_dc_raw.lower() in ("1", "true", "yes") or section.get("test_dc") is True
        )
        return cls(
            api_id=api_id_int,
            api_hash=api_hash,
            phone=pick("TELEGRAM_PHONE", "phone") or None,
            database_dir=base / "tdlib-db",
            files_dir=base / "tdlib-files",
            tdlib_path=Path(tdlib_raw) if tdlib_raw else None,
            use_test_dc=use_test_dc,
        )

    def masked(self) -> dict:
        """Safe-to-log view — never includes the api_hash value."""
        return {
            "api_id": self.api_id,
            "api_hash": "***" if self.api_hash else "",
            "phone": (self.phone[:4] + "…") if self.phone else None,
            "database_dir": str(self.database_dir),
            "tdlib_path": str(self.tdlib_path) if self.tdlib_path else None,
            "use_test_dc": self.use_test_dc,
        }
