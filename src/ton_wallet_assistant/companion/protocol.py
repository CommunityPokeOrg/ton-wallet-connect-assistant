"""Pairing protocol: tokens, payload validation, replay protection.

The mobile companion flow is a *relay*: the phone's browser opens a
token-gated page served by the desktop and POSTs payloads it scanned
(TonConnect universal links like ``tc://...`` or ``ton://transfer/...``).
The desktop validates and queues them for explicit user approval.

Security model
--------------
* Pairing token: 256-bit ``secrets.token_urlsafe(32)`` generated per server
  start. Required on every API call; the pairing page URL embeds it in the
  path so it is only ever exposed to whoever scanned the desktop's pairing QR.
* Replay protection: each relay POST carries a fresh ``nonce`` (client-random)
  and ``ts`` (unix seconds). Nonces are single-use; timestamps outside
  ``MAX_SKEW_SECONDS`` are rejected.
* Requests expire after ``REQUEST_TTL_SECONDS`` — a stale QR cannot be
  approved hours later.
* Payloads are strictly validated before they ever reach the approval layer:
  only ``tc://`` / https TonConnect universal links (``v=2&id=&r=``) and
  ``ton://`` transfer links are accepted.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import parse_qs, urlparse

MAX_SKEW_SECONDS = 120
REQUEST_TTL_SECONDS = 300
MAX_PAYLOAD_BYTES = 16 * 1024


def new_pairing_token() -> str:
    return secrets.token_urlsafe(32)


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


class PayloadKind(str, Enum):
    TONCONNECT_LINK = "tonconnect-link"  # tc:// or https universal link
    TON_TRANSFER = "ton-transfer"  # ton://transfer/<addr>?amount=&text=


class ValidationError(ValueError):
    pass


class ReplayError(ValueError):
    pass


@dataclass(frozen=True)
class TransferDetails:
    """Parsed contents of a ``ton://transfer/`` payload."""

    address: str
    amount_nano: int | None = None
    comment: str = ""
    jetton: str = ""  # jetton master address, if the link requests one

    @property
    def amount_text(self) -> str:
        if self.amount_nano is None:
            return "—"
        from ..wallet.chain import format_ton

        return f"{format_ton(self.amount_nano)} TON"


@dataclass(frozen=True)
class TonConnectLinkDetails:
    """Parsed contents of a TonConnect universal link."""

    url: str
    wallet_host: str  # app_name / host portion of the link
    session_id: str
    items: tuple[str, ...]  # requested items, e.g. ("ton_addr",)


def _parse_ton_transfer(url: str) -> TransferDetails:
    parsed = urlparse(url)
    # ton://transfer/<address>?amount=<nano>&text=<comment>&jetton=<master>
    if parsed.scheme != "ton" or parsed.netloc != "transfer":
        raise ValidationError("ton:// payload must be ton://transfer/<address>")
    address = parsed.path.strip("/")
    if not address:
        raise ValidationError("ton://transfer link has no address")
    from ..address_utils import is_friendly_address, is_raw_address

    if not (is_friendly_address(address) or is_raw_address(address)):
        raise ValidationError("transfer destination is not a valid TON address")
    params = parse_qs(parsed.query)
    amount = None
    if "amount" in params:
        try:
            amount = int(params["amount"][0])
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid amount in ton:// link") from exc
        if amount <= 0 or amount > 10**19:
            raise ValidationError("amount out of range")
    comment = params.get("text", [""])[0][:512]
    jetton = params.get("jetton", [""])[0]
    if jetton and not (is_friendly_address(jetton) or is_raw_address(jetton)):
        raise ValidationError("invalid jetton address in ton:// link")
    return TransferDetails(address=address, amount_nano=amount, comment=comment, jetton=jetton)


def _parse_tonconnect_link(url: str) -> TonConnectLinkDetails:
    parsed = urlparse(url)
    if parsed.scheme == "tc":
        query = parsed.query
        host = parsed.netloc or "tc"
    elif parsed.scheme == "https":
        query = parsed.query
        host = parsed.netloc
    else:
        raise ValidationError("TonConnect link must use tc:// or https:// scheme")
    params = parse_qs(query)
    if params.get("v", [""])[0] != "2":
        raise ValidationError("not a TonConnect v2 link")
    session_id = params.get("id", [""])[0]
    if not session_id or len(session_id) < 16:
        raise ValidationError("TonConnect link is missing a valid session id")
    raw_request = params.get("r", [""])[0]
    if not raw_request:
        raise ValidationError("TonConnect link has no request payload (r=)")
    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError as exc:
        raise ValidationError("TonConnect request payload is not valid JSON") from exc
    if not isinstance(request, dict) or not isinstance(request.get("items"), list):
        raise ValidationError("TonConnect request payload is malformed")
    items = tuple(str(i.get("name", "")) for i in request["items"] if isinstance(i, dict))
    return TonConnectLinkDetails(url=url, wallet_host=host, session_id=session_id, items=items)


def parse_payload(text: str) -> tuple[PayloadKind, TransferDetails | TonConnectLinkDetails]:
    """Validate a scanned/pasted payload. Raises ValidationError."""
    text = text.strip()
    if len(text.encode()) > MAX_PAYLOAD_BYTES:
        raise ValidationError("payload too large")
    if text.startswith("ton://"):
        return PayloadKind.TON_TRANSFER, _parse_ton_transfer(text)
    lowered = text.lower()
    if lowered.startswith("tc://") or (
        lowered.startswith("https://") and ("v=2" in text and "id=" in text and "r=" in text)
    ):
        return PayloadKind.TONCONNECT_LINK, _parse_tonconnect_link(text)
    raise ValidationError("unsupported payload — expected a tc://, ton://, or TonConnect link")


class RequestState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    COMPLETED = "completed"  # broadcast/connected
    FAILED = "failed"


@dataclass
class RelayedRequest:
    """One payload relayed from a paired mobile device."""

    request_id: str
    kind: PayloadKind
    payload: TransferDetails | TonConnectLinkDetails
    origin_ip: str
    received_at: float = field(default_factory=time.time)
    state: RequestState = RequestState.PENDING
    result: str = ""
    error: str = ""

    def expired(self, now: float | None = None) -> bool:
        return (now or time.time()) - self.received_at > REQUEST_TTL_SECONDS

    def as_dict(self) -> dict:
        out = {
            "id": self.request_id,
            "kind": self.kind.value,
            "state": self.state.value,
            "received_at": self.received_at,
        }
        if isinstance(self.payload, TransferDetails):
            out["details"] = {
                "address": self.payload.address,
                "amount_nano": self.payload.amount_nano,
                "comment": self.payload.comment,
                "jetton": self.payload.jetton,
            }
        else:
            out["details"] = {
                "wallet_host": self.payload.wallet_host,
                "session_id": self.payload.session_id,
                "items": list(self.payload.items),
            }
        if self.result:
            out["result"] = self.result
        if self.error:
            out["error"] = self.error
        return out


class NonceTracker:
    """Single-use nonces within a timestamp skew window."""

    def __init__(self, max_age: int = MAX_SKEW_SECONDS) -> None:
        self._seen: dict[str, float] = {}
        self._max_age = max_age

    def check(self, nonce: str, ts: float, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if not nonce or len(nonce) < 16:
            raise ReplayError("invalid nonce")
        if abs(now - ts) > self._max_age:
            raise ReplayError("timestamp outside accepted window")
        # purge old entries then reject reuse
        self._seen = {n: t for n, t in self._seen.items() if now - t <= self._max_age}
        if nonce in self._seen:
            raise ReplayError("nonce already used (replay)")
        self._seen[nonce] = now
