"""Mini-apps runtime tests — link parsing, TonConnect compact decoding,
JS injection escaping, host-state model, and link interception."""

import json
import re
import urllib.parse
from urllib.request import urlopen

import pytest

from ton_wallet_assistant.telegram.mini_apps import (
    TelegramMiniAppBridge,
    TelegramWebAppShim,
    _js_json,
    build_init_data,
    classify_link,
    decode_tonconnect_startapp,
    demo_app_url,
    demo_webapp_resolution,
    intercept_navigation,
    parse_tma_link,
    resolve_tma_url,
    validate_web_url,
    webapp_init_js,
    webchannel_bootstrap_js,
)
from ton_wallet_assistant.telegram.webapp_runtime import KNOWN_EVENTS, WebAppRuntime

# The exact launch link from the wallet connect flow.
EXACT_URL = (
    "https://t.me/wallet/start?startapp=tonconnect-v__2-"
    "id__8828fa5a17b3bf065be85df5081db6fa0c6bcb93bb72c9e6bed61f6c83bf2b1e-"
    "trace--5Fid__01a0c4ea--2D538d--2D709--2Da708--2Dd43c165949d5-"
    "r__--7B--22manifestUrl--22--3A--22https--3A--2F--2Fdns--2Eton--2Eorg"
    "--2Ftonconnect--2Dmanifest--2Ejson--22--2C--22items--22--3A--5B--7B"
    "--22name--22--3A--22ton--5Faddr--22--7D--5D--7D"
)


# ------------------------------------------------------------ t.me parsing


def test_parse_exact_wallet_tonconnect_url():
    ctx = parse_tma_link(EXACT_URL)
    assert ctx.bot == "wallet"
    assert ctx.app == "start"
    assert ctx.url == EXACT_URL
    # raw payload preserved verbatim
    assert ctx.start_param.startswith("tonconnect-v__2-id__8828fa5a")

    tc = ctx.tonconnect
    assert tc is not None
    assert tc.version == "2"
    assert tc.request_id == "8828fa5a17b3bf065be85df5081db6fa0c6bcb93bb72c9e6bed61f6c83bf2b1e"
    assert tc.trace_id == "01a0c4ea-538d-709-a708-d43c165949d5"
    assert tc.manifest_url == "https://dns.ton.org/tonconnect-manifest.json"
    assert tc.items == [{"name": "ton_addr"}]
    assert tc.raw == ctx.start_param


def test_parse_tma_link_variants():
    ctx = parse_tma_link("https://t.me/mybot/myapp?startapp=hello%20world")
    assert (ctx.bot, ctx.app, ctx.start_param) == ("mybot", "myapp", "hello world")

    ctx = parse_tma_link("https://t.me/justbot")
    assert ctx.bot == "justbot" and ctx.app == "" and ctx.start_param == ""

    for bad in (
        "https://example.com/wallet?startapp=x",  # not t.me
        "https://t.me/",                          # no bot
        "javascript:alert(1)",
        "ftp://t.me/bot",
        "not a url",
    ):
        with pytest.raises(ValueError):
            parse_tma_link(bad)


def test_tonconnect_decoder_opaque_and_malformed():
    # Non-tonconnect payloads stay opaque
    assert decode_tonconnect_startapp("plain-payload") is None
    assert decode_tonconnect_startapp("") is None
    # malformed tonconnect payload — never raises
    assert decode_tonconnect_startapp("tonconnect-") is None
    # a payload with an unknown field decodes the fields it can
    tc = decode_tonconnect_startapp("tonconnect-v__2-id__abc-extra__--7B--7D")
    assert tc.version == "2" and tc.request_id == "abc"
    # r field that isn't JSON → request stays empty, never raises
    tc = decode_tonconnect_startapp("tonconnect-v__2-r__notjson")
    assert tc is not None and tc.items == [] and tc.manifest_url == ""


def test_decoder_never_raises_on_garbage():
    for payload in ["tonconnect", "tonconnect-", "tonconnect-x", "--", "%%", "\x00\xff"]:
        decode_tonconnect_startapp(payload)  # must not raise


# ------------------------------------------------------------- url guard


def test_validate_web_url():
    assert validate_web_url(" https://example.com/x ") == "https://example.com/x"
    assert validate_web_url("http://localhost:8080") == "http://localhost:8080"
    for bad in ("javascript:x", "file:///etc/passwd", "https://", "", "tc://x"):
        with pytest.raises(ValueError):
            validate_web_url(bad)


