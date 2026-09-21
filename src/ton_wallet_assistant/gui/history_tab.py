"""History page — full transaction list with a details dialog on click."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..session import WalletSession
from ..wallet.chain import TxRecord
from .async_loop import AsyncLoop
from .dialogs import TxDetailsDialog
from .theme import TEXT_DIM


def tx_row_text(tx: TxRecord) -> str:
    arrow = "↑" if tx.direction == "out" else "↓"
    sign = "-" if tx.direction == "out" else "+"
    when = datetime.fromtimestamp(tx.timestamp).strftime("%Y-%m-%d %H:%M") if tx.timestamp else ""
    status = f" [{tx.status}]" if tx.status != "confirmed" else ""
    counter = tx.counterparty
    counter = f"{counter[:6]}…{counter[-4:]}" if len(counter) > 14 else counter
    comment = f" — {tx.comment}" if tx.comment else ""
    return f"{arrow} {sign}{tx.formatted_amount} {tx.asset}{status}  {counter}  {when}{comment}"


class HistoryTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.async_loop = async_loop
        self._history: list[TxRecord] = []

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("History")
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.list = QListWidget()
        self.list.itemActivated.connect(self._show_details)
        self.list.itemClicked.connect(self._show_details)
        layout.addWidget(self.list, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{TEXT_DIM};")
        layout.addWidget(self.status_label)

        self.refresh()

    def refresh(self) -> None:
        async def fetch():
            return await self.session.chain.get_history(
                self.session.account.friendly_bounceable, limit=50
            )

        self.status_label.setText("Loading history…")
        self.async_loop.submit(fetch(), self._on_history)

    def _on_history(self, result, error) -> None:
        if error:
            self.status_label.setText(f"History failed: {error}")
            return
        self._history = list(result or [])
        self.list.clear()
        for tx in self._history:
            self.list.addItem(QListWidgetItem(tx_row_text(tx)))
        self.status_label.setText(f"{len(self._history)} transactions" if self._history else "No transactions yet")

    def _show_details(self, item: QListWidgetItem) -> None:
        idx = self.list.row(item)
        if 0 <= idx < len(self._history):
            TxDetailsDialog(self, self._history[idx], self.session.account.network).exec()
