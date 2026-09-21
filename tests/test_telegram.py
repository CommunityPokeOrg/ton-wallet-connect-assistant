"""Tests for the pure-Python TDLib integration.

All tests use an in-process fake libtdjson (pure Python, no compiler, no
TDLib install) plus the offline demo client — covering library loading,
ctypes request/response behavior, auth states, update dispatch, errors,
and shutdown.
"""

import asyncio
import json
import queue
import subprocess
import sys
from pathlib import Path

import pytest

import ton_wallet_assistant.telegram
from ton_wallet_assistant.sdk import TonWalletSDK
from ton_wallet_assistant.telegram import (
    DemoTelegramClient,
    TdJson,
    TdJsonClient,
    TdJsonLoadError,
    TelegramAuthState,
    TelegramConfig,
    TelegramConfigError,
    TelegramError,
)

# ----------------------------------------------------------- fake libtdjson


class FakeTdLib:
    """In-process stand-in for libtdjson's td_json_client_* C functions.

    Implements just enough of the TDLib JSON protocol: clients, send/receive
    queues, @extra correlation, and the auth state machine.
    """

    def __init__(self) -> None:
        self.clients: dict[int, queue.Queue] = {}
        self.requests: list[dict] = []
        self.destroyed = False
        self._next_client = 0
        self._auth_state: dict[int, str] = {}

    # --- C API equivalents ----------------------------------------------

    def td_json_client_create(self):
        self._next_client += 1
        self.clients[self._next_client] = queue.Queue()
        self._auth_state[self._next_client] = "wait_params"
        return self._next_client

    def td_json_client_send(self, client, data: bytes) -> None:
        request = json.loads(data.decode())
        self.requests.append(request)
        td_type = request["@type"]
        extra = request.get("@extra")
        q = self.clients[client]

        def ok():
            if extra is not None:
                q.put(json.dumps({"@type": "ok", "@extra": extra}))

        def auth(state_td: str):
            q.put(json.dumps({
                "@type": "updateAuthorizationState",
                "authorization_state": {"@type": state_td},
            }))

        if td_type == "setTdlibParameters":
            assert request["api_id"] == 12345
            ok()
            auth("authorizationStateWaitPhoneNumber")
        elif td_type == "setAuthenticationPhoneNumber":
            ok()
            auth("authorizationStateWaitCode")
        elif td_type == "checkAuthenticationCode":
            if request["code"] == "12345":
                ok()
                auth("authorizationStateReady")
            else:
                q.put(json.dumps({
                    "@type": "error", "code": 400,
                    "message": "PHONE_CODE_INVALID", "@extra": extra,
                }))
        elif td_type == "checkAuthenticationPassword":
            if request["password"] == "hunter2":
                ok()
                auth("authorizationStateReady")
            else:
                q.put(json.dumps({
                    "@type": "error", "code": 400,
                    "message": "PASSWORD_HASH_INVALID", "@extra": extra,
                }))
        elif td_type == "getChats":
            q.put(json.dumps({"@type": "chats", "chat_ids": [7, 8], "@extra": extra}))
        elif td_type == "getChat":
            titles = {7: "Wallet (Telegram)", 8: "TON Community"}
            q.put(json.dumps({
                "@type": "chat", "id": request["chat_id"],
                "title": titles[request["chat_id"]], "@extra": extra,
            }))
        elif td_type == "sendMessage":
            q.put(json.dumps({
                "@type": "message", "id": 9000,
                "chat_id": request["chat_id"], "@extra": extra,
            }))
            # simulate an incoming-message update afterwards
            q.put(json.dumps({
                "@type": "updateNewMessage",
                "message": {
                    "id": 9001, "chat_id": request["chat_id"],
                    "content": {"@type": "messageText",
                                "text": {"text": "reply"}},
                },
            }))
        elif td_type == "close":
            ok()
            auth("authorizationStateClosed")
        else:
            ok()

    def td_json_client_receive(self, client, timeout: float):
        try:
            raw = self.clients[client].get(timeout=min(timeout, 0.05))
        except queue.Empty:
            return None
        return raw.encode()

    def td_json_client_execute(self, client, data: bytes):
        request = json.loads(data.decode())
        if request["@type"] == "getTextEntities":
            return json.dumps({"@type": "textEntities", "entities": []}).encode()
        return json.dumps({"@type": "error", "code": 400, "message": "unsupported"}).encode()

    def td_json_client_destroy(self, client) -> None:
        self.destroyed = True
        self.clients.pop(client, None)


def _config(tmp_path) -> TelegramConfig:
    return TelegramConfig(
        api_id=12345,
        api_hash="test-hash",
        database_dir=tmp_path / "db",
        files_dir=tmp_path / "files",
    )


