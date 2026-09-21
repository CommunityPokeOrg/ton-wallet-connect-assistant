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


class RequestApprovalDialog(QDialog):
    """Approve/reject a request relayed from the paired mobile companion.

    Shows origin, method, destination, amount/assets, payload/comment,
    network, and the estimated fee — then collects the wallet password for
    transfer requests (real mode) before signing.
    """

    def __init__(self, parent: QWidget | None, request, *, demo: bool, network: str) -> None:
        from ..companion.protocol import PayloadKind, TransferDetails

        super().__init__(parent)
        self.setWindowTitle("Approve request")
        self.setModal(True)
        self.password = ""
        self.is_transfer = request.kind is PayloadKind.TON_TRANSFER
        layout = QVBoxLayout(self)

        if demo:
            flag = QLabel("DEMO MODE — nothing will be sent on-chain.")
            flag.setStyleSheet("color:#f0a020; font-weight:bold;")
            layout.addWidget(flag)

        summary = QFormLayout()
        summary.addRow("Origin", QLabel(f"{request.origin_ip} (paired mobile device)"))
        if self.is_transfer:
            d: TransferDetails = request.payload
            summary.addRow("Method", QLabel("Send transfer (ton://transfer)"))
            to_label = QLabel(d.address)
            to_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            to_label.setWordWrap(True)
            summary.addRow("To", to_label)
            if d.jetton:
                summary.addRow("Asset", QLabel(f"Jetton {d.jetton[:10]}…"))
                amt = str(d.amount_nano) if d.amount_nano is not None else "—"
                summary.addRow("Amount", QLabel(f"{amt} (raw units)"))
                fee = "0 (demo)" if demo else "≤ 0.12 TON (incl. ~0.1 TON attached)"
            else:
                summary.addRow("Asset", QLabel("TON"))
                summary.addRow("Amount", QLabel(d.amount_text))
                fee = "0 (demo)" if demo else "≤ 0.02 TON"
            if d.comment:
                summary.addRow("Comment", QLabel(d.comment))
        else:
            d = request.payload
            summary.addRow("Method", QLabel("TonConnect connect (open in wallet app)"))
            summary.addRow("Wallet link", QLabel(d.wallet_host))
            summary.addRow("Session", QLabel(d.session_id[:16] + "…"))
            items = ", ".join(d.items) or "ton_addr"
            summary.addRow("Requested", QLabel(items))
            fee = "—"
        summary.addRow("Network", QLabel(network))
        summary.addRow("Est. fee", QLabel(fee))
        layout.addLayout(summary)

        if self.is_transfer and not demo:
            layout.addWidget(QLabel("Wallet password to sign:"))
            self.password_edit = QLineEdit()
            self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(self.password_edit)
        else:
            self.password_edit = None

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Approve")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Reject")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        if self.password_edit is not None:
            self.password = self.password_edit.text()
        super().accept()


class TxDetailsDialog(QDialog):
    """Read-only transaction detail view with explorer link."""

    def __init__(self, parent: QWidget | None, tx, network: str = "mainnet") -> None:
        super().__init__(parent)
        from datetime import datetime

        from ..wallet.chain import format_ton

        self.setWindowTitle("Transaction details")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        def row(label: str, value: str) -> None:
            lbl = QLabel(value or "—")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lbl.setWordWrap(True)
            form.addRow(label, lbl)

        sign = "+" if tx.direction == "in" else "-"
        row("Amount", f"{sign}{tx.formatted_amount} {tx.asset}")
        row("Direction", "Received" if tx.direction == "in" else "Sent")
        row("Status", tx.status)
        if tx.timestamp:
            row("Date", datetime.fromtimestamp(tx.timestamp).strftime("%Y-%m-%d %H:%M:%S"))
        if tx.sender:
            row("From", tx.sender)
        if tx.recipient:
            row("To", tx.recipient)
        elif tx.counterparty:
            row("Counterparty", tx.counterparty)
        if tx.fee_nano is not None:
            row("Fee", f"{format_ton(tx.fee_nano)} TON")
        if tx.comment:
            row("Comment", tx.comment)
        row("Event", tx.tx_hash)
        layout.addLayout(form)

        if tx.tx_hash and tx.tx_hash != "broadcast":
            host = "testnet.tonviewer.com" if network == "testnet" else "tonviewer.com"
            view_btn = QPushButton("View in Tonviewer")
            view_btn.clicked.connect(lambda: __import__("webbrowser").open(f"https://{host}/transaction/{tx.tx_hash}"))
            layout.addWidget(view_btn)
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
