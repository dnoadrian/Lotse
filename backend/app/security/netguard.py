"""SSRF-Schutz für vom Nutzer angegebene Mailserver und für Favicon-Abrufe.

Regeln:
- Hostname muss syntaktisch gültig sein (keine IP-Literale mit Tricks, kein Userinfo, keine Ports im Namen)
- Port muss in QUITLY_IMAP_ALLOWED_PORTS stehen (Standard: nur 993/IMAPS)
- Alle aufgelösten Adressen müssen öffentlich sein – außer der Host steht ausdrücklich
  in QUITLY_IMAP_ALLOWED_HOSTS (z. B. der eigene Mailcow im LAN)
- Die Verbindung wird zur geprüften IP aufgebaut (kein zweites DNS-Lookup → kein DNS-Rebinding)
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass

from ..config import get_settings

_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


class HostNotAllowed(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedTarget:
    host: str
    port: int
    ip: str


def normalize_host(host: str) -> str:
    h = (host or "").strip().lower().rstrip(".")
    if not h or len(h) > 253:
        raise HostNotAllowed("Ungültiger Servername")
    try:
        ipaddress.ip_address(h)
        is_ip = True
    except ValueError:
        is_ip = False
    if not is_ip:
        try:
            h = h.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise HostNotAllowed("Ungültiger Servername") from exc
        labels = h.split(".")
        if len(labels) < 2 or not all(_LABEL.match(lbl) for lbl in labels):
            raise HostNotAllowed("Ungültiger Servername")
    return h


def _is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


def resolve_public(host: str, port: int, resolver=socket.getaddrinfo) -> ResolvedTarget:
    """Für Abrufe, die Quitly selbst auslöst (z. B. Favicons): nur öffentliche Adressen, keine Ausnahmen."""
    h = normalize_host(host)
    try:
        ipaddress.ip_address(h)
        raise HostNotAllowed("IP-Adressen sind nicht erlaubt")
    except ValueError:
        pass
    try:
        infos = resolver(h, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HostNotAllowed("Server nicht gefunden") from exc
    ips = sorted({info[4][0] for info in infos})
    if not ips or any(not _is_public(ip) for ip in ips):
        raise HostNotAllowed("Keine öffentliche Adresse")
    ips.sort(key=lambda ip: ":" in ip)
    return ResolvedTarget(host=h, port=port, ip=ips[0])


def resolve_target(host: str, port: int, resolver=socket.getaddrinfo) -> ResolvedTarget:
    s = get_settings()
    h = normalize_host(host)
    if port not in s.allowed_ports:
        raise HostNotAllowed(f"Port {port} ist nicht erlaubt (erlaubt: {', '.join(map(str, sorted(s.allowed_ports)))})")
    try:
        infos = resolver(h, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise HostNotAllowed("Server nicht gefunden") from exc
    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise HostNotAllowed("Server nicht gefunden")
    if h not in s.allowed_hosts:
        bad = [ip for ip in ips if not _is_public(ip)]
        if bad:
            raise HostNotAllowed(
                "Der Server löst auf eine interne Adresse auf. Erlaube ihn ausdrücklich über QUITLY_IMAP_ALLOWED_HOSTS."
            )
    # IPv4 bevorzugen (stabiler in Containern)
    ips.sort(key=lambda ip: ":" in ip)
    return ResolvedTarget(host=h, port=port, ip=ips[0])
