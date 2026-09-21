"""Mobile companion pairing demo — fully offline.

Starts the SDK's companion bridge, then simulates a phone relaying a
scanned ``ton://`` transfer and a TonConnect universal link to it, and
approves them programmatically. On a real phone you would open the
pairing URL and scan QR codes with the camera instead.

Run:  python examples/pairing_demo.py
"""

import asyncio
import json
import time
from urllib.parse import quote

import httpx

from ton_wallet_assistant.companion.protocol import new_nonce
from ton_wallet_assistant.sdk import TonWalletSDK

DEST = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"  # burn address


async def phone_relay(port: int, token: str, payload: str) -> str:
    """What the mobile scanner page does: POST the scanned payload."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"http://127.0.0.1:{port}/api/relay",
            json={"payload": payload, "nonce": new_nonce(), "ts": int(time.time())},
            headers={"X-Pairing-Token": token},
        )
        r.raise_for_status()
        return r.json()["id"]


async def main() -> None:
    sdk = await TonWalletSDK.demo()
    try:
        url = await sdk.start_pairing(host="127.0.0.1")  # LAN: host="0.0.0.0"
        print(f"Pairing URL (open on phone / QR): {url}\n")

        # Phone scans a ton:// transfer QR somewhere and relays it.
        req_id = await phone_relay(
            sdk.pairing.port, sdk.pairing.token,
            f"ton://transfer/{DEST}?amount=2500000000&text=coffee",
        )
        req = sdk.pairing.get(req_id)
        print(f"Incoming request from {req.origin_ip}: send "
              f"{req.payload.amount_text} -> {req.payload.address[:14]}…")

        # Desktop approval — in the GUI this is the Approve/Reject dialog;
        # real mode would ask for the wallet password here.
        result = await sdk.approve_pairing_request(req_id)
        print(f"  approved -> {result} (state={req.state.value})\n")

        # Phone scans a TonConnect universal link.
        tc_r = quote(json.dumps({"items": [{"name": "ton_addr"}]}))
        req_id = await phone_relay(
            sdk.pairing.port, sdk.pairing.token,
            f"tc://connect?v=2&id={'a' * 64}&r={tc_r}",
        )
        result = await sdk.approve_pairing_request(req_id)
        print(f"TonConnect link relay -> {result}\n")

        # Rejecting works too.
        req_id = await phone_relay(
            sdk.pairing.port, sdk.pairing.token,
            f"ton://transfer/{DEST}?amount=1",
        )
        sdk.reject_pairing_request(req_id)
        print(f"Rejected request state: {sdk.pairing.get(req_id).state.value}")
    finally:
        await sdk.close()


if __name__ == "__main__":
    asyncio.run(main())
