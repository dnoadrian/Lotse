"""Eine einzelne Mail sicher zum Lesen aufbereiten.

- Nur im Arbeitsspeicher: nichts davon wird gespeichert oder protokolliert
- Text: reiner Text (Steuer- und Bidi-Zeichen entfernt, Länge begrenzt)
- HTML: serverseitig mit nh3 bereinigt (kein Script, keine Formulare, keine Frames, keine Event-Handler),
  anschließend nur in einem sandboxed iframe mit eigener, strenger CSP angezeigt
- Eingebettete Bilder (cid:) werden als data:-URI eingesetzt, externe Bilder blockiert die CSP standardmäßig
- Anhänge: nur Name, Typ und Größe – Inhalte werden nie ausgeliefert
"""
from __future__ import annotations

import base64
import email
import html as _html
import email.policy
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime

import nh3

from ..detection.headers import _CTRL, clean_text, decode_mime

MAX_MESSAGE_BYTES = 4 * 1024 * 1024
TEXT_LIMIT = 200_000
HTML_LIMIT = 1_000_000
INLINE_IMAGE_LIMIT = 300_000
INLINE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}

ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "center", "code", "col", "colgroup", "dd", "del", "div", "dl",
    "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p",
    "pre", "q", "s", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th",
    "thead", "tr", "tt", "u", "ul",
}
GENERIC_ATTRS = {"align", "valign", "width", "height", "style", "bgcolor", "color", "border", "dir", "title", "lang"}
ALLOWED_ATTRS = {
    "*": GENERIC_ATTRS,
    "a": {"href", "name"},
    "img": {"src", "alt"},
    "table": {"cellpadding", "cellspacing", "summary"},
    "td": {"colspan", "rowspan", "nowrap"},
    "th": {"colspan", "rowspan", "scope"},
    "font": {"face", "size"},
    "col": {"span"},
    "colgroup": {"span"},
    "ol": {"start", "type"},
    "li": {"value"},
}


@dataclass
class Attachment:
    name: str
    content_type: str
    size: int


@dataclass
class ParsedMessage:
    from_: str
    to: str
    cc: str
    date: str | None
    subject: str
    text: str
    html: str | None
    attachments: list[Attachment] = field(default_factory=list)
    unsubscribe_https: str | None = None
    unsubscribe_mailto: str | None = None
    truncated: bool = False


