"""Favicons der erkannten Dienste – serverseitig geladen, geprüft und zwischengespeichert.

Warum über den Server: Der Browser lädt so nichts von fremden Seiten (kein Tracking, keine Liste deiner
Konten bei Dritten) und die strenge CSP (img-src 'self') bleibt bestehen.

Sicherheit (SSRF):
- nur HTTPS auf Port 443, nur Namen (keine IP-Literale), DNS wird aufgelöst und jede Adresse muss öffentlich sein
- Verbindung zur geprüften IP, TLS-Zertifikat und Hostname werden geprüft (kein DNS-Rebinding)
- höchstens 3 Weiterleitungen, jede wird erneut geprüft; Zeitlimit; höchstens 512 KB
- nur echte Bilder anhand der Datei-Signatur (PNG, ICO, GIF, JPEG, WebP, SVG ohne Skripte) – kein HTML;
  ausgeliefert mit nosniff und einer CSP, die jedes Skript verbietet (auch bei direktem Aufruf)
"""
from __future__ import annotations

import asyncio
import html as _html
import http.client
import logging
import re
import socket
import ssl
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import timedelta
from urllib.parse import urljoin, urlsplit

import anyio
from sqlalchemy.orm import Session

from .config import get_settings

from .detection.resolver import registrable_domain
from .jdm.catalog import get_catalog
from .models import Favicon, Service, utcnow
from .security.netguard import HostNotAllowed, normalize_host, resolve_public

MAX_BYTES = 512 * 1024
HTML_BYTES = 512 * 1024
TIMEOUT = 5
MAX_REDIRECTS = 3
FRESH = timedelta(days=14)
RETRY_FAILED = timedelta(hours=1)
# Gesamtzeit pro Stufe – eine einzelne hängende Seite blockiert so nicht alles andere
PHASE_SECONDS = 9
# Viele Seiten (Cloudflare, Akamai) weisen unbekannte Programme ab – daher eine übliche Browser-Kennung
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0 Safari/537.36")
# Bei Änderungen am Abrufverfahren erhöhen: alte Fehlschläge werden dann sofort neu versucht
STRATEGY = "v5"

log = logging.getLogger("quitly.favicons")
# Eigener Pool: Favicon-Abrufe dürfen nie die Threads der übrigen API belegen
_POOL = ThreadPoolExecutor(max_workers=32, thread_name_prefix="favicon")
_LIMIT = anyio.CapacityLimiter(5)
_INFLIGHT: dict[str, asyncio.Future] = {}


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
    if data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if (head.startswith(b"<svg") or head.startswith((b"<?xml", b"<!--", b"<!doctype svg"))) and b"<svg" in head:
        body = data.lower()
        if any(bad in body for bad in (b"<script", b"javascript:", b"<foreignobject", b"onload=", b"onerror=")):
            return None
        return "image/svg+xml"
    return None


