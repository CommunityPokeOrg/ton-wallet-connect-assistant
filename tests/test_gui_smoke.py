"""Headless smoke test: onboarding -> demo session -> wallet & connect tabs."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QTabWidget

from ton_wallet_assistant.config import AppConfig
from ton_wallet_assistant.gui import MainWindow
from ton_wallet_assistant.services.demo import DemoWalletService


def _pump_until(predicate, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture()
def app():
    yield QApplication.instance() or QApplication([])


def test_demo_mode_full_flow(app):
    config = AppConfig.resolve(demo=True, env={}, file_config={})
    window = MainWindow(config, DemoWalletService(connect_delay=0.05))
    window.show()
    try:
        # Demo session builds asynchronously on the io loop.
        assert _pump_until(lambda: isinstance(window.centralWidget(), QTabWidget))
        wallet_tab = window.wallet_tab
        connect_tab = window.connect_tab

        # Wallet tab shows a demo account, balance and demo history.
        assert "DEMO" in window.windowTitle()
        assert _pump_until(lambda: wallet_tab.balance_label.text().endswith("TON"))
        assert wallet_tab.balance_label.text().startswith("42")
        assert _pump_until(lambda: wallet_tab.history_list.count() == 8)
        assert wallet_tab.assets_list.count() == 3  # TON + 2 demo jettons

        # TonConnect tab demo flow still works.
        assert _pump_until(lambda: connect_tab.wallet_list.count() == 1)
        connect_tab.wallet_list.setCurrentRow(0)
        connect_tab._connect_clicked()
        assert _pump_until(lambda: connect_tab.link_edit.text().startswith("demo://"))
        assert _pump_until(lambda: connect_tab._account is not None)
        assert connect_tab.status_label.text().startswith("Connected")
        connect_tab._disconnect_clicked()
        assert _pump_until(lambda: connect_tab._account is None)

        # Demo send: form -> confirm dialog -> fake broadcast.
        # (Dialogs are modal; drive the internals the same way the buttons do.)
        wallet_tab._do_send([], "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ", 1_000_000_000, "test")
        assert _pump_until(lambda: wallet_tab.history_list.count() == 9)
        assert "Transaction sent" in wallet_tab.status_label.text()
        assert "[pending]" in wallet_tab.history_list.item(0).text()
    finally:
        window.close()
        window.async_loop.stop()


def test_onboarding_shown_when_no_keystore(app, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from ton_wallet_assistant import config as cfg

    monkeypatch.setattr(cfg, "config_dir", lambda: tmp_path / "cfg")
    config = AppConfig.resolve(manifest_url="https://example.com/m.json", demo=False, env={}, file_config={})
    window = MainWindow(config, DemoWalletService(connect_delay=0.05))
    window.show()
    try:
        # No keystore -> onboarding welcome page visible.
        assert not isinstance(window.centralWidget(), QTabWidget)
        assert window.onboarding.stack.currentIndex() == window.onboarding.PAGE_WELCOME
        # Generate -> backup page shows 24 words.
        window.onboarding._start_create()
        assert window.onboarding.stack.currentIndex() == window.onboarding.PAGE_BACKUP
        assert window.onboarding._backup_grid.count() == 24
    finally:
        window.close()
        window.async_loop.stop()
