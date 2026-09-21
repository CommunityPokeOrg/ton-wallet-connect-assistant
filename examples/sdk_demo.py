"""SDK walkthrough — fully offline demo mode (no keys, no network).

Run:  python examples/sdk_demo.py
"""

import asyncio

from ton_wallet_assistant.sdk import TonWalletSDK

DEMO_DEST = "UQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJKZ"  # zero account


async def main() -> None:
    sdk = await TonWalletSDK.demo()
    try:
        print("Demo wallet:", sdk.account.friendly_bounceable)
        print("Balance:", await sdk.get_balance_ton(), "TON")

        print("\nJettons:")
        for j in await sdk.get_jettons():
            print(f"  {j.symbol:<6} {j.balance}  ({j.name})")

        print("\nCollectibles:")
        for nft in await sdk.get_nfts():
            print(f"  {nft.name}  — {nft.collection}")

        print("\nSending 1.5 TON (demo)…")
        tx = await sdk.send_ton(DEMO_DEST, "1.5", comment="hello from the SDK")
        print("  broadcast:", tx[:16], "…")

        print("Sending 10.5 dUSD (demo)…")
        await sdk.send_jetton("dUSD", DEMO_DEST, "10.5")

        print("\nRecent history:")
        for rec in (await sdk.get_history())[:5]:
            sign = "+" if rec.direction == "in" else "-"
            print(f"  {sign}{rec.formatted_amount} {rec.asset:<5} [{rec.status}] {rec.comment}")

        # TonConnect session lifecycle (demo wallet auto-approves):
        wallets = await sdk.tonconnect.list_wallets()
        link = await sdk.tonconnect.request_connection(wallets[0])
        print("\nTonConnect link:", link[:60], "…")
        account = await sdk.tonconnect.wait_for_connection(timeout=5)
        print("Connected as:", account.short_address, "via", account.wallet_app)
        await sdk.tonconnect.disconnect()
    finally:
        await sdk.close()


if __name__ == "__main__":
    asyncio.run(main())
