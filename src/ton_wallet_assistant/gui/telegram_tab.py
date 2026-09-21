"""Telegram tab — TDLib auth flow + update feed.

Demo mode uses the offline DemoTelegramClient (login code 12345).
Real mode builds a TdJsonClient from TELEGRAM_API_ID / TELEGRAM_API_HASH
(+ optional TDLIB_PATH); the pure-Python ctypes layer loads libtdjson at
runtime — no Cython or C extensions are involved.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..session import WalletSession
from ..telegram import TelegramAuthState, TelegramConfig, TelegramConfigError, TelegramError
from .async_loop import AsyncLoop
from .dialogs import show_error


class TelegramTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop) -> None:
        super().__init__()
        self.session = session
        self.async_loop = async_loop
        self.client = None
        self._poll_updates_running = False
        self._chats_loaded = False

        layout = QVBoxLayout(self)

        if session.demo:
            flag = QLabel(
                "DEMO MODE — the Telegram client is a fully offline simulation. "
                "Use code 12345 to sign in."
            )
            flag.setStyleSheet("color:#f0a020; font-weight:bold;")
            flag.setWordWrap(True)
            layout.addWidget(flag)

        self.status_label = QLabel("Not started")
        layout.addWidget(self.status_label)

        # ---- auth form -------------------------------------------------
        auth_box = QGroupBox("Sign in to Telegram")
        auth = QFormLayout(auth_box)
        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("+15551234567")
        auth.addRow("Phone", self.phone_edit)
        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("Login code")
        auth.addRow("Code", self.code_edit)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("2FA password (if enabled)")
        auth.addRow("Password", self.password_edit)
        layout.addWidget(auth_box)

        btns = QHBoxLayout()
        self.start_btn = QPushButton("Connect Telegram")
        self.start_btn.clicked.connect(self._start)
        btns.addWidget(self.start_btn)
        self.submit_btn = QPushButton("Submit")
        self.submit_btn.clicked.connect(self._submit)
        self.submit_btn.setEnabled(False)
        btns.addWidget(self.submit_btn)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self._disconnect)
        self.disconnect_btn.setEnabled(False)
        btns.addWidget(self.disconnect_btn)
        layout.addLayout(btns)

        # ---- chats + updates -------------------------------------------
        self.chats_list = QListWidget()
        layout.addWidget(QLabel("Chats"))
        layout.addWidget(self.chats_list, 1)

        layout.addWidget(QLabel("Updates"))
        self.updates_list = QListWidget()
        layout.addWidget(self.updates_list, 1)

        if not session.demo:
            creds_hint = QLabel(
                "Set TELEGRAM_API_ID and TELEGRAM_API_HASH (https://my.telegram.org), "
                "and TDLIB_PATH if libtdjson is not on the loader path."
            )
            creds_hint.setWordWrap(True)
            creds_hint.setStyleSheet("color:#9AA6B2;")
            layout.addWidget(creds_hint)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1500)
        self._poll_timer.timeout.connect(self._refresh_status)

    # ------------------------------------------------------------- actions

    def _start(self) -> None:
        if self.client is not None:
            return
        if self.session.demo:
            from ..telegram import DemoTelegramClient

            self.client = DemoTelegramClient()
        else:
            try:
                config = TelegramConfig.resolve()
            except TelegramConfigError as exc:
                show_error(self, "Telegram not configured", str(exc))
                return
            try:
                from ..telegram import TdJsonClient

                self.client = TdJsonClient(config)
            except TelegramError as exc:
                show_error(self, "TDLib unavailable", str(exc))
                return
        self.async_loop.submit(self.client.start(), self._on_started)
        self.status_label.setText("Initializing…")
        self.start_btn.setEnabled(False)

    def _on_started(self, _state, error) -> None:
        if error:
            self.start_btn.setEnabled(True)
            self.status_label.setText("Failed to start")
            show_error(self, "Telegram error", str(error))
            self.client = None
            return
        self._poll_timer.start()
        self._drain_updates()
        self._refresh_status()

    def _submit(self) -> None:
        if self.client is None:
            return
        state = self.client.auth_state
        if state is TelegramAuthState.WAIT_PHONE:
            phone = self.phone_edit.text().strip()
            self.async_loop.submit(self.client.submit_phone(phone), self._on_step)
        elif state is TelegramAuthState.WAIT_CODE:
            self.async_loop.submit(self.client.submit_code(self.code_edit.text().strip()), self._on_step)
        elif state is TelegramAuthState.WAIT_PASSWORD:
            self.async_loop.submit(
                self.client.submit_password(self.password_edit.text()), self._on_step
            )

    def _on_step(self, _state, error) -> None:
        if error:
            show_error(self, "Telegram", str(error))
        self._refresh_status()

    def _disconnect(self) -> None:
        if self.client is None:
            return
        self.async_loop.submit(self.client.close(), self._on_disconnected)

    def _on_disconnected(self, _result, error) -> None:
        self.client = None
        self._chats_loaded = False
        self._poll_updates_running = False
        self._poll_timer.stop()
        self.start_btn.setEnabled(True)
        self.submit_btn.setEnabled(False)
        self.disconnect_btn.setEnabled(False)
        self.status_label.setText("Not started")
        self.chats_list.clear()

    # ------------------------------------------------------------- display

    def _refresh_status(self) -> None:
        if self.client is None:
            return
        state = self.client.auth_state
        self.status_label.setText(f"Auth state: {state.value}")
        self.submit_btn.setEnabled(
            state in (TelegramAuthState.WAIT_PHONE, TelegramAuthState.WAIT_CODE, TelegramAuthState.WAIT_PASSWORD)
        )
        self.disconnect_btn.setEnabled(state is TelegramAuthState.READY)
        if state is TelegramAuthState.READY and not self._chats_loaded:
            self._chats_loaded = True
            self.async_loop.submit(self.client.get_chats(), self._on_chats)

    def _on_chats(self, chats, error) -> None:
        if error or chats is None:
            return
        self.chats_list.clear()
        for chat in chats:
            self.chats_list.addItem(chat.get("title") or str(chat.get("id")))

    def _drain_updates(self) -> None:
        if self.client is None or self._poll_updates_running:
            return
        self._poll_updates_running = True

        async def pump():
            async for update in self.client.updates():
                self.async_loop.post_to_gui(lambda u=update: self._apply_update(u))

        self.async_loop.submit(pump())

    def _apply_update(self, update) -> None:
        text = update.type
        if update.type == "new_message":
            text = f"message in chat {update.data.get('chat_id')}: {update.data.get('text', '')[:80]}"
        self.updates_list.insertItem(0, text)
        self._refresh_status()

    def shutdown(self) -> None:
        self._poll_timer.stop()
        if self.client is not None:
            self.async_loop.submit(self.client.close())