# ------------------------------------------------------------------- config


def test_config_from_env(tmp_path):
    env = {
        "TELEGRAM_API_ID": "999",
        "TELEGRAM_API_HASH": "abc",
        "TELEGRAM_PHONE": "+15551234567",
        "TELEGRAM_TEST_DC": "true",
    }
    cfg = TelegramConfig.from_env(env, data_dir=tmp_path)
    assert cfg.api_id == 999 and cfg.api_hash == "abc"
    assert cfg.use_test_dc is True
    assert cfg.database_dir == tmp_path / "tdlib-db"
    masked = cfg.masked()
    assert masked["api_hash"] == "***"
    assert "abc" not in str(masked)


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"TELEGRAM_API_ID": "1"},  # missing hash
        {"TELEGRAM_API_HASH": "x"},  # missing id
        {"TELEGRAM_API_ID": "notanint", "TELEGRAM_API_HASH": "x"},
        {"TELEGRAM_API_ID": "-1", "TELEGRAM_API_HASH": "x"},
    ],
)
def test_config_from_env_rejects_bad(env):
    with pytest.raises(TelegramConfigError):
        TelegramConfig.from_env(env)


# ------------------------------------------------------------ TdJson layer


def test_tdjson_load_failure():
    with pytest.raises(TdJsonLoadError):
        TdJson("/nonexistent/libtdjson.so")


def test_tdjson_calls_with_fake_lib(tmp_path):
    lib = FakeTdLib()
    td = TdJson(lib=lib)
    td.create()
    assert td.created
    td.send({"@type": "setTdlibParameters", "api_id": 12345, "@extra": "1"})
    assert lib.requests[0]["api_id"] == 12345
    msg = td.receive(timeout=0.5)
    assert msg["@type"] == "ok" and msg["@extra"] == "1"
    result = td.execute({"@type": "getTextEntities", "text": "hi"})
    assert result["@type"] == "textEntities"
    td.destroy()
    assert lib.destroyed


def test_tdjson_client_id_api_fallback():
    """Builds that only export the td_create_client_id API are supported."""

    class ClientIdLib(FakeTdLib):
        @property
        def td_json_client_create(self):
            raise AttributeError("not exported")

        def td_create_client_id(self):
            return FakeTdLib.td_json_client_create(self)

        def td_send(self, client_id, data):
            FakeTdLib.td_json_client_send(self, client_id, data)

        def td_receive(self, timeout):
            return FakeTdLib.td_json_client_receive(self, 1, timeout)

        def td_execute(self, data):
            return FakeTdLib.td_json_client_execute(self, 1, data)

    lib = ClientIdLib()
    td = TdJson(lib=lib)
    td.create()
    td.send({"@type": "getChats", "@extra": "5"})
    msg = td.receive(timeout=0.5)
    assert msg["chat_ids"] == [7, 8]
    td.destroy()


# --------------------------------------------------------- TdJsonClient flow


def test_tdjson_client_full_auth_flow(tmp_path):
    lib = FakeTdLib()

    async def run():
        client = TdJsonClient(_config(tmp_path), lib=lib)
        states: list[TelegramAuthState] = []
        client.on_auth_state(states.append)

        await client.start()
        assert TelegramAuthState.WAIT_PHONE in states or client.auth_state is TelegramAuthState.WAIT_PHONE

        await client.submit_phone("+15551234567")
        await asyncio.sleep(0.1)  # receive thread dispatches
        assert client.auth_state is TelegramAuthState.WAIT_CODE

        await client.submit_code("12345")
        await asyncio.sleep(0.1)
        assert client.auth_state is TelegramAuthState.READY

        chats = await client.get_chats()
        assert [c["title"] for c in chats] == ["Wallet (Telegram)", "TON Community"]

        updates = []
        client.on_update(updates.append)
        await client.send_message(7, "hello")
        await asyncio.sleep(0.2)
        assert any(u.type == "new_message" and u.data["text"] == "reply" for u in updates)

        await client.close()
        assert client.auth_state is TelegramAuthState.CLOSED
        assert lib.destroyed

    asyncio.run(run())


def test_tdjson_client_wrong_code(tmp_path):
    lib = FakeTdLib()

    async def run():
        client = TdJsonClient(_config(tmp_path), lib=lib)
        await client.start()
        await client.submit_phone("+15551234567")
        await asyncio.sleep(0.1)
        with pytest.raises(TelegramError, match="PHONE_CODE_INVALID"):
            await client.submit_code("99999")
        await client.close()

    asyncio.run(run())


