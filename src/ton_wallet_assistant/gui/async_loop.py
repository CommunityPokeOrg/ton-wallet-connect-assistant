"""Dedicated asyncio loop on a daemon thread, bridged to Qt."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from concurrent.futures import Future

from PySide6.QtCore import QObject, Signal


class AsyncLoop(QObject):
    """Runs wallet/chain I/O without blocking the Qt UI thread.

    Coroutines are submitted with :meth:`submit`; results and wallet events are
    marshalled back to the GUI thread via Qt signals.
    """

    invoke_in_gui = Signal(object)  # callable -> executed on the GUI thread

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.invoke_in_gui.connect(self._run_callable)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop_runner, name="wallet-io", daemon=True)
        self._thread.start()

    def _loop_runner(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_callable(self, fn: Callable) -> None:
        fn()

    def post_to_gui(self, fn: Callable) -> None:
        self.invoke_in_gui.emit(fn)

    def submit(self, coro, on_done: Callable | None = None) -> Future:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done(f: Future) -> None:
            def deliver() -> None:
                try:
                    result = f.result()
                except asyncio.CancelledError:
                    return
                except Exception as exc:
                    if on_done:
                        on_done(None, exc)
                    return
                if on_done:
                    on_done(result, None)

            self.post_to_gui(deliver)

        if on_done:
            future.add_done_callback(_done)
        return future

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
