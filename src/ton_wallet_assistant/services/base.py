"""Backend interface used by the GUI to talk to wallets."""

from __future__ import annotations

import abc
from collections.abc import Callable

from ..models import ServiceEvent, WalletOption

EventCallback = Callable[[ServiceEvent], None]


class WalletService(abc.ABC):
    """Common contract for real (TonConnect) and demo wallet backends.

    All methods are coroutines executed on the GUI-managed asyncio loop. The
    backend reports asynchronous wallet events (approval, rejection, disconnect)
    through the callback set with :meth:`set_event_callback`.
    """

    def __init__(self) -> None:
        self._on_event: EventCallback | None = None

    def set_event_callback(self, callback: EventCallback | None) -> None:
        self._on_event = callback

    def _emit(self, event: ServiceEvent) -> None:
        if self._on_event is not None:
            self._on_event(event)

    @abc.abstractmethod
    async def list_wallets(self) -> list[WalletOption]:
        """Return the wallets the user can connect through."""

    @abc.abstractmethod
    async def connect(self, wallet: WalletOption) -> str:
        """Start a connection request and return the universal link to display."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Terminate the current session."""

    @abc.abstractmethod
    async def restore(self) -> bool:
        """Attempt to restore a previously approved session. Returns connected-ness."""

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources (SSE streams, sessions)."""
