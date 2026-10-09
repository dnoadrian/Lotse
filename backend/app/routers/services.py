"""Erkannte Dienste inkl. JustDeleteMe-Zuordnung und manuellem Löschstatus."""
from __future__ import annotations

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..detection.classifier import quality_label
from ..jdm.catalog import get_catalog
from ..models import MailAccount, Service, utcnow
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
    for acc_id, info in (svc.sources or {}).items():
        acc = accounts.get(int(acc_id))
        if acc:
            sources.append({"account_id": acc.id, "label": acc.label, "provider": acc.provider,
                            "messages": info.get("messages", 0), "signals": info.get("signals", 0)})
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
        "status": svc.status,
        "status_changed_at": svc.status_changed_at,
    }


def _accounts(db: Session, user_id: int) -> dict[int, MailAccount]:
    return {a.id: a for a in db.execute(select(MailAccount).where(MailAccount.user_id == user_id)).scalars()}


@router.get("")
def list_services(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    accs = _accounts(db, auth.user.id)
    rows = db.execute(select(Service).where(Service.user_id == auth.user.id)).scalars().all()
    rows.sort(key=lambda s: (-s.confidence, s.display_name.lower()))
    return [service_out(s, accs) for s in rows]


@router.patch("/{service_id}")
def set_status(service_id: int, body: StatusIn, request: Request, auth: Auth = Depends(require_auth),
               db: Session = Depends(get_db)):
    svc = db.get(Service, service_id)
    if svc is None or svc.user_id != auth.user.id:
        raise HTTPException(404, "Dienst nicht gefunden.")
    svc.status, svc.status_changed_at = body.status, utcnow()
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
        svc.status, svc.status_changed_at = body.status, now
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
