"""Headless smoke test: builds the main window and runs the demo flow."""

import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from ton_wallet_assistant.config import AppConfig
from ton_wallet_assistant.gui import AsyncLoop, MainWindow
from ton_wallet_assistant.services.demo import DemoWalletService


def _pump_until(predicate, timeout: float = 10.0) -> bool:
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


def test_demo_flow_end_to_end(app):
    config = AppConfig.resolve(demo=True, env={}, file_config={})
    service = DemoWalletService(connect_delay=0.05)
    loop = AsyncLoop()
    try:
        window = MainWindow(config, service, loop)
        window.show()

        assert window.mode_badge.text() == "DEMO MODE"
        assert _pump_until(lambda: window.wallet_list.count() == 1)
        window.wallet_list.setCurrentRow(0)

        window._connect_clicked()
        assert _pump_until(lambda: bool(window.link_edit.text()))
        link = window.link_edit.text()
        assert link.startswith("demo://")

        assert _pump_until(lambda: window._account is not None)
        assert window.status_label.text().startswith("Connected")
        assert window.addr_friendly.text()
        assert "testnet" not in window.network_label.text()  # default demo network

        window._disconnect_clicked()
        assert _pump_until(lambda: window._account is None)
        assert window.status_label.text().startswith("Not connected")
    finally:
        loop.stop()
