"""Ordner auflisten, Nachrichten anzeigen und löschen – einheitlich für IMAP und Gmail."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..detection.classifier import REGISTRATION_CATEGORIES, classify
from ..detection.headers import from_mapping, parse_raw
from ..models import Evidence, MailAccount
from . import gmail_client, imap_client
from .accounts import credentials

GMAIL_ID = re.compile(r"^[0-9a-fA-F]{6,32}$")
GMAIL_LABEL = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
GMAIL_BULK_LIMIT = 1000
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


def _err(exc: Exception) -> OperationError:
    return OperationError(str(exc), 502)


# ------------------------------------------------------------------ Ordner

def folders(account: MailAccount) -> list[dict]:
    creds = credentials(account)
    try:
        if account.provider == "imap":
            with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
                out = []
                for f in imap_client.list_folders(c):
                    if not f.selectable:
                        continue
                    out.append({"id": f.raw, "name": f.name, "special": f.special, "count": imap_client.folder_count(c, f)})
                order = {"inbox": 0, "sent": 1, "archive": 2, "": 3, "drafts": 4, "junk": 5, "trash": 6, "all": 7}
                out.sort(key=lambda x: (order.get(x["special"], 3), x["name"].lower()))
                return out
        with gmail_client.GmailClient(creds["secret"]) as g:
            out = []
            for lbl in g.labels():
                lid = lbl.get("id", "")
                if not GMAIL_LABEL.match(lid):
                    continue
                if lbl.get("type") == "system" and lid not in gmail_client.SYSTEM_LABELS:
                    continue
                detail = g.label(lid)
                special = {"INBOX": "inbox", "SENT": "sent", "SPAM": "junk", "TRASH": "trash"}.get(lid, "")
                out.append({"id": lid, "name": gmail_client.SYSTEM_LABELS.get(lid, lbl.get("name", lid))[:120],
                            "special": special, "count": int(detail.get("messagesTotal", 0))})
            return out
    except (imap_client.ImapError, gmail_client.GmailError) as exc:
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


def _row(ref: str, h, category: str | None) -> MessageRow:
    c = classify(h)
    if category in ("contact", None) and c is not None and c.category != "contact":
        category = c.category
    return MessageRow(
        id=ref, from_name=h.from_name, from_addr=h.from_addr, subject=h.subject, date=h.date,
        category=None if category == "contact" else category,
    )


def list_messages(db: Session, account: MailAccount, folder: str, page: int, page_size: int, only_registration: bool,
                  cursor: str | None = None) -> dict:
    page = max(page, 1)
    page_size = max(10, min(page_size, PAGE_SIZE_MAX))
    creds = credentials(account)
    try:
        if account.provider == "imap":
            with imap_client.connect(account.imap_host, account.imap_port, creds["username"], creds["secret"]) as c:
                f = imap_client.resolve_folder(c, folder)
                _, uidvalidity = imap_client.select(c, f, readonly=True)
                uids = imap_client.search_uids(c)
                ev = _evidence_refs(db, account, f.raw, uidvalidity)
                if only_registration:
                    reg = _evidence_refs(db, account, f.raw, uidvalidity, registration_only=True)
                    uids = [u for u in uids if str(u) in reg]
                uids.sort(reverse=True)
                total = len(uids)
                chunk = uids[(page - 1) * page_size : page * page_size]
                headers = dict(imap_client.fetch_headers(c, chunk)) if chunk else {}
                items = [_row(str(u), parse_raw(headers[u]), ev.get(str(u))) for u in chunk if u in headers]
                return {"items": items, "total": total, "page": page, "page_size": page_size,
                        "uidvalidity": uidvalidity, "next_cursor": None}
        if not GMAIL_LABEL.match(folder):
            raise OperationError("Ungültiges Label.")
        with gmail_client.GmailClient(creds["secret"]) as g:
            ev = _evidence_refs(db, account, None)
            if only_registration:
                ids = sorted(_evidence_refs(db, account, None, registration_only=True).keys())
                total = len(ids)
                ids = ids[(page - 1) * page_size : page * page_size]
                next_cursor = None
            else:
                ids, next_cursor, total = g.list_page(folder, cursor, page_size)
                if total == 0:
                    total = int(g.label(folder).get("messagesTotal", 0))
            items = []
            for mid in ids:
                if not GMAIL_ID.match(mid):
                    continue
                m = g.metadata(mid)
                if only_registration and folder not in m.label_ids:
                    continue
                h = from_mapping(m.headers)
                if h.date is None and m.internal_date_ms:
                    h.date = datetime.fromtimestamp(m.internal_date_ms / 1000, tz=timezone.utc)
                items.append(_row(m.id, h, ev.get(m.id)))
            return {"items": items, "total": total, "page": page, "page_size": page_size,
                    "uidvalidity": "", "next_cursor": next_cursor}
    except (imap_client.ImapError, gmail_client.GmailError) as exc:
        raise _err(exc) from exc


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
        if account.provider == "imap":
            return _delete_imap(db, account, creds, folder, mode, ids, permanent, expected_count, uidvalidity)
        return _delete_gmail(db, account, creds, folder, mode, ids, permanent, expected_count)
    except (imap_client.ImapError, gmail_client.GmailError) as exc:
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


def _delete_gmail(db, account, creds, folder, mode, ids, permanent, expected_count) -> dict:
    if permanent:
        raise OperationError(
            "Endgültiges Löschen ist bei Gmail nicht aktiviert: Lotse fordert dafür bewusst keinen Vollzugriff an. "
            "Nachrichten im Gmail-Papierkorb werden von Google nach 30 Tagen automatisch gelöscht."
        )
    if not GMAIL_LABEL.match(folder):
        raise OperationError("Ungültiges Label.")
    with gmail_client.GmailClient(creds["secret"]) as g:
        if mode == "selected":
            targets = list(dict.fromkeys(ids))
        elif mode == "all":
            targets = list(g.iter_message_ids(label_id=folder))
        else:
            targets = sorted(_evidence_refs(db, account, None, registration_only=True).keys())
        if any(not GMAIL_ID.match(t) for t in targets):
            raise OperationError("Ungültige Nachrichten-ID.")
        if mode != "selected" and expected_count is not None and len(targets) != expected_count:
            raise OperationError(
                f"Es passen jetzt {len(targets)} statt {expected_count} Nachrichten. Bitte neu laden und erneut bestätigen.", 409
            )
        batch, remaining = targets[:GMAIL_BULK_LIMIT], max(0, len(targets) - GMAIL_BULK_LIMIT)
        failed: list[str] = []
        for mid in batch:
            g.trash(mid)
        # Überprüfung: jede Nachricht muss im Papierkorb liegen oder verschwunden sein
        for mid in batch:
            if not g.is_trashed_or_gone(mid):
                failed.append(mid)
    removed = set(batch) - set(failed)
    if removed:
        db.execute(delete(Evidence).where(Evidence.account_id == account.id, Evidence.msg_ref.in_(removed)))
        db.commit()
    return {
        "requested": len(batch),
        "deleted": len(batch) - len(failed),
        "already_missing": 0,
        "failed": len(failed),
        "failed_ids": failed[:50],
        "moved_to_trash": True,
        "verified": True,
        "remaining": remaining,
    }
