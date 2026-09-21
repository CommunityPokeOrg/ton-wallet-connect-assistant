import asyncio

from ton_wallet_assistant.address_utils import is_friendly_address, is_raw_address
from ton_wallet_assistant.models import ConnectionState, ServiceEvent
from ton_wallet_assistant.services.demo import DemoWalletService


def _collect(service: DemoWalletService) -> list[ServiceEvent]:
    events: list[ServiceEvent] = []
    service.set_event_callback(events.append)
    return events


def test_demo_list_wallets():
    service = DemoWalletService(connect_delay=0)
    wallets = asyncio.run(service.list_wallets())
    assert len(wallets) == 1
    assert wallets[0].app_name == "demo-wallet"


def test_demo_connect_link_format():
    service = DemoWalletService(connect_delay=10)

    async def run():
        link = await service.connect((await service.list_wallets())[0])
        await service.close()
        return link

    link = asyncio.run(run())
    assert link.startswith("demo://wallet.demo/ton-connect?v=2&id=")
    assert "%7B" in link or "manifestUrl" in link  # urlencoded connect request


def test_demo_full_connect_disconnect_cycle():
    async def run():
        service = DemoWalletService(network="testnet", connect_delay=0.01)
        events = _collect(service)
        wallet = (await service.list_wallets())[0]
        await service.connect(wallet)
        for _ in range(200):
            if any(e.state == ConnectionState.CONNECTED for e in events):
                break
            await asyncio.sleep(0.01)
        connected = [e for e in events if e.state == ConnectionState.CONNECTED]
        assert connected, "demo wallet never connected"
        account = connected[0].account
        assert account is not None
        assert account.network == "testnet"
        assert is_raw_address(account.raw_address)
        assert is_friendly_address(account.friendly_bounceable)
        assert await service.restore() is True
        await service.disconnect()
        assert events[-1].state == ConnectionState.DISCONNECTED

    asyncio.run(run())


def test_demo_cancelled_connect_emits_nothing():
    async def run():
        service = DemoWalletService(connect_delay=10)
        events = _collect(service)
        wallet = (await service.list_wallets())[0]
        await service.connect(wallet)
        await service.connect(wallet)  # replaces the pending request
        await service.close()
        assert not [e for e in events if e.state == ConnectionState.CONNECTED]

    asyncio.run(run())
