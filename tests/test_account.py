import asyncio

import pytest

from ton_wallet_assistant.address_utils import is_friendly_address, is_raw_address
from ton_wallet_assistant.wallet import account as acct

# A deterministic TON mnemonic generated for these tests (do not use with real funds).
TEST_MNEMONIC = (
    "type actor lazy december oppose dish change give frog session guard sell "
    "crazy doll grocery version strike digital life holiday burden amazing fold process"
).split()

# Address derived once from TEST_MNEMONIC and frozen here as a regression vector.
V4R2_MAINNET_BOUNCEABLE = "EQDh0VnvdLjjsJ2KidJ9xgkpkpFJNLarl-mHbfy_Ec42121d"


def test_generate_mnemonic_24_words():
    words = acct.generate_mnemonic()
    assert len(words) == 24
    assert all(w.isalpha() for w in words)


def test_validate_mnemonic_accepts_known_phrase():
    assert acct.validate_mnemonic(TEST_MNEMONIC) == TEST_MNEMONIC


def test_validate_mnemonic_rejects_bad_word_count():
    with pytest.raises(acct.MnemonicError):
        acct.validate_mnemonic(TEST_MNEMONIC[:12])
    with pytest.raises(acct.MnemonicError):
        acct.validate_mnemonic(TEST_MNEMONIC + ["extra"])


def test_validate_mnemonic_rejects_garbage():
    with pytest.raises(acct.MnemonicError):
        acct.validate_mnemonic(["notaword"] * 24)


def test_parse_mnemonic_text():
    text = "  dose, ice  enrich\n trigger "
    assert acct.parse_mnemonic_text(text) == ["dose", "ice", "enrich", "trigger"]


def test_keypair_deterministic():
    pk1, sk1 = acct.keypair_from_mnemonic(TEST_MNEMONIC)
    pk2, sk2 = acct.keypair_from_mnemonic(TEST_MNEMONIC)
    assert pk1 == pk2 and sk1 == sk2
    assert len(sk1) == 64 and len(pk1) == 32


def test_derive_account_v4r2_offline():
    account = asyncio.run(acct.derive_account(TEST_MNEMONIC, network="mainnet"))
    assert account.friendly_bounceable == V4R2_MAINNET_BOUNCEABLE
    assert is_raw_address(account.raw_address)
    assert is_friendly_address(account.friendly_bounceable)
    assert is_friendly_address(account.friendly_non_bounceable)
    assert account.wallet_version == "v4r2"
    assert account.network == "mainnet"
    assert len(account.public_key_hex) == 64


def test_derive_account_v5r1_differs_from_v4r2():
    a4 = asyncio.run(acct.derive_account(TEST_MNEMONIC, wallet_version="v4r2"))
    a5 = asyncio.run(acct.derive_account(TEST_MNEMONIC, wallet_version="v5r1"))
    assert a4.raw_address != a5.raw_address


def test_derive_account_testnet_flag():
    account = asyncio.run(acct.derive_account(TEST_MNEMONIC, network="testnet"))
    assert account.friendly_bounceable.startswith("k")
    assert account.network == "testnet"


def test_derive_account_bad_version():
    with pytest.raises(ValueError):
        asyncio.run(acct.derive_account(TEST_MNEMONIC, wallet_version="v9r9"))
