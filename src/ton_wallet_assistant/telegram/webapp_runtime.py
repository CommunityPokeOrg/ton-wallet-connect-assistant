"""Pure-Python model of the Telegram.WebApp host-side runtime.

Validates events coming from the embedded webview and tracks host state
(buttons, expansion, cloud storage). No Qt imports — the GUI bridge
(``gui.webapp_bridge``) and tests drive this directly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

#: Events the host accepts from the webview (JS → Python via postEvent).
KNOWN_EVENTS = frozenset(
    {
        "web_app_ready",
        "web_app_expand",
        "web_app_close",
        "web_app_data",
        "open_link",
        "open_tg_link",
        "open_invoice",
        "main_button_update",
        "back_button_update",
        "settings_button_update",
        "header_color",
        "background_color",
        "show_popup",
        "show_alert",
        "show_confirm",
        "show_scan_qr",
        "clipboard_read",
        "cloud_storage",
        "haptic",
        "share_to_story",
        "write_access",
        "request_contact",
    }
)

#: Events carrying a req_id that expect an _rpc_response.
RPC_EVENTS = frozenset(
    {
        "open_invoice",
        "show_popup",
        "show_alert",
        "show_confirm",
        "show_scan_qr",
        "clipboard_read",
        "cloud_storage",
        "write_access",
        "request_contact",
    }
)


@dataclass
class ButtonState:
    text: str = ""
    is_visible: bool = False
    is_active: bool = True
    is_progress: bool = False
    color: str = ""
    text_color: str = ""


@dataclass
class EventResult:
    """Normalized outcome of one incoming postEvent."""

    event: str
    payload: dict
    req_id: int | None = None
    ok: bool = True
    response: Any = None  # value to send back via _respond when req_id set
    error: str = ""


@dataclass
class WebAppRuntime:
    """Host-side state for one embedded WebApp session."""

    init_data: str = ""
    init_data_unsafe: dict = field(default_factory=dict)
    theme_params: dict = field(default_factory=dict)
    is_expanded: bool = False
    is_ready: bool = False
    main_button: ButtonState = field(default_factory=ButtonState)
    back_button: ButtonState = field(default_factory=ButtonState)
    settings_button: ButtonState = field(default_factory=ButtonState)
    header_color: str = ""
    background_color: str = ""
    storage: dict[str, str] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    # --------------------------------------------------------- validation

    @staticmethod
    def validate_event(event: str, payload: dict) -> str | None:
        """Return an error string, or None when the event is well-formed."""
        if not isinstance(event, str) or not event:
            return "event must be a non-empty string"
        if event not in KNOWN_EVENTS:
            return f"unknown event {event!r}"
        if not isinstance(payload, dict):
            return "payload must be an object"
        return None

    # ----------------------------------------------------------- dispatch

    def dispatch(self, event: str, payload: dict) -> EventResult:
        """Validate + apply one incoming event. Mutating host state here is
        bookkeeping only — wallet/signing actions are routed out as signals
        by the GUI layer and always need explicit approval."""
        error = self.validate_event(event, payload)
        if error:
            return EventResult(event=event, payload=payload, ok=False, error=error)
        req_id = payload.get("req_id")
        req_id = req_id if isinstance(req_id, int) and req_id > 0 else None

        handler = getattr(self, f"_on_{event}", None)
        response = None
        if handler is not None:
            try:
                response = handler(payload)
            except Exception as exc:
                return EventResult(
                    event=event, payload=payload, req_id=req_id, ok=False, error=str(exc)
                )
        return EventResult(event=event, payload=payload, req_id=req_id, response=response)

    # ------------------------------------------------------- event impls

    def _on_web_app_ready(self, _p: dict) -> None:
        self.is_ready = True

    def _on_web_app_expand(self, _p: dict) -> None:
        self.is_expanded = True

    def _on_main_button_update(self, p: dict) -> None:
        self._apply_button(self.main_button, p)

    def _on_back_button_update(self, p: dict) -> None:
        self._apply_button(self.back_button, p)

    def _on_settings_button_update(self, p: dict) -> None:
        self._apply_button(self.settings_button, p)

    def _on_header_color(self, p: dict) -> None:
        self.header_color = str(p.get("color", ""))

    def _on_background_color(self, p: dict) -> None:
        self.background_color = str(p.get("color", ""))

    def _on_cloud_storage(self, p: dict) -> Any:
        method = p.get("method")
        if method == "set":
            self.storage[str(p["key"])] = str(p.get("value", ""))
            return True
        if method == "get":
            return self.storage.get(str(p.get("key", "")), "")
        if method == "get_many":
            keys = p.get("keys") or []
            return {str(k): self.storage.get(str(k), "") for k in keys}
        if method == "remove":
            self.storage.pop(str(p.get("key", "")), None)
            return True
        if method == "remove_many":
            for k in p.get("keys") or []:
                self.storage.pop(str(k), None)
            return True
        if method == "keys":
            return sorted(self.storage)
        raise ValueError(f"unknown cloud storage method {method!r}")

    @staticmethod
    def _apply_button(state: ButtonState, p: dict) -> None:
        if "text" in p:
            state.text = str(p["text"])
        for src, attr in (
            ("is_visible", "is_visible"),
            ("is_active", "is_active"),
            ("is_progress", "is_progress"),
            ("color", "color"),
            ("text_color", "text_color"),
        ):
            if src in p:
                value = p[src]
                setattr(state, attr, bool(value) if src.startswith("is_") else str(value))


__all__ = [
    "ButtonState",
    "EventResult",
    "KNOWN_EVENTS",
    "RPC_EVENTS",
    "WebAppRuntime",
]
