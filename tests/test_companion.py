"""Tests for the mobile companion pairing bridge: validation, replay
protection, auth, the approval state machine, and the SDK integration."""

import asyncio
import json
import time
from urllib.parse import quote

import httpx
import pytest

from ton_wallet_assistant.companion import (
    PairingManager,
    PayloadKind,
    RequestState,
)
from ton_wallet_assistant.companion.protocol import (
    MAX_PAYLOAD_BYTES,
    NonceTracker,
    ReplayError,
    TonConnectLinkDetails,
    TransferDetails,
    ValidationError,
    new_nonce,
    parse_payload,
)
from ton_wallet_assistant.sdk import TonWalletSDK

DEST = "EQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAM9c"
TON_LINK = f"ton://transfer/{DEST}?amount=1500000000&text=hi%20there"
TC_R = quote(json.dumps({"items": [{"name": "ton_addr"}]}))
TC_LINK = f"tc://connect?v=2&id={'a' * 64}&r={TC_R}"
TC_HTTPS = f"https://app.tonkeeper.com/ton-connect?v=2&id={'b' * 64}&r={TC_R}"


def _relay_payload(payload=TON_LINK, **over):
    body = {"payload": payload, "nonce": new_nonce(), "ts": int(time.time())}
    body.update(over)
    return body


# --------------------------------------------------------------- validation


def test_parse_ton_transfer():
    kind, payload = parse_payload(TON_LINK)
    assert kind is PayloadKind.TON_TRANSFER
    assert isinstance(payload, TransferDetails)
    assert payload.address == DEST
    assert payload.amount_nano == 1_500_000_000
    assert payload.comment == "hi there"
    assert payload.amount_text == "1.5 TON"


def test_parse_tonconnect_links():
    for link in (TC_LINK, TC_HTTPS):
        kind, payload = parse_payload(link)
        assert kind is PayloadKind.TONCONNECT_LINK
        assert isinstance(payload, TonConnectLinkDetails)
        assert payload.session_id and "ton_addr" in payload.items


@pytest.mark.parametrize(
    "payload",
    [
        "ftp://example.com/x",
        "ton://other/abc",
        "ton://transfer/not-an-address",
        f"ton://transfer/{DEST}?amount=notanumber",
        f"ton://transfer/{DEST}?amount=-5",
        f"tc://connect?v=1&id={'a' * 64}&r=%7B%7D",
        f"tc://connect?v=2&id=&r={TC_R}",
        f"tc://connect?v=2&id={'a' * 64}&r=not-json",
        "x" * (MAX_PAYLOAD_BYTES + 1),
        "",
    ],
)
def test_parse_rejects_bad_payloads(payload):
    with pytest.raises(ValidationError):
        parse_payload(payload)


# ------------------------------------------------------------------ replay


def test_nonce_tracker_rejects_replay_and_stale():
    tracker = NonceTracker(max_age=60)
    nonce = new_nonce()
    tracker.check(nonce, ts=1000.0, now=1000.0)
    with pytest.raises(ReplayError):
        tracker.check(nonce, ts=1000.0, now=1001.0)  # reuse
    with pytest.raises(ReplayError):
        tracker.check(new_nonce(), ts=900.0, now=1000.0)  # stale ts
    with pytest.raises(ReplayError):
        tracker.check("short", ts=1000.0, now=1000.0)
    # a fresh nonce with a current timestamp is still accepted later
    tracker.check(new_nonce(), ts=1200.0, now=1200.0)


# ------------------------------------------------------------ http bridge


def test_companion_server_auth_relay_and_status():
    async def run():
        manager = PairingManager(host="127.0.0.1", demo=True)
        url = await manager.start()
        assert "/p/" in url
        results = {}

        async def handler(req):
            return "broadcast-demo"

        manager.transfer_handler = handler
        try:
            async with httpx.AsyncClient() as client:
                # pairing page requires the token in the path
                r = await client.get(url)
                assert r.status_code == 200 and "manual" in r.text.lower()
                r = await client.get(url.replace(manager.token, "bad-token"))
                assert r.status_code == 404
                # API requires the token header
                r = await client.post(
                    f"http://127.0.0.1:{manager.port}/api/relay", json=_relay_payload()
                )
                assert r.status_code == 403
                # valid relay → accepted, pending
                r = await client.post(
                    f"http://127.0.0.1:{manager.port}/api/relay",
                    json=_relay_payload(),
                    headers={"X-Pairing-Token": manager.token},
                )
                assert r.status_code == 202, r.text
                req_id = r.json()["id"]
                r = await client.get(
                    f"http://127.0.0.1:{manager.port}/api/requests/{req_id}",
                    headers={"X-Pairing-Token": manager.token},
                )
                assert r.status_code == 200
                assert r.json()["state"] == "pending"
                assert r.json()["details"]["address"] == DEST
                results["req_id"] = req_id
        finally:
            await manager.stop()
        return results

    results = asyncio.run(run())
    assert results["req_id"]


