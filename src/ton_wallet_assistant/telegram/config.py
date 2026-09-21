"""Telegram client configuration — all secrets come from the environment.

Never hardcode API credentials: Telegram requires ``api_id`` + ``api_hash``
from https://my.telegram.org. They are read from env vars at runtime:

* ``TELEGRAM_API_ID``    — integer app id (required for real mode)
* ``TELEGRAM_API_HASH``  — app hash (required, never logged)
* ``TELEGRAM_PHONE``     — optional default phone for the auth flow
* ``TDLIB_PATH``         — optional path to the prebuilt libtdjson library
* ``TELEGRAM_TEST_DC``   — ``1``/``true`` to use Telegram test datacenters
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class TelegramConfigError(Exception):
    """Raised when required Telegram configuration is missing/invalid."""


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
        env = os.environ if env is None else env
        api_id = env.get("TELEGRAM_API_ID", "").strip()
        api_hash = env.get("TELEGRAM_API_HASH", "").strip()
        missing = [n for n, v in (("TELEGRAM_API_ID", api_id), ("TELEGRAM_API_HASH", api_hash)) if not v]
        if missing:
            raise TelegramConfigError(
                f"missing required env vars: {', '.join(missing)} "
                "(get credentials at https://my.telegram.org)"
            )
        try:
            api_id_int = int(api_id)
        except ValueError as exc:
            raise TelegramConfigError("TELEGRAM_API_ID must be an integer") from exc
        if not api_id_int > 0:
            raise TelegramConfigError("TELEGRAM_API_ID must be a positive integer")

        base = Path(data_dir) if data_dir else Path(
            env.get("XDG_CONFIG_HOME", Path.home() / ".config")
        ) / "ton-wallet-connect-assistant"
        tdlib_path = Path(p) if (p := env.get("TDLIB_PATH", "").strip()) else None
        use_test_dc = env.get("TELEGRAM_TEST_DC", "").lower() in ("1", "true", "yes")
        return cls(
            api_id=api_id_int,
            api_hash=api_hash,
            phone=env.get("TELEGRAM_PHONE") or None,
            database_dir=base / "tdlib-db",
            files_dir=base / "tdlib-files",
            tdlib_path=tdlib_path,
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
