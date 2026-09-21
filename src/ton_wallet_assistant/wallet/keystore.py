"""Encrypted keystore for the wallet mnemonic.

The 24-word TON mnemonic is the only secret this app ever holds. It is stored
at rest as a NaCl SecretBox (XSalsa20-Poly1305) ciphertext whose key is derived
from the user's password with argon2id — the same construction used by wallet
software generally. The plaintext mnemonic is only decrypted in memory for the
short window needed to sign or display it.

File format (JSON)::

    {
      "version": 1,
      "kdf": "argon2id",
      "salt": "<b64>", "opslimit": 3, "memlimit": 67108864,
      "nonce": "<b64>", "ciphertext": "<b64>",
      "wallet_version": "v4r2",
      "network": "mainnet",
      "created": 1700000000,
      "address_hint": "EQ…"          // public, non-secret, for UI display
    }
"""

from __future__ import annotations

import base64
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

KEYSTORE_VERSION = 1


class KeystoreError(Exception):
    pass


class WrongPasswordError(KeystoreError):
    pass


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def _derive_key(password: str, salt: bytes, opslimit: int, memlimit: int) -> bytes:
    import nacl.pwhash

    return nacl.pwhash.argon2id.kdf(
        nacl.secret.SecretBox.KEY_SIZE,
        password.encode("utf-8"),
        salt,
        opslimit=opslimit,
        memlimit=memlimit,
    )


@dataclass(frozen=True)
class KeystoreMeta:
    """Non-secret metadata readable without unlocking."""

    wallet_version: str
    network: str
    created: int
    address_hint: str


class Keystore:
    """Password-encrypted mnemonic stored as a local JSON file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._plaintext: list[str] | None = None  # unlocked mnemonic words

    # ------------------------------------------------------------ metadata

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def is_unlocked(self) -> bool:
        return self._plaintext is not None

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except OSError as exc:
            raise KeystoreError(f"Cannot read keystore: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise KeystoreError("Keystore file is corrupted") from exc

    def meta(self) -> KeystoreMeta:
        data = self._read()
        return KeystoreMeta(
            wallet_version=data.get("wallet_version", "v4r2"),
            network=data.get("network", "mainnet"),
            created=int(data.get("created", 0)),
            address_hint=data.get("address_hint", ""),
        )

    # ------------------------------------------------------------ lifecycle

    def create(
        self,
        mnemonic: list[str],
        password: str,
        *,
        wallet_version: str = "v4r2",
        network: str = "mainnet",
        address_hint: str = "",
    ) -> None:
        """Encrypt ``mnemonic`` with ``password`` and write the keystore file."""
        if self.exists:
            raise KeystoreError("Keystore already exists; delete it first")
        if len(password) < 8:
            raise KeystoreError("Password must be at least 8 characters")
        import nacl.pwhash
        import nacl.secret
        import nacl.utils

        salt = nacl.utils.random(nacl.pwhash.argon2id.SALTBYTES)
        opslimit = nacl.pwhash.argon2id.OPSLIMIT_INTERACTIVE
        memlimit = nacl.pwhash.argon2id.MEMLIMIT_INTERACTIVE
        key = _derive_key(password, salt, opslimit, memlimit)
        nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
        box = nacl.secret.SecretBox(key)
        plaintext = " ".join(mnemonic).encode("utf-8")
        ciphertext = box.encrypt(plaintext, nonce).ciphertext

        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": KEYSTORE_VERSION,
            "kdf": "argon2id",
            "salt": _b64e(salt),
            "opslimit": opslimit,
            "memlimit": memlimit,
            "nonce": _b64e(nonce),
            "ciphertext": _b64e(ciphertext),
            "wallet_version": wallet_version,
            "network": network,
            "created": int(time.time()),
            "address_hint": address_hint,
        }
        # Write atomically: tempfile + rename, with owner-only permissions.
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, self.path)
        self._plaintext = list(mnemonic)

    def unlock(self, password: str) -> list[str]:
        """Decrypt and return the mnemonic words. Raises WrongPasswordError."""
        import nacl.secret

        data = self._read()
        if data.get("kdf") != "argon2id":
            raise KeystoreError(f"Unsupported kdf {data.get('kdf')!r}")
        key = _derive_key(
            password,
            _b64d(data["salt"]),
            int(data["opslimit"]),
            int(data["memlimit"]),
        )
        box = nacl.secret.SecretBox(key)
        try:
            plaintext = box.decrypt(_b64d(data["ciphertext"]), _b64d(data["nonce"]))
        except Exception as exc:
            raise WrongPasswordError("Incorrect password") from exc
        self._plaintext = plaintext.decode("utf-8").split()
        return list(self._plaintext)

    def lock(self) -> None:
        if self._plaintext is not None:
            for i in range(len(self._plaintext)):
                self._plaintext[i] = "x" * len(self._plaintext[i])
        self._plaintext = None

    def mnemonic(self) -> list[str]:
        """The unlocked mnemonic. Raises if locked — callers must unlock first."""
        if self._plaintext is None:
            raise KeystoreError("Keystore is locked")
        return list(self._plaintext)

    def change_password(self, old_password: str, new_password: str) -> None:
        mnemonic = self.unlock(old_password)
        meta = self.meta()
        self.delete()
        self.create(
            mnemonic,
            new_password,
            wallet_version=meta.wallet_version,
            network=meta.network,
            address_hint=meta.address_hint,
        )

    def delete(self) -> None:
        self.lock()
        if self.exists:
            self.path.unlink()