def test_relay_replay_and_bad_payload_rejected():
    async def run():
        manager = PairingManager(host="127.0.0.1", demo=True)
        await manager.start()
        try:
            base = f"http://127.0.0.1:{manager.port}/api/relay"
            headers = {"X-Pairing-Token": manager.token}
            async with httpx.AsyncClient() as client:
                body = _relay_payload()
                r = await client.post(base, json=body, headers=headers)
                assert r.status_code == 202
                # same nonce again → replay
                r = await client.post(base, json=body, headers=headers)
                assert r.status_code == 422 and "replay" in r.json()["error"]
                # stale timestamp
                r = await client.post(
                    base, json=_relay_payload(ts=int(time.time()) - 600), headers=headers
                )
                assert r.status_code == 422
                # invalid payload
                r = await client.post(
                    base, json=_relay_payload("https://phish.example/x"), headers=headers
                )
                assert r.status_code == 422
                # wrong content type
                r = await client.post(base, content=b"{}", headers=headers)
                assert r.status_code == 415
        finally:
            await manager.stop()

    asyncio.run(run())


def test_approval_state_machine():
    async def run():
        manager = PairingManager(host="127.0.0.1", demo=True)
        await manager.start()

        async def handler(req):
            return "demo-result"

        manager.transfer_handler = handler
        try:
            result = manager.submit_from_thread(
                origin_ip="10.0.0.5",
                raw_payload=TON_LINK,
                nonce=new_nonce(),
                ts=time.time(),
            )
            req_id = result["id"]

            pending = manager.pending_requests()
            assert [r.request_id for r in pending] == [req_id]

            # async iterator view sees the same request
            seen = await asyncio.wait_for(anext(manager.requests()), timeout=1)
            assert seen.request_id == req_id

            assert await manager.approve(req_id) == "demo-result"
            assert manager.get(req_id).state is RequestState.COMPLETED
            with pytest.raises(RuntimeError):
                await manager.approve(req_id)  # already completed

            # reject path
            result = manager.submit_from_thread(
                origin_ip="10.0.0.5", raw_payload=TON_LINK, nonce=new_nonce(), ts=time.time()
            )
            manager.reject(result["id"])
            assert manager.get(result["id"]).state is RequestState.REJECTED
            assert manager.pending_requests() == []

            # expiry
            result = manager.submit_from_thread(
                origin_ip="10.0.0.5", raw_payload=TON_LINK, nonce=new_nonce(), ts=time.time()
            )
            stale = manager.get(result["id"])
            stale.received_at = time.time() - 10_000
            assert manager.pending_requests() == []
            with pytest.raises(RuntimeError):
                await manager.approve(result["id"])
            assert stale.state is RequestState.EXPIRED
        finally:
            await manager.stop()

    asyncio.run(run())


# ------------------------------------------------------- SDK integration


def test_sdk_pairing_demo_flow():
    async def run():
        sdk = await TonWalletSDK.demo()
        await sdk.start_pairing(host="127.0.0.1")
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"http://127.0.0.1:{sdk.pairing.port}/api/relay",
                    json=_relay_payload(),
                    headers={"X-Pairing-Token": sdk.pairing.token},
                )
                assert r.status_code == 202
                req_id = r.json()["id"]

            pending = sdk.pairing_pending()
            assert pending and pending[0].request_id == req_id

            result = await sdk.approve_pairing_request(req_id)
            assert sdk.pairing.get(req_id).state is RequestState.COMPLETED
            assert result  # demo broadcast marker

            # TonConnect universal link relays through the demo handler
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"http://127.0.0.1:{sdk.pairing.port}/api/relay",
                    json=_relay_payload(TC_LINK),
                    headers={"X-Pairing-Token": sdk.pairing.token},
                )
                req_id = r.json()["id"]
            result = await sdk.approve_pairing_request(req_id)
            assert result.startswith("demo:")
        finally:
            await sdk.close()

    asyncio.run(run())


def test_pairing_url_is_loopback_when_bound_to_loopback():
    async def run():
        sdk = await TonWalletSDK.demo()
        url = await sdk.start_pairing(host="127.0.0.1")
        await sdk.close()
        return url

    url = asyncio.run(run())
    assert url.startswith("http://127.0.0.1:")
