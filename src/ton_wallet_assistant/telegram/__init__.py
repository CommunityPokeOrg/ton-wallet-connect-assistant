"""Telegram integration — pure-Python TDLib client + offline demo backend.

The real backend loads the prebuilt ``libtdjson`` shared library via ctypes
at runtime (no Cython, no C/C++ extensions, no generated bindings — this
package is 100% Python). Demo mode needs nothing but the standard library.
"""

from .client import (
    TelegramAuthState,
    TelegramClient,
    TelegramError,
    TelegramUpdate,
)
from .config import TelegramConfig, TelegramConfigError
from .demo import DemoTelegramClient
from .tdjson import TdJson, TdJsonClient, TdJsonLoadError

__all__ = [
    "DemoTelegramClient",
    "TdJson",
    "TdJsonClient",
    "TdJsonLoadError",
    "TelegramAuthState",
    "TelegramClient",
    "TelegramConfig",
    "TelegramConfigError",
    "TelegramError",
    "TelegramUpdate",
]
