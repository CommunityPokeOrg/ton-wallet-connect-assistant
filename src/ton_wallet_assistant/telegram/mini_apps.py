"""Telegram Mini App (TMA) support for the desktop wallet.

Two layers live here:

* ``webapp_init_js()`` — generates the ``window.Telegram.WebApp`` bridge
  injected into embedded webviews (see ``gui.mini_apps_tab``). The JS talks
  back to Python through ``window.__twa_bridge`` (a Qt WebChannel object)
  when present, and degrades to console logging otherwise.
* ``TelegramMiniAppBridge`` — URL validation, ``t.me`` link building, and a
  tiny loopback HTTP callback endpoint for apps opened in an external
  browser. No Node.js runtime is required anywhere.

Only HTTP(S) URLs are loadable; ``ton://``, ``tc://``, and ``tg://`` links
are never followed by the webview itself — they are handed to the desktop
approval flow instead.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer

#: Well-known TON/Telegram mini apps shown in the tab's preset list.
POPULAR_MINI_APPS: tuple[tuple[str, str], ...] = (
    ("Wallet (Telegram)", "https://t.me/wallet"),
    ("Tonkeeper", "https://app.tonkeeper.com"),
    ("STON.fi", "https://app.ston.fi"),
    ("DeDust", "https://app.dedust.io"),
    ("Fragment", "https://fragment.com"),
    ("Getgems", "https://getgems.io"),
)

#: Theme parameters matching the app's dark palette (see gui/theme.py),
#: exposed to web apps as ``Telegram.WebApp.themeParams``.
WEBAPP_THEME_PARAMS: dict[str, str] = {
    "bg_color": "#10161E",
    "secondary_bg_color": "#1D2633",
    "text_color": "#E7ECEF",
    "hint_color": "#9AA6B2",
    "link_color": "#45AEF5",
    "button_color": "#45AEF5",
    "button_text_color": "#0B1016",
    "section_bg_color": "#1D2633",
    "section_header_text_color": "#9AA6B2",
    "subtitle_text_color": "#9AA6B2",
    "destructive_text_color": "#E74C3C",
}

#: Schemes the embedded view is allowed to navigate to itself. Everything
#: else (ton://, tc://, tg://, file:, javascript:, …) is intercepted.
ALLOWED_NAV_SCHEMES = frozenset({"https", "http", "about", "data"})


def _js_json(obj: object) -> str:
    """json.dumps hardened for embedding — escapes chars that could break
    out of a JS string or a surrounding ``<script>`` context."""
    return (
        json.dumps(obj)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


# ------------------------------------------------------------ t.me parsing


@dataclass(frozen=True)
class TonConnectStartApp:
    """Decoded TonConnect v2 ``startapp`` payload (compact ``key__value``
    encoding with ``--XX`` byte escapes, fields separated by ``-``)."""

    version: str
    request_id: str
    request: dict = field(default_factory=dict)
    trace_id: str = ""
    raw: str = ""

    @property
    def manifest_url(self) -> str:
        return str(self.request.get("manifestUrl", ""))

    @property
    def items(self) -> list:
        items = self.request.get("items")
        return items if isinstance(items, list) else []


@dataclass(frozen=True)
class TmaLaunchContext:
    """A parsed ``t.me/<bot>[/<app>]?startapp=…`` launch link."""

    url: str
    bot: str
    app: str = ""
    start_param: str = ""
    tonconnect: TonConnectStartApp | None = None


def _decode_compact_fields(payload: str) -> dict[str, str]:
    """Split a ``key__value-key__value`` payload on field separators,
    honouring ``--XX`` hex escapes inside both keys and values."""
    fields: list[str] = []
    token: list[str] = []
    i = 0
    while i < len(payload):
        if payload[i] == "-" and i + 2 < len(payload) + 1 and payload[i + 1] == "-":
            # '--' introduces a two-hex-digit byte escape
            esc = payload[i + 2 : i + 4]
            if len(esc) == 2 and all(c in "0123456789abcdefABCDEF" for c in esc):
                token.append(chr(int(esc, 16)))
                i += 4
                continue
        if payload[i] == "-":
            fields.append("".join(token))
            token = []
            i += 1
            continue
        token.append(payload[i])
        i += 1
    fields.append("".join(token))

    result: dict[str, str] = {}
    for field_str in fields:
        if "__" in field_str:
            key, _, value = field_str.partition("__")
            result[key] = value
    return result


def decode_tonconnect_startapp(payload: str) -> TonConnectStartApp | None:
    """Decode a ``tonconnect-v__2-id__…-r__…`` startapp payload.

    Returns None when the payload is not a TonConnect compact payload
    (opaque payloads are kept intact by the caller). Never raises —
    malformed fields land in ``raw``/empty fields instead.
    """
    if not payload.startswith("tonconnect-"):
        return None
    try:
        fields = _decode_compact_fields(payload[len("tonconnect-"):])
    except Exception:
        return None
    if not fields:
        return None  # prefix but no decodable fields — truly malformed
    request: dict = {}
    raw_r = fields.get("r", "")
    if raw_r:
        try:
            decoded = urllib.parse.unquote(raw_r)
            request = json.loads(decoded)
            if not isinstance(request, dict):
                request = {}
        except (json.JSONDecodeError, ValueError):
            request = {}
    return TonConnectStartApp(
        version=fields.get("v", ""),
        request_id=fields.get("id", ""),
        trace_id=fields.get("trace_id", fields.get("traceId", "")),
        request=request,
        raw=payload,
    )


def parse_tma_link(url: str) -> TmaLaunchContext:
    """Parse ``https://t.me/<bot>[/<app>][?startapp=<payload>]``.

    The ``startapp`` value is URL-decoded and, when it is a TonConnect
    compact payload, decoded into structured form. Opaque payloads are
    preserved verbatim in ``start_param``.
    """
    parsed = urllib.parse.urlparse(validate_web_url(url))
    host = parsed.netloc.lower()
    if host != "t.me" and not host.endswith(".t.me"):
        raise ValueError("not a t.me mini-app link")
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        raise ValueError("t.me link has no bot/app path")
    query = urllib.parse.parse_qs(parsed.query)
    start_param = (query.get("startapp") or query.get("start") or [""])[0]
    return TmaLaunchContext(
        url=url,
        bot=parts[0],
        app=parts[1] if len(parts) > 1 else "",
        start_param=start_param,
        tonconnect=decode_tonconnect_startapp(start_param),
    )


#: Candidates, in order, for extracting a mini app's real web URL from the
#: HTML t.me serves for ``/<bot>/<app>`` links.
_RESOLVE_PATTERNS = (
    re.compile(r'<iframe[^>]+src=["\'](https://[^"\']+)["\']', re.I),
    re.compile(r'(?:location\.href|location\.replace|window\.open)\s*[=(]\s*["\'](https://[^"\']+)["\']', re.I),
)


def resolve_tma_url(
    context: TmaLaunchContext,
    *,
    http_get: Callable[[str], tuple[int, str, str]] | None = None,
    timeout: float = 10.0,
) -> str:
    """Resolve the real web URL a t.me bot/app link launches.

    ``http_get(url) -> (status, final_url, body)`` is injectable for tests;
    the default uses httpx with redirects followed. The ``startapp`` value
    is preserved on the t.me URL so Telegram's own redirect carries it into
    the app. Raises ValueError with a clear message when the target cannot
    be resolved without Telegram client authentication.
    """
    if http_get is None:
        import httpx

        def _fetch(u: str) -> tuple[int, str, str]:
            resp = httpx.get(u, follow_redirects=True, timeout=timeout)
            return resp.status_code, str(resp.url), resp.text

        http_get = _fetch

    status, final_url, body = http_get(context.url)
    final_host = urllib.parse.urlparse(final_url).netloc.lower()
    if status == 200 and final_host != "t.me" and not final_host.endswith(".t.me"):
        return final_url  # t.me already redirected to the app
    if status != 200 or not body:
        raise ValueError(
            f"could not resolve mini app (HTTP {status}) — it may require "
            "the Telegram client to open"
        )
    for pattern in _RESOLVE_PATTERNS:
        match = pattern.search(body)
        if match:
            return match.group(1)
    raise ValueError(
        "t.me did not expose a web target for this mini app — opening it "
        "requires Telegram client authentication"
    )


def validate_web_url(url: str) -> str:
    """Return ``url`` if it is an absolute HTTP(S) URL; raise ValueError."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Mini App URL must be an absolute HTTP(S) URL")
    return url.strip()


