"""Pure-Python TDLib client over the native ``libtdjson`` shared library.

100% Python: the only native component is the prebuilt ``libtdjson``
(``libtdjson.so`` / ``tdjson.dll`` / ``libtdjson.dylib``) loaded at runtime
via :mod:`ctypes`. There is no Cython, no C/C++ extension, and no generated
binding layer in this repository — the Python code below owns library
loading, JSON serialization, client lifecycle, send/receive polling, async
update dispatch, authorization-state handling, errors, and shutdown.

The classic ``td_json_client_*`` entry points are used when present; builds
that only export the newer ``td_create_client_id``/``td_send``/``td_receive``
API are also supported.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import logging
import threading
from pathlib import Path
from typing import Any

from .client import TelegramAuthState, TelegramClient, TelegramError, TelegramUpdate
from .config import TelegramConfig

log = logging.getLogger(__name__)

_AUTH_STATES = {
    "authorizationStateWaitTdlibParameters": TelegramAuthState.INITIALIZING,
    "authorizationStateWaitPhoneNumber": TelegramAuthState.WAIT_PHONE,
    "authorizationStateWaitCode": TelegramAuthState.WAIT_CODE,
    "authorizationStateWaitPassword": TelegramAuthState.WAIT_PASSWORD,
    "authorizationStateReady": TelegramAuthState.READY,
    "authorizationStateLoggingOut": TelegramAuthState.CLOSED,
    "authorizationStateClosing": TelegramAuthState.CLOSED,
    "authorizationStateClosed": TelegramAuthState.CLOSED,
}


class TdJsonLoadError(TelegramError):
    """libtdjson could not be found/loaded."""


class TdJson:
    """Thin, pure-Python ctypes wrapper around a libtdjson instance.

    ``lib`` may be injected for tests (any object exposing the
    ``td_json_client_*`` callables); otherwise the shared library is loaded
    via :func:`ctypes.CDLL`.
    """

    def __init__(self, path: str | Path | None = None, *, lib: Any = None) -> None:
        self._lib = lib if lib is not None else self._load_library(path)
        self._client: Any = None
        self._client_id: int | None = None  # client_id API fallback
        self._use_client_id_api = not hasattr(self._lib, "td_json_client_create")

    # ------------------------------------------------------------ loading

    @staticmethod
    def _load_library(path: str | Path | None) -> Any:
        from .loader import resolve_tdjson_library, searched_paths

        candidates: list[str] = []
        resolved = resolve_tdjson_library(path)
        if resolved is not None:
            candidates.append(str(resolved))
        candidates.extend(searched_paths(path))  # bare names → OS loader
        # de-duplicate while preserving order
        seen: set[str] = set()
        candidates = [c for c in candidates if not (c in seen or seen.add(c))]

        errors = []
        for name in candidates:
            try:
                return ctypes.CDLL(name)
            except OSError as exc:
                errors.append(f"{name}: {exc}")
        raise TdJsonLoadError(
            "could not load libtdjson — set TDLIB_PATH or place the prebuilt "
            "library in a searched directory.\nSearched:\n  "
            + "\n  ".join(errors)
        )

    @staticmethod
    def _sig(fn, restype, argtypes=()) -> None:
        """Apply a ctypes signature; plain-Python fakes ignore it."""
        try:
            fn.restype = restype
            fn.argtypes = list(argtypes)
        except AttributeError:
            pass

    def _bind(self) -> None:
        if self._use_client_id_api:
            for name in ("td_create_client_id", "td_send", "td_receive", "td_execute"):
                if not hasattr(self._lib, name):
                    raise TdJsonLoadError(f"libtdjson does not export {name}()")
            self._sig(self._lib.td_create_client_id, ctypes.c_int)
            self._sig(self._lib.td_send, None, (ctypes.c_int, ctypes.c_char_p))
            self._sig(self._lib.td_receive, ctypes.c_char_p, (ctypes.c_double,))
            self._sig(self._lib.td_execute, ctypes.c_char_p, (ctypes.c_char_p,))
        else:
            self._sig(self._lib.td_json_client_create, ctypes.c_void_p)
            self._sig(
                self._lib.td_json_client_send, None, (ctypes.c_void_p, ctypes.c_char_p)
            )
            self._sig(
                self._lib.td_json_client_receive,
                ctypes.c_char_p,
                (ctypes.c_void_p, ctypes.c_double),
            )
            self._sig(
                self._lib.td_json_client_execute,
                ctypes.c_char_p,
                (ctypes.c_void_p, ctypes.c_char_p),
            )
            if hasattr(self._lib, "td_json_client_destroy"):
                self._sig(self._lib.td_json_client_destroy, None, (ctypes.c_void_p,))

    # ---------------------------------------------------------- lifecycle

    @property
    def created(self) -> bool:
        return self._client is not None or self._client_id is not None

    def create(self) -> None:
        self._bind()
        if self._use_client_id_api:
            self._client_id = self._lib.td_create_client_id()
        else:
            self._client = self._lib.td_json_client_create()
            if not self._client:
                raise TelegramError("td_json_client_create returned NULL")

    def send(self, request: dict[str, Any]) -> None:
        data = json.dumps(request).encode("utf-8")
        if self._use_client_id_api:
            if self._client_id is None:
                raise TelegramError("client not created")
            self._lib.td_send(self._client_id, data)
        else:
            if self._client is None:
                raise TelegramError("client not created")
            self._lib.td_json_client_send(self._client, data)

    def receive(self, timeout: float = 1.0) -> dict[str, Any] | None:
        """Blocking poll — call from a dedicated thread/executor."""
        if self._use_client_id_api:
            raw = self._lib.td_receive(timeout)
        else:
            if self._client is None:
                raise TelegramError("client not created")
            raw = self._lib.td_json_client_receive(self._client, timeout)
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    def execute(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Synchronous request (only for TDLib functions documented as such)."""
        data = json.dumps(request).encode("utf-8")
        raw = (
            self._lib.td_execute(data)
            if self._use_client_id_api
            else self._lib.td_json_client_execute(self._client, data)
        )
        return json.loads(raw.decode("utf-8")) if raw else None

    def destroy(self) -> None:
        if self._use_client_id_api:
            self._client_id = None  # client_id API closes via "close" request
            return
        if self._client is not None:
            if hasattr(self._lib, "td_json_client_destroy"):
                self._lib.td_json_client_destroy(self._client)
            self._client = None


