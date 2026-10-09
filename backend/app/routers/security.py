from __future__ import annotations

import base64

import pyotp
import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import AuditLog, UserSession
from ..security.crypto import encrypt
from ..security.passwords import WeakPasswordError, hash_password, validate_password, verify_password
from ..security.sessions import Auth, require_auth, revoke_user_sessions
from .auth import totp_purpose, verify_totp

router = APIRouter(prefix="/api/security", tags=["security"])


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6,8}$")


class DisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)
    code: str = Field(pattern=r"^\d{6,8}$")


class PasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


@router.get("/overview")
def overview(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    sessions = db.execute(
        select(UserSession).where(UserSession.user_id == auth.user.id, UserSession.mfa_pending.is_(False))
        .order_by(UserSession.last_seen.desc())
    ).scalars()
    return {
        "totp_enabled": auth.user.totp_enabled,
        "sessions": [
            {"id": s.id, "created_at": s.created_at, "last_seen": s.last_seen, "ip": s.ip,
             "user_agent": s.user_agent, "current": s.id == auth.session.id}
            for s in sessions
        ],
    }


@router.post("/totp/setup")
def totp_setup(request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    if auth.user.totp_enabled:
        raise HTTPException(400, "Zwei-Faktor-Anmeldung ist bereits aktiv.")
    secret = pyotp.random_base32()
    auth.user.totp_pending_enc = encrypt(secret, totp_purpose(auth.user.id))
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=auth.user.username, issuer_name="Lotse")
    svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2).to_string()
    return {"secret": secret, "otpauth_uri": uri, "qr_svg_base64": base64.b64encode(svg).decode("ascii")}


@router.post("/totp/enable")
def totp_enable(body: CodeIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    user = auth.user
    if not user.totp_pending_enc or not verify_totp(db, user, user.totp_pending_enc, body.code):
        raise HTTPException(400, "Der Code ist ungültig.")
    user.totp_secret_enc, user.totp_pending_enc, user.totp_enabled = user.totp_pending_enc, None, True
    db.commit()
    audit.record(db, "totp_enabled", user.id, request)
    return {"ok": True}


@router.post("/totp/disable")
def totp_disable(body: DisableIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    user = auth.user
    if not user.totp_enabled or not verify_password(user.password_hash, body.password) \
            or not verify_totp(db, user, user.totp_secret_enc, body.code):
        raise HTTPException(400, "Passwort oder Code ist falsch.")
    user.totp_enabled, user.totp_secret_enc = False, None
    db.commit()
    audit.record(db, "totp_disabled", user.id, request)
    return {"ok": True}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    user = auth.user
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Das aktuelle Passwort ist falsch.")
    try:
        validate_password(body.new_password, user.username)
    except WeakPasswordError as exc:
        raise HTTPException(400, str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    db.commit()
    revoked = revoke_user_sessions(db, user.id, except_id=auth.session.id)
    audit.record(db, "password_changed", user.id, request, other_sessions_revoked=revoked)
    return {"ok": True, "other_sessions_revoked": revoked}


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    sess = db.get(UserSession, session_id)
    if sess is None or sess.user_id != auth.user.id:
        raise HTTPException(404, "Sitzung nicht gefunden.")
    db.delete(sess)
    db.commit()
    audit.record(db, "session_revoked", auth.user.id, request)
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 100, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    rows = db.execute(
        select(AuditLog).where(AuditLog.user_id == auth.user.id).order_by(AuditLog.ts.desc()).limit(limit)
    ).scalars()
    return [{"id": r.id, "ts": r.ts, "action": r.action, "detail": r.detail, "ip": r.ip} for r in rows]
