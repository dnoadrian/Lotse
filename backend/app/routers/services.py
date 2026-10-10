"""Erkannte Dienste inkl. JustDeleteMe-Zuordnung und manuellem Löschstatus."""
from __future__ import annotations

import csv
import io
from typing import Literal

from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, favicons, scanner
from ..db import get_db
from ..detection.classifier import LABELS, quality_label
from ..detection.headers import parse_raw
from ..jdm.catalog import get_catalog
from ..mail import imap_client
from ..mail.accounts import credentials
from ..models import Evidence, MailAccount, Service, utcnow
from ..security.sessions import Auth, require_auth

router = APIRouter(prefix="/api/services", tags=["services"])

Status = Literal["offen", "angefragt", "geloescht", "behalten"]


class StatusIn(BaseModel):
    status: Status


class BulkStatusIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=5000)
    status: Status


def service_out(svc: Service, accounts: dict[int, MailAccount]) -> dict:
    entry = get_catalog().by_name(svc.jdm_name)
    jdm = None
    if entry is not None:
        jdm = {
            "name": entry.name,
            "url": entry.delete_url,
            "difficulty": entry.difficulty,
            "instructions": entry.instructions,
            "email": entry.email,
            "email_subject": entry.email_subject,
            "email_body": entry.email_body,
            "domains": list(entry.domains),
        }
    sources = []
    per_account = svc.account_memory or {}
    # Auch Postfächer, deren Mails inzwischen gelöscht sind – das Gedächtnis je Postfach bleibt
    for acc_id in list(svc.sources or {}) + [k for k in per_account if k not in (svc.sources or {})]:
        acc = accounts.get(int(acc_id))
        if not acc:
            continue
        info = (svc.sources or {}).get(acc_id, {})
        mem = per_account.get(acc_id) or {}
        left = scanner.deletion_kind(mem) if scanner.leaving_detected(mem) else None
        sources.append({"account_id": acc.id, "label": acc.label, "provider": acc.provider,
                        "messages": info.get("messages", 0), "signals": info.get("signals", 0),
                        "senders": info.get("senders", 0), "left": left,
                        "unconfirmed": scanner.unconfirmed(mem) if mem else False})
    return {
        "id": svc.id,
        "name": svc.display_name,
        "domains": svc.domains or [],
        "jdm": jdm,
        "sources": sources,
        "message_count": svc.message_count,
        "signal_count": svc.signal_count,
        "sender_count": svc.sender_count,
        "signals": svc.signals or {},
        "confidence": svc.confidence,
        "quality": quality_label(svc.confidence),
        "first_seen": svc.first_seen,
        "last_seen": svc.last_seen,
        "deletion_detected": svc.deletion_detected,
        "deletion_requested_by_mail": "deletion_request" in (svc.memory or {}),
        "email_changed": "email_change" in (svc.memory or {}),
        "deletion_kind": scanner.service_leaving_kind(svc) if svc.deletion_detected else None,
        "unconfirmed": scanner.unconfirmed(svc.memory or {}),
        "mails_in_mailbox": svc.signal_count,
        "memory_only": bool(svc.memory) and svc.signal_count == 0,
        "lifecycle": lifecycle(svc),
        "explanation": explanation(svc),
        "status": svc.status,
        "status_changed_at": svc.status_changed_at,
    }


LIKELY_DELETED_AFTER = timedelta(days=14)


