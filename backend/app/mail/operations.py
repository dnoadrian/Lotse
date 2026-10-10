"""Ordner auflisten, Nachrichten anzeigen, lesen, markieren, verschieben und löschen (IMAP)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..detection.classifier import REGISTRATION_CATEGORIES, classify
from ..detection.headers import parse_raw
from ..models import Evidence, MailAccount
from . import imap_client
from .accounts import credentials
from .message import MAX_MESSAGE_BYTES, parse_message

PAGE_SIZE_MAX = 100


class OperationError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class MessageRow:
    id: str
    from_name: str
    from_addr: str
    subject: str
    date: datetime | None
    category: str | None
    seen: bool = True


def _err(exc: Exception) -> OperationError:
    return OperationError(str(exc), 502)


# ------------------------------------------------------------------ Ordner

def folders(account: MailAccount) -> list[dict]:
    creds = credentials(account)
    try:
        with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
            out = []
            for f in imap_client.list_folders(c):
                if not f.selectable:
                    continue
                out.append({"id": f.raw, "name": f.name, "special": f.special, "count": imap_client.folder_count(c, f)})
            order = {"inbox": 0, "sent": 1, "archive": 2, "": 3, "drafts": 4, "junk": 5, "trash": 6, "all": 7}
            out.sort(key=lambda x: (order.get(x["special"], 3), x["name"].lower()))
            return out
    except imap_client.ImapError as exc:
        raise _err(exc) from exc


# ------------------------------------------------------------------ Nachrichten

def _evidence_refs(db: Session, account: MailAccount, folder: str | None, uidvalidity: str | None = None,
                   registration_only: bool = False) -> dict[str, str]:
    q = select(Evidence.msg_ref, Evidence.category).where(Evidence.account_id == account.id)
    if registration_only:
        q = q.where(Evidence.category.in_(REGISTRATION_CATEGORIES))
    if folder is not None:
        q = q.where(Evidence.folder == folder)
    if uidvalidity:
        q = q.where(Evidence.uidvalidity == uidvalidity)
    return {ref: cat for ref, cat in db.execute(q).all()}


def _row(ref: str, h, category: str | None, seen: bool = True) -> MessageRow:
    c = classify(h)
    if category in ("contact", None) and c is not None and c.category != "contact":
        category = c.category
    return MessageRow(
        id=ref, from_name=h.from_name, from_addr=h.from_addr, subject=h.subject, date=h.date,
        category=None if category == "contact" else category, seen=seen,
    )


def list_messages(db: Session, account: MailAccount, folder: str, page: int, page_size: int, only_registration: bool,
                  query: str = "") -> dict:
    page = max(page, 1)
    page_size = max(10, min(page_size, PAGE_SIZE_MAX))
    creds = credentials(account)
    try:
        with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
            f = imap_client.resolve_folder(c, folder)
            _, uidvalidity = imap_client.select(c, f, readonly=True)
            uids = imap_client.search_text(c, query) if query else imap_client.search_uids(c)
            ev = _evidence_refs(db, account, f.raw, uidvalidity)
            if only_registration:
                reg = _evidence_refs(db, account, f.raw, uidvalidity, registration_only=True)
                uids = [u for u in uids if str(u) in reg]
            uids.sort(reverse=True)
            total = len(uids)
            chunk = uids[(page - 1) * page_size : page * page_size]
            fetched = {u: (head, seen) for u, head, seen in imap_client.fetch_headers(c, chunk)} if chunk else {}
            items = [_row(str(u), parse_raw(fetched[u][0]), ev.get(str(u)), fetched[u][1]) for u in chunk if u in fetched]
            return {"items": items, "total": total, "page": page, "page_size": page_size, "uidvalidity": uidvalidity}
    except imap_client.ImapError as exc:
        raise _err(exc) from exc


def _uid(value: str) -> int:
    try:
        uid = int(value)
    except (TypeError, ValueError) as exc:
        raise OperationError("Ungültige Nachrichten-ID.") from exc
    if uid <= 0:
        raise OperationError("Ungültige Nachrichten-ID.")
    return uid


def read_message(db: Session, account: MailAccount, folder: str, uid: str) -> dict:
    """Eine Mail zum Lesen holen (ändert den Gelesen-Status nicht)."""
    n = _uid(uid)
    creds = credentials(account)
    try:
        with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
            f = imap_client.resolve_folder(c, folder)
            _, uidvalidity = imap_client.select(c, f, readonly=True)
            raw, seen, truncated = imap_client.fetch_message(c, n, MAX_MESSAGE_BYTES)
    except imap_client.ImapError as exc:
        raise _err(exc) from exc
    m = parse_message(raw, truncated)
    category = _evidence_refs(db, account, f.raw, uidvalidity).get(str(n))
    return {
        "id": str(n), "folder": f.raw, "folder_name": f.name, "uidvalidity": uidvalidity, "seen": seen,
        "from": m.from_, "to": m.to, "cc": m.cc, "date": m.date, "subject": m.subject,
        "category": None if category == "contact" else category,
        "text": m.text, "has_html": m.html is not None, "truncated": m.truncated,
        "attachments": [vars(a) for a in m.attachments],
        "unsubscribe": {"https": m.unsubscribe_https, "mailto": m.unsubscribe_mailto},
        "_html": m.html,
    }


def set_seen(account: MailAccount, folder: str, ids: list[str], seen: bool) -> dict:
    uids = sorted({_uid(x) for x in ids})
    if not uids:
        raise OperationError("Keine Nachrichten ausgewählt.")
    creds = credentials(account)
    try:
        with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
            f = imap_client.resolve_folder(c, folder)
            imap_client.select(c, f, readonly=False)
            imap_client.set_seen(c, uids, seen)
    except imap_client.ImapError as exc:
        raise _err(exc) from exc
    return {"updated": len(uids), "seen": seen}


def move_messages(db: Session, account: MailAccount, folder: str, ids: list[str], target: str) -> dict:
    uids = sorted({_uid(x) for x in ids})
    if not uids:
        raise OperationError("Keine Nachrichten ausgewählt.")
    if target == folder:
        raise OperationError("Ziel- und Quellordner sind gleich.")
    creds = credentials(account)
    try:
        with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
            src = imap_client.resolve_folder(c, folder)
            dst = imap_client.resolve_folder(c, target)  # nur Ordner, die der Server selbst meldet
            imap_client.select(c, src, readonly=False)
            remaining = imap_client.move_uids(c, uids, dst)
    except imap_client.ImapError as exc:
        raise _err(exc) from exc
    moved = {str(u) for u in uids} - {str(u) for u in remaining}
    if moved:
        # Belege zeigen auf (Ordner, UID); nach dem Verschieben stimmt die UID nicht mehr → beim nächsten Scan neu
        db.execute(delete(Evidence).where(Evidence.account_id == account.id, Evidence.folder == src.raw,
                                          Evidence.msg_ref.in_(moved)))
        db.commit()
    return {"requested": len(uids), "moved": len(moved), "failed": len(remaining), "verified": True}


# ------------------------------------------------------------------ Löschen

def delete_messages(db: Session, account: MailAccount, folder: str, mode: str, ids: list[str], permanent: bool,
                    expected_count: int | None, uidvalidity: str | None) -> dict:
    """mode: selected | all | registration. Gibt ein überprüftes Ergebnis zurück."""
    if mode not in ("selected", "all", "registration"):
        raise OperationError("Unbekannter Löschmodus.")
    if mode == "selected" and not ids:
        raise OperationError("Keine Nachrichten ausgewählt.")
    creds = credentials(account)
    try:
        return _delete_imap(db, account, creds, folder, mode, ids, permanent, expected_count, uidvalidity)
    except imap_client.ImapError as exc:
        raise _err(exc) from exc


def _delete_imap(db, account, creds, folder, mode, ids, permanent, expected_count, uidvalidity) -> dict:
    try:
        wanted = [int(x) for x in ids]
    except ValueError as exc:
        raise OperationError("Ungültige Nachrichten-ID.") from exc
    if any(u <= 0 for u in wanted):
        raise OperationError("Ungültige Nachrichten-ID.")
    with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
        f = imap_client.resolve_folder(c, folder)
        _, current_uv = imap_client.select(c, f, readonly=True)
        if uidvalidity and current_uv and uidvalidity != current_uv:
            raise OperationError("Der Ordner hat sich auf dem Server geändert. Bitte neu laden.", 409)
        if mode == "selected":
            uids = sorted(set(wanted))
        elif mode == "all":
            uids = imap_client.search_uids(c)
        else:
            ev = _evidence_refs(db, account, f.raw, current_uv, registration_only=True)
            uids = sorted(u for u in imap_client.search_uids(c) if str(u) in ev)
        if mode != "selected" and expected_count is not None and len(uids) != expected_count:
            raise OperationError(
                f"Im Ordner liegen jetzt {len(uids)} statt {expected_count} passende Nachrichten. Bitte neu laden und erneut bestätigen.",
                409,
            )
        result = imap_client.delete_uids(c, f, uids, permanent, current_uv)
    removed = {str(u) for u in uids} - {str(u) for u in result.failed_uids}
    if removed:
        db.execute(delete(Evidence).where(Evidence.account_id == account.id, Evidence.folder == f.raw,
                                          Evidence.msg_ref.in_(removed)))
        db.commit()
    return {
        "requested": result.requested,
        "deleted": result.deleted,
        "already_missing": result.already_missing,
        "failed": len(result.failed_uids),
        "failed_ids": [str(u) for u in result.failed_uids[:50]],
        "moved_to_trash": result.moved_to_trash,
        "verified": result.verified,
        "remaining": 0,
    }