def build_tma_url(username: str, startapp: str | None = None) -> str:
    """Build a ``https://t.me/<bot>`` URL with an optional startapp payload."""
    username = username.lstrip("@ ").strip()
    if not username or any(ch in username for ch in "/?#"):
        raise ValueError("username must be a Telegram handle")
    url = f"https://t.me/{username}"
    return f"{url}?startapp={urllib.parse.quote(startapp, safe='')}" if startapp else url


def webapp_init_js(
    init_data: str | None = None,
    init_data_unsafe: dict | None = None,
    theme_params: dict | None = None,
    bridge_object: str = "__twa_bridge",
    start_param: str | None = None,
) -> str:
    """JS defining ``window.Telegram.WebApp`` backed by the desktop bridge.

    ``window.__twa_bridge`` is a QObject registered on the page's
    QWebChannel; when absent (external browser / fallback) calls degrade to
    console logging so injected code never throws.

    ``start_param`` lands in ``initData`` (query-string form, as Telegram
    sends it) and ``initDataUnsafe.start_param``. All values go through
    JSON serialization — no untrusted input is interpolated into JS source.
    """
    theme = dict(WEBAPP_THEME_PARAMS)
    if theme_params:
        theme.update({str(k): str(v) for k, v in theme_params.items()})
    unsafe = dict(init_data_unsafe or {})
    if start_param is not None:
        unsafe["start_param"] = start_param
    if init_data is None:
        fields = []
        if start_param is not None:
            fields.append("start_param=" + urllib.parse.quote(start_param, safe=""))
        init_data = "&".join(fields)
    init_json = _js_json(init_data)
    unsafe_json = _js_json(unsafe)
    theme_json = _js_json(theme)
    bridge = _js_json(bridge_object)
    return f"""
(function () {{
  if (window.__twa_initialized) return;
  window.__twa_initialized = true;
  var listeners = {{}};
  var pending = {{}};
  var reqCounter = 0;
  var bridgeName = {bridge};
  function post(event, payload) {{
    try {{
      var bridge = window[bridgeName];
      if (bridge && bridge.postEvent) {{
        bridge.postEvent(event, JSON.stringify(payload || {{}}));
      }} else {{
        console.log('[telegram-bridge]', event, JSON.stringify(payload || {{}}));
      }}
    }} catch (err) {{ console.error('telegram bridge post failed', err); }}
  }}
  function request(event, payload, cb) {{
    // Callback-style API: the host replies with _rpc_response(req_id).
    var id = ++reqCounter;
    pending[id] = cb || function () {{}};
    post(event, Object.assign({{ req_id: id }}, payload || {{}}));
    return id;
  }}
  function makeButton(updateEvent, pressEvent) {{
    return {{
      text: '', isVisible: false, isActive: true, isProgressVisible: false,
      color: '', textColor: '', _cb: null,
      _sync: function () {{ post(updateEvent, this._state()); }},
      _state: function () {{
        return {{ text: this.text, is_visible: this.isVisible,
                  is_active: this.isActive, is_progress: this.isProgressVisible,
                  color: this.color, text_color: this.textColor }};
      }},
      setText: function (t) {{ this.text = String(t); this._sync(); }},
      setParams: function (p) {{
        if (p.text !== undefined) this.text = String(p.text);
        if (p.color !== undefined) this.color = String(p.color);
        if (p.text_color !== undefined) this.textColor = String(p.text_color);
        if (p.is_visible !== undefined) this.isVisible = !!p.is_visible;
        if (p.is_active !== undefined) this.isActive = !!p.is_active;
        if (p.is_progress_visible !== undefined) this.isProgressVisible = !!p.is_progress_visible;
        this._sync();
      }},
      show: function () {{ this.isVisible = true; this._sync(); }},
      hide: function () {{ this.isVisible = false; this._sync(); }},
      enable: function () {{ this.isActive = true; this._sync(); }},
      disable: function () {{ this.isActive = false; this._sync(); }},
      showProgress: function () {{ this.isProgressVisible = true; this._sync(); }},
      hideProgress: function () {{ this.isProgressVisible = false; this._sync(); }},
      onClick: function (cb) {{ this._cb = cb; }},
      offClick: function (cb) {{ if (this._cb === cb) this._cb = null; }},
      _press: function () {{ if (this._cb) this._cb(); }}
    }};
  }}
  var webApp = {{
    initData: {init_json},
    initDataUnsafe: {unsafe_json},
    version: '7.8',
    platform: 'tdesktop',
    colorScheme: 'dark',
    isExpanded: false,
    viewportHeight: window.innerHeight,
    viewportStableHeight: window.innerHeight,
    themeParams: {theme_json},
    onEvent: function (e, cb) {{ (listeners[e] = listeners[e] || []).push(cb); }},
    offEvent: function (e, cb) {{
      var l = listeners[e] || [];
      var i = l.indexOf(cb);
      if (i >= 0) l.splice(i, 1);
    }},
    _emit: function (e, data) {{
      (listeners[e] || []).slice().forEach(function (cb) {{
        try {{ cb(data); }} catch (err) {{ console.error(err); }}
      }});
    }},
    _respond: function (reqId, ok, value) {{
      var cb = pending[reqId];
      if (cb) {{ delete pending[reqId]; try {{ cb(ok, value); }} catch (err) {{ console.error(err); }} }}
    }},
    _pressMain: function () {{ webApp.MainButton._press(); }},
    _pressBack: function () {{ webApp.BackButton._press(); webApp._emit('backButtonPressed', {{}}); }},
    _pressSettings: function () {{ webApp.SettingsButton._press(); webApp._emit('settingsButtonPressed', {{}}); }},
    _post: post,
    ready: function () {{ post('web_app_ready', {{}}); }},
    expand: function () {{
      webApp.isExpanded = true;
      post('web_app_expand', {{}});
      webApp._emit('viewportChanged', {{ isStateStable: true, isExpanded: true }});
    }},
    close: function () {{ post('web_app_close', {{}}); }},
    sendData: function (data) {{ post('web_app_data', {{ data: String(data) }}); }},
    openLink: function (url) {{ post('open_link', {{ url: String(url) }}); }},
    openTelegramLink: function (url) {{ post('open_tg_link', {{ url: String(url) }}); }},
    openInvoice: function (url, cb) {{
      request('open_invoice', {{ url: String(url) }}, function (ok, status) {{ if (cb) cb(status || 'cancelled'); }});
    }},
    setHeaderColor: function (c) {{ post('header_color', {{ color: String(c) }}); }},
    setBackgroundColor: function (c) {{ post('background_color', {{ color: String(c) }}); }},
    showPopup: function (params, cb) {{
      request('show_popup', params || {{}}, function (ok, buttonId) {{ if (cb) cb(buttonId || null); }});
    }},
    showAlert: function (msg, cb) {{
      request('show_alert', {{ message: String(msg) }}, function () {{ if (cb) cb(); }});
    }},
    showConfirm: function (msg, cb) {{
      request('show_confirm', {{ message: String(msg) }}, function (ok, yes) {{ if (cb) cb(!!yes); }});
    }},
    showScanQrPopup: function (params, cb) {{
      request('show_scan_qr', params || {{}}, function (ok, data) {{
        if (cb) return cb(data || null);
      }});
    }},
    readTextFromClipboard: function (cb) {{
      request('clipboard_read', {{}}, function (ok, text) {{ if (cb) cb(text || ''); }});
    }},
    shareToStory: function (mediaUrl, params) {{ post('share_to_story', {{ url: String(mediaUrl) }}); }},
    requestWriteAccess: function (cb) {{ request('write_access', {{}}, function (ok, v) {{ if (cb) cb(!!v); }}); }},
    requestContact: function (cb) {{
      request('request_contact', {{}}, function (ok, v) {{ if (cb) cb(ok ? v : null); }});
    }},
    MainButton: makeButton('main_button_update', 'main_button_pressed'),
    BackButton: makeButton('back_button_update', 'back_button_pressed'),
    SettingsButton: makeButton('settings_button_update', 'settings_button_pressed'),
    HapticFeedback: {{
      impactOccurred: function (style) {{ post('haptic', {{ type: 'impact', style: String(style) }}); }},
      notificationOccurred: function (type) {{ post('haptic', {{ type: 'notification', kind: String(type) }}); }},
      selectionChanged: function () {{ post('haptic', {{ type: 'selection' }}); }}
    }},
    CloudStorage: {{
      setItem: function (key, value, cb) {{
        request('cloud_storage', {{ method: 'set', key: String(key), value: String(value) }},
                function (ok) {{ if (cb) cb(null, !!ok); }});
      }},
      getItem: function (key, cb) {{
        request('cloud_storage', {{ method: 'get', key: String(key) }},
                function (ok, v) {{ if (cb) cb(ok ? null : 'error', ok ? v : null); }});
      }},
      getItems: function (keys, cb) {{
        request('cloud_storage', {{ method: 'get_many', keys: keys }},
                function (ok, v) {{ if (cb) cb(ok ? null : 'error', ok ? v : null); }});
      }},
      removeItem: function (key, cb) {{
        request('cloud_storage', {{ method: 'remove', key: String(key) }},
                function (ok) {{ if (cb) cb(null, !!ok); }});
      }},
      removeItems: function (keys, cb) {{
        request('cloud_storage', {{ method: 'remove_many', keys: keys }},
                function (ok) {{ if (cb) cb(null, !!ok); }});
      }},
      getKeys: function (cb) {{
        request('cloud_storage', {{ method: 'keys' }},
                function (ok, v) {{ if (cb) cb(ok ? null : 'error', ok ? v : []); }});
      }}
    }}
  }};
  window.Telegram = window.Telegram || {{}};
  window.Telegram.WebApp = webApp;
  window.TelegramWebviewProxy = {{
    postEvent: function (event, payload) {{ post(event, JSON.parse(payload || '{{}}')); }}
  }};
}})();
"""


