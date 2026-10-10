"""Lesen von Mails: Bereinigung, Anhänge, Abmelde-Links; Favicon-Prüfungen; SSRF für Favicons."""
from __future__ import annotations

import socket

import pytest

from app.favicons import sniff
from app.mail.message import parse_message, sanitize_html
from app.security.netguard import HostNotAllowed, resolve_public

MIXED = (
    b"From: =?utf-8?q?B=C3=A4ckerei?= <shop@baeckerei.at>\r\nTo: a@b.at\r\nSubject: Rechnung\r\n"
    b"Date: Mon, 05 Oct 2026 10:00:00 +0000\r\nList-Unsubscribe: <javascript:alert(1)>, <https://x.example/u>\r\n"
    b"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=m\r\n\r\n"
    b"--m\r\nContent-Type: multipart/related; boundary=r\r\n\r\n"
    b"--r\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
    b"<p style=\"color:red\">Danke <img src=\"cid:logo1\"> <img src=\"https://t.example/p.gif\"></p>"
    b"<a href=\"https://shop.example\" onmouseover=\"x()\">Shop</a>\r\n"
    b"--r\r\nContent-Type: image/png\r\nContent-ID: <logo1>\r\nContent-Transfer-Encoding: base64\r\n\r\n"
    b"iVBORw0KGgo=\r\n--r--\r\n"
    b"--m\r\nContent-Type: application/pdf; name=rechnung.pdf\r\nContent-Disposition: attachment; filename=rechnung.pdf\r\n"
    b"Content-Transfer-Encoding: base64\r\n\r\nJVBERi0xLjQ=\r\n--m--\r\n"
)


def test_parse_message_html_only_with_inline_image_and_attachment():
    m = parse_message(MIXED)
    assert m.from_.startswith("Bäckerei") and m.subject == "Rechnung"
    assert "Danke" in m.text  # Text aus HTML abgeleitet
    assert m.html and "data:image/png;base64," in m.html  # cid eingebettet
    assert "onmouseover" not in m.html and 'target="_blank"' in m.html
    assert [a.name for a in m.attachments] == ["rechnung.pdf"] and m.attachments[0].size > 0
    assert m.unsubscribe_https == "https://x.example/u"  # javascript: wird ignoriert


@pytest.mark.parametrize("dirty", [
    '<img src=x onerror=alert(1)>', '<svg onload=alert(1)>', '<a href="javascript:alert(1)">x</a>',
    '<iframe src="https://evil"></iframe>', '<form><input name=a></form>', '<script>alert(1)</script>',
    '<div style="background:url(javascript:alert(1))">x</div>', '<object data="x"></object>',
    '<meta http-equiv="refresh" content="0;url=https://evil">', '<base href="https://evil/">',
    '<a href="data:text/html,<script>alert(1)</script>">x</a>',
])
def test_sanitizer_removes_active_content(dirty):
    clean = sanitize_html(dirty).lower()
    for bad in ("onerror", "onload", "javascript:", "<iframe", "<form", "<input", "<script", "<object", "<meta", "<base", "<svg",
                "data:text"):
        assert bad not in clean


