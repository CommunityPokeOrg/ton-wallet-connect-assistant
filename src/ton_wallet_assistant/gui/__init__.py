"""PySide6 desktop UI for the TON wallet."""

from __future__ import annotations

from ..config import AppConfig
from ..services.base import WalletService
from .async_loop import AsyncLoop
from .main_window import MainWindow


def run_app(config: AppConfig, connect_service: WalletService) -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from .theme import STYLESHEET

    app.setStyleSheet(STYLESHEET)
    window = MainWindow(config, connect_service)
    window.show()
    return app.exec()


__all__ = ["AsyncLoop", "MainWindow", "run_app"]