#: JS bootstrap that binds ``window.__twa_bridge`` to the Qt WebChannel
#: object registered on the page. Safe to run on any page (no-op without Qt).
def webchannel_bootstrap_js(object_name: str = "telegramBridge") -> str:
    name = json.dumps(object_name)
    return f"""
(function () {{
  function init() {{
    try {{
      new QWebChannel(qt.webChannelTransport, function (channel) {{
        window.__twa_bridge = channel.objects[{name}];
      }});
    }} catch (err) {{ console.error('webchannel init failed', err); }}
  }}
  if (typeof QWebChannel === 'undefined') {{
    var s = document.createElement('script');
    s.src = 'qrc:///qtwebchannel/qwebchannel.js';
    s.onload = init;
    document.head.appendChild(s);
  }} else {{
    init();
  }}
}})();
"""


# ------------------------------------------------------------ resolution


@dataclass(frozen=True)
class WebAppResolution:
    """Everything needed to host a mini app: the URL to load plus the
    initData/context to inject. ``authenticated`` is True only when the
    initData came from a signed-in TDLib session — synthetic demo data is
    never passed off as authenticated Telegram data."""

    url: str
    init_data: str
    init_data_unsafe: dict
    via: str  # "tdlib" | "http-resolve" | "demo"
    authenticated: bool
    query_id: str = ""
    bot: str = ""
    app: str = ""


