"""Telegram integration demo — fully offline (DemoTelegramClient).

Shows the SDK-side auth flow: start → submit phone → submit the demo
code ``12345`` → ready → list chats → send a message → watch updates.

For real operation, build a TdJsonClient from TelegramConfig (env:
TELEGRAM_API_ID / TELEGRAM_API_HASH / optional TDLIB_PATH) — the client
is pure Python and loads the prebuilt libtdjson via ctypes at runtime;
no Cython, C extensions, or generated bindings are involved.

Run:  python examples/telegram_demo.py
"""

import asyncio

from ton_wallet_assistant.sdk import TonWalletSDK
from ton_wallet_assistant.telegram import TelegramAuthState


async def main() -> None:
    sdk = await TonWalletSDK.demo()
    try:
        tg = sdk.telegram  # DemoTelegramClient in demo mode
        await tg.start()
        print(f"auth state: {tg.auth_state.value}")

        await tg.submit_phone("+15551234567")
        await tg.submit_code("12345")  # demo login code
        print(f"auth state: {tg.auth_state.value}  (ready={tg.is_ready})")

        for chat in await tg.get_chats():
            print(f"  chat {chat['id']}: {chat['title']}")

        await tg.send_message(1, "demo hello from the SDK")

        # Drain updates for a moment.
        updates = []
        async def collect():
            async for u in tg.updates():
                updates.append(u)
        collector = asyncio.create_task(collect())
        await asyncio.sleep(0.2)
        collector.cancel()
        for u in updates:
            label = u.data.get("text", u.data.get("state", ""))
            print(f"  update {u.type}: {label}")

        await tg.close()
        assert tg.auth_state is TelegramAuthState.CLOSED
        print("closed cleanly")
    finally:
        await sdk.close()


if __name__ == "__main__":
    asyncio.run(main())
