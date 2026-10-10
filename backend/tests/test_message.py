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
