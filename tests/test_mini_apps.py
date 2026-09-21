from urllib.request import urlopen

import pytest

from ton_wallet_assistant.telegram.mini_apps import TelegramMiniAppBridge, TelegramWebAppShim


def test_tma_url_and_validation():
    assert TelegramMiniAppBridge.build_tma_url("@wallet", "a b") == "https://t.me/wallet?startapp=a%20b"
    with pytest.raises(ValueError):
        TelegramMiniAppBridge.build_tma_url("wallet/bad")
    with pytest.raises(ValueError):
        TelegramMiniAppBridge().launch("javascript:alert(1)")


def test_sdk_shim_events():
    events = []
    shim = TelegramWebAppShim("query_id=1")
    shim.onEvent("ready", lambda: events.append("ready"))
    shim.ready()
    assert events == ["ready"]
    assert shim.initData == "query_id=1"


def test_callback_server():
    received = []
    bridge = TelegramMiniAppBridge(received.append)
    endpoint = bridge.start_callback_server()
    try:
        with urlopen(endpoint + "?tonconnect=tc%3A%2F%2Frequest", timeout=2) as response:
            assert response.status == 200
        assert received == ["tc://request"]
    finally:
        bridge.close()
