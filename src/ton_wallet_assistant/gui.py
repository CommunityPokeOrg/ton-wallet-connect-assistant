"""PySide6 desktop UI for the TON Wallet Connect Assistant."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig
from .models import ConnectedAccount, ConnectionState, ServiceEvent, WalletOption
from .qr import qr_png_bytes
from .services.base import WalletService

_STATE_COLORS = {
    ConnectionState.DISCONNECTED: "#9e9e9e",
    ConnectionState.AWAITING_CONFIRMATION: "#f0a020",
    ConnectionState.CONNECTED: "#2ecc71",
    ConnectionState.ERROR: "#e74c3c",
}

_STATE_TEXT = {
    ConnectionState.DISCONNECTED: "Not connected",
    ConnectionState.AWAITING_CONFIRMATION: "Waiting for wallet approval…",
    ConnectionState.CONNECTED: "Connected",
    ConnectionState.ERROR: "Error",
}


class AsyncLoop(QObject):
    """Owns a dedicated asyncio loop on a daemon thread.

    Wallet I/O (SSE bridge listening, HTTP fetches) is async; Qt is not. This
    bridge lets the GUI submit coroutines and receive results without blocking
    the UI thread.
    """

    invoke_in_gui = Signal(object)  # callable -> executed on the GUI thread

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.invoke_in_gui.connect(self._run_callable)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_runner, name="wallet-io", daemon=True)
        self._thread.start()

    def _loop_runner(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_callable(self, fn: Callable) -> None:
        fn()

    def post_to_gui(self, fn: Callable) -> None:
        self.invoke_in_gui.emit(fn)

    def submit(self, coro, on_done: Callable | None = None) -> Future:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done(f: Future) -> None:
            def deliver() -> None:
                try:
                    result = f.result()
                except asyncio.CancelledError:
                    return
                except Exception as exc:  # surfaced to the UI as an error event
                    if on_done:
                        on_done(None, exc)
                    return
                if on_done:
                    on_done(result, None)

            self.post_to_gui(deliver)

        if on_done:
            future.add_done_callback(_done)
        return future

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)


class MainWindow(QMainWindow):
    event_received = Signal(object)  # ServiceEvent

    def __init__(self, config: AppConfig, service: WalletService, loop: AsyncLoop | None = None) -> None:
        super().__init__()
        self.config = config
        self.service = service
        self.async_loop = loop or AsyncLoop(self)
        self.service.set_event_callback(self._on_service_event)
        self.event_received.connect(self._handle_service_event)

        self._wallets: list[WalletOption] = []
        self._current_link = ""
        self._account: ConnectedAccount | None = None

        self.setWindowTitle("TON Wallet Connect Assistant")
        self.resize(760, 640)
        self._build_ui()
        self._set_state(ConnectionState.DISCONNECTED)
        self._refresh_wallets()
        self.async_loop.submit(self.service.restore(), self._on_restored)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        root = QWidget(self)
        outer = QVBoxLayout(root)

        header = QHBoxLayout()
        title = QLabel("<b>TON Wallet Connect Assistant</b>")
        title.setStyleSheet("font-size: 16px;")
        header.addWidget(title)
        header.addStretch(1)
        self.mode_badge = QLabel("DEMO MODE" if self.config.demo_mode else "LIVE")
        self.mode_badge.setStyleSheet(
            "padding: 2px 8px; border-radius: 8px; font-weight: bold; "
            + ("background:#f0a020; color:#202020;" if self.config.demo_mode else "background:#2ecc71; color:#202020;")
        )
        header.addWidget(self.mode_badge)
        outer.addLayout(header)

        if self.config.demo_mode:
            banner = QLabel(
                "Demo mode — no real wallet connection is made. "
                "Set TON_WALLET_ASSISTANT_MANIFEST_URL (see README) to connect a real wallet."
            )
            banner.setWordWrap(True)
            banner.setStyleSheet("background:#3a3320; color:#f0d080; padding:6px; border-radius:4px;")
            outer.addWidget(banner)

        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("font-size:18px;")
        self.status_label = QLabel("")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        outer.addLayout(status_row)

        middle = QHBoxLayout()

        wallets_box = QGroupBox("1 · Choose a wallet")
        wallets_layout = QVBoxLayout(wallets_box)
        self.wallet_list = QListWidget()
        self.wallet_list.currentRowChanged.connect(self._on_wallet_selected)
        wallets_layout.addWidget(self.wallet_list)
        wallet_buttons = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._refresh_wallets)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._connect_clicked)
        wallet_buttons.addWidget(self.refresh_button)
        wallet_buttons.addWidget(self.connect_button)
        wallets_layout.addLayout(wallet_buttons)
        middle.addWidget(wallets_box, 1)

        link_box = QGroupBox("2 · Approve in the wallet app")
        link_layout = QVBoxLayout(link_box)
        self.qr_label = QLabel("Connect link QR appears here")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(220, 220)
        self.qr_label.setStyleSheet("border:1px dashed #888; color:#888;")
        link_layout.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        link_row = QHBoxLayout()
        self.link_edit = QLineEdit()
        self.link_edit.setReadOnly(True)
        self.link_edit.setPlaceholderText("Universal connect link")
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self._copy_link)
        link_row.addWidget(self.link_edit, 1)
        link_row.addWidget(self.copy_button)
        link_layout.addLayout(link_row)
        self.open_button = QPushButton("Open in wallet / Telegram")
        self.open_button.clicked.connect(self._open_link)
        link_layout.addWidget(self.open_button)
        middle.addWidget(link_box, 1)

        outer.addLayout(middle, 1)

        self.account_box = QGroupBox("Connected wallet")
        form = QFormLayout(self.account_box)
        self.addr_friendly = self._copyable_row(form, "Address")
        self.addr_raw = self._copyable_row(form, "Raw form")
        self.network_label = QLabel("—")
        form.addRow("Network", self.network_label)
        self.wallet_app_label = QLabel("—")
        form.addRow("Wallet app", self.wallet_app_label)
        self.disconnect_button = QPushButton("Disconnect")
        self.disconnect_button.clicked.connect(self._disconnect_clicked)
        form.addRow("", self.disconnect_button)
        outer.addWidget(self.account_box)

        outer.addWidget(QLabel("Log"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setFixedHeight(110)
        outer.addWidget(self.log_view)

        self.setCentralWidget(root)

    def _copyable_row(self, form: QFormLayout, label: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setReadOnly(True)
        btn = QPushButton("Copy")
        btn.setFixedWidth(60)
        btn.clicked.connect(lambda _=None, e=edit: self._copy_text(e.text()))
        row.addWidget(edit, 1)
        row.addWidget(btn)
        form.addRow(label, row)
        return edit

    # ------------------------------------------------------------- actions

    def _on_service_event(self, event: ServiceEvent) -> None:
        # Called from the asyncio thread — marshal to the GUI thread.
        self.event_received.emit(event)

    def _handle_service_event(self, event: ServiceEvent) -> None:
        if event.state == ConnectionState.CONNECTED and event.account:
            self._account = event.account
            self._show_account(event.account)
            self._set_state(ConnectionState.CONNECTED)
            self._log(f"Connected to {event.wallet_name or event.account.wallet_app or 'wallet'}")
        elif event.state == ConnectionState.DISCONNECTED:
            self._account = None
            self._show_account(None)
            self._set_state(ConnectionState.DISCONNECTED)
            self._log("Disconnected")
        elif event.state == ConnectionState.ERROR:
            self._set_state(ConnectionState.ERROR, event.error)
            self._log(f"Error: {event.error}")

    def _refresh_wallets(self) -> None:
        self.refresh_button.setEnabled(False)
        self.wallet_list.clear()
        self._log("Fetching wallet list…")
        self.async_loop.submit(self.service.list_wallets(), self._on_wallets_loaded)

    def _on_wallets_loaded(self, result, error) -> None:
        self.refresh_button.setEnabled(True)
        if error:
            self._set_state(ConnectionState.ERROR, f"Could not load wallets: {error}")
            self._log(f"Wallet list failed: {error}")
            return
        self._wallets = result or []
        for w in self._wallets:
            item = QListWidgetItem(f"{w.name}\n{w.about_url or w.universal_url}")
            item.setData(Qt.ItemDataRole.UserRole, w)
            self.wallet_list.addItem(item)
        if self._wallets:
            self.wallet_list.setCurrentRow(0)
        self._log(f"{len(self._wallets)} wallet(s) available")

    def _on_wallet_selected(self, _row: int) -> None:
        self._update_connect_button()

    def _update_connect_button(self) -> None:
        self.connect_button.setEnabled(self.wallet_list.currentRow() >= 0)

    def _connect_clicked(self) -> None:
        item = self.wallet_list.currentItem()
        if item is None:
            return
        wallet: WalletOption = item.data(Qt.ItemDataRole.UserRole)
        self._set_state(ConnectionState.AWAITING_CONFIRMATION)
        self._log(f"Requesting connection via {wallet.name}…")
        self.async_loop.submit(self.service.connect(wallet), self._on_link_ready)

    def _on_link_ready(self, result, error) -> None:
        if error:
            self._set_state(ConnectionState.ERROR, f"Could not create connect link: {error}")
            self._log(f"Connect failed: {error}")
            return
        self._current_link = result or ""
        self.link_edit.setText(self._current_link)
        try:
            pixmap = QPixmap()
            pixmap.loadFromData(qr_png_bytes(self._current_link))
            self.qr_label.setPixmap(
                pixmap.scaled(220, 220, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            self.qr_label.setStyleSheet("border:1px solid #555;")
        except Exception as exc:
            self.qr_label.setText("QR generation failed")
            self._log(f"QR generation failed: {exc}")
        self._log("Scan the QR or open the link in your wallet to approve")

    def _on_restored(self, result, error) -> None:
        if result:
            self._log("Restored previous wallet session")

    def _copy_link(self) -> None:
        self._copy_text(self._current_link)

    def _copy_text(self, text: str) -> None:
        if text:
            QGuiApplication.clipboard().setText(text)
            self._log("Copied to clipboard")

    def _open_link(self) -> None:
        if self._current_link:
            QDesktopServices.openUrl(QUrl(self._current_link))
            self._log("Opened link with the system handler")

    def _disconnect_clicked(self) -> None:
        self.async_loop.submit(self.service.disconnect())
        self._current_link = ""
        self.link_edit.clear()
        self.qr_label.setPixmap(QPixmap())
        self.qr_label.setText("Connect link QR appears here")
        self.qr_label.setStyleSheet("border:1px dashed #888; color:#888;")

    # -------------------------------------------------------------- helpers

    def _show_account(self, account: ConnectedAccount | None) -> None:
        if account is None:
            self.addr_friendly.clear()
            self.addr_raw.clear()
            self.network_label.setText("—")
            self.wallet_app_label.setText("—")
            self.disconnect_button.setEnabled(False)
            return
        self.addr_friendly.setText(account.friendly_bounceable)
        self.addr_raw.setText(account.raw_address)
        self.network_label.setText(
            f"{account.network} (workchain {account.workchain})"
            if account.network != "unknown"
            else f"unknown (workchain {account.workchain})"
        )
        self.wallet_app_label.setText(account.wallet_app or "—")
        self.disconnect_button.setEnabled(True)

    def _set_state(self, state: ConnectionState, detail: str = "") -> None:
        self.status_dot.setStyleSheet(f"font-size:18px; color:{_STATE_COLORS[state]};")
        self.status_label.setText(f"{_STATE_TEXT[state]}{(' — ' + detail) if detail else ''}")

    def _log(self, message: str) -> None:
        from datetime import datetime

        self.log_view.appendPlainText(f"[{datetime.now():%H:%M:%S}] {message}")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            self.async_loop.submit(self.service.close())
        finally:
            self.async_loop.stop()
        super().closeEvent(event)


def run_app(config: AppConfig, service: WalletService) -> int:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config, service)
    window.show()
    return app.exec()
