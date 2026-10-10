from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pathlib import Path

from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import inspect, text
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db as dbmod
from .config import get_settings
from .db import Base
from .jdm.catalog import get_catalog
from .routers import accounts, auth, mail, scans, security, services
from .security.middleware import SecurityMiddleware

log = logging.getLogger("quitly")


def _migrate(conn) -> None:
    """Kleine, additive Schema-Änderungen für bestehende Installationen."""
    additions = {
        "evidence": {"reasons": "JSON"},
        "services": {"memory": "JSON"},
    }
    insp = inspect(conn)
    for table, columns in additions.items():
        present = {c["name"] for c in insp.get_columns(table)}
        for name, sqltype in columns.items():
            if name not in present:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sqltype}"))


def _reset_stale_jobs() -> None:
    """Scans, die beim letzten Neustart liefen, sind abgebrochen (Threads überleben keinen Neustart)."""
    from .models import ScanJob, utcnow
    with dbmod.new_session() as db:
        for job in db.query(ScanJob).filter(ScanJob.status.in_(("queued", "running"))):
            job.status, job.error, job.finished_at = "error", "Durch einen Neustart des Servers unterbrochen.", utcnow()
        db.commit()


def _refresh_memory() -> None:
    """Nach Updates: entfernte Gmail-Postfächer aufräumen, Gedächtnis und Kennzahlen für alle Nutzer neu berechnen."""
    from sqlalchemy import delete, select

    from .models import Evidence, MailAccount, ScanJob, User
    from .scanner import recompute
    with dbmod.new_session() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(724502)"))  # mehrere Worker: nacheinander
        gmail = [a for a in db.execute(select(MailAccount.id).where(MailAccount.provider != "imap")).scalars()]
        if gmail:
            db.execute(delete(ScanJob).where(ScanJob.account_id.in_(gmail)))
            db.execute(delete(Evidence).where(Evidence.account_id.in_(gmail)))
            db.execute(delete(MailAccount).where(MailAccount.id.in_(gmail)))
            log.info("Gmail-Unterstützung entfernt: %d Postfach-Verbindung(en) gelöscht", len(gmail))
        for uid in list(db.execute(select(User.id)).scalars()):
            recompute(db, uid)
        db.commit()


def _mount_frontend(app: FastAPI, root: Path) -> None:
    """Liefert das gebaute Frontend aus; unbekannte Pfade bekommen index.html (Single-Page-App)."""
    root = root.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    s = get_settings()
    s.validate_secrets()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    engine = dbmod.init_engine(s.database_url)
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            # Mehrere Worker starten gleichzeitig: Schema-Anlage serialisieren
            conn.execute(text("SELECT pg_advisory_xact_lock(724501)"))
        Base.metadata.create_all(conn)
        _migrate(conn)
    _reset_stale_jobs()
    _refresh_memory()
    get_catalog()  # früh laden: defekte Daten sollen den Start verhindern

    docs = None if s.is_production else "/api/docs"
    app = FastAPI(title="Quitly", docs_url=docs, redoc_url=None, openapi_url=None if s.is_production else "/api/openapi.json")
    app.add_middleware(SecurityMiddleware)

    for r in (auth.router, security.router, accounts.router, scans.router, services.router, mail.router):
        app.include_router(r)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        # Keine Eingabewerte zurückspiegeln (könnten Passwörter enthalten)
        fields = sorted({".".join(str(p) for p in e.get("loc", [])[1:]) for e in exc.errors()})
        return JSONResponse({"detail": "Ungültige Eingabe", "fields": fields}, status_code=422)

    if s.static_dir and Path(s.static_dir, "index.html").is_file():
        _mount_frontend(app, Path(s.static_dir))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.error("Unbehandelter Fehler: %s", type(exc).__name__)
        return JSONResponse({"detail": "Interner Fehler"}, status_code=500)

    return app
