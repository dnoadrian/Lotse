"""Ersteinrichtung im Browser – nur solange noch kein Benutzer existiert.

Gedacht für Plattformen ohne Konsole (z. B. Render Free). Erfordert das Einmal-Token aus der
Umgebungsvariable LOTSE_SETUP_TOKEN. Sobald ein Benutzer existiert, ist der Endpunkt wirkungslos.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import User
from ..security import ratelimit
from ..security.crypto import constant_time_equals
from ..security.passwords import WeakPasswordError, hash_password, validate_password
from ..security.sessions import client_ip

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupIn(BaseModel):
    token: str = Field(min_length=1, max_length=256)
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    password: str = Field(min_length=1, max_length=256)


def _needed(db: Session) -> bool:
    return bool(get_settings().setup_token) and db.execute(select(func.count(User.id))).scalar_one() == 0


@router.get("/status")
def status(db: Session = Depends(get_db)):
    return {"needed": _needed(db)}


@router.post("")
def create_first_user(body: SetupIn, request: Request, db: Session = Depends(get_db)):
    ok, retry = ratelimit.hit(db, f"setup:{client_ip(request)}", 5, timedelta(minutes=15))
    if not ok:
        raise HTTPException(429, "Zu viele Versuche.", headers={"Retry-After": str(retry)})
    if not _needed(db):
        raise HTTPException(404, "Die Ersteinrichtung ist abgeschlossen.")
    if not constant_time_equals(body.token.strip(), get_settings().setup_token):
        raise HTTPException(403, "Das Einrichtungs-Token ist falsch.")
    name = body.username.strip().lower()
    try:
        validate_password(body.password, name)
    except WeakPasswordError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.add(User(username=name, password_hash=hash_password(body.password)))
    db.commit()
    audit.record(db, "setup_completed", None, request)
    return {"ok": True}
