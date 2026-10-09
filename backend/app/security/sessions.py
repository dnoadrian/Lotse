"""Serverseitige Sitzungen mit zufälligen, nur gehasht gespeicherten Tokens.

- Cookie: HttpOnly, Secure, SameSite=Strict, __Host- Präfix
- Leerlauf- und absolute Ablaufzeit
- Neues Token bei Login und nach erfolgreicher Zwei-Faktor-Prüfung (Schutz vor Session Fixation)
- CSRF-Token = HMAC(secret, Sitzungs-ID); wird per Header X-CSRF-Token zurückgeschickt
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import User, UserSession
from .crypto import constant_time_equals, hmac_sign, new_token, token_hash


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def client_ip(request: Request) -> str:
    s = get_settings()
    if s.trusted_proxies > 0:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= s.trusted_proxies:
            return parts[-s.trusted_proxies][:64]
    return (request.client.host if request.client else "unknown")[:64]


def create_session(db: Session, user: User, request: Request, response: Response, mfa_pending: bool) -> UserSession:
    s = get_settings()
    token = new_token()
    now = _now()
    sess = UserSession(
        token_hash=token_hash(token),
        user_id=user.id,
        mfa_pending=mfa_pending,
        created_at=now,
        last_seen=now,
        expires_at=now + (timedelta(minutes=5) if mfa_pending else timedelta(hours=s.session_absolute_hours)),
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    db.add(sess)
    db.commit()
    set_cookie(response, token)
    return sess


def set_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.cookie_name,
        value=token,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
        max_age=s.session_absolute_hours * 3600,
    )


def clear_cookie(response: Response) -> None:
    s = get_settings()
    response.delete_cookie(key=s.cookie_name, path="/", secure=s.cookie_secure, httponly=True, samesite="strict")


def csrf_token_for(session_id: int) -> str:
    return hmac_sign(f"csrf:{session_id}")


@dataclass
class Auth:
    user: User
    session: UserSession

    @property
    def csrf_token(self) -> str:
        return csrf_token_for(self.session.id)


def _load_session(request: Request, db: Session) -> UserSession | None:
    s = get_settings()
    token = request.cookies.get(s.cookie_name)
    if not token or len(token) > 128:
        return None
    sess = db.execute(select(UserSession).where(UserSession.token_hash == token_hash(token))).scalar_one_or_none()
    if sess is None:
        return None
    now = _now()
    idle_limit = timedelta(minutes=5) if sess.mfa_pending else timedelta(minutes=s.session_idle_minutes)
    if _aware(sess.expires_at) <= now or _aware(sess.last_seen) + idle_limit <= now:
        db.delete(sess)
        db.commit()
        return None
    # last_seen nur gelegentlich schreiben
    if (now - _aware(sess.last_seen)).total_seconds() > 30:
        sess.last_seen = now
        db.commit()
    return sess


def optional_pending_session(request: Request, db: Session = Depends(get_db)) -> UserSession | None:
    return _load_session(request, db)


def require_auth(request: Request, db: Session = Depends(get_db)) -> Auth:
    sess = _load_session(request, db)
    if sess is None or sess.mfa_pending:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    user = db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet")
    request.state.user_id = user.id
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        sent = request.headers.get("x-csrf-token", "")
        if not sent or not constant_time_equals(sent, csrf_token_for(sess.id)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF-Prüfung fehlgeschlagen")
    return Auth(user=user, session=sess)


def revoke_user_sessions(db: Session, user_id: int, except_id: int | None = None) -> int:
    q = delete(UserSession).where(UserSession.user_id == user_id)
    if except_id is not None:
        q = q.where(UserSession.id != except_id)
    res = db.execute(q)
    db.commit()
    return res.rowcount or 0


def cleanup_expired(db: Session) -> None:
    db.execute(delete(UserSession).where(UserSession.expires_at < _now()))
    db.commit()
