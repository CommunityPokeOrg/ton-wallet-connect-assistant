"""Wallet account derivation: mnemonic -> keypair -> wallet contract address.

Uses ``pytoniq-core`` for TON mnemonics (24 BIP-39-english words + local PBKDF2
password check) and ``pytoniq`` wallet-contract classes to derive the on-chain
address of a v4r2/v5r1 wallet. Address derivation is fully offline — no network
access is needed (or made) here.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..address_utils import raw_to_friendly

SUPPORTED_VERSIONS = ("v4r2", "v5r1")
DEFAULT_VERSION = "v4r2"


class MnemonicError(ValueError):
    pass


def generate_mnemonic() -> list[str]:
    """Generate a fresh 24-word TON mnemonic."""
    from pytoniq_core.crypto.keys import mnemonic_new

    return list(mnemonic_new())


def validate_mnemonic(words: list[str]) -> list[str]:
    """Normalize and validate a mnemonic phrase. Returns the word list."""
    normalized = [w.strip().lower() for w in words if w.strip()]
    if len(normalized) != 24:
        raise MnemonicError(f"A TON mnemonic has 24 words, got {len(normalized)}")
    from pytoniq_core.crypto.keys import mnemonic_is_valid

    try:
        ok = mnemonic_is_valid(normalized)
    except Exception as exc:
        raise MnemonicError(f"Invalid mnemonic: {exc}") from exc
    if not ok:
        raise MnemonicError("Mnemonic failed the TON seed check")
    return normalized


def parse_mnemonic_text(text: str) -> list[str]:
    """Split pasted text (whitespace/comma separated) into words."""
    return text.replace(",", " ").split()


def keypair_from_mnemonic(words: list[str]) -> tuple[bytes, bytes]:
    """Return ``(public_key, secret_key)`` for a TON mnemonic."""
    from pytoniq_core.crypto.keys import mnemonic_to_private_key

    public_key, secret_key = mnemonic_to_private_key(list(words))
    return public_key, secret_key


def private_key_from_mnemonic(words: list[str]) -> bytes:
    return keypair_from_mnemonic(words)[1]


@dataclass(frozen=True)
class WalletAccount:
    """A derived wallet account. Contains no secret material."""

    raw_address: str
    friendly_bounceable: str
    friendly_non_bounceable: str
    public_key_hex: str
    wallet_version: str
    network: str  # mainnet | testnet (affects friendly-address test flag only)

    @property
    def short_address(self) -> str:
        a = self.friendly_bounceable
        return f"{a[:8]}…{a[-6:]}"


class _OfflineProvider:
    """Stand-in provider for deriving wallet state/address without a network.

    ``pytoniq`` wallet classes only use the provider when sending/fetching;
    constructing them offline is safe.
    """

    async def raw_send_message(self, message):  # pragma: no cover - never called offline
        raise RuntimeError("offline provider cannot send")

    async def raw_get_account_state(self, address):
        # from_address() unpacks (account, shard_account); None leaves the
        # contract usable for pure address derivation.
        return None, None


async def derive_account(
    words: list[str], *, network: str = "mainnet", wallet_version: str = DEFAULT_VERSION
) -> WalletAccount:
    """Derive a wallet account (address + public key) from a mnemonic."""
    if wallet_version not in SUPPORTED_VERSIONS:
        raise ValueError(f"unsupported wallet version {wallet_version!r}")
    if network not in ("mainnet", "testnet"):
        raise ValueError(f"unsupported network {network!r}")

    public_key, private_key = keypair_from_mnemonic(words)

    wallet = await _wallet_from_key(private_key, wallet_version, network)
    raw = wallet.address.to_str(is_user_friendly=False)
    test_only = network == "testnet"
    return WalletAccount(
        raw_address=raw,
        friendly_bounceable=raw_to_friendly(raw, bounceable=True, test_only=test_only),
        friendly_non_bounceable=raw_to_friendly(raw, bounceable=False, test_only=test_only),
        public_key_hex=public_key.hex(),
        wallet_version=wallet_version,
        network=network,
    )


async def _wallet_from_key(private_key: bytes, wallet_version: str, network: str = "mainnet"):
    if wallet_version == "v5r1":
        from pytoniq.contract.wallets import WalletV5R1

        return await WalletV5R1.from_private_key(
            provider=_OfflineProvider(),
            private_key=private_key,
            network_global_id=-3 if network == "testnet" else -239,
        )
    from pytoniq.contract.wallets import WalletV4R2

    return await WalletV4R2.from_private_key(provider=_OfflineProvider(), private_key=private_key)


def mnemonic_is_valid(words: list[str]) -> bool:
    try:
        validate_mnemonic(words)
    except MnemonicError:
        return False
    return True
