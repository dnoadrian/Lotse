"""Zentrale Konfiguration. Alle Werte kommen aus Umgebungsvariablen (Präfix QUITLY_).

Die alten Namen mit Präfix LOTSE_ (vor der Umbenennung) werden weiterhin gelesen, wenn die
entsprechende QUITLY_-Variable fehlt. So laufen bestehende .env-Dateien und der Render-Dienst ohne Änderung.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QUITLY_", env_file=None, extra="ignore")

    # Betrieb
    environment: str = "production"  # production | development | test
    public_url: str = Field(default="https://localhost", validate_default=True)
    database_url: str = "postgresql+psycopg://lotse:lotse@db:5432/lotse"

    # Geheimnisse (Pflicht in Produktion)
    secret_key: str = Field(default="", description="Mindestens 32 zufällige Bytes, base64")
    encryption_key: str = Field(default="", description="32 Bytes base64 für AES-256-GCM")
    encryption_keys_old: str = ""  # kommagetrennte frühere Schlüssel für Rotation

    # Sitzungen
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    cookie_secure: bool = True

    # Rate-Limits
    login_max_attempts: int = 5
    login_window_minutes: int = 15
    login_ip_max_attempts: int = 20
    totp_max_attempts: int = 5

    # Reverse Proxy: Anzahl vertrauenswürdiger Proxys vor der App (Caddy = 1)
    trusted_proxies: int = 0

    # IMAP / SSRF-Schutz
    imap_allowed_ports: str = "993"
    imap_allowed_hosts: str = ""  # Hosts, die auch auf private IPs auflösen dürfen (z. B. eigener Mailcow im LAN)
    imap_ca_file: str = ""  # optionale zusätzliche CA (PEM) für selbst signierte Mailserver
    imap_timeout_seconds: int = 30

    # Gmail (optional)
    google_client_id: str = ""
    google_client_secret: str = ""

    # Daten
    jdm_data_dir: str = str(BASE_DIR / "data" / "jdm")
    # Gebautes Frontend direkt aus dem Backend ausliefern (Render: ein einziger Web-Dienst)
    static_dir: str = ""
    # Jeder darf sich ein eigenes Konto anlegen (Daten sind strikt pro Konto getrennt)
    open_registration: bool = True
    registrations_per_ip_per_hour: int = 5
    gmail_scan_limit: int = 3000

    @field_validator("public_url", mode="before")
    @classmethod
    def _public_url(cls, v: str) -> str:
        # Render setzt RENDER_EXTERNAL_URL automatisch (https://<name>.onrender.com)
        if (not v or v == "https://localhost") and os.environ.get("RENDER_EXTERNAL_URL"):
            v = os.environ["RENDER_EXTERNAL_URL"]
        return str(v).rstrip("/")

    @field_validator("database_url", mode="before")
    @classmethod
    def _db_driver(cls, v: str) -> str:
        # Render/Heroku liefern postgres:// bzw. postgresql:// – SQLAlchemy braucht den psycopg-Treiber
        v = str(v)
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def public_origin(self) -> str:
        p = urlparse(self.public_url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def cookie_name(self) -> str:
        # __Host- Präfix erzwingt Secure, Path=/ und keine Domain
        return "__Host-quitly_session" if self.cookie_secure else "quitly_session"

    @property
    def allowed_ports(self) -> set[int]:
        return {int(p) for p in self.imap_allowed_ports.split(",") if p.strip()}

    @property
    def allowed_hosts(self) -> set[str]:
        return {h.strip().lower().rstrip(".") for h in self.imap_allowed_hosts.split(",") if h.strip()}

    @property
    def gmail_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def gmail_redirect_uri(self) -> str:
        return f"{self.public_url}/api/oauth/google/callback"

    def decoded_key(self, value: str) -> bytes:
        raw = base64.b64decode(value, validate=True)
        if len(raw) != 32:
            raise ValueError("Schlüssel muss genau 32 Bytes (base64) lang sein")
        return raw

    def validate_secrets(self) -> None:
        """Bricht den Start ab, wenn Pflichtgeheimnisse fehlen oder zu schwach sind."""
        problems = []
        try:
            if len(base64.b64decode(self.secret_key, validate=True)) < 32:
                problems.append("QUITLY_SECRET_KEY ist kürzer als 32 Bytes")
        except Exception:
            problems.append("QUITLY_SECRET_KEY fehlt oder ist kein gültiges base64")
        try:
            self.decoded_key(self.encryption_key)
        except Exception:
            problems.append("QUITLY_ENCRYPTION_KEY fehlt oder ist nicht 32 Bytes base64")
        if self.is_production:
            if not self.public_url.startswith("https://"):
                problems.append("QUITLY_PUBLIC_URL muss in Produktion mit https:// beginnen")
            if not self.cookie_secure:
                problems.append("QUITLY_COOKIE_SECURE darf in Produktion nicht false sein")
        if problems:
            raise RuntimeError("Unsichere Konfiguration: " + "; ".join(problems))


LEGACY_PREFIX = "LOTSE_"


def _apply_legacy_env() -> None:
    for key, value in list(os.environ.items()):
        if key.startswith(LEGACY_PREFIX):
            os.environ.setdefault("QUITLY_" + key[len(LEGACY_PREFIX):], value)


@lru_cache
def get_settings() -> Settings:
    _apply_legacy_env()
    return Settings()
