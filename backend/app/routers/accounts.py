"""Postfach-Verbindungen (Mailcow/IMAP und Gmail)."""
from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import audit, scanner
from ..config import get_settings
from ..db import get_db
from ..jdm.catalog import get_catalog
from ..mail import gmail_client, imap_client
from ..mail.accounts import credentials, store_credentials
from ..models import Evidence, MailAccount, OAuthState, ScanJob
from ..security import ratelimit
from ..security.crypto import decrypt, encrypt, new_token, token_hash
from ..security.netguard import HostNotAllowed, normalize_host
from ..security.sessions import Auth, _load_session, require_auth

router = APIRouter(tags=["accounts"])


class ImapIn(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    host: str = Field(min_length=3, max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class ImapUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    host: str | None = Field(default=None, min_length=3, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=254)
    password: str | None = Field(default=None, min_length=1, max_length=1024)


class GmailStartIn(BaseModel):
    label: str = Field(default="Gmail", min_length=1, max_length=80)


def owned_account(db: Session, auth: Auth, account_id: int) -> MailAccount:
    acc = db.get(MailAccount, account_id)
    # Gleiche Antwort für "existiert nicht" und "gehört jemand anderem" → keine Aufzählung fremder IDs
    if acc is None or acc.user_id != auth.user.id:
        raise HTTPException(404, "Postfach nicht gefunden.")
    return acc


def account_out(acc: MailAccount) -> dict:
    return {
        "id": acc.id,
        "provider": acc.provider,
        "label": acc.label,
        "email_address": acc.email_address,
        "imap_host": acc.imap_host if acc.provider == "imap" else None,
        "imap_port": acc.imap_port if acc.provider == "imap" else None,
        "status": acc.status,
        "last_error": acc.last_error,
        "created_at": acc.created_at,
        "last_scan_at": acc.last_scan_at,
    }


def _limit_connection_tests(db: Session, auth: Auth) -> None:
    """Verbindungstests begrenzen (kein Missbrauch als Passwort-Rater oder Port-Scanner gegen fremde Server)."""
    ok, retry = ratelimit.hit(db, f"imap-test:{auth.user.id}", 10, timedelta(minutes=5))
    if not ok:
        raise HTTPException(429, "Zu viele Verbindungsversuche. Bitte kurz warten.", headers={"Retry-After": str(retry)})


def _test_imap(host: str, port: int, username: str, password: str) -> None:
    try:
        with imap_client.connect(host, port, username, password) as c:
            imap_client.list_folders(c)
    except HostNotAllowed as exc:
        raise HTTPException(400, str(exc)) from exc
    except imap_client.ImapError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/config")
def config(auth: Auth = Depends(require_auth)):
    s = get_settings()
    cat = get_catalog()
    return {
        "gmail_enabled": s.gmail_enabled,
        "imap_allowed_ports": sorted(s.allowed_ports),
        "jdm": {"entries": len(cat), **{k: v for k, v in cat.version.items() if k in ("commit", "date", "source")}},
    }


@router.get("/api/mail-accounts")
def list_accounts(auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    rows = db.execute(select(MailAccount).where(MailAccount.user_id == auth.user.id).order_by(MailAccount.id)).scalars()
    return [account_out(a) for a in rows]


@router.post("/api/mail-accounts/imap", status_code=201)
def add_imap(body: ImapIn, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    try:
        host = normalize_host(body.host)
    except HostNotAllowed as exc:
        raise HTTPException(400, str(exc)) from exc
    _limit_connection_tests(db, auth)
    _test_imap(host, body.port, body.username, body.password)
    acc = MailAccount(user_id=auth.user.id, provider="imap", label=body.label.strip(), email_address=body.username.strip()[:254],
                      imap_host=host, imap_port=body.port)
    store_credentials(acc, body.username, body.password)
    db.add(acc)
    db.commit()
    audit.record(db, "account_added", auth.user.id, request, provider="imap", account_id=acc.id)
    return account_out(acc)


@router.put("/api/mail-accounts/{account_id}/imap")
def update_imap(account_id: int, body: ImapUpdate, request: Request, auth: Auth = Depends(require_auth),
                db: Session = Depends(get_db)):
    acc = owned_account(db, auth, account_id)
    if acc.provider != "imap":
        raise HTTPException(400, "Kein IMAP-Postfach.")
    creds = credentials(acc)
    try:
        host = normalize_host(body.host) if body.host else acc.imap_host
    except HostNotAllowed as exc:
        raise HTTPException(400, str(exc)) from exc
    port = body.port or acc.imap_port
    username = body.username or creds["username"]
    password = body.password or creds["secret"]
    _limit_connection_tests(db, auth)
    _test_imap(host, port, username, password)
    acc.imap_host, acc.imap_port = host, port
    if body.label:
        acc.label = body.label.strip()
    acc.email_address = username.strip()[:254]
    store_credentials(acc, username, password)
    acc.status, acc.last_error = "ok", ""
    db.commit()
    audit.record(db, "account_updated", auth.user.id, request, account_id=acc.id)
    return account_out(acc)


@router.post("/api/mail-accounts/{account_id}/test")
def test_account(account_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    acc = owned_account(db, auth, account_id)
    _limit_connection_tests(db, auth)
    creds = credentials(acc)
    try:
        if acc.provider == "imap":
            with imap_client.connect(acc.imap_host, acc.imap_port, creds["username"], creds["secret"]) as c:
                imap_client.list_folders(c)
        else:
            with gmail_client.GmailClient(creds["secret"]) as g:
                g.profile()
        acc.status, acc.last_error = "ok", ""
    except (imap_client.ImapError, gmail_client.GmailError, HostNotAllowed) as exc:
        acc.status, acc.last_error = "error", str(exc)[:300]
    db.commit()
    return account_out(acc)


@router.delete("/api/mail-accounts/{account_id}")
def remove_account(account_id: int, request: Request, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    acc = owned_account(db, auth, account_id)
    if acc.provider == "gmail":
        try:
            gmail_client.revoke(credentials(acc)["secret"])
        except Exception:  # Widerruf ist best effort; das Token wird ohnehin gelöscht
            logging.getLogger("lotse.gmail").warning("Gmail-Token konnte nicht widerrufen werden")
    db.execute(delete(ScanJob).where(ScanJob.account_id == acc.id))
    db.execute(delete(Evidence).where(Evidence.account_id == acc.id))
    db.delete(acc)
    db.flush()
    scanner.recompute(db, auth.user.id)  # Mail-Zahlen dieses Postfachs aus den Diensten entfernen
    db.commit()
    audit.record(db, "account_removed", auth.user.id, request, provider=acc.provider, account_id=account_id)
    return {"ok": True}


# ------------------------------------------------------------------ Gmail OAuth

@router.post("/api/mail-accounts/gmail/start")
def gmail_start(body: GmailStartIn, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    if not get_settings().gmail_enabled:
        raise HTTPException(400, "Gmail ist nicht eingerichtet (LOTSE_GOOGLE_CLIENT_ID/SECRET fehlen).")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.execute(delete(OAuthState).where(OAuthState.created_at < cutoff))
    state, verifier = new_token(32), new_token(48)
    db.add(OAuthState(state_hash=token_hash(state), session_id=auth.session.id, user_id=auth.user.id,
                      verifier_enc=encrypt(verifier, f"oauth:{auth.user.id}"), label=body.label.strip()))
    db.commit()
    return {"authorization_url": gmail_client.authorization_url(state, verifier)}


@router.get("/api/oauth/google/callback")
def gmail_callback(request: Request, state: str = "", code: str = "", error: str = "", db: Session = Depends(get_db)):
    def back(result: str) -> RedirectResponse:
        return RedirectResponse(f"/verbindungen?gmail={result}", status_code=303)

    if not state or len(state) > 128:
        return back("fehler")
    row = db.execute(select(OAuthState).where(OAuthState.state_hash == token_hash(state))).scalar_one_or_none()
    if row is None:
        return back("fehler")
    db.delete(row)  # State ist nur einmal gültig
    db.commit()
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
    sess = _load_session(request, db)
    # State muss zur aktuellen Browser-Sitzung gehören (Login-CSRF / Account-Injection verhindern)
    if sess is None or sess.mfa_pending or sess.id != row.session_id or sess.user_id != row.user_id \
            or created < datetime.now(timezone.utc) - timedelta(minutes=10):
        return back("fehler")
    if error or not code or len(code) > 512:
        return back("abgebrochen")
    try:
        verifier = decrypt(row.verifier_enc, f"oauth:{row.user_id}")
        tokens = gmail_client.exchange_code(code, verifier)
        with gmail_client.GmailClient(tokens["refresh_token"]) as g:
            email_address = str(g.profile().get("emailAddress", ""))[:254]
    except gmail_client.GmailError:
        return back("fehler")
    acc = MailAccount(user_id=row.user_id, provider="gmail", label=row.label, email_address=email_address)
    store_credentials(acc, "", tokens["refresh_token"])
    db.add(acc)
    db.commit()
    audit.record(db, "account_added", row.user_id, request, provider="gmail", account_id=acc.id)
    return back("ok")
