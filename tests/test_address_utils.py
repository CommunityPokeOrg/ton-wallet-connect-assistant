"""Address conversion tests using reference vectors from the TON ecosystem."""

import pytest

from ton_wallet_assistant.address_utils import (
    AddressError,
    chain_from_network,
    crc16_xmodem,
    friendly_to_raw,
    is_friendly_address,
    is_raw_address,
    network_from_chain,
    parse_raw_address,
    raw_to_friendly,
)

# (raw, bounceable, non_bounceable, testnet_bounceable) — generated with pytoniq-core.
VECTORS = [
    (
        "0:83dfd552e63729b472fcbcc8c45ebcc6691702558b68ec7527e1ba403a0f31a8",
        "EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2N",
        "UQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqEBI",
        "kQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqKYH",
    ),
    (
        "0:0000000000000000000000000000000000000000000000000000000000000000",
        "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c",
        "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ",
        "kQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAHTW",
    ),
    (
        "-1:3333333333333333333333333333333333333333333333333333333333333333",
        "Ef8zMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzM0vF",
        "Uf8zMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMxYA",
        "kf8zMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzM_BP",
    ),
    (
        "0:e2a2ef49ef944e56b1605ad4f6a3f3dc711675ef44e1d53459b14c1be40e6e1c",
        "EQDiou9J75ROVrFgWtT2o_PccRZ170Th1TRZsUwb5A5uHF4P",
        "UQDiou9J75ROVrFgWtT2o_PccRZ170Th1TRZsUwb5A5uHAPK",
        "kQDiou9J75ROVrFgWtT2o_PccRZ170Th1TRZsUwb5A5uHOWF",
    ),
]


@pytest.mark.parametrize("raw,bounceable,non_bounceable,testnet", VECTORS)
def test_raw_to_friendly(raw, bounceable, non_bounceable, testnet):
    assert raw_to_friendly(raw) == bounceable
    assert raw_to_friendly(raw, bounceable=False) == non_bounceable
    assert raw_to_friendly(raw, test_only=True) == testnet


@pytest.mark.parametrize("raw,bounceable,non_bounceable,testnet", VECTORS)
def test_friendly_to_raw_roundtrip(raw, bounceable, non_bounceable, testnet):
    for friendly, expected_bounce, expected_test in (
        (bounceable, True, False),
        (non_bounceable, False, False),
        (testnet, True, True),
    ):
        workchain, account_id, is_bounce, is_test = friendly_to_raw(friendly)
        assert f"{workchain}:{account_id.hex()}" == raw
        assert is_bounce is expected_bounce
        assert is_test is expected_test


def test_crc16_xmodem_known_value():
    # CRC16-XMODEM of "123456789" is 0x31C3.
    assert crc16_xmodem(b"123456789") == 0x31C3


def test_friendly_bad_checksum_rejected():
    bad = "EQCD39VS5jcptHL8vMjEXrzGaRcCVYto7HUn4bpAOg8xqB2O"  # last char changed
    assert not is_friendly_address(bad)
    with pytest.raises(AddressError):
        friendly_to_raw(bad)


@pytest.mark.parametrize(
    "raw",
    [
        "not-an-address",
        "0:xyz",
        "0:1234",
        "x:00" + "00" * 31,
        "0",
        "",
    ],
)
def test_parse_raw_address_invalid(raw):
    assert not is_raw_address(raw)
    with pytest.raises(AddressError):
        parse_raw_address(raw)


def test_network_chain_mapping():
    assert network_from_chain("-239") == "mainnet"
    assert network_from_chain("-3") == "testnet"
    assert network_from_chain("bogus") == "unknown"
    assert network_from_chain(None) == "unknown"
    assert chain_from_network("testnet") == "-3"
    assert chain_from_network("mainnet") == "-239"
