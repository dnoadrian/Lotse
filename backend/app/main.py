from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db as dbmod
from .config import get_settings
from .db import Base
from .jdm.catalog import get_catalog
from .routers import accounts, auth, mail, scans, security, services
from .security.middleware import SecurityMiddleware

log = logging.getLogger("lotse")


def create_app() -> FastAPI:
    s = get_settings()
    s.validate_secrets()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # httpx protokolliert sonst URLs von Google-API-Aufrufen (Nachrichten-IDs)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    engine = dbmod.init_engine(s.database_url)
    Base.metadata.create_all(engine)
    get_catalog()  # früh laden: defekte Daten sollen den Start verhindern

    docs = None if s.is_production else "/api/docs"
    app = FastAPI(title="Lotse", docs_url=docs, redoc_url=None, openapi_url=None if s.is_production else "/api/openapi.json")
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

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.error("Unbehandelter Fehler: %s", type(exc).__name__)
        return JSONResponse({"detail": "Interner Fehler"}, status_code=500)

    return app
