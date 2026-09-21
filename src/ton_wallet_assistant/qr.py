"""QR code generation (GUI-free, returns PNG bytes)."""

from __future__ import annotations

import io

import qrcode


def qr_png_bytes(text: str, *, box_size: int = 6, border: int = 2) -> bytes:
    """Render ``text`` as a PNG-encoded QR code."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
