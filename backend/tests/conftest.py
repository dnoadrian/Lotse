from __future__ import annotations

import base64
import os

import pytest

# Standard: SQLite im Speicher. Mit LOTSE_TEST_DATABASE_URL laufen dieselben Tests gegen PostgreSQL.
TEST_DB = os.environ.get("LOTSE_TEST_DATABASE_URL", "sqlite://")
os.environ.update({
    "LOTSE_ENVIRONMENT": "test",
    "LOTSE_DATABASE_URL": TEST_DB,
    "LOTSE_SECRET_KEY": base64.b64encode(b"s" * 32).decode(),
    "LOTSE_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
    "LOTSE_COOKIE_SECURE": "false",
    "LOTSE_PUBLIC_URL": "http://testserver",
})

from fastapi.testclient import TestClient  # noqa: E402

from app import scanner  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import User  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402

PASSWORD = "korrekt-pferd-batterie-42"
H = {"X-Lotse-Request": "1"}


@pytest.fixture
def settings_env(monkeypatch):
    """Erlaubt Tests, einzelne Einstellungen zu überschreiben."""
    def apply(**values):
        for k, v in values.items():
            monkeypatch.setenv(f"LOTSE_{k.upper()}", str(v))
        get_settings.cache_clear()
    yield apply
    get_settings.cache_clear()


@pytest.fixture
def app(monkeypatch):
    get_settings.cache_clear()
    # Scans in Tests synchron ausführen
    monkeypatch.setattr(scanner, "submit", scanner.run)
    if not TEST_DB.startswith("sqlite"):
        from sqlalchemy import create_engine
        from app.db import Base
        eng = create_engine(TEST_DB)
        Base.metadata.drop_all(eng)
        eng.dispose()
    application = create_app()
    yield application
    get_settings.cache_clear()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db(app):
    from app import db as dbmod
    s = dbmod.new_session()
    yield s
    s.close()


def make_user(db, username="anna", password=PASSWORD) -> User:
    u = User(username=username, password_hash=hash_password(password))
    db.add(u)
    db.commit()
    return u


class Session:
    """Angemeldeter Test-Client mit CSRF-Token."""

    def __init__(self, client: TestClient, csrf: str):
        self.c = client
        self.csrf = csrf

    def _h(self, extra=None):
        return {**H, "X-CSRF-Token": self.csrf, **(extra or {})}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json if json is not None else {}, headers=self._h(kw.pop("headers", None)), **kw)

    def put(self, url, json=None, **kw):
        return self.c.put(url, json=json or {}, headers=self._h(kw.pop("headers", None)), **kw)

    def patch(self, url, json=None, **kw):
        return self.c.patch(url, json=json or {}, headers=self._h(kw.pop("headers", None)), **kw)

    def delete(self, url, **kw):
        return self.c.delete(url, headers=self._h(kw.pop("headers", None)), **kw)


def login(client: TestClient, username="anna", password=PASSWORD) -> Session:
    r = client.post("/api/auth/login", json={"username": username, "password": password}, headers=H)
    assert r.status_code == 200, r.text
    assert r.json()["mfa_required"] is False
    return Session(client, r.json()["csrf_token"])


@pytest.fixture
def user(db):
    return make_user(db)


@pytest.fixture
def auth(client, user) -> Session:
    return login(client)
