"""Collectibles page — NFT grid (Tonkeeper 'Collectibles' equivalent)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication
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
from ..wallet.chain import Nft
from .async_loop import AsyncLoop
from .dialogs import show_info
from .icons import letter_icon
from .theme import TEXT_DIM


class CollectiblesTab(QWidget):
    def __init__(self, session: WalletSession, async_loop: AsyncLoop, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.async_loop = async_loop
        self._nfts: list[Nft] = []

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        title = QLabel("Collectibles")
        title.setStyleSheet("font-size:20px; font-weight:bold;")
        top.addWidget(title)
        top.addStretch(1)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        top.addWidget(self.refresh_button)
        layout.addLayout(top)

        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setSpacing(12)
        self.grid.setIconSize(QSize(96, 96))
        self.grid.setWordWrap(True)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.itemActivated.connect(self._show_nft)
        self.grid.itemClicked.connect(self._show_nft)
        layout.addWidget(self.grid, 1)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color:{TEXT_DIM};")
        layout.addWidget(self.status_label)

        self.refresh()

    def refresh(self) -> None:
        async def fetch():
            return await self.session.chain.get_nfts(self.session.account.friendly_bounceable)

        self.status_label.setText("Loading collectibles…")
        self.async_loop.submit(fetch(), self._on_nfts)

    def _on_nfts(self, result, error) -> None:
        if error:
            self.status_label.setText(f"Collectibles failed: {error}")
            return
        self._nfts = list(result or [])
        self.grid.clear()
        for nft in self._nfts:
            item = QListWidgetItem(letter_icon(nft.name, 96), nft.name)
            item.setSizeHint(QSize(140, 140))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.grid.addItem(item)
        self.status_label.setText(f"{len(self._nfts)} collectibles" if self._nfts else "No collectibles yet")

    def _show_nft(self, item: QListWidgetItem) -> None:
        idx = self.grid.row(item)
        if not (0 <= idx < len(self._nfts)):
            return
        nft = self._nfts[idx]
        QGuiApplication.clipboard().setText(nft.address)
        show_info(
            self,
            nft.name,
            f"Collection: {nft.collection or '—'}\n"
            f"Address: {nft.address}\n"
            f"{nft.description}\n\n(address copied to clipboard)",
        )