def test_tdjson_client_2fa_path(tmp_path):
    lib = FakeTdLib()
    # make the code step land on waitPassword instead
    orig_send = lib.td_json_client_send

    def patched_send(client, data):
        request = json.loads(data.decode())
        if request["@type"] == "checkAuthenticationCode":
            extra = request.get("@extra")
            lib.clients[client].put(json.dumps({"@type": "ok", "@extra": extra}))
            lib.clients[client].put(json.dumps({
                "@type": "updateAuthorizationState",
                "authorization_state": {"@type": "authorizationStateWaitPassword"},
            }))
            return
        orig_send(client, data)

    lib.td_json_client_send = patched_send

    async def run():
        client = TdJsonClient(_config(tmp_path), lib=lib)
        await client.start()
        await client.submit_phone("+15551234567")
        await asyncio.sleep(0.1)
        await client.submit_code("12345")
        await asyncio.sleep(0.1)
        assert client.auth_state is TelegramAuthState.WAIT_PASSWORD
        with pytest.raises(TelegramError, match="PASSWORD_HASH_INVALID"):
            await client.submit_password("wrong")
        await client.submit_password("hunter2")
        await asyncio.sleep(0.1)
        assert client.auth_state is TelegramAuthState.READY
        await client.close()

    asyncio.run(run())


def test_tdjson_request_before_start_fails(tmp_path):
    async def run():
        client = TdJsonClient(_config(tmp_path), lib=FakeTdLib())
        with pytest.raises(TelegramError, match="not started"):
            await client.submit_phone("+15551234567")

    asyncio.run(run())


# --------------------------------------------------------- library resolver


def test_platform_library_names():
    from ton_wallet_assistant.telegram.loader import platform_library_name

    assert platform_library_name("darwin") == "libtdjson.dylib"
    assert platform_library_name("linux") == "libtdjson.so"
    assert platform_library_name("win32") == "tdjson.dll"
    assert platform_library_name("freebsd13") == "libtdjson.so"


def test_bundle_dirs_for_macos_app():
    from ton_wallet_assistant.telegram.loader import _bundle_dirs

    exe = Path("/Applications/TonWallet.app/Contents/MacOS/ton-wallet-assistant")
    dirs = _bundle_dirs(exe)
    assert Path("/Applications/TonWallet.app/Contents/Frameworks") in dirs
    assert Path("/Applications/TonWallet.app/Contents/Resources") in dirs
    assert Path("/Applications/TonWallet.app/Contents/MacOS") in dirs


def test_candidate_dirs_include_package_and_libs():
    from ton_wallet_assistant.telegram.loader import candidate_dirs

    dirs = candidate_dirs()
    package_dir = Path(ton_wallet_assistant.telegram.__file__).resolve().parent
    assert package_dir in dirs
    assert package_dir.parent / "lib" in dirs
    assert package_dir.parent / "libs" in dirs
    assert len(dirs) == len(set(dirs))  # no duplicates


def test_resolve_explicit_path_wins(tmp_path, monkeypatch):
    from ton_wallet_assistant.telegram.loader import resolve_tdjson_library

    explicit = tmp_path / "libtdjson.so"
    explicit.write_bytes(b"fake")
    env_lib = tmp_path / "other" / "libtdjson.so"
    env_lib.parent.mkdir()
    env_lib.write_bytes(b"fake")
    monkeypatch.setenv("TDLIB_PATH", str(env_lib))
    assert resolve_tdjson_library(explicit) == explicit
    # env fallback when no explicit path
    assert resolve_tdjson_library(None, env={"TDLIB_PATH": str(env_lib)}) == env_lib


def test_resolve_package_dir_fallback(tmp_path, monkeypatch):
    import ton_wallet_assistant.telegram as tg_pkg
    from ton_wallet_assistant.telegram import loader

    fake = tmp_path / "libtdjson.so"
    fake.write_bytes(b"fake")
    monkeypatch.delenv("TDLIB_PATH", raising=False)
    monkeypatch.setattr(loader, "candidate_dirs", lambda: [tmp_path])
    monkeypatch.setattr("sys.platform", "linux")
    assert loader.resolve_tdjson_library() == fake
    assert tg_pkg  # imported


def test_searched_paths_and_failure_diagnostics(tmp_path):
    from ton_wallet_assistant.telegram.loader import searched_paths

    paths = searched_paths(env={})
    assert "libtdjson.so" in paths  # bare loader fallback present
    assert any(p.endswith("libtdjson.so") for p in paths)

    # missing library → diagnostics list the searched paths
    try:
        TdJson(tmp_path / "definitely-missing-dir" / "libtdjson.so")
    except TdJsonLoadError as exc:
        text = str(exc)
        assert "Searched:" in text
        assert "libtdjson.so" in text
        assert str(tmp_path) in text
    else:
        pytest.fail("expected TdJsonLoadError")