def _aware(dt):
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lifecycle(svc: Service) -> str | None:
    """Hinweis zum Löschstatus, wenn der Anbieter keine Bestätigung schickt.

    still_active    nach der Löschanfrage kamen noch normale Mails → Konto offenbar noch aktiv
    likely_deleted  seit ≥ 14 Tagen keine Mail mehr seit der Anfrage → wahrscheinlich gelöscht (bitte bestätigen)
    waiting         Anfrage läuft, noch zu früh für eine Aussage
    """
    if svc.status != "angefragt" or not svc.status_changed_at:
        return None
    requested = _aware(svc.status_changed_at)
    last_regular = None
    for cat, m in (svc.memory or {}).items():
        if cat in ("deletion", "deletion_request", "email_change") or cat in scanner.WEAK_CATEGORIES:
            continue
        d = scanner._from_iso(m.get("last"))
        if d and (last_regular is None or d > last_regular):
            last_regular = d
    if last_regular and last_regular > requested:
        return "still_active"
    if utcnow() - requested >= LIKELY_DELETED_AFTER:
        return "likely_deleted"
    return "waiting"


def explanation(svc: Service) -> list[dict]:
    items = []
    for cat, m in (svc.memory or {}).items():
        items.append({"category": cat, "label": LABELS.get(cat, cat), "count": int(m.get("count", 0)),
                      "best": float(m.get("best", 0.0)), "first": m.get("first"), "last": m.get("last")})
    items.sort(key=lambda x: -x["best"])
    return items


def _accounts(db: Session, user_id: int) -> dict[int, MailAccount]:
    return {a.id: a for a in db.execute(select(MailAccount).where(MailAccount.user_id == user_id)).scalars()}


