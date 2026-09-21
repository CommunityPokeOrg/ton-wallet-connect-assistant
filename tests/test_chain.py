import asyncio

import pytest

from ton_wallet_assistant.wallet.chain import format_ton, nano_to_ton, ton_to_nano
from ton_wallet_assistant.wallet.demo import DemoChainClient
from ton_wallet_assistant.wallet.tonapi import _action_to_record


def test_ton_to_nano():
    assert ton_to_nano("1") == 1_000_000_000
    assert ton_to_nano("0.5") == 500_000_000
    assert ton_to_nano("1.000000001") == 1_000_000_001
    assert ton_to_nano("42.1337") == 42_133_700_000
    for bad in ("", "abc", "-1", "1.0000000001", "1,5", "+1"):
        with pytest.raises(ValueError):
            ton_to_nano(bad)


def test_format_ton():
    assert format_ton(1_000_000_000) == "1"
    assert format_ton(1_500_000_000) == "1.5"
    assert format_ton(0) == "0"


def test_nano_to_ton():
    assert nano_to_ton(2_500_000_000) == 2.5


# ---- tonapi action parsing -------------------------------------------------

OWN = "UQCfO0UY3G5vlfbqPOsqX4FsbWk0DOxAXRlnq5AjoAXBRckm"

TON_TRANSFER_ACTION = {
    "type": "TonTransfer",
    "status": "ok",
    "timestamp": 1726900000,
    "TonTransfer": {
        "amount": 1_500_000_000,
        "comment": "hello",
        "sender": {"address": "0:aaaabbbb"},
        "recipient": {"address": OWN},
    },
}

JETTON_ACTION = {
    "type": "JettonTransfer",
    "status": "ok",
    "timestamp": 1726900100,
    "JettonTransfer": {
        "amount": "12.5",
        "comment": "",
        "sender": {"address": OWN},
        "recipient": {"address": "0:ccccdddd"},
        "jetton": {"symbol": "USDT", "decimals": 6},
    },
}


def test_ton_transfer_parsed_incoming():
    rec = _action_to_record(TON_TRANSFER_ACTION, OWN, "ev1")
    assert rec.direction == "in"
    assert rec.amount_nano == 1_500_000_000
    assert rec.comment == "hello"
    assert rec.status == "confirmed"
    assert rec.tx_hash == "ev1"
    assert rec.asset == "TON"


def test_jetton_transfer_parsed_outgoing():
    rec = _action_to_record(JETTON_ACTION, OWN, "ev2")
    assert rec.direction == "out"
    assert rec.amount_nano == 12_500_000
    assert rec.asset == "USDT"


def test_unknown_action_skipped():
    assert _action_to_record({"type": "ContractDeploy"}, OWN, "ev") is None


# ---- demo chain client ------------------------------------------------------


def test_demo_chain_client_cycle():
    async def run():
        client = DemoChainClient()
        addr = "UQtest"
        bal = await client.get_balance(addr)
        assert bal == 42_133_700_000
        jets = await client.get_jettons(addr)
        assert {j.symbol for j in jets} == {"dUSD", "DEMO"}
        hist = await client.get_history(addr)
        assert len(hist) == 8
        tx = await client.send([], "v4r2", "UQdest", 1_000_000_000, "test send")
        assert tx
        hist = await client.get_history(addr)
        assert hist[0].tx_hash == tx
        assert hist[0].status == "pending"
        assert hist[0].direction == "out"
        assert await client.get_balance(addr) == bal - 1_000_000_000
        await client.close()

    asyncio.run(run())


def test_demo_send_insufficient_balance():
    async def run():
        client = DemoChainClient()
        from ton_wallet_assistant.wallet.chain import ChainError

        with pytest.raises(ChainError):
            await client.send([], "v4r2", "UQdest", client._balance + 1)

    asyncio.run(run())