def test_classify_and_intercept():
    assert classify_link("tc://?v=2&id=x") == "tonconnect"
    assert classify_link("ton://transfer/abc") == "tonconnect"
    assert classify_link("https://t.me/wallet") == "telegram"
    assert classify_link("tg://resolve?domain=x") == "telegram"
    assert classify_link("https://app.example") == "web"
    assert classify_link("javascript:alert(1)") == "blocked"

    assert intercept_navigation("https://app.example/page") == (True, "web")
    assert intercept_navigation("ton://transfer/x")[0] is False
    assert intercept_navigation("https://t.me/bot/app")[0] is False
    assert intercept_navigation("javascript:evil()") == (False, "blocked")


# --------------------------------------------------------- init data / JS


def test_build_init_data_marks_demo():
    init_data, unsafe = build_init_data("start=1", query_id="qq", demo=True)
    assert "query_id=qq" in init_data
    assert "start_param=start%3D1" in init_data
    assert unsafe == {"query_id": "qq", "start_param": "start=1", "demo": True}


def test_demo_resolution_is_never_authenticated():
    ctx = parse_tma_link(EXACT_URL)
    res = demo_webapp_resolution(ctx)
    assert res.authenticated is False and res.via == "demo"
    assert res.init_data_unsafe["demo"] is True
    assert "auth_date" not in res.init_data and "hash=" not in res.init_data


def test_demo_resolution_targets_bundled_harness():
    """Demo mode must not navigate the webview to the remote t.me stub
    (which immediately bounces to tg://) — it resolves to the bundled
    loopback harness carrying the launch context."""
    ctx = parse_tma_link("https://t.me/wallet")
    res = demo_webapp_resolution(ctx)
    host_url = res.url.split("?")[0]
    assert host_url.startswith("http://127.0.0.1:") and host_url.endswith("/demo")
    assert "t.me" not in host_url
    assert "bot=wallet" in res.url
    assert res.via == "demo" and res.authenticated is False


def test_demo_app_url_carries_context():
    ctx = parse_tma_link("https://t.me/wallet/start?startapp=abc")
    url = demo_app_url(ctx)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["bot"] == ["wallet"]
    assert query["app"] == ["start"]
    assert query["startapp"] == ["abc"]
    assert query["src"] == [ctx.url]


def test_demo_harness_served_over_loopback():
    """The bundled harness is actually served: real HTML over loopback HTTP."""
    url = demo_app_url()
    with urlopen(url, timeout=5) as resp:
        body = resp.read().decode()
        assert resp.status == 200
    assert "twa-demo-harness" in body
    assert "Telegram.WebApp" in body


def test_js_json_escaping():
    """Untrusted strings must be JSON + HTML-context escaped."""
    hostile = '</script><img src=x onerror=alert(1)>\u2028"\\'
    out = _js_json(hostile)
    assert "</script>" not in out
    assert "\\u003c" in out and "\\u003e" in out and "\\u2028" in out
    # still valid JSON
    assert json.loads(out) == hostile


def test_webapp_init_js_never_interpolates_raw():
    hostile = '";alert(1);//\n</script>'
    js = webapp_init_js(start_param=hostile)
    assert "</script>" not in js
    # the value appears only as an escaped JSON literal
    assert _js_json(hostile) in js
    # full API surface present
    for api in (
        "MainButton", "BackButton", "SettingsButton", "HapticFeedback",
        "CloudStorage", "openInvoice", "showPopup", "showConfirm",
        "showScanQrPopup", "readTextFromClipboard", "initDataUnsafe",
        "TelegramWebviewProxy",
    ):
        assert api in js


def test_webapp_init_js_includes_start_param_in_both():
    js = webapp_init_js(start_param="tonconnect-v__2-id__abc")
    assert '"start_param": "tonconnect-v__2-id__abc"' in js
    assert "start_param=tonconnect-v__2-id__abc" in js  # initData query-string
    assert json.loads(re.search(r"initDataUnsafe: (\{.*?\}),", js).group(1))[
        "start_param"
    ] == "tonconnect-v__2-id__abc"


def test_webchannel_bootstrap_js_references_object():
    js = webchannel_bootstrap_js("telegramBridge")
    assert "qwebchannel.js" in js and '"telegramBridge"' in js


# ------------------------------------------------------------- runtime


