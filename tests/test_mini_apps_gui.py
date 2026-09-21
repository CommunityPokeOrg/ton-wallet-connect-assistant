"""Bridge + tab tests — headless-safe (no QtWebEngine required)."""

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ton_wallet_assistant.gui.webapp_bridge import WebAppBridge


@pytest.fixture()
def app():
    yield QApplication.instance() or QApplication([])


def test_bridge_dispatches_send_data(app):
    bridge = WebAppBridge()
    got = []
    bridge.send_data_received.connect(got.append)
    bridge.postEvent("web_app_data", json.dumps({"data": "hello-bot"}))
    assert got == ["hello-bot"]
    assert bridge.runtime.is_ready is False


def test_bridge_routes_tonconnect_data_to_approval_signal(app):
    bridge = WebAppBridge()
    tc, plain = [], []
    bridge.tonconnect_requested.connect(tc.append)
    bridge.send_data_received.connect(plain.append)
    bridge.postEvent("web_app_data", json.dumps({"data": "tc://?v=2&id=x"}))
    bridge.sendData("ton://transfer/EQabc?amount=1")
    assert len(tc) == 2 and plain == []


def test_bridge_rejects_unknown_events(app):
    bridge = WebAppBridge()
    events = []
    bridge.webapp_event.connect(lambda e, p: events.append(e))
    bridge.postEvent("exec_javascript", "{}")
    bridge.postEvent("web_app_ready", "{}")
    assert events == ["invalid_event", "web_app_ready"]
    assert bridge.runtime.is_ready


def test_bridge_main_button_and_back_button_signals(app):
    bridge = WebAppBridge()
    main, back = [], []
    bridge.main_button_changed.connect(main.append)
    bridge.back_button_changed.connect(back.append)
    bridge.postEvent(
        "main_button_update",
        json.dumps({"text": "Pay 2 TON", "is_visible": True, "is_active": True}),
    )
    bridge.postEvent("back_button_update", json.dumps({"is_visible": True}))
    assert main[-1]["text"] == "Pay 2 TON" and main[-1]["is_visible"]
    assert back[-1]["is_visible"]


def test_bridge_cloud_storage_roundtrip_via_rpc(app):
    bridge = WebAppBridge()
    responses = []
    bridge.respond.connect(lambda req, ok, val: responses.append((req, ok, val)))
    bridge.postEvent("cloud_storage",
                     json.dumps({"req_id": 1, "method": "set", "key": "a", "value": "1"}))
    bridge.postEvent("cloud_storage",
                     json.dumps({"req_id": 2, "method": "get", "key": "a"}))
    assert responses == [(1, True, True), (2, True, "1")]


def test_bridge_popups_delegated(app):
    bridge = WebAppBridge()
    popup = []
    bridge.popup_requested.connect(lambda e, r, p: popup.append((e, r, p)))
    bridge.postEvent("show_confirm", json.dumps({"req_id": 7, "message": "ok?"}))
    assert popup == [("show_confirm", 7, {"req_id": 7, "message": "ok?"})]


def test_mini_apps_tab_constructs_headless(app, tmp_path, monkeypatch):
    """Tab builds without QtWebEngine: fallback panel, parse + demo resolve,
    approval forwarding — all still work."""
    import os

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from ton_wallet_assistant.gui.async_loop import AsyncLoop
    from ton_wallet_assistant.gui.mini_apps_tab import MiniAppsTab, webengine_supported
    from ton_wallet_assistant.services.demo import DemoWalletService
    from ton_wallet_assistant.session import WalletSession
    from ton_wallet_assistant.wallet.account import WalletAccount
    from ton_wallet_assistant.wallet.demo import DemoChainClient

    assert not webengine_supported()

    loop = AsyncLoop()
    try:
        forwarded = []
        account = WalletAccount(
            raw_address="0:" + "0" * 64,
            friendly_bounceable="EQ" + "A" * 44 + "=",
            friendly_non_bounceable="UQ" + "A" * 44 + "=",
            public_key_hex="0" * 64,
            wallet_version="v4r2",
            network="testnet",
        )
        session = WalletSession(
            account=account,
            chain=DemoChainClient("testnet"),
            keystore=None,
            demo=True,
            connect_service=DemoWalletService(),
        )
        tab = MiniAppsTab(session, loop, submit_link=lambda p, o: forwarded.append((p, o)))
        assert tab.web_view is None

        # valid t.me link parses and demo-resolves without network
        tab.url_edit.setText(
            "https://t.me/wallet/start?startapp=tonconnect-v__2-id__abc"
        )
        tab._load_clicked()
        assert "wallet" in tab.context_label.text()
        assert tab._resolution is not None
        assert tab._resolution.authenticated is False
        # demo mode resolves to the bundled loopback harness, never t.me
        assert tab._resolution.url.startswith("http://127.0.0.1:")
        assert "t.me" not in tab._resolution.url.split("?")[0]

        # direct URLs in demo mode also land on the local harness
        tab.url_edit.setText("https://app.ston.fi")
        tab._load_clicked()
        assert tab._resolution.url.startswith("http://127.0.0.1:")
        assert "src=https%3A%2F%2Fapp.ston.fi" in tab._resolution.url

        # a failed load surfaces a diagnostics panel, not a silent blank page
        tab._on_load_finished(False)
        assert tab.stack.currentWidget() is tab.error_panel
        assert "failed" in tab.error_title.text().lower()
        assert tab.error_detail.text()

        # invalid URL is refused
        tab.url_edit.setText("javascript:alert(1)")
        tab._load_clicked()
        assert "Invalid URL" in tab.status_label.text()

        # webview-originated tc:// payload routes to the approval channel
        tab.bridge.postEvent("web_app_data", json.dumps({"data": "tc://?v=2&id=x"}))
        assert forwarded and forwarded[-1][0].startswith("tc://")

        # refused main-frame navigations are recorded for diagnostics
        tab.bridge.webapp_event.emit("navigation_blocked", "telegram: tg://resolve?domain=wallet")
        assert tab._last_blocked_nav.startswith("telegram:")
        assert "Blocked navigation" in tab.status_label.text()
        tab.shutdown()
    finally:
        loop.stop()