#: TDLib methods tried, in order, to resolve a web app launch URL.
#: Availability depends on the installed TDLib version — the client probes
#: them and reports which one worked (or all errors tried).
WEBAPP_TD_METHODS = ("getWebAppUrl", "searchWebApp", "getWebAppLinkUrl")


def build_init_data(
    start_param: str = "",
    *,
    query_id: str = "",
    demo: bool = False,
) -> tuple[str, dict]:
    """Build (init_data query-string, init_data_unsafe dict).

    Demo data is explicitly marked: ``demo=True`` in initDataUnsafe and a
    ``demo`` marker in the query string — never shaped like real signed
    initData (no auth_date/hash/user claims).
    """
    unsafe: dict = {}
    fields: list[str] = []
    if query_id:
        fields.append("query_id=" + urllib.parse.quote(query_id, safe=""))
        unsafe["query_id"] = query_id
    if start_param:
        fields.append("start_param=" + urllib.parse.quote(start_param, safe=""))
        unsafe["start_param"] = start_param
    if demo:
        fields.append("demo=1")
        unsafe["demo"] = True
    return "&".join(fields), unsafe


def demo_webapp_resolution(context: TmaLaunchContext, *, resolved_url: str = "") -> WebAppResolution:
    """Synthetic resolution for demo/offline mode — clearly marked."""
    init_data, unsafe = build_init_data(context.start_param, demo=True)
    return WebAppResolution(
        url=resolved_url or context.url,
        init_data=init_data,
        init_data_unsafe=unsafe,
        via="demo",
        authenticated=False,
        bot=context.bot,
        app=context.app,
    )