def test_runtime_dispatch_and_validation():
    rt = WebAppRuntime()
    assert rt.dispatch("web_app_ready", {}).ok
    assert rt.is_ready

    bad = rt.dispatch("not_a_real_event", {})
    assert not bad.ok and "unknown event" in bad.error

    bad = rt.dispatch("web_app_ready", {"x": 1})  # still a dict — ok
    assert bad.ok

    res = rt.dispatch("main_button_update", {"text": "Pay", "is_visible": True})
    assert res.ok
    assert rt.main_button.text == "Pay" and rt.main_button.is_visible


def test_runtime_cloud_storage_rpc():
    rt = WebAppRuntime()
    r = rt.dispatch("cloud_storage", {"req_id": 1, "method": "set", "key": "k", "value": "v"})
    assert r.ok and r.req_id == 1 and r.response is True
    r = rt.dispatch("cloud_storage", {"req_id": 2, "method": "get", "key": "k"})
    assert r.response == "v"
    r = rt.dispatch("cloud_storage", {"req_id": 3, "method": "keys"})
    assert r.response == ["k"]
    r = rt.dispatch("cloud_storage", {"req_id": 4, "method": "remove", "key": "k"})
    assert r.response is True and rt.storage == {}
    bad = rt.dispatch("cloud_storage", {"req_id": 5, "method": "nuke"})
    assert not bad.ok


def test_known_events_cover_js_surface():
    """Every event name the injected JS can post is whitelisted."""
    js = webapp_init_js()
    posted = set(re.findall(r"post\('([a-z_]+)'", js))
    posted |= set(re.findall(r"request\('([a-z_]+)'", js))
    posted |= {"main_button_update", "back_button_update", "settings_button_update"}
    assert posted <= KNOWN_EVENTS, f"JS posts unvalidated events: {posted - KNOWN_EVENTS}"


# -------------------------------------------------------------- resolver


def test_resolve_tma_url_fetches_iframe_target():
    ctx = parse_tma_link(EXACT_URL)

    def fake_get(url):
        assert url == ctx.url  # startapp preserved on the fetch
        return 200, url, '<html><iframe src="https://wallet.example/app?embedded=1"></iframe></html>'

    assert resolve_tma_url(ctx, http_get=fake_get) == "https://wallet.example/app?embedded=1"


def test_resolve_tma_url_follows_redirect():
    ctx = parse_tma_link("https://t.me/bot/app?startapp=p")

    def fake(url):
        return 200, "https://app.example/play?tgWebAppStartParam=p", ""

    assert resolve_tma_url(ctx, http_get=fake) == "https://app.example/play?tgWebAppStartParam=p"


def test_resolve_tma_url_auth_required_error():
    ctx = parse_tma_link("https://t.me/bot/app")

    def plain_page(url):
        return 200, url, "<html>no frame, no redirect</html>"

    def dead(url):
        return 502, url, ""

    with pytest.raises(ValueError, match="Telegram client"):
        resolve_tma_url(ctx, http_get=plain_page)
    with pytest.raises(ValueError, match="HTTP 502"):
        resolve_tma_url(ctx, http_get=dead)


# ------------------------------------------------- legacy bridge/shim API


def test_tma_url_and_validation():
    assert TelegramMiniAppBridge.build_tma_url("@wallet", "a b") == "https://t.me/wallet?startapp=a%20b"
    with pytest.raises(ValueError):
        TelegramMiniAppBridge.build_tma_url("wallet/bad")
    with pytest.raises(ValueError):
        TelegramMiniAppBridge().launch("javascript:alert(1)")


def test_sdk_shim_events():
    events = []
    shim = TelegramWebAppShim("query_id=1")
    shim.onEvent("ready", lambda: events.append("ready"))
    shim.ready()
    assert events == ["ready"]
    assert shim.initData == "query_id=1"


def test_demo_harness_404_for_unknown_path():
    import urllib.error

    base = demo_app_url().split("/demo")[0]
    with pytest.raises(urllib.error.HTTPError) as exc:
        urlopen(base + "/nope", timeout=5)
    assert exc.value.code == 404


def test_callback_server():
    received = []
    bridge = TelegramMiniAppBridge(received.append)
    endpoint = bridge.start_callback_server()
    try:
        with urlopen(endpoint + "?tonconnect=tc%3A%2F%2Frequest", timeout=2) as response:
            assert response.status == 200
        assert received == ["tc://request"]
    finally:
        bridge.close()