def _addresses(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for name, addr in getaddresses([decode_mime(value)]):
        name, addr = clean_text(name, 120), clean_text(addr, 254)
        parts.append(f"{name} <{addr}>" if name and addr else (addr or name))
    return clean_text(", ".join(p for p in parts if p), 1000)


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def _unsubscribe(value: str | None) -> tuple[str | None, str | None]:
    """List-Unsubscribe nur auswerten, nie serverseitig aufrufen."""
    https, mailto = None, None
    for target in re.findall(r"<([^<>\s]{1,2000})>", value or ""):
        lowered = target.lower()
        if https is None and lowered.startswith("https://") and not _CTRL.search(target):
            https = target
        elif mailto is None and lowered.startswith("mailto:") and not _CTRL.search(target):
            mailto = target
    return https, mailto


def _content(part) -> str:
    try:
        value = part.get_content()
    except (LookupError, ValueError, AssertionError, UnicodeError):
        payload = part.get_payload(decode=True) or b""
        value = payload.decode("utf-8", "replace")
    return value if isinstance(value, str) else ""


def _inline_images(msg: EmailMessage) -> dict[str, str]:
    """cid → data:-URI für kleine eingebettete Bilder (lokal, kein Tracking)."""
    out: dict[str, str] = {}
    for part in msg.walk():
        cid = (part.get("content-id") or "").strip().strip("<>")
        ctype = part.get_content_type()
        if not cid or ctype not in INLINE_IMAGE_TYPES or len(out) >= 30:
            continue
        data = part.get_payload(decode=True) or b""
        if 0 < len(data) <= INLINE_IMAGE_LIMIT:
            out[cid.lower()] = f"data:{ctype};base64,{base64.b64encode(data).decode('ascii')}"
    return out


def sanitize_html(html: str, inline: dict[str, str] | None = None) -> str:
    inline = inline or {}

    def attribute_filter(tag: str, attr: str, value: str) -> str | None:
        if tag == "img" and attr == "src":
            v = value.strip()
            if v.lower().startswith("cid:"):
                return inline.get(v[4:].strip("<>").lower())
            if v.lower().startswith(("https://", "http://", "data:image/")):
                return v
            return None
        if attr == "href" and value.strip().lower().startswith(("data:", "cid:")):
            return None
        if attr == "style" and re.search(r"expression\s*\(|javascript:|behavior\s*:|-moz-binding", value, re.I):
            return None
        return value

    return nh3.clean(
        html[:HTML_LIMIT],
        tags=ALLOWED_TAGS,
        clean_content_tags={"script", "style", "title", "head", "template", "noscript", "svg", "math"},
        attributes=ALLOWED_ATTRS,
        attribute_filter=attribute_filter,
        url_schemes={"http", "https", "mailto", "data", "cid"},
        link_rel="noopener noreferrer nofollow",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        strip_comments=True,
    )


def html_document(clean_html: str) -> str:
    """Bereinigtes HTML in ein schlichtes Dokument mit Grundstil einbetten (für das sandboxed iframe)."""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><base target=\"_blank\">"
        "<style>html{background:#fff}body{margin:16px;font:15px/1.5 system-ui,-apple-system,'Segoe UI',sans-serif;"
        "color:#15171a;overflow-wrap:anywhere}img{max-width:100%;height:auto}table{max-width:100%}"
        "a{color:#1d4ed8}</style></head><body>" + clean_html + "</body></html>"
    )


def html_to_text(html: str) -> str:
    text = nh3.clean(html[:HTML_LIMIT], tags={"br", "p", "div", "li", "tr"}, attributes={})
    text = re.sub(r"<(br|/p|/div|/li|/tr)\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return _html.unescape(text)


def _clean_body(text: str) -> str:
    text = _CTRL.sub("", text.replace("\r\n", "\n"))
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()[:TEXT_LIMIT]


def parse_message(raw: bytes, truncated: bool = False) -> ParsedMessage:
    msg = email.message_from_bytes(raw[:MAX_MESSAGE_BYTES], policy=email.policy.default)
    plain_part = msg.get_body(preferencelist=("plain",))
    html_part = msg.get_body(preferencelist=("html",))
    html_raw = _content(html_part) if html_part is not None else ""
    text = _content(plain_part) if plain_part is not None else ""
    if not text and html_raw:
        text = html_to_text(html_raw)

    attachments: list[Attachment] = []
    for part in msg.iter_attachments():
        if len(attachments) >= 50:
            break
        name = clean_text(decode_mime(part.get_filename() or ""), 200) or "(ohne Namen)"
        payload = part.get_payload(decode=True) or b""
        attachments.append(Attachment(name=name, content_type=clean_text(part.get_content_type(), 100), size=len(payload)))

    https, mailto = _unsubscribe(str(msg.get("list-unsubscribe") or ""))
    clean_html = sanitize_html(html_raw, _inline_images(msg)) if html_raw else None
    return ParsedMessage(
        from_=_addresses(str(msg.get("from") or "")),
        to=_addresses(str(msg.get("to") or "")),
        cc=_addresses(str(msg.get("cc") or "")),
        date=_date(str(msg.get("date") or "")),
        subject=clean_text(decode_mime(str(msg.get("subject") or "")), 500),
        text=_clean_body(text),
        html=clean_html,
        attachments=attachments,
        unsubscribe_https=https,
        unsubscribe_mailto=mailto,
        truncated=truncated,
    )
