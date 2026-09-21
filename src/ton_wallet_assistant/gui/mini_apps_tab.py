"""Mini Apps tab — embedded Telegram Mini App (TMA) runtime host.

Uses ``PySide6.QtWebEngineWidgets.QWebEngineView`` when available and never
required: without QtWebEngine (or under ``QT_QPA_PLATFORM=offscreen`` /
``TWA_DISABLE_WEBENGINE=1``) a fallback panel keeps URL validation,
t.me launch parsing, and external-browser launch working.

Layout mirrors real TMA hosting: a native header bar (back, app title,
settings, close), the webview, and a native bottom MainButton driven by the
injected ``Telegram.WebApp`` shim.

Resolution order for ``t.me/<bot>/<app>`` links: authenticated TDLib client
(genuine query_id/initData) → Telegram's own t.me redirect/iframe target →
demo/offline synthetic context (clearly marked, never presented as
authenticated) → error panel.

Security: external web content is untrusted. ``ton://``/``tc://``/``tg://``
links and ``WebApp.sendData`` payloads are never executed — they are routed
into the same explicit desktop approval flow as the mobile companion.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..session import WalletSession
from ..telegram.mini_apps import (
    POPULAR_MINI_APPS,
    TelegramMiniAppBridge,
    TmaLaunchContext,
    WebAppResolution,
    build_init_data,
    demo_webapp_resolution,
    parse_tma_link,
    resolve_tma_url,
    validate_web_url,
    webapp_init_js,
    webchannel_bootstrap_js,
)
from .async_loop import AsyncLoop
from .webapp_bridge import WebAppBridge, intercept_navigation

try:  # optional — PySide6-Addons ships QtWebEngine; CI/headless may lack it
    from PySide6.QtWebChannel import QWebChannel
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_AVAILABLE = True
except Exception:  # ImportError / missing QtWebEngineProcess / etc.
    QWebChannel = QWebEnginePage = QWebEngineView = None  # type: ignore[assignment]
    _WEBENGINE_AVAILABLE = False


def webengine_supported() -> bool:
    """Runtime check — importable AND usable in this environment."""
    if not _WEBENGINE_AVAILABLE or os.environ.get("TWA_DISABLE_WEBENGINE"):
        return False
    return os.environ.get("QT_QPA_PLATFORM") != "offscreen"


if _WEBENGINE_AVAILABLE:

    class _MiniAppPage(QWebEnginePage):
        """Navigation policy: only HTTP(S) navigates; wallet/Telegram links
        are intercepted and forwarded to the approval flow."""

        def __init__(self, bridge: WebAppBridge, parent=None) -> None:
            super().__init__(parent)
            self._bridge = bridge

        def acceptNavigationRequest(self, url, nav_type, is_main_frame):  # noqa: N802
            allowed, kind = intercept_navigation(url.toString())
            if allowed:
                return True
            if kind == "tonconnect":
                self._bridge.tonconnect_requested.emit(url.toString())
            elif kind == "telegram":
                self._bridge.telegram_link_requested.emit(url.toString())
            return False


class MiniAppsTab(QWidget):
    def __init__(
        self,
        session: WalletSession,
        async_loop: AsyncLoop,
        submit_link: Callable[[str, str], None] | None = None,
        resolver: Callable[[TmaLaunchContext], object] | None = None,
        *,
        webview_enabled: bool | None = None,
    ) -> None:
        super().__init__()
        self.session = session
        self.async_loop = async_loop
        self.submit_link = submit_link
        # resolver: async callable (context) -> dict|None, typically backed
        # by the authenticated TDLib client when one is signed in.
        self.resolver = resolver
        self._external = TelegramMiniAppBridge()
        self._context: TmaLaunchContext | None = None
        self._resolution: WebAppResolution | None = None
        self._webview_ok = (
            webengine_supported() if webview_enabled is None else webview_enabled
        )

        layout = QVBoxLayout(self)

        warning = QLabel(
            "EXPERIMENTAL — Mini Apps run untrusted web content. Wallet and "
            "TonConnect actions always require explicit desktop approval; "
            "nothing is signed automatically."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color:#f0a020; font-weight:bold;")
        layout.addWidget(warning)

        if session.demo:
            demo = QLabel("DEMO MODE — resolution and requests are fully synthetic/offline.")
            demo.setStyleSheet("color:#f0a020;")
            layout.addWidget(demo)

        # ---- address bar -------------------------------------------------
        bar = QHBoxLayout()
        self.presets = QComboBox()
        self.presets.addItem("Popular apps…")
        for title, url in POPULAR_MINI_APPS:
            self.presets.addItem(title, url)
        self.presets.activated.connect(self._preset_activated)
        bar.addWidget(self.presets)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://t.me/bot/app?startapp=… or https://app.example")
        self.url_edit.returnPressed.connect(self._load_clicked)
        bar.addWidget(self.url_edit, 1)
        self.load_btn = QPushButton("Load")
        self.load_btn.clicked.connect(self._load_clicked)
        bar.addWidget(self.load_btn)
        self.open_ext_btn = QPushButton("Open in browser")
        self.open_ext_btn.clicked.connect(self._open_external)
        bar.addWidget(self.open_ext_btn)
        layout.addLayout(bar)

        # ---- native TMA header bar ----------------------------------------
        header = QHBoxLayout()
        self.back_btn = QPushButton("←")
        self.back_btn.setFixedWidth(36)
        self.back_btn.setVisible(False)
        self.back_btn.clicked.connect(self._press_back)
        header.addWidget(self.back_btn)
        self.title_label = QLabel("Mini App")
        self.title_label.setStyleSheet("font-weight:bold;")
        header.addWidget(self.title_label, 1)
        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setFixedWidth(36)
        self.settings_btn.setVisible(False)
        self.settings_btn.clicked.connect(self._press_settings)
        header.addWidget(self.settings_btn)
        self.close_btn = QPushButton("✕")
        self.close_btn.setFixedWidth(36)
        self.close_btn.setToolTip("Unload the current mini app")
        self.close_btn.clicked.connect(self._unload)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.status_label = QLabel(
            "WebView available" if self._webview_ok else
            "QtWebEngine not available — showing link controls only "
            "(install PySide6-Addons / run on a desktop session)"
        )
        self.status_label.setStyleSheet("color:#9AA6B2;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # ---- webview or fallback ------------------------------------------
        self.stack = QStackedWidget()
        self.web_view = None
        self.bridge = WebAppBridge()
        self.bridge.clipboard_reader = self._read_clipboard
        self.bridge.invoice_handler = self._handle_invoice
        self.bridge.send_data_received.connect(self._on_send_data)
        self.bridge.tonconnect_requested.connect(self._on_tonconnect_link)
        self.bridge.telegram_link_requested.connect(self._on_telegram_link)
        self.bridge.link_requested.connect(self._on_external_link)
        self.bridge.webapp_event.connect(self._on_webapp_event)
        self.bridge.close_requested.connect(self._unload)
        self.bridge.main_button_changed.connect(self._on_main_button)
        self.bridge.back_button_changed.connect(self._on_back_button)
        self.bridge.settings_button_changed.connect(self._on_settings_button)
        self.bridge.popup_requested.connect(self._on_popup)
        self.bridge.respond.connect(self._respond_to_js)

        if self._webview_ok:
            try:
                self.web_view = QWebEngineView()
                page = _MiniAppPage(self.bridge, self.web_view)
                self.web_view.setPage(page)
                self._channel = QWebChannel(page)
                self._channel.registerObject("telegramBridge", self.bridge)
                page.setWebChannel(self._channel)
                page.loadFinished.connect(self._on_load_finished)
                self.stack.addWidget(self.web_view)
            except Exception:
                self.web_view = None
                self._webview_ok = False

        self.fallback_panel = QWidget()
        fb = QVBoxLayout(self.fallback_panel)
        fb.addWidget(
            QLabel(
                "Embedded view unavailable. Parsed launch details appear here; "
                "use “Open in browser” to launch the app externally."
            )
        )
        self.context_label = QLabel("")
        self.context_label.setWordWrap(True)
        self.context_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        fb.addWidget(self.context_label)
        fb.addStretch(1)
        self.stack.addWidget(self.fallback_panel)
        layout.addWidget(self.stack, 1)

        # ---- native bottom MainButton --------------------------------------
        self.main_button = QPushButton("")
        self.main_button.setObjectName("primary")
        self.main_button.setVisible(False)
        self.main_button.clicked.connect(self._press_main)
        layout.addWidget(self.main_button)

    # ------------------------------------------------------------ loading

    def _preset_activated(self, index: int) -> None:
        url = self.presets.itemData(index)
        if url:
            self.url_edit.setText(url)
            self._load(url)

    def _load_clicked(self) -> None:
        self._load(self.url_edit.text())

    def _load(self, url: str) -> None:
        try:
            url = validate_web_url(url)
        except ValueError as exc:
            self.status_label.setText(f"Invalid URL: {exc}")
            return
        try:
            self._context = parse_tma_link(url)
        except ValueError:
            self._context = None

        if self._context is not None:
            self.context_label.setText(self._describe_context(self._context))
            self.title_label.setText(
                f"@{self._context.bot}" + (f"/{self._context.app}" if self._context.app else "")
            )
            if self.session.demo:
                self._finish_load(demo_webapp_resolution(self._context))
            else:
                self.status_label.setText("Resolving mini app…")
                self.async_loop.submit(self._resolve(self._context), self._on_resolved)
        else:
            init_data, unsafe = build_init_data()
            self._finish_load(
                WebAppResolution(
                    url=url,
                    init_data=init_data,
                    init_data_unsafe=unsafe,
                    via="direct",
                    authenticated=False,
                )
            )

    async def _resolve(self, ctx: TmaLaunchContext) -> WebAppResolution:
        # 1. Authenticated TDLib resolution (genuine query_id/initData).
        if self.resolver is not None:
            try:
                result = await self.resolver(ctx)
            except Exception:
                result = None
            if result and result.get("url"):
                init_data, unsafe = build_init_data(
                    ctx.start_param, query_id=result.get("query_id", "")
                )
                return WebAppResolution(
                    url=result["url"],
                    init_data=init_data,
                    init_data_unsafe=unsafe,
                    via="tdlib",
                    authenticated=True,
                    query_id=result.get("query_id", ""),
                    bot=ctx.bot,
                    app=ctx.app,
                )
        # 2. Telegram's own t.me redirect/iframe resolution.
        try:
            target = resolve_tma_url(ctx)
            init_data, unsafe = build_init_data(ctx.start_param)
            return WebAppResolution(
                url=target, init_data=init_data, init_data_unsafe=unsafe,
                via="http-resolve", authenticated=False, bot=ctx.bot, app=ctx.app,
            )
        except ValueError:
            raise

    def _on_resolved(self, resolution: WebAppResolution | None, error) -> None:
        if error or resolution is None:
            self.status_label.setText(
                f"Cannot resolve mini app: {error or 'unavailable'} — "
                "it may require Telegram client authentication"
            )
            self.stack.setCurrentWidget(self.fallback_panel)
            return
        self._finish_load(resolution)

    def _finish_load(self, resolution: WebAppResolution) -> None:
        self._resolution = resolution
        self.bridge.runtime.init_data = resolution.init_data
        self.bridge.runtime.init_data_unsafe = resolution.init_data_unsafe
        if self.web_view is not None:
            self.web_view.setUrl(QUrl(resolution.url))
            self.stack.setCurrentWidget(self.web_view)
        else:
            self.status_label.setText(
                f"Ready to open externally: {resolution.url} "
                f"(initData via {resolution.via})"
            )
            self.stack.setCurrentWidget(self.fallback_panel)

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            self.status_label.setText("Page failed to load")
            return
        page = self.web_view.page()
        page.runJavaScript(webchannel_bootstrap_js())
        res = self._resolution
        page.runJavaScript(
            webapp_init_js(
                init_data=res.init_data if res else None,
                init_data_unsafe=res.init_data_unsafe if res else None,
                start_param=None if res else (self._context.start_param if self._context else None),
            )
        )
        label = res.url if res else page.url().toString()
        auth = "authenticated" if (res and res.authenticated) else "unauthenticated"
        self.status_label.setText(f"Loaded: {label} ({auth})")

    @staticmethod
    def _describe_context(ctx: TmaLaunchContext) -> str:
        lines = [f"Bot: @{ctx.bot}", f"App: {ctx.app or '(default)'}"]
        if ctx.start_param:
            lines.append(f"start_param: {ctx.start_param[:120]}")
        if ctx.tonconnect is not None:
            tc = ctx.tonconnect
            lines.append(f"TonConnect v{tc.version} request {tc.request_id[:12]}…")
            if tc.manifest_url:
                lines.append(f"manifest: {tc.manifest_url}")
            if tc.items:
                names = ", ".join(str(i.get("name", "?")) for i in tc.items)
                lines.append(f"items: {names}")
        return "\n".join(lines)

    def _open_external(self) -> None:
        try:
            url = validate_web_url(self.url_edit.text())
        except ValueError as exc:
            self.status_label.setText(f"Invalid URL: {exc}")
            return
        self._external.launch(url)

    def _unload(self) -> None:
        if self.web_view is not None:
            self.web_view.setUrl(QUrl("about:blank"))
        self.stack.setCurrentWidget(self.fallback_panel)
        self.main_button.setVisible(False)
        self.back_btn.setVisible(False)
        self.settings_btn.setVisible(False)
        self.status_label.setText("Mini app closed")

    # -------------------------------------------- native chrome → JS press

    def _press_main(self) -> None:
        self._emit("mainButtonPressed")
        if self.web_view is not None:
            self.web_view.page().runJavaScript("window.Telegram.WebApp._pressMain();")

    def _press_back(self) -> None:
        self._emit("backButtonPressed")
        if self.web_view is not None:
            self.web_view.page().runJavaScript("window.Telegram.WebApp._pressBack();")

    def _press_settings(self) -> None:
        self._emit("settingsButtonPressed")
        if self.web_view is not None:
            self.web_view.page().runJavaScript("window.Telegram.WebApp._pressSettings();")

    # --------------------------------------------- bridge signal slots

    def _on_send_data(self, data: str) -> None:
        self._forward("web_app_data", data)

    def _on_tonconnect_link(self, url: str) -> None:
        self._forward("TonConnect", url)

    def _on_telegram_link(self, url: str) -> None:
        self._forward("Telegram link", url)

    def _forward(self, kind: str, payload: str) -> None:
        """Route a webview-originated payload into the desktop approval flow."""
        if self.submit_link is None:
            self.status_label.setText(
                f"{kind} payload received (no approval channel): {payload[:80]}"
            )
            return
        self.submit_link(payload, f"miniapp:{kind}")
        self.status_label.setText(f"{kind} payload sent to approval flow")

    def _on_external_link(self, url: str) -> None:
        try:
            self._external.launch(validate_web_url(url))
        except ValueError:
            self.status_label.setText(f"Blocked unsafe link: {url[:80]}")

    def _on_webapp_event(self, event: str, _payload: str) -> None:
        self.status_label.setText(f"WebApp event: {event}")

    def _on_main_button(self, state: dict) -> None:
        self.main_button.setText(state.get("text") or "Continue")
        self.main_button.setVisible(bool(state.get("is_visible")))
        self.main_button.setEnabled(bool(state.get("is_active", True)))
        if state.get("color"):
            self.main_button.setStyleSheet(
                f"background:{state['color']};color:{state.get('text_color') or '#fff'};"
            )
        else:
            self.main_button.setStyleSheet("")

    def _on_back_button(self, state: dict) -> None:
        self.back_btn.setVisible(bool(state.get("is_visible")))

    def _on_settings_button(self, state: dict) -> None:
        self.settings_btn.setVisible(bool(state.get("is_visible")))

    def _on_popup(self, event: str, req_id: int, payload: dict) -> None:
        """Native popups for show_alert/show_confirm/show_popup."""
        message = str(payload.get("message") or payload.get("title") or "")
        if event == "show_confirm":
            ok = QMessageBox.question(self, "Mini App", message) == QMessageBox.StandardButton.Yes
            self.bridge.respond.emit(req_id, True, ok)
        elif event == "show_popup":
            QMessageBox.information(self, "Mini App", message)
            self.bridge.respond.emit(req_id, True, None)
        else:
            QMessageBox.information(self, "Mini App", message)
            self.bridge.respond.emit(req_id, True, None)

    def _respond_to_js(self, req_id: int, ok: bool, value: object) -> None:
        if self.web_view is None:
            return
        import json

        self.web_view.page().runJavaScript(
            "window.Telegram && window.Telegram.WebApp._respond("
            f"{int(req_id)}, {json.dumps(bool(ok))}, {json.dumps(value)});"
        )

    def _read_clipboard(self) -> str:
        return QGuiApplication.clipboard().text()

    def _handle_invoice(self, url: str) -> str:
        """Invoice links go through the explicit approval flow like any
        payment request — never auto-approved."""
        self._forward("invoice", url)
        return "cancelled"  # the JS promise resolves once; real pay happens via approval

    def emit_event(self, name: str, payload_json: str = "{}") -> None:
        """Push a Telegram event (viewportChanged, themeChanged, …) into JS."""
        self._emit(name, payload_json)

    def _emit(self, name: str, payload_json: str = "{}") -> None:
        if self.web_view is not None:
            import json

            self.web_view.page().runJavaScript(
                f"window.Telegram && window.Telegram.WebApp._emit({json.dumps(name)}, "
                f"JSON.parse({json.dumps(payload_json)}));"
            )

    def shutdown(self) -> None:
        self._external.close()
        if self.web_view is not None:
            self.web_view.setPage(None)
            self.web_view.deleteLater()
            self.web_view = None
