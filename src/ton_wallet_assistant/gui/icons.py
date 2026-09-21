"""Deterministic letter-avatar icons for assets and collectibles.

Jetton/NFT metadata carries image URLs, but we render local letter avatars so
the UI is instant, offline-safe (demo mode), and never leaks wallet addresses
to third-party CDNs on every launch.
"""

from __future__ import annotations

import hashlib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap


def _color_for(key: str) -> QColor:
    digest = hashlib.sha1(key.encode()).digest()
    hue = int.from_bytes(digest[:2], "big") % 360
    return QColor.fromHsv(hue, 140, 200)


def letter_icon(text: str, size: int = 36) -> QIcon:
    """Rounded-square avatar with the first letters of ``text``."""
    label = "".join(part[0] for part in text.split()[:2]).upper() or "?"
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(_color_for(text))
    painter.setPen(QPen(Qt.GlobalColor.transparent))
    painter.drawRoundedRect(0, 0, size, size, size // 4, size // 4)
    painter.setPen(QColor("#FFFFFF"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(10, size // 2 - 4))
    painter.setFont(font)
    painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, label)
    painter.end()
    return QIcon(pix)
