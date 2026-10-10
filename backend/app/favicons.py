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
TIMEOUT = 5
MAX_REDIRECTS = 3
FRESH = timedelta(days=14)
RETRY_FAILED = timedelta(days=2)
USER_AGENT = "Quitly-Favicon/1.0 (+https://github.com/dnoadrian)"


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


def _get(url: str) -> tuple[bytes, str] | None:
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
            conn.request("GET", path, headers={"Host": host, "User-Agent": USER_AGENT, "Accept": "image/*"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location") or ""
                url = urljoin(url, location)
                continue
            if resp.status != 200:
                return None
            length = resp.getheader("Content-Length")
            if length and length.isdigit() and int(length) > MAX_BYTES:
                return None
            data = resp.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                return None
            ctype = sniff(data)
            return (data, ctype) if ctype else None
        finally:
            conn.close()
    return None


def fetch(site: str) -> tuple[bytes, str] | None:
    for url in (f"https://{site}/favicon.ico", f"https://www.{site}/favicon.ico"):
        try:
            got = _get(url)
        except (HostNotAllowed, OSError, ssl.SSLError, http.client.HTTPException, ValueError):
            got = None
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
        if not row.data and age < RETRY_FAILED:
            return None
    got = await run_in_threadpool(fetch, site)
    if row is None:
        row = Favicon(site=site)
        db.add(row)
    row.data, row.content_type, row.fetched_at = (got[0], got[1], now) if got else (None, "", now)
    try:
        db.commit()
    except Exception:  # noqa: BLE001 – paralleler Abruf hat schon gespeichert
        db.rollback()
    return got
