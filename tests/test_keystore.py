import stat
from pathlib import Path

import pytest

from ton_wallet_assistant.wallet.keystore import Keystore, KeystoreError, WrongPasswordError

MNEMONIC = [f"word{i:02d}" for i in range(24)]
PASSWORD = "correct horse battery"


@pytest.fixture()
def ks_path(tmp_path: Path) -> Path:
    return tmp_path / "keystore.json"


def test_create_unlock_roundtrip(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD, wallet_version="v4r2", network="mainnet", address_hint="EQtest")
    assert ks.exists
    assert ks.is_unlocked
    ks.lock()
    assert not ks.is_unlocked
    words = ks.unlock(PASSWORD)
    assert words == MNEMONIC


def test_file_permissions_owner_only(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    mode = stat.S_IMODE(ks_path.stat().st_mode)
    assert mode & 0o077 == 0  # no group/other access


def test_wrong_password(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    ks.lock()
    with pytest.raises(WrongPasswordError):
        ks.unlock("wrong password here")


def test_short_password_rejected(ks_path):
    ks = Keystore(ks_path)
    with pytest.raises(KeystoreError):
        ks.create(MNEMONIC, "short")


def test_create_twice_rejected(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    with pytest.raises(KeystoreError):
        ks.create(MNEMONIC, PASSWORD)


def test_locked_mnemonic_raises(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    ks.lock()
    with pytest.raises(KeystoreError):
        ks.mnemonic()


def test_meta_without_unlock(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD, wallet_version="v5r1", network="testnet", address_hint="kQabc")
    ks.lock()
    meta = Keystore(ks_path).meta()
    assert meta.wallet_version == "v5r1"
    assert meta.network == "testnet"
    assert meta.address_hint == "kQabc"


def test_change_password(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    ks.lock()
    ks.change_password(PASSWORD, "new longer password")
    ks.lock()
    assert Keystore(ks_path).unlock("new longer password") == MNEMONIC


def test_delete(ks_path):
    ks = Keystore(ks_path)
    ks.create(MNEMONIC, PASSWORD)
    ks.delete()
    assert not ks.exists
    assert not ks.is_unlocked