# ------------------------------------------------- config-file resolution


def test_config_resolve_file_section(tmp_path):
    cfg = TelegramConfig.resolve(
        env={},
        file_config={"telegram": {"api_id": 555, "api_hash": "file-hash"}},
        data_dir=tmp_path,
    )
    assert cfg.api_id == 555 and cfg.api_hash == "file-hash"


def test_config_resolve_env_overrides_file(tmp_path):
    cfg = TelegramConfig.resolve(
        env={"TELEGRAM_API_ID": "777", "TELEGRAM_API_HASH": "env-hash"},
        file_config={"telegram": {"api_id": 555, "api_hash": "file-hash"}},
        data_dir=tmp_path,
    )
    assert cfg.api_id == 777 and cfg.api_hash == "env-hash"


def test_config_resolve_tdlib_path_and_test_dc(tmp_path):
    cfg = TelegramConfig.resolve(
        env={"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"},
        file_config={"telegram": {"tdlib_path": "/opt/td/libtdjson.so", "test_dc": True}},
        data_dir=tmp_path,
    )
    assert str(cfg.tdlib_path) == "/opt/td/libtdjson.so"
    assert cfg.use_test_dc is True


# --------------------------------------------------------------- demo client


def test_demo_client_auth_flow():
    async def run():
        client = DemoTelegramClient()
        await client.start()
        assert client.auth_state is TelegramAuthState.WAIT_PHONE

        with pytest.raises(TelegramError):
            await client.submit_phone("not a phone")
        await client.submit_phone("+15551234567")
        assert client.auth_state is TelegramAuthState.WAIT_CODE

        with pytest.raises(TelegramError):
            await client.submit_code("00000")
        await client.submit_code("12345")
        assert client.auth_state is TelegramAuthState.READY

        chats = await client.get_chats()
        assert len(chats) == 3 and all(c["demo"] for c in chats)

        updates = []
        client.on_update(updates.append)
        await client.send_message(1, "hi")
        assert any(u.data.get("text") == "hi" for u in updates)
        with pytest.raises(TelegramError):
            await client.send_message(999, "hi")

        await client.close()
        assert client.auth_state is TelegramAuthState.CLOSED
        with pytest.raises(TelegramError):
            await client.get_chats()

    asyncio.run(run())


def test_demo_client_2fa():
    async def run():
        client = DemoTelegramClient(demo_password="s3cret")
        await client.start()
        await client.submit_phone("+15551234567")
        await client.submit_code("12345")
        assert client.auth_state is TelegramAuthState.WAIT_PASSWORD
        with pytest.raises(TelegramError):
            await client.submit_password("wrong")
        await client.submit_password("s3cret")
        assert client.auth_state is TelegramAuthState.READY
        await client.close()

    asyncio.run(run())


# --------------------------------------------------------------- SDK wiring


def test_sdk_telegram_demo():
    async def run():
        sdk = await TonWalletSDK.demo()
        assert sdk.telegram_configured
        client = sdk.telegram
        assert isinstance(client, DemoTelegramClient)
        await client.start()
        await client.submit_phone("+15551234567")
        await client.submit_code("12345")
        assert client.is_ready
        assert sdk.telegram is client  # cached
        await sdk.close()
        assert client.auth_state is TelegramAuthState.CLOSED

    asyncio.run(run())


def test_sdk_telegram_real_requires_env(monkeypatch):
    sdk = TonWalletSDK(network="mainnet", demo=False)
    monkeypatch.delenv("TELEGRAM_API_ID", raising=False)
    monkeypatch.delenv("TELEGRAM_API_HASH", raising=False)
    assert not sdk.telegram_configured
    with pytest.raises(TelegramConfigError):
        _ = sdk.telegram


# ------------------------------------------------------------- pure python


def test_telegram_import_needs_no_qt_or_tdlib():
    """Importing the telegram package pulls in neither PySide6 nor a real
    libtdjson — and introduces no Cython/native wrapper layer."""
    code = (
        "import sys; import ton_wallet_assistant.telegram; "
        "from ton_wallet_assistant.sdk import TonWalletSDK; "
        "assert 'PySide6' not in sys.modules; "
        "assert all('tdjson' not in m or 'telegram.tdjson' in m for m in sys.modules); "
        "print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_no_native_wrapper_files_in_package():
    """Guard: the telegram layer must stay 100% Python — no .c/.pyx/.so
    committed under src/."""
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "ton_wallet_assistant"
    native = [p for p in src.rglob("*") if p.suffix in {".c", ".cpp", ".pyx", ".so", ".dll", ".dylib"}]
    assert native == [], f"native artifacts found: {native}"
