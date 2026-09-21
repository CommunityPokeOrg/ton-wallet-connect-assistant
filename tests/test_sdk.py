"""Headless SDK coverage: public API surface, keystore flows, demo + real backends."""

import asyncio
import subprocess
import sys

import pytest

from ton_wallet_assistant.sdk import TonWalletSDK
from ton_wallet_assistant.wallet.chain import ChainError

DEMO_DEST = "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ"


def test_sdk_public_import_no_qt():
    """The SDK must be importable without pulling in PySide6/Qt."""
    code = (
        "import sys, ton_wallet_assistant.sdk as s; "
        "assert 'PySide6' not in sys.modules, 'SDK pulled in Qt'; "
        "assert s.TonWalletSDK and s.TonConnectClient; "
        "from ton_wallet_assistant import TonWalletSDK, TonConnectClient; print('ok')"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_sdk_demo_wallet_flow():
    async def run():
        sdk = await TonWalletSDK.demo(connect_delay=0.05)
        try:
            assert sdk.demo and sdk.is_unlocked
            assert sdk.account.friendly_bounceable.startswith(("EQ", "UQ"))
            assert await sdk.get_balance() > 0
            jets = await sdk.get_jettons()
            assert {j.symbol for j in jets} == {"dUSD", "DEMO"}
            nfts = await sdk.get_nfts()
            assert len(nfts) == 3
            hist = await sdk.get_history()
            assert len(hist) == 8

            tx = await sdk.send_ton(DEMO_DEST, "1.5", comment="sdk test")
            assert tx
            tx2 = await sdk.send_jetton("dUSD", DEMO_DEST, "10.5")
            assert tx2
            hist = await sdk.get_history()
            assert hist[0].asset == "dUSD"
            jets = await sdk.get_jettons()
            assert next(j for j in jets if j.symbol == "dUSD").raw_balance == 1_240_000_000
        finally:
            await sdk.close()

    asyncio.run(run())


def test_sdk_demo_tonconnect_lifecycle():
    async def run():
        sdk = await TonWalletSDK.demo(connect_delay=0.05)
        try:
            tc = sdk.tonconnect
            wallets = await tc.list_wallets()
            assert len(wallets) == 1
            link = await tc.request_connection(wallets[0])
            assert link.startswith("demo://")
            assert tc.pending
            account = await tc.wait_for_connection(timeout=5)
            assert tc.connected
            assert account.raw_address.startswith("0:")
            await tc.disconnect()
            assert not tc.connected
        finally:
            await sdk.close()

    asyncio.run(run())


def test_sdk_keystore_create_unlock_send(tmp_path):
    """Real-mode keystore flows stay offline-testable via a stub chain."""

    async def run():
        from ton_wallet_assistant.wallet.demo import DemoChainClient

        sdk = TonWalletSDK(network="testnet", data_dir=tmp_path)
        assert not sdk.demo
        assert not sdk.has_keystore

        words, account = await sdk.create_wallet(password="test-password")
        assert len(words) == 24
        assert account.friendly_bounceable.startswith(("kQ", "0Q"))  # testnet flag
        assert sdk.has_keystore and sdk.is_unlocked
        assert sdk.address == account.friendly_bounceable

        # Offline send path through the demo chain backend.
        sdk._chain = DemoChainClient("testnet")
        tx = await sdk.send_ton(DEMO_DEST, "0.25")
        assert tx

        sdk.lock()
        assert not sdk.is_unlocked
        with pytest.raises(RuntimeError):
            await sdk.send_ton(DEMO_DEST, "0.1")

        await sdk.unlock_and_derive("test-password")
        assert sdk.is_unlocked and sdk.account.raw_address == account.raw_address

        assert sdk.reveal_mnemonic("test-password") == list(words)
        sdk.delete_wallet("test-password")
        assert not sdk.has_keystore

    asyncio.run(run())


def test_sdk_wrong_password_rejected(tmp_path):
    from ton_wallet_assistant.wallet.keystore import WrongPasswordError

    async def run():
        sdk = TonWalletSDK(network="mainnet", data_dir=tmp_path)
        await sdk.create_wallet(password="test-password")
        with pytest.raises(WrongPasswordError):
            await sdk.unlock_and_derive("wrong-password")

    asyncio.run(run())


def test_sdk_locked_send_raises(tmp_path):
    async def run():
        from ton_wallet_assistant.wallet.demo import DemoChainClient

        sdk = TonWalletSDK(network="mainnet", data_dir=tmp_path)
        await sdk.create_wallet(password="test-password")
        sdk.lock()
        sdk._chain = DemoChainClient()
        with pytest.raises(RuntimeError):
            await sdk.send_ton(DEMO_DEST, "1")
        await sdk.close()

    asyncio.run(run())


def test_sdk_send_jetton_unknown_symbol(tmp_path):
    async def run():
        sdk = await TonWalletSDK.demo()
        with pytest.raises(ChainError):
            await sdk.send_jetton("NOSUCH", DEMO_DEST, "1")
        await sdk.close()

    asyncio.run(run())


def test_sdk_builders():
    body = TonWalletSDK.build_transfer_body("hi")
    cs = body.begin_parse()
    assert cs.load_uint(32) == 0
    assert cs.load_snake_bytes().decode() == "hi"
    cell = TonWalletSDK.build_jetton_transfer(
        DEMO_DEST, 1_000_000, "UQAREREREREREREREREREREREREREREREREREREREREREbvW", comment="c"
    )
    assert cell is not None
