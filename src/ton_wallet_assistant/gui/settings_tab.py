"""Settings tab — wallet info, security actions, app configuration."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..session import WalletSession
from ..wallet.keystore import WrongPasswordError
from .async_loop import AsyncLoop
from .dialogs import PasswordDialog, SeedRevealDialog, confirm, show_error, show_info


class SettingsTab(QWidget):
    def __init__(
        self,
        config: AppConfig,
        session: WalletSession,
        async_loop: AsyncLoop,
        on_wallet_deleted,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.session = session
        self.async_loop = async_loop
        self._on_wallet_deleted = on_wallet_deleted
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        account_box = QGroupBox("Wallet")
        form = QFormLayout(account_box)
        acc = self.session.account
        form.addRow("Address", self._ro(acc.friendly_bounceable))
        form.addRow("Wallet version", QLabel(acc.wallet_version))
        form.addRow("Network", QLabel(acc.network))
        mode = "DEMO (in-memory, nothing persisted)" if self.session.demo else "Real (encrypted keystore)"
        form.addRow("Mode", QLabel(mode))
        outer.addWidget(account_box)

        security = QGroupBox("Security")
        sec = QVBoxLayout(security)
        self.lock_state = QLabel(self._lock_text())
        sec.addWidget(self.lock_state)
        row = QHBoxLayout()
        self.lock_button = QPushButton("Lock now")
        self.lock_button.clicked.connect(self._lock_now)
        self.reveal_button = QPushButton("Reveal recovery phrase")
        self.reveal_button.clicked.connect(self._reveal)
        row.addWidget(self.lock_button)
        row.addWidget(self.reveal_button)
        sec.addLayout(row)
        if self.session.demo:
            for b in (self.lock_button, self.reveal_button):
                b.setEnabled(False)
            sec.addWidget(QLabel("Demo session: no keystore exists — nothing to lock or reveal."))
        outer.addWidget(security)

        app_box = QGroupBox("TonConnect / app")
        app_form = QFormLayout(app_box)
        app_form.addRow("Manifest URL", self._ro(self.config.manifest_url or "(not set — connect tab runs in demo)"))
        app_form.addRow("Config file", self._ro(str(self.config.config_path)))
        ks_path = str(self.session.keystore.path) if self.session.keystore else "(none — demo)"
        app_form.addRow("Keystore file", self._ro(ks_path))
        outer.addWidget(app_box)

        danger = QGroupBox("Danger zone")
        d = QVBoxLayout(danger)
        del_btn = QPushButton("Delete wallet from this device")
        del_btn.setStyleSheet("color:#e74c3c;")
        del_btn.clicked.connect(self._delete_wallet)
        d.addWidget(del_btn)
        outer.addWidget(danger)
        outer.addStretch(1)

    def _ro(self, text: str) -> QLineEdit:
        e = QLineEdit(text)
        e.setReadOnly(True)
        return e

    def _lock_text(self) -> str:
        if self.session.keystore is None:
            return "Demo session — no keystore"
        return "Unlocked" if self.session.keystore.is_unlocked else "Locked"

    def _refresh_lock_state(self) -> None:
        self.lock_state.setText(self._lock_text())

    def _lock_now(self) -> None:
        if self.session.keystore:
            self.session.keystore.lock()
            self._refresh_lock_state()
            show_info(self, "Locked", "The wallet is locked. Your password is required to send or reveal the phrase.")

    def _reveal(self) -> None:
        if self.session.keystore is None:
            return
        dlg = PasswordDialog(self, "Enter your password to reveal the recovery phrase")
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        try:
            words = self.session.keystore.unlock(dlg.password)
        except WrongPasswordError:
            show_error(self, "Wrong password", "Could not unlock the keystore.")
            return
        SeedRevealDialog(self, words).exec()

    def _delete_wallet(self) -> None:
        if self.session.keystore is None or not self.session.keystore.exists:
            show_info(self, "Nothing to delete", "Demo session — no keystore on disk.")
            return
        if not confirm(
            self,
            "Delete wallet?",
            "This permanently deletes the encrypted keystore from this device.\n"
            "Without your recovery phrase the wallet cannot be restored. Continue?",
        ):
            return
        dlg = PasswordDialog(self, "Confirm your password to delete the wallet")
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        try:
            self.session.keystore.unlock(dlg.password)
        except WrongPasswordError:
            show_error(self, "Wrong password", "Could not unlock the keystore.")
            return
        self.session.keystore.delete()
        self._on_wallet_deleted()
