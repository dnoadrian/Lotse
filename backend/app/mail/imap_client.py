"""IMAP-Zugriff (Mailcow/Dovecot und andere RFC-3501-Server).

Sicherheitsprinzipien:
- Nur IMAPS (TLS ab dem ersten Byte), Zertifikat und Hostname werden immer geprüft
- Verbindung zur vorab geprüften IP (siehe netguard), SNI/Hostname-Prüfung mit dem echten Namen
- Ordnernamen werden nur verwendet, wenn der Server sie selbst per LIST geliefert hat,
  und dann korrekt gequotet → keine IMAP-Command-Injection
- UIDs werden als Ganzzahlen validiert
- Es werden nur ausgewählte Kopfzeilen gelesen (BODY.PEEK, setzt kein \\Seen)
"""
from __future__ import annotations

import base64
import imaplib
import re
import socket
import ssl
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import logging

from ..config import get_settings
from ..security.netguard import ResolvedTarget, resolve_target

log = logging.getLogger("quitly.imap")

HEADER_FIELDS = "FROM SUBJECT DATE LIST-UNSUBSCRIBE AUTO-SUBMITTED"
# Für die Text-Erkennung zusätzlich die MIME-Struktur
SCAN_HEADER_FIELDS = HEADER_FIELDS + " CONTENT-TYPE CONTENT-TRANSFER-ENCODING"
BODY_BYTES = 8192
FETCH_BATCH = 250
MUTATE_BATCH = 500
TRASH_NAMES = ("trash", "papierkorb", "deleted items", "deleted messages", "gelöschte elemente", "inbox.trash")


class ImapError(Exception):
    """Fehler mit nutzerfreundlicher, nicht sensibler Meldung."""


@dataclass
class Folder:
    raw: str  # Name wie vom Server (modified UTF-7)
    name: str  # dekodiert für die Anzeige
    flags: list[str] = field(default_factory=list)
    selectable: bool = True

    @property
    def special(self) -> str:
        lowered = [f.lower() for f in self.flags]
        for flag, key in (("\\trash", "trash"), ("\\junk", "junk"), ("\\sent", "sent"), ("\\drafts", "drafts"),
                          ("\\archive", "archive"), ("\\all", "all")):
            if flag in lowered:
                return key
        if self.raw.upper() == "INBOX":
            return "inbox"
        if self.name.lower() in TRASH_NAMES:
            return "trash"
        return ""


@dataclass
class DeleteResult:
    requested: int
    deleted: int
    failed_uids: list[int]
    moved_to_trash: bool
    verified: bool
    already_missing: int = 0


