import pytest

from ton_wallet_assistant.address_utils import AddressError, is_friendly_address
from ton_wallet_assistant.models import (
    ConnectedAccount,
    ConnectionState,
    ServiceEvent,
    WalletOption,
)

RAW = "0:83dfd552e63729b472fcbcc8c45ebcc6691702558b68ec7527e1ba403a0f31a8"

TONCONNECT_WALLET = {
    "app_name": "telegram-wallet",
    "name": "Wallet",
    "image": "https://wallet.tg/images/logo-288.png",
    "about_url": "https://wallet.tg/",
    "universal_url": "https://t.me/wallet?attach=wallet",
    "bridge": [{"type": "sse", "url": "https://bridge.tonapi.io/bridge"}],
    "platforms": ["ios", "android", "macos", "windows", "linux"],
}

WALLET_INFO = {
    "account": {"address": RAW, "chain": "-239", "public_key": "ab" * 32},
    "device": {"app_name": "Tonkeeper", "platform": "iphone"},
}


def test_wallet_option_from_tonconnect():
    w = WalletOption.from_tonconnect(TONCONNECT_WALLET)
    assert w.name == "Wallet"
    assert w.app_name == "telegram-wallet"
    assert w.universal_url.startswith("https://t.me/")
    assert w.bridge_url == "https://bridge.tonapi.io/bridge"
    assert w.supports_desktop
    assert w.raw is TONCONNECT_WALLET


def test_wallet_option_minimal():
    w = WalletOption.from_tonconnect({"name": "Bare"})
    assert w.name == "Bare"
    assert w.app_name == "Bare"
    assert w.bridge_url == ""


def test_connected_account_from_tonconnect():
    acc = ConnectedAccount.from_tonconnect(WALLET_INFO)
    assert acc.raw_address == RAW
    assert acc.network == "mainnet"
    assert acc.workchain == 0
    assert acc.wallet_app == "Tonkeeper"
    assert acc.device_platform == "iphone"
    assert is_friendly_address(acc.friendly_bounceable)
    assert is_friendly_address(acc.friendly_non_bounceable)
    assert acc.friendly_bounceable != acc.friendly_non_bounceable
    assert "…" in acc.short_address


def test_connected_account_testnet_flag():
    info = {
        "account": {"address": RAW, "chain": "-3"},
        "device": {},
    }
    acc = ConnectedAccount.from_tonconnect(info)
    assert acc.network == "testnet"
    # testnet-friendly addresses carry the test-only flag (k…/0… prefixes)
    assert acc.friendly_bounceable.startswith("k")


def test_connected_account_missing_address():
    with pytest.raises(AddressError):
        ConnectedAccount.from_tonconnect({"account": {}, "device": {}})


def test_service_event_defaults():
    ev = ServiceEvent(state=ConnectionState.DISCONNECTED)
    assert ev.account is None
    assert ev.error == ""
    assert ev.link == ""
