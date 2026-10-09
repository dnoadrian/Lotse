from __future__ import annotations

import time
from datetime import timedelta

import pyotp
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import User, UserSession
from ..security import ratelimit
from ..security.crypto import constant_time_equals, decrypt
from ..security.passwords import hash_password, needs_rehash, verify_password
from ..security.sessions import (
    _load_session,
    clear_cookie,
    client_ip,
    create_session,
    csrf_token_for,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TotpIn(BaseModel):
    code: str = Field(min_length=6, max_length=8, pattern=r"^\d{6,8}$")


def _too_many(retry: int) -> HTTPException:
    return HTTPException(429, "Zu viele Versuche. Bitte später erneut versuchen.", headers={"Retry-After": str(retry)})


def totp_purpose(user_id: int) -> str:
    return f"totp:{user_id}"


def verify_totp(db: Session, user: User, secret_enc: str, code: str) -> bool:
    """Prüft einen TOTP-Code (±30 s) und verhindert die Wiederverwendung desselben Codes."""
    secret = decrypt(secret_enc, totp_purpose(user.id))
    totp = pyotp.TOTP(secret)
    now = time.time()
    for offset in (-1, 0, 1):
        step = int(now // 30) + offset
        if constant_time_equals(totp.at(step * 30), code) and step > (user.totp_last_step or 0):
            user.totp_last_step = step
            db.commit()
            return True
    return False


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    window = timedelta(minutes=s.login_window_minutes)
    ip = client_ip(request)
    username = body.username.strip().lower()

    ok, retry = ratelimit.hit(db, f"login:ip:{ip}", s.login_ip_max_attempts, window)
    if not ok:
        raise _too_many(retry)
    user_key = f"login:user:{username}"
    retry = ratelimit.is_blocked(db, user_key, s.login_max_attempts, window)
    if retry:
        raise _too_many(retry)

    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if not verify_password(user.password_hash if user else None, body.password) or user is None:
        ratelimit.hit(db, user_key, s.login_max_attempts, window)
        audit.record(db, "login_failed", user.id if user else None, request)
        raise HTTPException(401, "Benutzername oder Passwort falsch.")

    ratelimit.reset(db, user_key)
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
        db.commit()
    # Session Fixation verhindern: vorhandene Sitzung dieses Browsers verwerfen
    old = _load_session(request, db)
    if old is not None:
        db.delete(old)
        db.commit()
    sess = create_session(db, user, request, response, mfa_pending=user.totp_enabled)
    if user.totp_enabled:
        return {"mfa_required": True}
    audit.record(db, "login", user.id, request)
    return {"mfa_required": False, "csrf_token": csrf_token_for(sess.id)}


@router.post("/totp")
def totp(body: TotpIn, request: Request, response: Response, db: Session = Depends(get_db)):
    s = get_settings()
    sess = _load_session(request, db)
    if sess is None or not sess.mfa_pending:
        raise HTTPException(401, "Bitte zuerst mit Passwort anmelden.")
    ok, retry = ratelimit.hit(db, f"totp:{sess.id}", s.totp_max_attempts, timedelta(minutes=5))
    if not ok:
        db.delete(sess)
        db.commit()
        clear_cookie(response)
        raise _too_many(retry)
    user = db.get(User, sess.user_id)
    if user is None or not user.totp_enabled or not user.totp_secret_enc or not verify_totp(db, user, user.totp_secret_enc, body.code):
        audit.record(db, "totp_failed", sess.user_id, request)
        raise HTTPException(401, "Der Code ist ungültig.")
    # Neues Token nach erfolgreicher Zwei-Faktor-Prüfung
    db.delete(sess)
    db.commit()
    new = create_session(db, user, request, response, mfa_pending=False)
    audit.record(db, "login", user.id, request, mfa=True)
    return {"csrf_token": csrf_token_for(new.id)}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sess = _load_session(request, db)
    if sess is not None:
        if not sess.mfa_pending:
            sent = request.headers.get("x-csrf-token", "")
            if not constant_time_equals(sent, csrf_token_for(sess.id)):
                raise HTTPException(403, "CSRF-Prüfung fehlgeschlagen")
        uid = sess.user_id
        db.delete(sess)
        db.commit()
        audit.record(db, "logout", uid, request)
    clear_cookie(response)
    return {"ok": True}


@router.get("/session")
def session_info(request: Request, db: Session = Depends(get_db)):
    sess: UserSession | None = _load_session(request, db)
    if sess is None:
        return {"authenticated": False, "mfa_pending": False}
    if sess.mfa_pending:
        return {"authenticated": False, "mfa_pending": True}
    user = db.get(User, sess.user_id)
    return {
        "authenticated": True,
        "mfa_pending": False,
        "csrf_token": csrf_token_for(sess.id),
        "user": {"username": user.username, "totp_enabled": user.totp_enabled},
    }
