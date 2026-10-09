from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, scanner
from ..db import get_db
from ..models import MailAccount, ScanJob
from ..security.sessions import Auth, require_auth
from .accounts import owned_account

router = APIRouter(prefix="/api/scans", tags=["scans"])


class ScanIn(BaseModel):
    account_id: int
    since_days: int | None = Field(default=None, ge=1, le=36500)


def job_out(job: ScanJob) -> dict:
    return {
        "id": job.id, "account_id": job.account_id, "status": job.status, "step": job.step,
        "progress": round(job.progress, 3), "messages_total": job.messages_total, "messages_seen": job.messages_seen,
        "signals_found": job.signals_found, "error": job.error, "started_at": job.started_at, "finished_at": job.finished_at,
    }


def owned_job(db: Session, auth: Auth, job_id: int) -> ScanJob:
    job = db.get(ScanJob, job_id)
    if job is None or job.user_id != auth.user.id:
        raise HTTPException(404, "Scan nicht gefunden.")
    return job


@router.post("", status_code=202)
def start(body: ScanIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    acc = owned_account(db, auth, body.account_id)
    running = db.execute(
        select(ScanJob).where(ScanJob.account_id == acc.id, ScanJob.status.in_(("queued", "running")))
    ).scalar_one_or_none()
    if running is not None:
        raise HTTPException(409, "Für dieses Postfach läuft bereits ein Scan.")
    job = ScanJob(user_id=auth.user.id, account_id=acc.id, since_days=body.since_days)
    db.add(job)
    db.commit()
    audit.record(db, "scan_started", auth.user.id, request, account_id=acc.id)
    scanner.submit(job.id)
    return job_out(job)


@router.get("")
def latest(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    """Letzter Scan je Postfach."""
    out = []
    accounts = db.execute(select(MailAccount.id).where(MailAccount.user_id == auth.user.id)).scalars().all()
    for acc_id in accounts:
        job = db.execute(
            select(ScanJob).where(ScanJob.account_id == acc_id, ScanJob.user_id == auth.user.id)
            .order_by(ScanJob.id.desc()).limit(1)
        ).scalar_one_or_none()
        if job:
            out.append(job_out(job))
    return out


@router.get("/{job_id}")
def get_job(job_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    return job_out(owned_job(db, auth, job_id))


@router.post("/{job_id}/cancel")
def cancel(job_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    job = owned_job(db, auth, job_id)
    if job.status in ("queued", "running"):
        job.cancel_requested = True
        db.commit()
    return job_out(job)
