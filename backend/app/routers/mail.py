"""E-Mail-Verwaltung: Ordner, Nachrichtenliste und Löschen mit Bestätigung."""
from __future__ import annotations

import unicodedata
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..mail import operations
from ..security import ratelimit
from ..security.sessions import Auth, require_auth
from .accounts import owned_account

router = APIRouter(prefix="/api/mail", tags=["mail"])

CONFIRM_WORD = "LÖSCHEN"


class DeleteIn(BaseModel):
    folder: str = Field(min_length=1, max_length=512)
    mode: Literal["selected", "all", "registration"]
    ids: list[str] = Field(default_factory=list, max_length=5000)
    permanent: bool = False
    expected_count: int | None = Field(default=None, ge=0)
    uidvalidity: str | None = Field(default=None, max_length=32)
    confirmation: str = Field(default="", max_length=32)


def _normalize(word: str) -> str:
    return unicodedata.normalize("NFC", word.strip()).upper()


def needs_confirmation(body: DeleteIn) -> bool:
    return body.mode != "selected" or len(body.ids) > 1 or body.permanent


@router.get("/{account_id}/folders")
async def folders(account_id: int, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    acc = owned_account(db, auth, account_id)
    try:
        return await run_in_threadpool(operations.folders, acc)
    except operations.OperationError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get("/{account_id}/messages")
async def messages(account_id: int, folder: str, page: int = 1, page_size: int = 50, only_registration: bool = False,
                   cursor: str | None = None, auth: Auth = Depends(require_auth), db: Session = Depends(get_db)):
    if len(folder) > 512 or (cursor and len(cursor) > 256):
        raise HTTPException(400, "Ungültige Anfrage.")
    acc = owned_account(db, auth, account_id)
    try:
        result = await run_in_threadpool(operations.list_messages, db, acc, folder, page, page_size, only_registration, cursor)
    except operations.OperationError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    result["items"] = [vars(r) for r in result["items"]]
    return result


@router.post("/{account_id}/delete")
async def delete(account_id: int, body: DeleteIn, request: Request, auth: Auth = Depends(require_auth),
                 db: Session = Depends(get_db)):
    acc = owned_account(db, auth, account_id)
    ok, retry = ratelimit.hit(db, f"delete:{auth.user.id}", 30, timedelta(minutes=1))
    if not ok:
        raise HTTPException(429, "Zu viele Löschvorgänge. Bitte kurz warten.", headers={"Retry-After": str(retry)})
    if needs_confirmation(body) and _normalize(body.confirmation) != CONFIRM_WORD:
        raise HTTPException(400, f"Bitte zur Bestätigung „{CONFIRM_WORD}“ eingeben.")
    if body.mode != "selected" and body.expected_count is None:
        raise HTTPException(400, "Die erwartete Anzahl fehlt.")
    try:
        result = await run_in_threadpool(
            operations.delete_messages, db, acc, body.folder, body.mode, body.ids, body.permanent,
            body.expected_count, body.uidvalidity,
        )
    except operations.OperationError as exc:
        audit.record(db, "mail_delete_failed", auth.user.id, request, account_id=acc.id, mode=body.mode,
                     reason=str(exc)[:120])
        raise HTTPException(exc.status, str(exc)) from exc
    audit.record(db, "mail_delete", auth.user.id, request, account_id=acc.id, provider=acc.provider, mode=body.mode,
                 permanent=body.permanent, requested=result["requested"], deleted=result["deleted"],
                 failed=result["failed"], verified=result["verified"])
    return result