def classify_link(url: str) -> str:
    """Classify a link: 'tonconnect', 'telegram', 'web', or 'blocked'."""
    url = url.strip()
    scheme = urllib.parse.urlparse(url).scheme.lower()
    host = urllib.parse.urlparse(url).netloc.lower()
    if scheme in {"ton", "tc"} or "tonconnect" in url or "ton-connect" in url:
        return "tonconnect"
    if scheme == "tg" or host == "t.me" or host.endswith(".t.me"):
        return "telegram"
    if scheme in ALLOWED_NAV_SCHEMES:
        return "web"
    return "blocked"


def intercept_navigation(url: str) -> tuple[bool, str]:
    """Return (allowed, kind). 'tonconnect'/'telegram'/'blocked' kinds are
    not navigated by the webview — they are handed to the bridge instead."""
    kind = classify_link(url)
    if kind != "web":
        return False, kind
    try:
        validate_web_url(url)
    except ValueError:
        return False, "blocked"
    return True, kind


@dataclass(frozen=True)
class MiniAppLaunch:
    url: str
    title: str = "Telegram Mini App"


class TelegramWebAppShim:
    """Small SDK-compatible state shim for apps loaded outside Telegram."""

    def __init__(self, init_data: str = "") -> None:
        self.initData = init_data  # noqa: N815 — mirrors the JS API
        self.initDataUnsafe: dict[str, object] = {}  # noqa: N815
        self._events: dict[str, list[Callable[..., None]]] = {}

    def onEvent(self, event: str, callback: Callable[..., None]) -> None:  # noqa: N802
        self._events.setdefault(event, []).append(callback)

    def offEvent(self, event: str, callback: Callable[..., None]) -> None:  # noqa: N802
        if event in self._events and callback in self._events[event]:
            self._events[event].remove(callback)

    def emit(self, event: str, *args: object) -> None:
        for callback in tuple(self._events.get(event, ())):
            callback(*args)

    def ready(self) -> None:
        self.emit("ready")

    def expand(self) -> None:
        self.emit("viewportChanged", True)

    def close(self) -> None:
        self.emit("close")


class TelegramMiniAppBridge:
    """Launch external TMAs and receive TonConnect/deep-link callbacks."""

    def __init__(self, callback: Callable[[str], None] | None = None) -> None:
        self.callback = callback
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    build_tma_url = staticmethod(build_tma_url)
    validate_web_url = staticmethod(validate_web_url)

    def launch(self, url: str, *, title: str = "Telegram Mini App") -> MiniAppLaunch:
        launch = MiniAppLaunch(validate_web_url(url), title)
        webbrowser.open(launch.url)
        return launch

    def start_callback_server(self) -> str:
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                payload = query.get("tonconnect", query.get("url", [self.path]))[0]
                if bridge.callback:
                    bridge.callback(payload)
                body = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}/callback"

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
