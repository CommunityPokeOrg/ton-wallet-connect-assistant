"""TON address conversion helpers.

A TON account is identified on-chain by its *raw* form ``<workchain>:<64-hex>``,
but wallets and explorers display the *user-friendly* form: a base64url string
that bundles a flags byte (bounceable / test-only), the workchain id, the
256-bit account id, and a CRC16-XMODEM checksum.

This module implements that conversion with no third-party dependencies.
"""

from __future__ import annotations

import base64
import binascii

BOUNCEABLE_TAG = 0x11
NON_BOUNCEABLE_TAG = 0x51
TEST_ONLY_FLAG = 0x80

_MAINNET_CHAIN = "-239"
_TESTNET_CHAIN = "-3"


class AddressError(ValueError):
    """Raised when an address string cannot be parsed or validated."""


def crc16_xmodem(data: bytes) -> int:
    """CRC16-XMODEM (poly 0x1021, init 0x0000) as used by TON addresses."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc <<= 1
            if crc & 0x10000:
                crc ^= 0x1021
            crc &= 0xFFFF
    return crc


def parse_raw_address(raw: str) -> tuple[int, bytes]:
    """Parse ``<workchain>:<64-hex>`` into ``(workchain, account_id)``."""
    parts = raw.strip().split(":")
    if len(parts) != 2:
        raise AddressError(f"raw address must be '<workchain>:<64-hex>', got {raw!r}")
    try:
        workchain = int(parts[0], 10)
    except ValueError as exc:
        raise AddressError(f"invalid workchain in address {raw!r}") from exc
    if not -128 <= workchain <= 127:
        raise AddressError(f"workchain {workchain} out of int8 range")
    try:
        account_id = bytes.fromhex(parts[1])
    except ValueError as exc:
        raise AddressError(f"invalid account id in address {raw!r}") from exc
    if len(account_id) != 32:
        raise AddressError("account id must be 32 bytes (64 hex chars)")
    return workchain, account_id


def is_raw_address(value: str) -> bool:
    try:
        parse_raw_address(value)
    except AddressError:
        return False
    return True


def raw_to_friendly(raw: str, *, bounceable: bool = True, test_only: bool = False) -> str:
    """Convert a raw ``<workchain>:<hex>`` address to user-friendly base64url."""
    workchain, account_id = parse_raw_address(raw)
    tag = BOUNCEABLE_TAG if bounceable else NON_BOUNCEABLE_TAG
    if test_only:
        tag |= TEST_ONLY_FLAG
    payload = bytes([tag, workchain & 0xFF]) + account_id
    payload += crc16_xmodem(payload).to_bytes(2, "big")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def friendly_to_raw(friendly: str) -> tuple[int, bytes, bool, bool]:
    """Decode a user-friendly address.

    Returns ``(workchain, account_id, bounceable, test_only)``.
    Raises :class:`AddressError` on malformed input or a bad checksum.
    """
    text = friendly.strip()
    if len(text) != 48:
        raise AddressError("friendly address must be 48 base64 characters")
    urlsafe = "-" in text or "_" in text
    try:
        if urlsafe:
            payload = base64.urlsafe_b64decode(text)
        else:
            payload = base64.b64decode(text)
    except (binascii.Error, ValueError) as exc:
        raise AddressError(f"address {friendly!r} is not valid base64") from exc
    if len(payload) != 36:
        raise AddressError("decoded address must be 36 bytes")
    body, checksum = payload[:34], int.from_bytes(payload[34:], "big")
    if crc16_xmodem(body) != checksum:
        raise AddressError("address checksum mismatch")
    tag, workchain = body[0], int.from_bytes(body[1:2], "big", signed=True)
    test_only = bool(tag & TEST_ONLY_FLAG)
    base_tag = tag & ~TEST_ONLY_FLAG
    if base_tag == BOUNCEABLE_TAG:
        bounceable = True
    elif base_tag == NON_BOUNCEABLE_TAG:
        bounceable = False
    else:
        raise AddressError(f"unknown address tag byte {tag:#04x}")
    return workchain, body[2:], bounceable, test_only


def is_friendly_address(value: str) -> bool:
    try:
        friendly_to_raw(value)
    except AddressError:
        return False
    return True


def network_from_chain(chain: str | int | None) -> str:
    """Map a TonConnect ``account.chain`` value to ``mainnet``/``testnet``."""
    chain = str(chain) if chain is not None else ""
    if chain == _MAINNET_CHAIN:
        return "mainnet"
    if chain == _TESTNET_CHAIN:
        return "testnet"
    return "unknown"


def chain_from_network(network: str) -> str:
    return _TESTNET_CHAIN if network == "testnet" else _MAINNET_CHAIN
