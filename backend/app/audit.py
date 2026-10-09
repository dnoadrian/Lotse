"""Audit-Protokoll. Enthält nie Passwörter, Tokens, Betreffzeilen oder Mail-Inhalte."""
from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog
from .security.sessions import client_ip

log = logging.getLogger("lotse.audit")

FORBIDDEN_KEYS = {"password", "secret", "token", "code", "subject", "body", "refresh_token", "access_token"}


def record(db: Session, action: str, user_id: int | None, request: Request | None = None, **detail) -> None:
    clean = {k: v for k, v in detail.items() if k.lower() not in FORBIDDEN_KEYS}
    db.add(AuditLog(user_id=user_id, action=action, detail=clean, ip=client_ip(request) if request else ""))
    db.commit()
    log.info("audit action=%s user=%s", action, user_id)
