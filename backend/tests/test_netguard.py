"""SSRF-Schutz und sicherer Verbindungsaufbau."""
from __future__ import annotations

import socket

import pytest

from app.security.netguard import HostNotAllowed, normalize_host, resolve_target


def fake_resolver(ips):
    def resolver(host, port, type=None):
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]
    return resolver


@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.10", "169.254.169.254", "100.64.0.1", "0.0.0.0",
    "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "224.0.0.1",
])
def test_internal_addresses_blocked(app, ip):
    with pytest.raises(HostNotAllowed):
        resolve_target("mail.example.org", 993, resolver=fake_resolver([ip]))


def test_mixed_public_and_private_blocked(app):
    with pytest.raises(HostNotAllowed):
        resolve_target("mail.example.org", 993, resolver=fake_resolver(["93.184.216.34", "10.0.0.1"]))


def test_public_address_allowed_and_pinned(app):
    t = resolve_target("Mail.Example.org.", 993, resolver=fake_resolver(["93.184.216.34"]))
    assert (t.host, t.port, t.ip) == ("mail.example.org", 993, "93.184.216.34")


def test_port_allowlist(app):
    for port in (25, 143, 22, 6379, 80):
        with pytest.raises(HostNotAllowed, match="Port"):
            resolve_target("mail.example.org", port, resolver=fake_resolver(["93.184.216.34"]))


def test_allowlisted_internal_host(settings_env):
    settings_env(imap_allowed_hosts="mailcow.lan.example")
    t = resolve_target("mailcow.lan.example", 993, resolver=fake_resolver(["192.168.1.20"]))
    assert t.ip == "192.168.1.20"


@pytest.mark.parametrize("host", [
    "", "localhost", "user@evil.example", "evil.example:25", "evil.example/x", "-bad.example", "a..example",
    "http://evil.example", "evil example.org", "x" * 300, "mail.example.org\r\nQUIT",
])
def test_invalid_hostnames(app, host):
    with pytest.raises(HostNotAllowed):
        normalize_host(host)


def test_idn_hostname_normalized(app):
    assert normalize_host("mail.bücher.example") == "mail.xn--bcher-kva.example"


def test_connection_uses_pinned_ip(app, monkeypatch):
    """Kein zweites DNS-Lookup: Verbindung geht an die geprüfte IP, Zertifikat gegen den Hostnamen."""
    from app.mail import imap_client
    from app.security.netguard import ResolvedTarget

    seen = {}

    def fake_create_connection(addr, timeout=None):
        seen["addr"] = addr
        raise OSError("Abbruch nach Prüfung")

    monkeypatch.setattr(imap_client.socket, "create_connection", fake_create_connection)
    target = ResolvedTarget(host="mail.example.org", port=993, ip="93.184.216.34")
    with pytest.raises(OSError):
        imap_client._PinnedIMAP4_SSL(target, imap_client.make_ssl_context(), timeout=1)
    assert seen["addr"] == ("93.184.216.34", 993)


def test_tls_context_is_strict(app):
    from app.mail.imap_client import make_ssl_context
    import ssl
    ctx = make_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
