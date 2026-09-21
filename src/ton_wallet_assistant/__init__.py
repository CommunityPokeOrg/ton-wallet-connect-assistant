"""TON Wallet Connect Assistant — Tonkeeper-style desktop TON wallet + headless SDK."""

__version__ = "0.1.0"


def __getattr__(name: str):
    if name == "TonWalletSDK":
        from .sdk import TonWalletSDK

        return TonWalletSDK
    if name == "TonConnectClient":
        from .sdk import TonConnectClient

        return TonConnectClient
    raise AttributeError(name)


__all__ = ["TonConnectClient", "TonWalletSDK", "__version__"]
