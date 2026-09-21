"""Entry point: ``python -m ton_wallet_assistant`` or the ``ton-wallet-assistant`` script."""

from __future__ import annotations

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ton-wallet-assistant",
        description="Desktop assistant for connecting a TON wallet via TonConnect.",
    )
    parser.add_argument(
        "--manifest-url",
        help="HTTPS URL of the tonconnect-manifest.json for this app (enables real connections).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Force demo mode (mock wallet, no network, clearly labelled).",
    )
    parser.add_argument(
        "--demo-network",
        choices=["mainnet", "testnet"],
        help="Network the demo wallet pretends to use (default: mainnet).",
    )
    parser.add_argument(
        "--network",
        choices=["mainnet", "testnet"],
        help="Blockchain network for the wallet (default: mainnet).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from .config import AppConfig
    from .gui import run_app
    from .services import DemoWalletService, TonConnectService

    args = build_parser().parse_args(argv)
    config = AppConfig.resolve(
        manifest_url=args.manifest_url,
        demo=True if args.demo else None,
        demo_network=args.demo_network,
        network=args.network,
    )

    if config.demo_mode:
        service = DemoWalletService(network=config.demo_network)
    else:
        service = TonConnectService(config.manifest_url, config.storage_path)

    return run_app(config, service)


def run() -> None:  # console-script wrapper
    sys.exit(main())


if __name__ == "__main__":
    run()
