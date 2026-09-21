"""Wallet tab — balance, assets, send/receive, transaction history."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..address_utils import is_friendly_address, is_raw_address
from ..session import WalletSession
from ..wallet import format_ton, ton_to_nano
from ..wallet.chain import TxRecord
from .async_loop import AsyncLoop
from .dialogs import ConfirmSendDialog, ReceiveDialog, show_error, show_info


class WalletTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.async_loop = async_loop
        self._history: list[TxRecord] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        self.balance_label = QLabel("—")
        self.balance_label.setStyleSheet("font-size:32px; font-weight:bold;")
        top.addWidget(self.balance_label)
        top.addStretch(1)
        net = self.session.account.network
        chips = [net]
        if self.session.demo:
            chips.append("DEMO")
        for text in chips:
            chip = QLabel(text.upper())
            chip.setStyleSheet(
                "padding:2px 8px; border-radius:8px; font-weight:bold; "
                + ("background:#f0a020;color:#202020;" if text == "DEMO" else "background:#3b7dd8;color:white;")
            )
            top.addWidget(chip)
        outer.addLayout(top)

        addr_row = QHBoxLayout()
        self.address_label = QLabel(self.session.account.short_address)
        self.address_label.setStyleSheet("font-family:monospace; font-size:13px;")
        self.address_label.setToolTip(self.session.account.friendly_bounceable)
        addr_row.addWidget(self.address_label)
        copy_addr = QPushButton("Copy")
        copy_addr.setFixedWidth(60)
        copy_addr.clicked.connect(self._copy_address)
        addr_row.addWidget(copy_addr)
        addr_row.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        addr_row.addWidget(self.refresh_button)
        outer.addLayout(addr_row)

        buttons = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._send_clicked)
        self.receive_button = QPushButton("Receive")
        self.receive_button.clicked.connect(self._receive_clicked)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.receive_button)
        outer.addLayout(buttons)

        assets_box = QGroupBox("Assets")
        assets_layout = QVBoxLayout(assets_box)
        self.assets_list = QListWidget()
        self.assets_list.setMaximumHeight(120)
        assets_layout.addWidget(self.assets_list)
        outer.addWidget(assets_box)

        hist_box = QGroupBox("Recent activity")
        hist_layout = QVBoxLayout(hist_box)
        self.history_list = QListWidget()
        hist_layout.addWidget(self.history_list)
        outer.addWidget(hist_box, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        if self.session.demo:
            self._do_refresh()
            return
        self.refresh_button.setEnabled(False)
        self.status_label.setText("Refreshing…")
        address = self.session.account.friendly_bounceable
        self.async_loop.submit(self.session.chain.get_balance(address), self._on_balance)
        self.async_loop.submit(self.session.chain.get_jettons(address), self._on_jettons)
        self.async_loop.submit(self.session.chain.get_history(address), self._on_history)

    def _do_refresh(self) -> None:
        """Synchronous refresh path used by the demo backend."""

        async def gather():
            addr = self.session.account.friendly_bounceable
            return (
                await self.session.chain.get_balance(addr),
                await self.session.chain.get_jettons(addr),
                await self.session.chain.get_history(addr),
            )

        self.async_loop.submit(gather(), self._on_demo_data)

    def _on_demo_data(self, result, error) -> None:
        if error:
            self.status_label.setText(f"Demo refresh failed: {error}")
            return
        balance, jettons, history = result
        self._render_balance(balance)
        self._render_assets(balance, jettons)
        self._render_history(history)

    def _on_balance(self, result, error) -> None:
        self.refresh_button.setEnabled(True)
        if error:
            self.status_label.setText(f"Balance: {error}")
            return
        self._balance = result
        self._render_balance(result)

    def _on_jettons(self, result, error) -> None:
        if error:
            self.status_label.setText(f"Jettons: {error}")
            return
        self._render_assets(getattr(self, "_balance", 0), result or [])

    def _on_history(self, result, error) -> None:
        if error:
            self.status_label.setText(f"History: {error}")
            return
        self._render_history(result or [])
        self.status_label.setText("")

    # -------------------------------------------------------------- render

    def _render_balance(self, nano: int) -> None:
        self.balance_label.setText(f"{format_ton(nano)} TON")

    def _render_assets(self, ton_nano: int, jettons) -> None:
        self.assets_list.clear()
        self.assets_list.addItem(QListWidgetItem(f"TON — {format_ton(ton_nano)}"))
        for j in jettons:
            self.assets_list.addItem(QListWidgetItem(f"{j.symbol} ({j.name}) — {j.balance}"))

    def _render_history(self, records) -> None:
        self._history = list(records)
        self.history_list.clear()
        for tx in records:
            arrow = "↑" if tx.direction == "out" else "↓"
            sign = "-" if tx.direction == "out" else "+"
            when = datetime.fromtimestamp(tx.timestamp).strftime("%Y-%m-%d %H:%M") if tx.timestamp else ""
            status = f" [{tx.status}]" if tx.status != "confirmed" else ""
            counter = tx.counterparty
            counter = f"{counter[:6]}…{counter[-4:]}" if len(counter) > 14 else counter
            comment = f" — {tx.comment}" if tx.comment else ""
            text = f"{arrow} {sign}{format_ton(tx.amount_nano)} {tx.asset}{status}  {counter}  {when}{comment}"
            self.history_list.addItem(QListWidgetItem(text))

    # ------------------------------------------------------------- actions

    def _copy_address(self) -> None:
        QGuiApplication.clipboard().setText(self.session.account.friendly_bounceable)
        self.status_label.setText("Address copied to clipboard")

    def _receive_clicked(self) -> None:
        address = self.session.account.friendly_non_bounceable
        ton_link = f"ton://transfer/{address}"
        ReceiveDialog(self, address, ton_link).exec()

    def _send_clicked(self) -> None:
        if self.session.locked:
            show_error(self, "Locked", "Unlock the wallet in Settings before sending.")
            return
        dlg = _SendFormDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            amount_nano = ton_to_nano(dlg.amount_edit.text())
        except ValueError:
            show_error(self, "Invalid amount", "Enter a valid TON amount (e.g. 1.5).")
            return
        destination = dlg.to_edit.text().strip()
        if not (is_friendly_address(destination) or is_raw_address(destination)):
            show_error(self, "Invalid address", "Destination is not a valid TON address.")
            return
        confirm = ConfirmSendDialog(
            self,
            destination=destination,
            amount_text=dlg.amount_edit.text(),
            comment=dlg.comment_edit.text().strip(),
            demo=self.session.demo,
        )
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return

        if self.session.demo:
            self._do_send([], destination, amount_nano, dlg.comment_edit.text().strip())
            return
        try:
            mnemonic = self.session.keystore.unlock(confirm.password)
        except Exception:
            show_error(self, "Wrong password", "Could not unlock the keystore.")
            return
        self._do_send(mnemonic, destination, amount_nano, dlg.comment_edit.text().strip())

    def _do_send(self, mnemonic, destination: str, amount_nano: int, comment: str) -> None:
        self.send_button.setEnabled(False)
        self.status_label.setText("Broadcasting transaction…")
        self.async_loop.submit(
            self.session.chain.send(
                mnemonic,
                self.session.account.wallet_version,
                destination,
                amount_nano,
                comment,
            ),
            self._on_sent,
        )

    def _on_sent(self, result, error) -> None:
        self.send_button.setEnabled(True)
        if error:
            self.status_label.setText(f"Send failed: {error}")
            show_error(self, "Send failed", str(error))
            return
        self.status_label.setText(f"Transaction sent: {result}")
        show_info(self, "Sent", "The transaction was broadcast. It will appear in history shortly.")
        self.refresh()


class _SendFormDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Send TON")
        self.setModal(True)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("EQ… / UQ… or 0:hex")
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.0")
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("optional")
        form.addRow("To", self.to_edit)
        form.addRow("Amount (TON)", self.amount_edit)
        form.addRow("Comment", self.comment_edit)
        layout.addLayout(form)
        row = QHBoxLayout()
        ok = QPushButton("Continue")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)
