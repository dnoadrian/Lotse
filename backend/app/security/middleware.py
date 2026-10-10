"""HTTP-Middleware: Sicherheits-Header, Origin-Prüfung, Größenlimit, datensparsames Access-Log."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import get_settings

log = logging.getLogger("quitly.access")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}

MAX_BODY_BYTES = 256 * 1024
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        s = get_settings()
        start = time.perf_counter()

        if request.method in UNSAFE_METHODS:
            # 1. Origin muss zur eigenen Adresse passen (zweite Verteidigungslinie neben SameSite + CSRF-Token)
            origin = request.headers.get("origin")
            if origin is not None and origin != s.public_origin:
                return self._finish(request, JSONResponse({"detail": "Ungültige Herkunft"}, status_code=403), start)
            # 2. Eigener Header erzwingt bei Cross-Site-Anfragen einen CORS-Preflight, den wir nie erlauben
            if request.headers.get("x-quitly-request") != "1":
                return self._finish(request, JSONResponse({"detail": "Fehlender Anfrage-Header"}, status_code=403), start)
            # 3. Nur JSON annehmen
            ctype = request.headers.get("content-type", "")
            length = request.headers.get("content-length")
            if length is not None and length.isdigit() and int(length) > MAX_BODY_BYTES:
                return self._finish(request, JSONResponse({"detail": "Anfrage zu groß"}, status_code=413), start)
            if length not in (None, "0") and not ctype.startswith("application/json"):
                return self._finish(request, JSONResponse({"detail": "Nur JSON erlaubt"}, status_code=415), start)

        response = await call_next(request)
        return self._finish(request, response, start)

    def _finish(self, request: Request, response: Response, start: float) -> Response:
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if get_settings().is_production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        if request.url.path.startswith("/api/"):
            # Routen dürfen selbst cachen lassen (Favicons: privat); sonst nie zwischenspeichern
            if "cache-control" not in response.headers:
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
        # Kein Query-String im Log (enthält z. B. Ordnernamen oder Suchbegriffe), keine Bodies, keine Cookies
        log.info(
            "%s %s %s %.0fms",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - start) * 1000,
        )
        return response
