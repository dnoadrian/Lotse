"""Favicons der erkannten Dienste – serverseitig geladen, geprüft und zwischengespeichert.

Warum über den Server: Der Browser lädt so nichts von fremden Seiten (kein Tracking, keine Liste deiner
Konten bei Dritten) und die strenge CSP (img-src 'self') bleibt bestehen.

Sicherheit (SSRF):
- nur HTTPS auf Port 443, nur Namen (keine IP-Literale), DNS wird aufgelöst und jede Adresse muss öffentlich sein
- Verbindung zur geprüften IP, TLS-Zertifikat und Hostname werden geprüft (kein DNS-Rebinding)
- höchstens 3 Weiterleitungen, jede wird erneut geprüft; Zeitlimit; höchstens 256 KB
- nur echte Rasterbilder (PNG, ICO, GIF, JPEG, WebP) anhand der Datei-Signatur – kein SVG, kein HTML
"""
from __future__ import annotations

import http.client
import re
import socket
import ssl
from datetime import timedelta
from urllib.parse import urljoin, urlsplit

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .detection.resolver import registrable_domain
from .jdm.catalog import get_catalog
from .models import Favicon, Service, utcnow
from .security.netguard import HostNotAllowed, normalize_host, resolve_public

MAX_BYTES = 256 * 1024
HTML_BYTES = 512 * 1024
TIMEOUT = 5
MAX_REDIRECTS = 3
FRESH = timedelta(days=14)
RETRY_FAILED = timedelta(hours=12)
# Viele Seiten (Cloudflare, Akamai) weisen unbekannte Programme ab – daher eine übliche Browser-Kennung
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0 Safari/537.36")
# Bei Änderungen am Abrufverfahren erhöhen: alte Fehlschläge werden dann sofort neu versucht
STRATEGY = "v2"


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Verbindet zur vorab geprüften IP, prüft aber Zertifikat und Namen des echten Hosts."""

    def __init__(self, host: str, ip: str, context: ssl.SSLContext):
        super().__init__(host, 443, timeout=TIMEOUT, context=context)
        self._ip = ip
        self._ctx = context

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, 443), timeout=TIMEOUT)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


def _context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


def sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _request(url: str, accept: str, max_bytes: int) -> tuple[bytes, str] | None:
    """GET mit SSRF-Prüfung bei jedem Sprung. → (Daten, endgültige URL) bei 200, sonst None."""
    ctx = _context()
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password:
            return None
        host = normalize_host(parts.hostname or "")
        target = resolve_public(host, 443)
        conn = _PinnedHTTPSConnection(host, target.ip, ctx)
        try:
            path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            conn.request("GET", path, headers={
                "Host": host, "User-Agent": USER_AGENT, "Accept": accept, "Accept-Language": "de,en;q=0.8",
            })
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                url = urljoin(url, resp.getheader("Location") or "")
                continue
            if resp.status != 200:
                return None
            length = resp.getheader("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                return None
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            return data, url
        finally:
            conn.close()
    return None


def _image(url: str) -> tuple[bytes, str] | None:
    try:
        got = _request(url, "image/avif,image/webp,image/png,image/*;q=0.8,*/*;q=0.5", MAX_BYTES)
    except (HostNotAllowed, OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        return None
    if not got:
        return None
    data = got[0]
    ctype = sniff(data)
    # Winzige Platzhalter (z. B. leere 1×1-Bilder) zählen nicht
    return (data, ctype) if ctype and len(data) >= 100 else None


_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def icon_links(html: str, base: str) -> list[str]:
    """Symbol-Links aus dem <head> einer Startseite, große PNGs zuerst (apple-touch-icon), SVG ausgeschlossen."""
    found: list[tuple[int, str]] = []
    for tag in _LINK.findall(html[:300_000]):
        attrs = {k.lower(): v.strip("\"'") for k, v in _ATTR.findall(tag)}
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "")
        if "icon" not in rel or not href or href.startswith("data:"):
            continue
        if href.lower().split("?")[0].endswith(".svg") or "svg" in attrs.get("type", "").lower():
            continue
        url = urljoin(base, href)
        if not url.startswith("https://"):
            continue
        size = 0
        m = re.search(r"(\d+)x\d+", attrs.get("sizes", ""))
        if m:
            size = int(m.group(1))
        if "apple-touch-icon" in rel:
            size = max(size, 180)
        found.append((size, url))
    found.sort(key=lambda x: -x[0])
    return [u for _, u in found][:4]


def fetch(site: str) -> tuple[bytes, str] | None:
    """Mehrstufig, damit auch Seiten mit Bot-Schutz ein Symbol bekommen:
    1. /favicon.ico der Seite  2. Symbol-Links der Startseite  3. DuckDuckGo-Favicon-Dienst  4. Google-Favicon-Dienst.
    Die Dienste in 3/4 sehen nur die Domain und die IP des Servers – nie den Nutzer."""
    for url in (f"https://{site}/favicon.ico", f"https://www.{site}/favicon.ico"):
        got = _image(url)
        if got:
            return got
    try:
        page = _request(f"https://{site}/", "text/html,application/xhtml+xml", HTML_BYTES)
    except (HostNotAllowed, OSError, ssl.SSLError, http.client.HTTPException, ValueError):
        page = None
    if page:
        for url in icon_links(page[0].decode("utf-8", "replace"), page[1]):
            got = _image(url)
            if got:
                return got
    for url in (f"https://icons.duckduckgo.com/ip3/{site}.ico",
                f"https://www.google.com/s2/favicons?domain={site}&sz=64"):
        got = _image(url)
        if got:
            return got
    return None


def site_for(svc: Service) -> str | None:
    """Die Website des Dienstes: bevorzugt die Domain aus JustDeleteMe, sonst die registrierbare Absender-Domain."""
    entry = get_catalog().by_name(svc.jdm_name)
    candidates = list(entry.domains) if entry is not None else []
    candidates += [registrable_domain(d) for d in (svc.domains or [])]
    for c in candidates:
        try:
            return normalize_host(c)
        except HostNotAllowed:
            continue
    return None


async def get_icon(db: Session, site: str | None) -> tuple[bytes, str] | None:
    if not site:
        return None
    row = db.get(Favicon, site)
    now = utcnow()
    if row is not None:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=now.tzinfo)
        age = now - fetched
        if row.data and age < FRESH:
            return row.data, row.content_type
        if not row.data and age < RETRY_FAILED and row.content_type == f"fail:{STRATEGY}":
            return None
    got = await run_in_threadpool(fetch, site)
    if row is None:
        row = Favicon(site=site)
        db.add(row)
    row.data, row.content_type, row.fetched_at = (got[0], got[1], now) if got else (None, f"fail:{STRATEGY}", now)
    try:
        db.commit()
    except Exception:  # noqa: BLE001 – paralleler Abruf hat schon gespeichert
        db.rollback()
    return got
