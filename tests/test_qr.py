import io

from ton_wallet_assistant.qr import qr_png_bytes


def test_qr_png_bytes_valid_png():
    data = qr_png_bytes("demo://wallet.demo/ton-connect?v=2&id=abc")
    assert data[:8] == b"\x89PNG\r\n\x1a\n"

    from PIL import Image

    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.width > 50
    assert image.height == image.width


def test_qr_empty_input_still_encodable():
    assert qr_png_bytes("x")[:4] == b"\x89PNG"
