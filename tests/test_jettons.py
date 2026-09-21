"""Jetton amount conversion and TEP-74 transfer body construction."""

import pytest

from ton_wallet_assistant.wallet.jettons import (
    OP_JETTON_TRANSFER,
    build_jetton_transfer_body,
    jetton_amount_to_units,
)

DEST = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"  # burn address
RESPONSE = "UQAREREREREREREREREREREREREREREREREREREREREREbvW"


def test_jetton_amount_to_units():
    assert jetton_amount_to_units("1", 6) == 1_000_000
    assert jetton_amount_to_units("12.5", 6) == 12_500_000
    assert jetton_amount_to_units("0.000000001", 9) == 1
    assert jetton_amount_to_units(".5", 9) == 500_000_000
    for bad in ("", "abc", "-1", "1.0000001", "1,5", "+1"):
        with pytest.raises(ValueError):
            jetton_amount_to_units(bad, 6)


def test_build_jetton_transfer_body_parses_back():
    from pytoniq_core import Address

    cell = build_jetton_transfer_body(
        destination=DEST,
        amount_units=12_500_000,
        response_address=RESPONSE,
        forward_ton_amount=50_000_000,
        comment="test comment",
        query_id=42,
    )
    cs = cell.begin_parse()
    assert cs.load_uint(32) == OP_JETTON_TRANSFER
    assert cs.load_uint(64) == 42
    assert cs.load_coins() == 12_500_000
    assert cs.load_address() == Address(DEST)
    assert cs.load_address() == Address(RESPONSE)
    assert cs.load_bit() == 0  # no custom payload
    assert cs.load_coins() == 50_000_000
    assert cs.load_bit() == 1  # forward payload present
    payload = cs.load_ref().begin_parse()
    assert payload.load_uint(32) == 0  # text-comment opcode
    assert payload.load_snake_bytes().decode() == "test comment"


def test_build_jetton_transfer_body_no_comment():
    cell = build_jetton_transfer_body(
        destination=DEST, amount_units=1, response_address=RESPONSE, comment=""
    )
    cs = cell.begin_parse()
    cs.load_uint(96)  # op + query_id
    cs.load_coins()
    cs.load_address()
    cs.load_address()
    cs.load_bit()
    cs.load_coins()
    assert cs.load_bit() == 0


def test_build_jetton_transfer_body_rejects_bad_input():
    from pytoniq_core import AddressError

    with pytest.raises(ValueError):
        build_jetton_transfer_body(destination=DEST, amount_units=0, response_address=RESPONSE)
    with pytest.raises(AddressError):
        build_jetton_transfer_body(destination="not-an-address", amount_units=1, response_address=RESPONSE)


def test_demo_jetton_send():
    import asyncio

    from ton_wallet_assistant.wallet.demo import DemoChainClient

    async def run():
        client = DemoChainClient()
        jets = await client.get_jettons("UQtest")
        dusd = next(j for j in jets if j.symbol == "dUSD")
        tx = await client.send_jetton([], "v4r2", dusd, "UQdest", 100_000_000, "pay")
        assert tx
        hist = await client.get_history("UQtest")
        assert hist[0].asset == "dUSD"
        assert hist[0].amount_nano == 100_000_000
        assert hist[0].status == "pending"
        jets = await client.get_jettons("UQtest")
        assert next(j for j in jets if j.symbol == "dUSD").raw_balance == 1_150_500_000
        nfts = await client.get_nfts("UQtest")
        assert len(nfts) == 3

    asyncio.run(run())


def test_demo_jetton_send_insufficient():
    import asyncio

    from ton_wallet_assistant.wallet.chain import ChainError
    from ton_wallet_assistant.wallet.demo import DemoChainClient

    async def run():
        client = DemoChainClient()
        jets = await client.get_jettons("UQtest")
        dusd = next(j for j in jets if j.symbol == "dUSD")
        with pytest.raises(ChainError):
            await client.send_jetton([], "v4r2", dusd, "UQdest", dusd.raw_balance + 1)

    asyncio.run(run())