class TdJsonClient(TelegramClient):
    """Async TelegramClient backed by :class:`TdJson`.

    A background thread polls ``td_receive``/``td_json_client_receive`` and
    funnels updates onto the owning asyncio loop; requests carry an
    ``@extra`` correlation id resolved through pending futures.
    """

    def __init__(self, config: TelegramConfig, *, lib: Any = None) -> None:
        super().__init__()
        self.config = config
        self._td = TdJson(config.tdlib_path, lib=lib)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recv_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._extra_counter = 0
        self._pending: dict[str, asyncio.Future] = {}
        self._log_out_sent = False

    # ------------------------------------------------------------- loop

    async def start(self) -> TelegramAuthState:
        if self._td.created:
            return self._auth_state
        self._loop = asyncio.get_running_loop()
        self.config.database_dir.mkdir(parents=True, exist_ok=True)
        self.config.files_dir.mkdir(parents=True, exist_ok=True)
        self._td.create()
        self._stop.clear()
        self._recv_thread = threading.Thread(target=self._poll, daemon=True)
        self._recv_thread.start()
        # Kick off parameter setup; TDLib responds via updateAuthorizationState.
        try:
            await self._request(
                "setTdlibParameters",
                use_test_dc=self.config.use_test_dc,
                database_directory=str(self.config.database_dir),
                files_directory=str(self.config.files_dir),
                database_encryption_key=None,
                use_file_database=True,
                use_chat_info_database=True,
                use_message_database=True,
                use_secret_chats=False,
                api_id=self.config.api_id,
                api_hash=self.config.api_hash,
                system_language_code=self.config.system_language_code,
                device_model=self.config.device_model,
                application_version=self.config.application_version,
            )
        except TelegramError:
            raise
        except Exception as exc:
            raise TelegramError(f"setTdlibParameters failed: {exc}") from exc
        return self._auth_state

    def _poll(self) -> None:
        while not self._stop.is_set():
            try:
                obj = self._td.receive(timeout=0.5)
            except Exception as exc:  # keep the thread alive on transient errors
                log.debug("td receive error: %s", exc)
                continue
            if obj is None or self._loop is None:
                continue
            self._loop.call_soon_threadsafe(self._dispatch, obj)

    def _dispatch(self, obj: dict[str, Any]) -> None:
        extra = obj.get("@extra")
        if extra is not None and extra in self._pending:
            fut = self._pending.pop(extra)
            if not fut.done():
                if obj.get("@type") == "error":
                    fut.set_exception(
                        TelegramError(obj.get("message", "TDLib error"), obj.get("code"))
                    )
                else:
                    fut.set_result(obj)
            return

        td_type = obj.get("@type", "")
        if td_type == "updateAuthorizationState":
            td_state = obj.get("authorization_state", {}).get("@type", "")
            mapped = _AUTH_STATES.get(td_state)
            if mapped is not None:
                if td_state == "authorizationStateWaitTdlibParameters":
                    return  # params already sent in start()
                self._set_auth_state(mapped)
            else:
                self._emit_update(TelegramUpdate("authorization_state", {"raw": td_state}))
            return
        if td_type == "updateNewMessage":
            msg = obj.get("message", {})
            content = msg.get("content", {})
            text = ""
            if content.get("@type") == "messageText":
                text = content.get("text", {}).get("text", "")
            self._emit_update(
                TelegramUpdate(
                    "new_message",
                    {
                        "chat_id": msg.get("chat_id"),
                        "sender_id": msg.get("sender_id"),
                        "text": text,
                        "id": msg.get("id"),
                    },
                )
            )
            return
        self._emit_update(TelegramUpdate("raw", obj))

    async def _request(self, td_type: str, timeout: float = 30.0, **params: Any) -> dict:
        if self._loop is None:
            raise TelegramError("client not started")
        self._extra_counter += 1
        extra = str(self._extra_counter)
        request = {"@type": td_type, "@extra": extra, **params}
        fut = self._loop.create_future()
        self._pending[extra] = fut
        try:
            self._td.send(request)
        except Exception:
            self._pending.pop(extra, None)
            raise
        return await asyncio.wait_for(fut, timeout=timeout)

    # ----------------------------------------------------------- auth API

    async def submit_phone(self, phone: str) -> TelegramAuthState:
        await self._request("setAuthenticationPhoneNumber", phone_number=phone)
        return self._auth_state

    async def submit_code(self, code: str) -> TelegramAuthState:
        await self._request("checkAuthenticationCode", code=code)
        return self._auth_state

    async def submit_password(self, password: str) -> TelegramAuthState:
        await self._request("checkAuthenticationPassword", password=password)
        return self._auth_state

    async def log_out(self) -> None:
        await self._request("logOut")

    # ------------------------------------------------------------ queries

    async def get_chats(self, limit: int = 20) -> list[dict]:
        result = await self._request("getChats", limit=limit)
        chat_ids = result.get("chat_ids") or []
        chats = []
        for chat_id in chat_ids[:limit]:
            chat = await self._request("getChat", chat_id=chat_id)
            chats.append({"id": chat.get("id"), "title": chat.get("title", ""), "raw": chat})
        return chats

    async def send_message(self, chat_id: int, text: str) -> dict:
        return await self._request(
            "sendMessage",
            chat_id=chat_id,
            input_message_content={
                "@type": "inputMessageText",
                "text": {"@type": "formattedText", "text": text},
            },
        )

    async def close(self) -> None:
        if self._auth_state is TelegramAuthState.READY and not self._log_out_sent:
            try:
                self._log_out_sent = True
                await self._request("close", timeout=5.0)
            except Exception:
                pass
        self._stop.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=3)
            self._recv_thread = None
        self._td.destroy()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(TelegramError("client closed"))
        self._pending.clear()
        self._set_auth_state(TelegramAuthState.CLOSED)