class _PinnedIMAP4_SSL(imaplib.IMAP4_SSL):
    """Verbindet sich zur geprüften IP, validiert das Zertifikat aber gegen den Hostnamen."""

    def __init__(self, target: ResolvedTarget, ssl_context: ssl.SSLContext, timeout: float):
        self._pinned_ip = target.ip
        super().__init__(host=target.host, port=target.port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):  # noqa: D401 – überschreibt imaplib-Intern
        sock = socket.create_connection((self._pinned_ip, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    ca = get_settings().imap_ca_file
    if ca:
        ctx.load_verify_locations(cafile=ca)
    return ctx


@contextmanager
def connect(host: str, port: int, username: str, password: str) -> Iterator[imaplib.IMAP4_SSL]:
    s = get_settings()
    target = resolve_target(host, port)
    try:
        client = _PinnedIMAP4_SSL(target, make_ssl_context(), timeout=s.imap_timeout_seconds)
    except ssl.SSLCertVerificationError as exc:
        raise ImapError("Das TLS-Zertifikat des Servers ist ungültig oder passt nicht zum Hostnamen.") from exc
    except ssl.SSLError as exc:
        raise ImapError("TLS-Verbindung fehlgeschlagen.") from exc
    except (OSError, imaplib.IMAP4.error) as exc:
        raise ImapError("Server nicht erreichbar.") from exc
    try:
        try:
            client.login(username, password)
        except imaplib.IMAP4.error as exc:
            raise ImapError("Anmeldung am Mailserver fehlgeschlagen. Benutzername oder Passwort prüfen.") from exc
        yield client
    finally:
        try:
            client.logout()
        except Exception:  # Verbindung ist ggf. schon geschlossen – kein Datenverlust möglich
            log.debug("IMAP-Logout fehlgeschlagen")


# ---------- Modified UTF-7 (RFC 3501, 5.1.3) ----------

def decode_mutf7(name: str) -> str:
    out, i = [], 0
    while i < len(name):
        ch = name[i]
        if ch == "&":
            j = name.find("-", i)
            if j == -1:
                out.append(name[i:])
                break
            chunk = name[i + 1 : j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:
                    out.append(name[i : j + 1])
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def quote_mailbox(raw: str) -> str:
    if any(c in raw for c in ("\r", "\n", "\x00")):
        raise ImapError("Ungültiger Ordnername")
    return '"' + raw.replace("\\", "\\\\").replace('"', '\\"') + '"'


_LIST_RE = re.compile(r'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s+(?P<name>.*)$')


def _unquote(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return re.sub(r"\\(.)", r"\1", s[1:-1])
    return s


def list_folders(client: imaplib.IMAP4_SSL) -> list[Folder]:
    typ, data = client.list()
    if typ != "OK":
        raise ImapError("Ordnerliste konnte nicht gelesen werden.")
    folders: list[Folder] = []
    for item in data:
        if item is None:
            continue
        if isinstance(item, tuple):  # Name als Literal
            head = item[0].decode("utf-8", "replace")
            m = _LIST_RE.match(head.rsplit("{", 1)[0].strip() + ' ""')
            raw = item[1].decode("utf-8", "replace")
            flags = m.group("flags").split() if m else []
        else:
            line = item.decode("utf-8", "replace")
            m = _LIST_RE.match(line)
            if not m:
                continue
            raw = _unquote(m.group("name"))
            flags = m.group("flags").split()
        selectable = not any(f.lower() in ("\\noselect", "\\nonexistent") for f in flags)
        folders.append(Folder(raw=raw, name=decode_mutf7(raw), flags=flags, selectable=selectable))
    return folders


def resolve_folder(client: imaplib.IMAP4_SSL, wanted: str) -> Folder:
    """Akzeptiert nur Ordner, die der Server selbst gemeldet hat."""
    for f in list_folders(client):
        if f.raw == wanted and f.selectable:
            return f
    raise ImapError("Ordner nicht gefunden.")


def find_trash(folders: Iterable[Folder]) -> Folder | None:
    flagged = [f for f in folders if f.selectable and f.special == "trash"]
    return flagged[0] if flagged else None


def select(client: imaplib.IMAP4_SSL, folder: Folder, readonly: bool) -> tuple[int, str]:
    typ, data = client.select(quote_mailbox(folder.raw), readonly=readonly)
    if typ != "OK":
        raise ImapError("Ordner konnte nicht geöffnet werden.")
    try:
        count = int(data[0])
    except (TypeError, ValueError, IndexError):
        count = 0
    _, uv = client.response("UIDVALIDITY")
    uidvalidity = uv[0].decode() if uv and uv[0] else ""
    return count, uidvalidity


def folder_count(client: imaplib.IMAP4_SSL, folder: Folder) -> int:
    typ, data = client.status(quote_mailbox(folder.raw), "(MESSAGES)")
    if typ != "OK" or not data or data[0] is None:
        return 0
    m = re.search(rb"MESSAGES (\d+)", data[0] if isinstance(data[0], bytes) else data[0][0])
    return int(m.group(1)) if m else 0


def search_uids(client: imaplib.IMAP4_SSL, since: str | None = None) -> list[int]:
    criteria = ("SINCE", since) if since else ("ALL",)
    typ, data = client.uid("SEARCH", *criteria)
    if typ != "OK":
        raise ImapError("Suche im Ordner fehlgeschlagen.")
    raw = b" ".join(d for d in data if d)
    return sorted(int(x) for x in raw.split() if x.isdigit())


def uid_set(uids: Iterable[int]) -> str:
    """Komprimiert UIDs zu einer IMAP-Sequenz wie 1:5,7,9:12."""
    nums = sorted({int(u) for u in uids})
    for u in nums:
        if u <= 0:
            raise ImapError("Ungültige UID")
    parts, start, prev = [], None, None
    for u in nums:
        if start is None:
            start = prev = u
        elif u == prev + 1:
            prev = u
        else:
            parts.append(f"{start}:{prev}" if start != prev else str(start))
            start = prev = u
    if start is not None:
        parts.append(f"{start}:{prev}" if start != prev else str(start))
    return ",".join(parts)


def _chunks(seq: list[int], n: int) -> Iterator[list[int]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


_UID_RE = re.compile(rb"UID (\d+)")


def fetch_headers(client: imaplib.IMAP4_SSL, uids: list[int]) -> Iterator[tuple[int, bytes]]:
    for chunk in _chunks(sorted(uids), FETCH_BATCH):
        typ, data = client.uid("FETCH", uid_set(chunk), f"(UID BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})])")
        if typ != "OK":
            raise ImapError("Nachrichten konnten nicht gelesen werden.")
        for item in data:
            if isinstance(item, tuple) and len(item) >= 2:
                m = _UID_RE.search(item[0])
                if m:
                    yield int(m.group(1)), item[1][:16384]


_BODY_RE = re.compile(rb"BODY\[TEXT\]")


def fetch_for_scan(client: imaplib.IMAP4_SSL, uids: list[int]) -> Iterator[tuple[int, bytes, bytes]]:
    """Kopfzeilen und die ersten 8 KB des Textes je Nachricht (BODY.PEEK → setzt kein \\Seen)."""
    for chunk in _chunks(sorted(uids), FETCH_BATCH):
        typ, data = client.uid(
            "FETCH", uid_set(chunk),
            f"(UID BODY.PEEK[HEADER.FIELDS ({SCAN_HEADER_FIELDS})] BODY.PEEK[TEXT]<0.{BODY_BYTES}>)",
        )
        if typ != "OK":
            raise ImapError("Nachrichten konnten nicht gelesen werden.")
        current: int | None = None
        parts: dict[int, list[bytes]] = {}
        for item in data:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            m = _UID_RE.search(item[0])
            if m:
                current = int(m.group(1))
            if current is None:
                continue
            slot = parts.setdefault(current, [b"", b""])
            if _BODY_RE.search(item[0]):
                slot[1] = item[1][:BODY_BYTES]
            else:
                slot[0] = item[1][:16384]
        for uid, (head, body) in parts.items():
            yield uid, head, body


def existing_uids(client: imaplib.IMAP4_SSL, uids: list[int]) -> set[int]:
    found: set[int] = set()
    for chunk in _chunks(sorted(uids), MUTATE_BATCH):
        typ, data = client.uid("SEARCH", "UID", uid_set(chunk))
        if typ != "OK":
            raise ImapError("Überprüfung fehlgeschlagen.")
        raw = b" ".join(d for d in data if d)
        found.update(int(x) for x in raw.split() if x.isdigit())
    return found


def delete_uids(
    client: imaplib.IMAP4_SSL,
    folder: Folder,
    uids: list[int],
    permanent: bool,
    expected_uidvalidity: str | None,
) -> DeleteResult:
    """Löscht (oder verschiebt in den Papierkorb) und prüft danach, ob die Nachrichten weg sind."""
    folders = list_folders(client)
    trash = find_trash(folders)
    _, uidvalidity = select(client, folder, readonly=False)
    if expected_uidvalidity and uidvalidity and expected_uidvalidity != uidvalidity:
        raise ImapError("Der Ordner hat sich auf dem Server geändert. Bitte die Liste neu laden.")

    present = sorted(existing_uids(client, uids)) if uids else []
    caps = {c.upper() for c in client.capabilities}
    use_move = (not permanent) and trash is not None and trash.raw != folder.raw and "MOVE" in caps

    if present:
        if use_move:
            for chunk in _chunks(present, MUTATE_BATCH):
                typ, _ = client.uid("MOVE", uid_set(chunk), quote_mailbox(trash.raw))
                if typ != "OK":
                    raise ImapError("Verschieben in den Papierkorb fehlgeschlagen.")
        else:
            if not permanent and trash is not None and trash.raw != folder.raw:
                # Server ohne MOVE: kopieren, dann löschen
                for chunk in _chunks(present, MUTATE_BATCH):
                    typ, _ = client.uid("COPY", uid_set(chunk), quote_mailbox(trash.raw))
                    if typ != "OK":
                        raise ImapError("Kopieren in den Papierkorb fehlgeschlagen.")
            for chunk in _chunks(present, MUTATE_BATCH):
                typ, _ = client.uid("STORE", uid_set(chunk), "+FLAGS.SILENT", r"(\Deleted)")
                if typ != "OK":
                    raise ImapError("Markieren zum Löschen fehlgeschlagen.")
            if "UIDPLUS" in caps:
                for chunk in _chunks(present, MUTATE_BATCH):
                    typ, _ = client.uid("EXPUNGE", uid_set(chunk))
                    if typ != "OK":
                        raise ImapError("Endgültiges Löschen fehlgeschlagen.")
            else:
                typ, _ = client.expunge()
                if typ != "OK":
                    raise ImapError("Endgültiges Löschen fehlgeschlagen.")

    # Erfolg tatsächlich überprüfen: Sind die UIDs im Ordner noch vorhanden?
    remaining = sorted(existing_uids(client, present)) if present else []
    missing_before = len(uids) - len(present)  # waren schon weg
    return DeleteResult(
        requested=len(uids),
        deleted=len(present) - len(remaining),
        failed_uids=remaining,
        already_missing=missing_before,
        moved_to_trash=use_move or (not permanent and trash is not None and trash.raw != folder.raw),
        verified=True,
    )
