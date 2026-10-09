"""Robustes, defensives Parsen von Kopfzeilen. Es werden nie Bodies oder Anhänge verarbeitet."""
from __future__ import annotations

import base64
import binascii
import codecs
import email
import email.policy
import html
import quopri
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import getaddresses, parsedate_to_datetime

_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u2069]")
_WS = re.compile(r"\s+")


def clean_text(value: str, limit: int = 300) -> str:
    """Steuer- und Bidi-Zeichen entfernen, Whitespace normalisieren, Länge begrenzen."""
    value = _CTRL.sub("", value or "")
    value = _WS.sub(" ", value).strip()
    return value[:limit]


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


@dataclass
class MailHeaders:
    from_name: str
    from_addr: str
    from_domain: str
    subject: str
    date: datetime | None
    list_unsubscribe: bool
    auto_submitted: bool


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _domain_of(addr: str) -> str:
    if "@" not in addr:
        return ""
    dom = addr.rsplit("@", 1)[1].strip().strip(">").lower().rstrip(".")
    if not re.fullmatch(r"[a-z0-9.-]{1,253}", dom) or ".." in dom or "." not in dom:
        try:
            dom = dom.encode("idna").decode("ascii")
        except Exception:
            return ""
        if not re.fullmatch(r"[a-z0-9.-]{1,253}", dom):
            return ""
    return dom


def from_mapping(h: dict[str, str]) -> MailHeaders:
    raw_from = decode_mime(h.get("from", ""))
    try:
        pairs = getaddresses([raw_from])
    except Exception:
        pairs = []
    name, addr = (pairs[0] if pairs else ("", ""))
    addr = clean_text(addr, 254).lower()
    return MailHeaders(
        from_name=clean_text(name, 120),
        from_addr=addr,
        from_domain=_domain_of(addr),
        subject=clean_text(decode_mime(h.get("subject", "")), 300),
        date=_parse_date(h.get("date")),
        list_unsubscribe=bool(h.get("list-unsubscribe")),
        auto_submitted=(h.get("auto-submitted", "").strip().lower() not in ("", "no")),
    )


def parse_raw(raw: bytes) -> MailHeaders:
    raw = raw[:16384]
    # Viele Server liefern 8-Bit-UTF-8 in Kopfzeilen (RFC 6532); sonst Latin-1 als verlustfreier Rückfall
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    msg = email.message_from_string(text, policy=email.policy.compat32)
    h = {}
    for key in ("from", "subject", "date", "list-unsubscribe", "auto-submitted"):
        v = msg.get(key)
        if v is not None:
            h[key] = str(v)[:2000]
    return from_mapping(h)


# ------------------------------------------------------------------ Text-Anfang (nur im Speicher)

_TAGS = re.compile(r"<(script|style|head)\b.*?</\1\s*>|<[^>]{0,2000}>", re.IGNORECASE | re.DOTALL)
TEXT_LIMIT = 4000


def _charset(name: str | None) -> str:
    try:
        return codecs.lookup(name or "utf-8").name
    except LookupError:
        return "utf-8"


def _decode_part(part) -> str:
    raw = part.get_payload(decode=False)
    if not isinstance(raw, str):
        return ""
    cte = (part.get("content-transfer-encoding") or "").strip().lower()
    data = raw.encode("latin-1", "replace")
    if cte == "base64":
        cleaned = re.sub(rb"[^A-Za-z0-9+/=]", b"", data)
        cleaned = cleaned[: len(cleaned) // 4 * 4]  # abgeschnittene Daten tolerieren
        try:
            data = base64.b64decode(cleaned)
        except (binascii.Error, ValueError):
            return ""
    elif cte == "quoted-printable":
        data = quopri.decodestring(data)
    text = data.decode(_charset(part.get_content_charset()), "replace")
    if part.get_content_type() == "text/html":
        text = html.unescape(_TAGS.sub(" ", text))
    return text


def body_text(raw_headers: bytes, raw_body: bytes, limit: int = TEXT_LIMIT) -> str:
    """Liest den Anfang des Textes einer Mail für die Erkennung (nie gespeichert, nie geloggt).

    Es werden nur text/plain- und text/html-Teile betrachtet; Anhänge werden übersprungen,
    HTML wird nicht gerendert, sondern zu Text reduziert.
    """
    if not raw_body:
        return ""
    try:
        msg = email.message_from_bytes(raw_headers[:16384] + b"\r\n" + raw_body[:16384], policy=email.policy.compat32)
    except Exception:
        return ""
    out: list[str] = []
    size = 0
    try:
        parts = list(msg.walk())
    except Exception:
        parts = [msg]
    for part in parts[:20]:
        if part.is_multipart():
            continue
        if part.get_content_type() not in ("text/plain", "text/html"):
            continue
        if (part.get("content-disposition") or "").lower().startswith("attachment"):
            continue
        try:
            chunk = _decode_part(part)
        except Exception:
            continue
        out.append(chunk)
        size += len(chunk)
        if size >= limit:
            break
    return clean_text(" ".join(out), limit)
