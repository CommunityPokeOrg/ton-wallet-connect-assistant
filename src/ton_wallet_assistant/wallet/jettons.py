"""Jetton (TEP-74) transfer message construction.

Builds the internal-message body a wallet contract must send to its own jetton
wallet to move jettons. Pure cell construction — fully offline and unit
testable.
"""

from __future__ import annotations

OP_JETTON_TRANSFER = 0xF8A7EA5


def build_jetton_transfer_body(
    *,
    destination: str,
    amount_units: int,
    response_address: str,
    forward_amount_nano: int = 1,  # 1 nanoton notification by default
    forward_ton_amount: int = 50_000_000,  # 0.05 TON attached for the notification
    comment: str = "",
    query_id: int = 0,
):
    """Return a ``Cell`` body for a TEP-74 ``transfer`` request.

    The wallet sends this body to *its own jetton wallet* contract along with
    ``forward_ton_amount`` + fees in TON. ``amount_units`` is the raw jetton
    amount (already multiplied by 10**decimals).
    """
    from pytoniq_core import Address, begin_cell

    if amount_units <= 0:
        raise ValueError("jetton amount must be positive")
    dest = Address(destination)
    response = Address(response_address)

    builder = (
        begin_cell()
        .store_uint(OP_JETTON_TRANSFER, 32)
        .store_uint(query_id, 64)
        .store_coins(amount_units)
        .store_address(dest)
        .store_address(response)
        .store_bit(0)  # no custom payload
        .store_coins(forward_ton_amount)
    )
    if comment.strip():
        forward_payload = begin_cell().store_uint(0, 32).store_snake_string(comment.strip()).end_cell()
        builder = builder.store_bit(1).store_ref(forward_payload)
    else:
        builder = builder.store_bit(0)  # no forward payload
    return builder.end_cell()


def jetton_amount_to_units(amount_text: str, decimals: int) -> int:
    """Convert a human-readable jetton amount to raw units for ``decimals``."""
    text = amount_text.strip()
    if not text or text.startswith("-") or "+" in text:
        raise ValueError("invalid amount")
    whole, dot, frac = text.partition(".")
    if not whole:
        whole = "0"
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise ValueError(f"invalid amount {amount_text!r}")
    if len(frac) > decimals:
        raise ValueError(f"too many decimals (max {decimals})")
    return int(whole) * 10**decimals + int(frac.ljust(decimals, "0") or 0)
