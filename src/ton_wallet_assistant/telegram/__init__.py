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
from .loader import (
    candidate_dirs,
    platform_library_name,
    resolve_tdjson_library,
    searched_paths,
)
from .tdjson import TdJson, TdJsonClient, TdJsonLoadError
from .webapp_runtime import KNOWN_EVENTS, WebAppRuntime

__all__ = [
    "DemoTelegramClient",
    "KNOWN_EVENTS",
    "TdJson",
    "TdJsonClient",
    "TdJsonLoadError",
    "TelegramAuthState",
    "TelegramClient",
    "TelegramConfig",
    "TelegramConfigError",
    "TelegramError",
    "TelegramUpdate",
    "WebAppRuntime",
    "candidate_dirs",
    "platform_library_name",
    "resolve_tdjson_library",
    "searched_paths",
]
