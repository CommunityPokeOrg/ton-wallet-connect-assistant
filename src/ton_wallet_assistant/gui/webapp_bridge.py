"""Qt WebChannel bridge between the embedded webview and Python.

``WebAppBridge`` is registered on the page's QWebChannel as
``telegramBridge``; the injected JS (``telegram.mini_apps.webapp_init_js``)
calls ``postEvent``/``sendData`` on it. Host state lives in a pure-Python
``WebAppRuntime``; wallet-relevant payloads are re-emitted as Qt signals and
routed into the explicit desktop approval flow — nothing signs here.

RPC-style events (popups, cloud storage, clipboard, invoices) carry a
``req_id``; the tab answers them through ``respond()`` which invokes
``WebApp._respond(req_id, ok, value)`` in the page.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal, Slot

from ..telegram.mini_apps import classify_link, intercept_navigation  # noqa: F401
from ..telegram.webapp_runtime import RPC_EVENTS, WebAppRuntime


class WebAppBridge(QObject):
    """Python side of ``window.Telegram.WebApp``."""

    webapp_event = Signal(str, str)  # (event name, JSON payload)
    send_data_received = Signal(str)  # WebApp.sendData() payload
    link_requested = Signal(str)  # external http(s) link to open
    telegram_link_requested = Signal(str)  # t.me / tg:// link
    tonconnect_requested = Signal(str)  # tc:// or ton:// link → approval flow
    close_requested = Signal()
    # native-host requests: main/back/settings button state, popups, …
    main_button_changed = Signal(dict)
    back_button_changed = Signal(dict)
    settings_button_changed = Signal(dict)
    popup_requested = Signal(str, int, dict)  # (event, req_id, payload)
    respond = Signal(int, bool, object)  # (req_id, ok, value) → JS _respond

    def __init__(
        self,
        runtime: WebAppRuntime | None = None,
        *,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.runtime = runtime or WebAppRuntime()
        # injectable hooks (the tab wires real clipboard/popup impls)
        self.clipboard_reader: Callable[[], str] = lambda: ""
        self.invoice_handler: Callable[[str], str] = lambda url: "cancelled"

    # ------------------------------------------------------------- slots

    @Slot(str, str)
    def postEvent(self, event: str, payload_json: str) -> None:  # noqa: N802
        """Generic event sink called by the injected JS. Strict validation:
        unknown events and non-object payloads are refused."""
        try:
            payload = json.loads(payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        result = self.runtime.dispatch(event, payload)
        if not result.ok:
            self.webapp_event.emit("invalid_event", json.dumps({"event": event}))
            return

        if result.req_id is not None:
            self._handle_rpc(event, result.req_id, payload, result)

        if event == "web_app_data":
            data = str(payload.get("data", ""))
            if classify_link(data) == "tonconnect":
                self.tonconnect_requested.emit(data)
            else:
                self.send_data_received.emit(data)
        elif event == "open_link":
            self.link_requested.emit(str(payload.get("url", "")))
        elif event == "open_tg_link":
            self.telegram_link_requested.emit(str(payload.get("url", "")))
        elif event == "web_app_close":
            self.close_requested.emit()
        elif event == "main_button_update":
            self.main_button_changed.emit(self.runtime.main_button.__dict__)
        elif event == "back_button_update":
            self.back_button_changed.emit(self.runtime.back_button.__dict__)
        elif event == "settings_button_update":
            self.settings_button_changed.emit(self.runtime.settings_button.__dict__)
        self.webapp_event.emit(event, payload_json)

    @Slot(str)
    def sendData(self, data: str) -> None:  # noqa: N802
        if classify_link(data) == "tonconnect":
            self.tonconnect_requested.emit(data)
        else:
            self.send_data_received.emit(data)

    # --------------------------------------------------------------- rpc

    def _handle_rpc(self, event: str, req_id: int, payload: dict, result) -> None:
        """Answer callback-style APIs. Storage is native; popups/clipboard/
        invoices are delegated to injectable GUI handlers."""
        if event == "cloud_storage":
            try:
                self.respond.emit(req_id, True, result.response)
            except Exception:
                self.respond.emit(req_id, False, None)
        elif event == "clipboard_read":
            self.respond.emit(req_id, True, self.clipboard_reader())
        elif event == "open_invoice":
            self.respond.emit(req_id, True, self.invoice_handler(str(payload.get("url", ""))))
        elif event in ("show_popup", "show_alert", "show_confirm", "show_scan_qr",
                       "write_access", "request_contact"):
            self.popup_requested.emit(event, req_id, payload)

    @staticmethod
    def is_rpc_event(event: str) -> bool:
        return event in RPC_EVENTS


__all__ = ["WebAppBridge", "classify_link", "intercept_navigation"]