def _request(url: str, accept: str, max_bytes: int, why: list[str] | None = None) -> tuple[bytes, str] | None:
    """GET mit SSRF-Prüfung bei jedem Sprung. → (Daten, endgültige URL) bei 200, sonst None (Grund in `why`)."""
    why = why if why is not None else []
    ctx = _context()
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.port not in (None, 443) or parts.username or parts.password:
            why.append(f"{url}: kein HTTPS")
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
                why.append(f"{url}: HTTP {resp.status}")
                return None
            length = resp.getheader("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                why.append(f"{url}: zu groß")
                return None
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                why.append(f"{url}: zu groß")
                return None
            encoding = (resp.getheader("Content-Encoding") or "").lower()
            if encoding in ("gzip", "x-gzip", "deflate"):
                # Manche CDNs komprimieren trotzdem – begrenzt entpacken (Schutz vor Zip-Bomben)
                d = zlib.decompressobj(zlib.MAX_WBITS | 32 if encoding != "deflate" else zlib.MAX_WBITS)
                data = d.decompress(data, max_bytes + 1)
                if len(data) > max_bytes:
                    return None
            elif encoding not in ("", "identity"):
                why.append(f"{url}: Kodierung {encoding}")
                return None
            return data, url
        finally:
            conn.close()
    why.append(f"{url}: zu viele Weiterleitungen")
    return None


_NET_ERRORS = (HostNotAllowed, OSError, ssl.SSLError, http.client.HTTPException, ValueError, zlib.error)


def _image(url: str, why: list[str] | None = None) -> tuple[bytes, str] | None:
    why = why if why is not None else []
    try:
        got = _request(url, "image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5", MAX_BYTES, why)
    except _NET_ERRORS as exc:
        why.append(f"{url}: {type(exc).__name__}")
        return None
    if not got:
        return None
    data = got[0]
    ctype = sniff(data)
    if not ctype:
        why.append(f"{url}: kein Bild")
        return None
    # Winzige Platzhalter (z. B. leere 1×1-Bilder) zählen nicht
    if len(data) < 100:
        why.append(f"{url}: Platzhalter")
        return None
    return data, ctype


_LINK = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def icon_links(html: str, base: str) -> list[str]:
    """Symbol-Links aus dem <head> einer Startseite, große zuerst (apple-touch-icon, dann SVG, dann nach Größe)."""
    found: list[tuple[int, str]] = []
    for tag in _LINK.findall(html[:300_000]):
        attrs = {k.lower(): _html.unescape(v.strip("\"'")) for k, v in _ATTR.findall(tag)}
        rel = attrs.get("rel", "").lower()
        href = attrs.get("href", "")
        if "icon" not in rel or not href or href.startswith("data:"):
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
        elif href.lower().split("?")[0].endswith(".svg") or "svg" in attrs.get("type", "").lower():
            size = max(size, 120)  # SVG ist in jeder Größe scharf
        found.append((size, url))
    found.sort(key=lambda x: -x[0])
    return [u for _, u in found][:4]


def _from_homepage(host: str, why: list[str]) -> tuple[bytes, str] | None:
    try:
        page = _request(f"https://{host}/", "text/html,application/xhtml+xml", HTML_BYTES, why)
    except _NET_ERRORS as exc:
        why.append(f"https://{host}/: {type(exc).__name__}")
        return None
    if not page:
        return None
    for url in icon_links(page[0].decode("utf-8", "replace"), page[1]):
        got = _image(url, why)
        if got:
            return got
    return None


def _best(tasks: list, why: list[str]) -> tuple[bytes, str] | None:
    """Alle Abrufe einer Stufe parallel; Ergebnis nach Rangfolge der Liste, gemeinsames Zeitlimit."""
    futures = [_POOL.submit(task) for task in tasks]
    deadline = time.monotonic() + PHASE_SECONDS
    try:
        for fut in futures:
            try:
                got = fut.result(timeout=max(0.0, deadline - time.monotonic()))
            except FutureTimeout:
                why.append("Zeitlimit")
                continue
            except Exception as exc:  # noqa: BLE001 – ein Fehler darf die anderen Wege nicht abbrechen
                why.append(type(exc).__name__)
                continue
            if got:
                return got
        return None
    finally:
        for fut in futures:
            fut.cancel()


def fetch(site: str, why: list[str] | None = None) -> tuple[bytes, str] | None:
    """Zwei Stufen, jeweils für die Domain und ihre www.-Variante (viele Seiten laufen nur unter www.):
    1. die Seite selbst: /favicon.ico und die Symbol-Links der Startseite
    2. Symboldienste: DuckDuckGo, Google, gstatic – sie sehen nur die Domain und die IP des Servers, nie den Nutzer."""
    why = why if why is not None else []
    hosts = [site, f"www.{site}"] if not site.startswith("www.") else [site, site[4:]]
    own = [lambda h=h: _image(f"https://{h}/favicon.ico", why) for h in hosts]
    own += [lambda h=h: _from_homepage(h, why) for h in hosts]
    got = _best(own, why)
    if got:
        return got
    services = []
    for h in hosts:
        services += [
            lambda h=h: _image(f"https://icons.duckduckgo.com/ip3/{h}.ico", why),
            lambda h=h: _image(f"https://www.google.com/s2/favicons?domain={h}&sz=64", why),
            lambda h=h: _image("https://t1.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL"
                               f"&url=https://{h}&size=64", why),
        ]
    return _best(services, why)


def sites_for(svc: Service) -> list[str]:
    """Mögliche Websites des Dienstes: Domains aus JustDeleteMe, dann die registrierbaren Absender-Domains."""
    entry = get_catalog().by_name(svc.jdm_name)
    candidates = list(entry.domains) if entry is not None else []
    candidates += [registrable_domain(d) for d in (svc.domains or [])]
    out: list[str] = []
    for c in candidates:
        try:
            host = normalize_host(c)
        except HostNotAllowed:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host not in out:
            out.append(host)
    return out[:3]


def site_for(svc: Service) -> str | None:
    sites = sites_for(svc)
    return sites[0] if sites else None


def fetch_any(sites: list[str]) -> tuple[bytes, str] | None:
    why: list[str] = []
    for site in sites:
        got = fetch(site, why)
        if got:
            return got
    if get_settings().favicon_debug:
        # Nur Domains und Fehlerarten – keine Nutzer- oder Maildaten
        log.info("Kein Favicon für %s: %s", ", ".join(sites), "; ".join(why[:40]))
    return None


async def _fetch_once(sites: list[str]) -> tuple[bytes, str] | None:
    """Gleichzeitige Anfragen für dieselbe Seite teilen sich einen Abruf."""
    key = sites[0]
    pending = _INFLIGHT.get(key)
    if pending is not None:
        return await asyncio.shield(pending)
    fut = asyncio.get_running_loop().create_future()
    _INFLIGHT[key] = fut
    got = None
    try:
        got = await anyio.to_thread.run_sync(fetch_any, sites, limiter=_LIMIT)
        return got
    finally:
        _INFLIGHT.pop(key, None)
        fut.set_result(got)


async def get_icon(db: Session, sites: list[str] | str | None) -> tuple[bytes, str] | None:
    if isinstance(sites, str):
        sites = [sites]
    if not sites:
        return None
    site = sites[0]
    row = db.get(Favicon, site)
    now = utcnow()
    if row is not None:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=now.tzinfo)
        age = now - fetched
        if row.data and age < FRESH:
            return row.data, row.content_type
        if not row.data and age < RETRY_FAILED and row.content_type == f"fail:{STRATEGY}":
            return None
    got = await _fetch_once(sites)
    row = db.get(Favicon, site)
    if row is None:
        row = Favicon(site=site)
        db.add(row)
    row.data, row.content_type, row.fetched_at = (got[0], got[1], now) if got else (None, f"fail:{STRATEGY}", now)
    try:
        db.commit()
    except Exception:  # noqa: BLE001 – paralleler Abruf hat schon gespeichert
        db.rollback()
    return got
