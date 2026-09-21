"""Modal dialogs: password prompts, send confirmation, receive, seed reveal."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..qr import qr_png_bytes


class PasswordDialog(QDialog):
    """Modal password prompt used before any sensitive action."""

    def __init__(self, parent: QWidget | None = None, reason: str = "Enter your password to continue") -> None:
        super().__init__(parent)
        self.setWindowTitle("Unlock wallet")
        self.setModal(True)
        self.password = ""
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(reason))
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.returnPressed.connect(self.accept)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.password = self.edit.text()
        super().accept()


class ConfirmSendDialog(QDialog):
    """Summarizes an outgoing transfer and collects the wallet password."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        destination: str,
        amount_text: str,
        comment: str,
        demo: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm transfer")
        self.setModal(True)
        self.password = ""
        layout = QVBoxLayout(self)

        if demo:
            flag = QLabel("DEMO MODE — nothing will be sent on-chain.")
            flag.setStyleSheet("color:#f0a020; font-weight:bold;")
            layout.addWidget(flag)

        summary = QFormLayout()
        to_label = QLabel(destination)
        to_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        to_label.setWordWrap(True)
        summary.addRow("To", to_label)
        summary.addRow("Amount", QLabel(f"{amount_text} TON"))
        if comment:
            summary.addRow("Comment", QLabel(comment))
        summary.addRow("Est. fee", QLabel("≤ 0.02 TON" if not demo else "0 TON (demo)"))
        layout.addLayout(summary)

        layout.addWidget(QLabel("Wallet password to sign:"))
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        if demo:
            self.password_edit.setPlaceholderText("(not needed in demo)")
            self.password_edit.setEnabled(False)
        layout.addWidget(self.password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sign & send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.password = self.password_edit.text()
        super().accept()


class ReceiveDialog(QDialog):
    """Shows the wallet address as text + QR for receiving funds."""

    def __init__(self, parent: QWidget | None, address: str, ton_link: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Receive TON")
        self.setModal(True)
        layout = QVBoxLayout(self)

        qr = QLabel()
        pixmap = QPixmap()
        pixmap.loadFromData(qr_png_bytes(ton_link, box_size=8))
        qr.setPixmap(pixmap.scaled(240, 240, Qt.AspectRatioMode.KeepAspectRatio))
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(qr)

        addr = QLineEdit(address)
        addr.setReadOnly(True)
        layout.addWidget(addr)
        copy_btn = QPushButton("Copy address")
        copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(address))
        layout.addWidget(copy_btn)
        note = QLabel("Share this address or QR to receive TON and jettons on this account.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SeedRevealDialog(QDialog):
    """Displays the recovery phrase after the keystore has been unlocked."""

    def __init__(self, parent: QWidget | None, words: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recovery phrase")
        self.setModal(True)
        layout = QVBoxLayout(self)
        warn = QLabel("Anyone with these 24 words controls this wallet. Never share them.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#e74c3c; font-weight:bold;")
        layout.addWidget(warn)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(" ".join(f"{i + 1}. {w}" for i, w in enumerate(words)))
        view.setFixedHeight(140)
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


_open_boxes: list[QMessageBox] = []


def _notify(parent: QWidget, icon, title: str, text: str) -> None:
    """Non-modal notification (a modal box would freeze the event pump)."""
    box = QMessageBox(parent)
    box.setIcon(icon)
    box.setWindowTitle(title)
    box.setText(text)
    box.setModal(False)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    _open_boxes.append(box)
    box.finished.connect(lambda: _open_boxes.remove(box) if box in _open_boxes else None)
    box.show()


def show_error(parent: QWidget, title: str, text: str) -> None:
    _notify(parent, QMessageBox.Icon.Warning, title, text)


def show_info(parent: QWidget, title: str, text: str) -> None:
    _notify(parent, QMessageBox.Icon.Information, title, text)


def confirm(parent: QWidget, title: str, text: str) -> bool:
    return (
        QMessageBox.question(parent, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        == QMessageBox.StandardButton.Yes
    )