def test_favicon_sniffing_accepts_only_raster_images():
    assert sniff(b"\x89PNG\r\n\x1a\n....") == "image/png"
    assert sniff(b"\x00\x00\x01\x00rest") == "image/x-icon"
    assert sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff(b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>") is None
    assert sniff(b"<!doctype html><html>") is None


def _fake(ip):
    return lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


def test_favicon_fetch_only_to_public_addresses():
    assert resolve_public("example.com", 443, resolver=_fake("93.184.216.34")).ip == "93.184.216.34"
    for ip in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        with pytest.raises(HostNotAllowed):
            resolve_public("evil.example", 443, resolver=_fake(ip))
    with pytest.raises(HostNotAllowed):
        resolve_public("127.0.0.1", 443)


def test_icon_links_prefers_large_icons_including_svg():
    from app.favicons import icon_links

    html = (
        '<head><link rel="icon" type="image/svg+xml" href="/icon.svg">'
        '<link rel="shortcut icon" href="/favicon-32.png" sizes="32x32">'
        "<link rel='apple-touch-icon' href='https://cdn.example.com/apple.png'>"
        '<link rel="icon" href="javascript:alert(1)"><link rel="stylesheet" href="/a.css"></head>'
    )
    assert icon_links(html, "https://www.example.com/") == [
        "https://cdn.example.com/apple.png", "https://www.example.com/icon.svg",
        "https://www.example.com/favicon-32.png",
    ]
    assert icon_links('<link rel="icon" href="/i.png?a=1&amp;b=2">', "https://x.example/") == ["https://x.example/i.png?a=1&b=2"]


def test_svg_icons_only_without_scripts():
    good = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><circle r="4"/></svg>'
    assert sniff(good) == "image/svg+xml"
    for bad in (b'<svg onload="alert(1)"></svg>', b"<svg><script>alert(1)</script></svg>",
                b'<svg><a href="javascript:alert(1)"/></svg>', b"<svg><foreignObject><p/></foreignObject></svg>"):
        assert sniff(bad) is None


def test_favicon_tries_all_candidate_sites(monkeypatch):
    from app import favicons

    seen = []
    monkeypatch.setattr(favicons, "fetch", lambda site, why=None: seen.append(site) or ((b"x", "image/png") if site == "petpanda.at" else None))
    assert favicons.fetch_any(["mailer-petpanda.com", "petpanda.at"]) == (b"x", "image/png")
    assert seen == ["mailer-petpanda.com", "petpanda.at"]


def test_favicon_fetch_falls_back_to_icon_services(monkeypatch):
    from app import favicons

    tried = []
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200

    def fake_image(url, why=None):
        tried.append(url)
        return (png, "image/png") if "duckduckgo" in url else None

    monkeypatch.setattr(favicons, "_image", fake_image)
    monkeypatch.setattr(favicons, "_request", lambda *a, **k: None)  # Startseite blockiert (Bot-Schutz)
    assert favicons.fetch("builtbybit.com") == (png, "image/png")
    assert {"https://builtbybit.com/favicon.ico", "https://www.builtbybit.com/favicon.ico"} <= set(tried)
    assert "https://icons.duckduckgo.com/ip3/builtbybit.com.ico" in tried


def test_favicon_also_tries_www_variant(monkeypatch):
    from app import favicons

    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    monkeypatch.setattr(favicons, "_image", lambda url, why=None: (png, "image/png") if url.startswith("https://www.holding-graz.at/") else None)
    monkeypatch.setattr(favicons, "_request", lambda *a, **k: None)
    assert favicons.fetch("holding-graz.at") == (png, "image/png")


def test_favicon_prefers_site_icon_and_survives_slow_or_broken_paths(monkeypatch):
    import time as _t

    from app import favicons

    ico = b"\x00\x00\x01\x00" + b"0" * 200
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200

    def fake_image(url, why=None):
        if url == "https://github.com/favicon.ico":
            _t.sleep(0.2)  # langsamer, aber vorrangig
            return (ico, "image/x-icon")
        if url.startswith("https://www."):
            raise RuntimeError("kaputt")
        return (png, "image/png")

    monkeypatch.setattr(favicons, "_image", fake_image)
    monkeypatch.setattr(favicons, "_request", lambda *a, **k: None)
    assert favicons.fetch("github.com") == (ico, "image/x-icon")

    def hanging(url, why=None):
        if "duckduckgo" in url:
            return (png, "image/png")
        _t.sleep(5)
        return None

    monkeypatch.setattr(favicons, "_image", hanging)
    monkeypatch.setattr(favicons, "PHASE_SECONDS", 0.3)
    started = _t.monotonic()
    assert favicons.fetch("hangs.example") == (png, "image/png")
    assert _t.monotonic() - started < 2


def test_avif_is_recognized():
    assert sniff(b"\x00\x00\x00\x1cftypavif" + b"0" * 50) == "image/avif"
