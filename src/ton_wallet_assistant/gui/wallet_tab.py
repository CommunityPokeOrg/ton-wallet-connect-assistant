"""Wallet page — balance card, multi-asset list, send/receive actions."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
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
from ..wallet.chain import JettonBalance
from ..wallet.jettons import jetton_amount_to_units
from .async_loop import AsyncLoop
from .dialogs import ConfirmSendDialog, ReceiveDialog, show_error, show_info
from .icons import letter_icon
from .theme import TEXT_DIM, WARNING


class WalletTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.async_loop = async_loop
        self._balance_nano = 0
        self._jettons: list[JettonBalance] = []
        self._build_ui()
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        top = QHBoxLayout()
        self.balance_label = QLabel("—")
        self.balance_label.setObjectName("balance")
        top.addWidget(self.balance_label)
        top.addStretch(1)
        net = self.session.account.network
        chips = [net]
        if self.session.demo:
            chips.append("DEMO")
        for text in chips:
            chip = QLabel(text.upper())
            color = WARNING if text == "DEMO" else "#45AEF5"
            chip.setStyleSheet(
                f"padding:2px 8px; border-radius:8px; font-weight:bold; background:{color}; color:#0b1016;"
            )
            top.addWidget(chip)
        outer.addLayout(top)

        addr_row = QHBoxLayout()
        self.address_label = QLabel(self.session.account.short_address)
        self.address_label.setStyleSheet(f"font-family:monospace; font-size:13px; color:{TEXT_DIM};")
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
        self.send_button.setObjectName("primary")
        self.send_button.clicked.connect(self._send_clicked)
        self.receive_button = QPushButton("Receive")
        self.receive_button.clicked.connect(self._receive_clicked)
        buttons.addWidget(self.send_button)
        buttons.addWidget(self.receive_button)
        outer.addLayout(buttons)

        assets_box = QGroupBox("Assets")
        assets_layout = QVBoxLayout(assets_box)
        self.assets_list = QListWidget()
        assets_layout.addWidget(self.assets_list)
        outer.addWidget(assets_box, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color:{TEXT_DIM};")
        outer.addWidget(self.status_label)

    # ------------------------------------------------------------- refresh

    def refresh(self) -> None:
        self.refresh_button.setEnabled(False)
        address = self.session.account.friendly_bounceable
        self.async_loop.submit(self.session.chain.get_balance(address), self._on_balance)
        self.async_loop.submit(self.session.chain.get_jettons(address), self._on_jettons)

    def _on_balance(self, result, error) -> None:
        self.refresh_button.setEnabled(True)
        if error:
            self.status_label.setText(f"Balance: {error}")
            return
        self._balance_nano = result
        self._render()

    def _on_jettons(self, result, error) -> None:
        if error:
            self.status_label.setText(f"Jettons: {error}")
            return
        self._jettons = list(result or [])
        self._render()

    # -------------------------------------------------------------- render

    def _render(self) -> None:
        self.balance_label.setText(f"{format_ton(self._balance_nano)} TON")
        self.assets_list.clear()
        ton_item = QListWidgetItem(letter_icon("TON"), "TON")
        ton_item.setText(f"TON — The Open Network\t{format_ton(self._balance_nano)} TON")
        self.assets_list.addItem(ton_item)
        for j in self._jettons:
            item = QListWidgetItem(letter_icon(j.symbol), j.symbol)
            item.setText(f"{j.symbol} — {j.name}\t{j.balance}")
            self.assets_list.addItem(item)

    # ------------------------------------------------------------- actions

    def _copy_address(self) -> None:
        QGuiApplication.clipboard().setText(self.session.account.friendly_bounceable)
        self.status_label.setText("Address copied to clipboard")

    def _receive_clicked(self) -> None:
        address = self.session.account.friendly_non_bounceable
        ReceiveDialog(self, address, f"ton://transfer/{address}").exec()

    def _send_clicked(self) -> None:
        if self.session.locked:
            show_error(self, "Locked", "Unlock the wallet in Settings before sending.")
            return
        dlg = _SendFormDialog(self, self._jettons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        destination = dlg.to_edit.text().strip()
        if not (is_friendly_address(destination) or is_raw_address(destination)):
            show_error(self, "Invalid address", "Destination is not a valid TON address.")
            return
        comment = dlg.comment_edit.text().strip()
        jetton: JettonBalance | None = dlg.selected_jetton()

        try:
            if jetton is None:
                amount_units = ton_to_nano(dlg.amount_edit.text())
                if amount_units > self._balance_nano:
                    raise ValueError(f"insufficient TON balance ({format_ton(self._balance_nano)} available)")
                amount_text = f"{dlg.amount_edit.text().strip()} TON"
            else:
                amount_units = jetton_amount_to_units(dlg.amount_edit.text(), jetton.decimals)
                if amount_units > jetton.raw_balance:
                    raise ValueError(f"insufficient {jetton.symbol} balance ({jetton.balance} available)")
                amount_text = f"{dlg.amount_edit.text().strip()} {jetton.symbol}"
        except ValueError as exc:
            show_error(self, "Invalid amount", str(exc))
            return

        confirm = ConfirmSendDialog(
            self,
            destination=destination,
            amount_text=amount_text,
            comment=comment,
            demo=self.session.demo,
        )
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return

        mnemonic: list[str] = []
        if not self.session.demo:
            try:
                mnemonic = self.session.keystore.unlock(confirm.password)
            except Exception:
                show_error(self, "Wrong password", "Could not unlock the keystore.")
                return
        self._do_send(mnemonic, destination, amount_units, comment, jetton)

    def _do_send(self, mnemonic, destination: str, amount_units: int, comment: str, jetton) -> None:
        self.send_button.setEnabled(False)
        self.status_label.setText("Broadcasting transaction…")
        if jetton is None:
            coro = self.session.chain.send(
                mnemonic, self.session.account.wallet_version, destination, amount_units, comment
            )
        else:
            coro = self.session.chain.send_jetton(
                mnemonic, self.session.account.wallet_version, jetton, destination, amount_units, comment
            )
        self.async_loop.submit(coro, self._on_sent)

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
    """Tonkeeper-style send form: asset picker, recipient, amount, comment."""

    def __init__(self, parent: QWidget | None, jettons: list[JettonBalance]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Send")
        self.setModal(True)
        self._jettons = jettons
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.asset_combo = QComboBox()
        self.asset_combo.addItem("TON", userData=None)
        for j in jettons:
            self.asset_combo.addItem(f"{j.symbol} — {j.name}", userData=j)
        self.asset_combo.currentIndexChanged.connect(self._asset_changed)

        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText("EQ… / UQ… or 0:hex")
        self.amount_edit = QLineEdit()
        self.amount_edit.setPlaceholderText("0.0")
        self.comment_edit = QLineEdit()
        self.comment_edit.setPlaceholderText("optional")
        form.addRow("Asset", self.asset_combo)
        form.addRow("To", self.to_edit)
        form.addRow("Amount", self.amount_edit)
        form.addRow("Comment", self.comment_edit)
        layout.addLayout(form)
        row = QHBoxLayout()
        ok = QPushButton("Continue")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)
        self._asset_changed(0)

    def _asset_changed(self, _index: int) -> None:
        j = self.selected_jetton()
        if j is not None:
            self.amount_edit.setPlaceholderText(f"0.0 (balance: {j.balance} {j.symbol})")

    def selected_jetton(self) -> JettonBalance | None:
        return self.asset_combo.currentData()