@router.get("")
def list_services(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    accs = _accounts(db, auth.user.id)
    rows = db.execute(select(Service).where(Service.user_id == auth.user.id)).scalars().all()
    # Nur Dienste mit sicheren Konto-Hinweisen (Willkommen, Bestätigung, Login, Abo, Bestellung, Löschung …)
    rows = [s for s in rows if scanner.is_sure(s.memory)]
    rows.sort(key=lambda s: (-s.confidence, s.display_name.lower()))
    return [service_out(s, accs) for s in rows]


MAILS_LIMIT = 100


@router.get("/{service_id}/mails")
def service_mails(service_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    """Die erkannten Mails eines Dienstes. Betreff und Absender werden live vom Server geholt (nicht gespeichert)."""
    svc = db.get(Service, service_id)
    if svc is None or svc.user_id != auth.user.id:
        raise HTTPException(404, "Dienst nicht gefunden.")
    accs = _accounts(db, auth.user.id)
    evs = db.execute(
        select(Evidence).where(Evidence.service_id == svc.id, Evidence.user_id == auth.user.id)
    ).scalars().all()
    evs.sort(key=lambda e: (_aware(e.received_at) or utcnow().replace(year=1970)), reverse=True)
    evs = evs[:MAILS_LIMIT]
    live: dict[int, dict] = {}
    warnings: list[str] = []
    by_account: dict[int, list[Evidence]] = {}
    for ev in evs:
        by_account.setdefault(ev.account_id, []).append(ev)
    for acc_id, items in by_account.items():
        acc = accs.get(acc_id)
        if acc is None:
            continue
        try:
            creds = credentials(acc)
            with imap_client.connect(acc.imap_host, acc.imap_port, creds["username"], creds["secret"]) as c:
                folders = {f.raw: f for f in imap_client.list_folders(c) if f.selectable}
                by_folder: dict[str, list[Evidence]] = {}
                for ev in items:
                    by_folder.setdefault(ev.folder, []).append(ev)
                for folder, fitems in by_folder.items():
                    f = folders.get(folder)
                    if f is None:
                        continue
                    _, uv = imap_client.select(c, f, readonly=True)
                    valid = [ev for ev in fitems if not ev.uidvalidity or ev.uidvalidity == uv]
                    uids = [int(ev.msg_ref) for ev in valid if ev.msg_ref.isdigit()]
                    heads = {u: (head, seen) for u, head, seen in imap_client.fetch_headers(c, uids)} if uids else {}
                    for ev in valid:
                        got = heads.get(int(ev.msg_ref)) if ev.msg_ref.isdigit() else None
                        if got:
                            h = parse_raw(got[0])
                            live[ev.id] = {"subject": h.subject, "from_name": h.from_name, "from_addr": h.from_addr,
                                           "seen": got[1], "folder_name": f.name}
        except Exception as exc:  # noqa: BLE001 – Postfach nicht erreichbar: Liste trotzdem aus dem Gedächtnis zeigen
            warnings.append(f"{acc.label}: {exc if isinstance(exc, imap_client.ImapError) else 'nicht erreichbar'}")
    return {
        "items": [
            {
                "id": ev.id, "account_id": ev.account_id,
                "account_label": accs[ev.account_id].label if ev.account_id in accs else "",
                "folder": ev.folder, "folder_name": live.get(ev.id, {}).get("folder_name"), "msg_ref": ev.msg_ref,
                "category": ev.category, "seen": live.get(ev.id, {}).get("seen"),
                "label": LABELS.get(ev.category, ev.category), "score": ev.score, "reasons": ev.reasons or [],
                "received_at": ev.received_at, "sender_domain": ev.sender_domain,
                "subject": live.get(ev.id, {}).get("subject"), "from_name": live.get(ev.id, {}).get("from_name"),
                "from_addr": live.get(ev.id, {}).get("from_addr"),
                "still_in_mailbox": ev.id in live,
            }
            for ev in evs
        ],
        "explanation": explanation(svc),
        "confidence": svc.confidence,
        "memory_only": bool(svc.memory) and not evs,
        "warnings": warnings,
    }


@router.get("/{service_id}/favicon")
async def service_favicon(service_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    """Favicon des Dienstes über Quitly (kein direkter Abruf durch den Browser → kein Tracking, strenge CSP bleibt)."""
    svc = db.get(Service, service_id)
    if svc is None or svc.user_id != auth.user.id:
        raise HTTPException(404, "Dienst nicht gefunden.")
    icon = await favicons.get_icon(db, favicons.sites_for(svc))
    if icon is None:
        raise HTTPException(404, "Kein Symbol.")
    data, ctype = icon
    return Response(content=data, media_type=ctype, headers={
        "Cache-Control": "private, max-age=604800",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "X-Content-Type-Options": "nosniff",
    })


@router.patch("/{service_id}")
def set_status(service_id: int, body: StatusIn, request: Request, auth: Auth = Depends(require_auth),
               db: Session = Depends(get_db)):
    svc = db.get(Service, service_id)
    if svc is None or svc.user_id != auth.user.id:
        raise HTTPException(404, "Dienst nicht gefunden.")
    svc.status, svc.status_changed_at, svc.status_auto = body.status, utcnow(), False
    db.commit()
    audit.record(db, "service_status", auth.user.id, request, service_id=svc.id, status=body.status)
    return service_out(svc, _accounts(db, auth.user.id))


@router.post("/bulk-status")
def bulk_status(body: BulkStatusIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    ids = set(body.ids)
    rows = db.execute(select(Service).where(Service.user_id == auth.user.id, Service.id.in_(ids))).scalars().all()
    if len(rows) != len(ids):
        raise HTTPException(404, "Mindestens ein Dienst wurde nicht gefunden.")
    now = utcnow()
    for svc in rows:
        svc.status, svc.status_changed_at, svc.status_auto = body.status, now, False
    db.commit()
    audit.record(db, "service_status_bulk", auth.user.id, request, count=len(rows), status=body.status)
    return {"updated": len(rows)}


def _csv_safe(value) -> str:
    """Formel-Injection in Tabellenprogrammen verhindern."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.get("/export.csv")
def export_csv(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Dienst", "Domains", "Status", "Erkennung %", "Mails", "Schwierigkeit", "Löschlink"])
    for item in list_services(auth, db):
        jdm = item["jdm"] or {}
        w.writerow([_csv_safe(x) for x in (
            item["name"], ", ".join(item["domains"]), item["status"], round(item["confidence"] * 100),
            item["message_count"], jdm.get("difficulty", ""), jdm.get("url", ""),
        )])
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="quitly-konten.csv"'},
    )
