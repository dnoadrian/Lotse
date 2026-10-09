"""Sicherheitsmechanismen: Header, CSRF, Sitzungen, Brute-Force, Isolation, Verschlüsselung, Logging."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.models import AuditLog, MailAccount, ScanJob, Service, UserSession
from app.security import crypto
from app.security.crypto import DecryptionError, decrypt, encrypt

from .conftest import H, PASSWORD, Session, login, make_user


# ---------------------------------------------------------------- Header & Grundschutz

def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["content-security-policy"].startswith("default-src 'self'")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_mutation_requires_custom_header(client, user):
    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD})
    assert r.status_code == 403


def test_foreign_origin_rejected(client, user):
    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD},
                    headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_only_json_accepted(client, user):
    r = client.post("/api/auth/login", content=b"username=anna&password=x",
                    headers={**H, "Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415


def test_body_size_limit(client, user):
    r = client.post("/api/auth/login", content=b"{" + b" " * 300_000 + b"}",
                    headers={**H, "Content-Type": "application/json"})
    assert r.status_code == 413


def test_docs_disabled_in_production(settings_env, monkeypatch):
    from app import scanner
    from app.main import create_app
    settings_env(environment="production", public_url="https://lotse.example", cookie_secure="true")
    monkeypatch.setattr(scanner, "submit", scanner.run)
    with TestClient(create_app(), base_url="https://lotse.example") as c:
        assert c.get("/api/docs").status_code == 404
        assert c.get("/api/openapi.json").status_code == 404


@pytest.mark.parametrize("override,needle", [
    ({"secret_key": ""}, "LOTSE_SECRET_KEY"),
    ({"encryption_key": "zu-kurz"}, "LOTSE_ENCRYPTION_KEY"),
    ({"environment": "production", "public_url": "http://lotse.example"}, "https://"),
    ({"environment": "production", "public_url": "https://x.example", "cookie_secure": "false"}, "COOKIE_SECURE"),
])
def test_insecure_config_refused(settings_env, override, needle):
    from app.config import get_settings
    settings_env(**override)
    with pytest.raises(RuntimeError, match=needle):
        get_settings().validate_secrets()


# ---------------------------------------------------------------- Authentifizierung

PROTECTED = [
    ("GET", "/api/mail-accounts"), ("GET", "/api/services"), ("GET", "/api/scans"), ("GET", "/api/config"),
    ("GET", "/api/security/overview"), ("GET", "/api/security/audit"), ("GET", "/api/services/export.csv"),
    ("GET", "/api/mail/1/folders"), ("GET", "/api/mail/1/messages?folder=INBOX"),
    ("POST", "/api/mail/1/delete"), ("POST", "/api/scans"), ("PATCH", "/api/services/1"),
    ("POST", "/api/mail-accounts/imap"), ("DELETE", "/api/mail-accounts/1"), ("POST", "/api/security/totp/setup"),
]


@pytest.mark.parametrize("method,url", PROTECTED)
def test_endpoints_require_login(client, method, url):
    r = client.request(method, url, json={} if method != "GET" else None, headers=H)
    assert r.status_code in (401, 422), (method, url, r.status_code)
    if r.status_code == 422:  # Validierung vor Auth ist ok, darf aber keine Daten liefern
        assert "detail" in r.json()


def test_all_api_routes_are_covered(app):
    """Jede neue Route muss bewusst öffentlich sein oder Anmeldung verlangen."""
    public = {"/api/health", "/api/auth/login", "/api/auth/totp", "/api/auth/logout", "/api/auth/session",
              "/api/oauth/google/callback"}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api") or path in public or path.startswith("/api/docs") or path == "/api/openapi.json":
            continue
        deps = [d.call.__name__ for d in route.dependant.dependencies]
        assert "require_auth" in deps, f"{path} ist nicht geschützt"


def test_login_generic_error_and_no_user_enumeration(client, user):
    a = client.post("/api/auth/login", json={"username": "anna", "password": "falsch-falsch-falsch"}, headers=H)
    b = client.post("/api/auth/login", json={"username": "niemand", "password": "falsch-falsch-falsch"}, headers=H)
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_cookie_flags(client, user):
    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}, headers=H)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie


def test_secure_cookie_has_host_prefix(settings_env, monkeypatch):
    from app import scanner
    from app import db as dbmod
    from app.main import create_app
    settings_env(cookie_secure="true", public_url="https://testserver")
    monkeypatch.setattr(scanner, "submit", scanner.run)
    app = create_app()
    with dbmod.new_session() as s:
        make_user(s, "carla-secure")
    with TestClient(app, base_url="https://testserver") as c:
        r = c.post("/api/auth/login", json={"username": "carla-secure", "password": PASSWORD}, headers=H)
        cookie = r.headers["set-cookie"]
        assert cookie.startswith("__Host-lotse_session=") and "Secure" in cookie


def test_session_rotates_on_login(client, user):
    login(client)
    first = client.cookies.get("lotse_session")
    login(client)
    second = client.cookies.get("lotse_session")
    assert first and second and first != second


def test_session_token_stored_hashed(client, user, db):
    login(client)
    token = client.cookies.get("lotse_session")
    stored = db.execute(select(UserSession.token_hash)).scalars().all()
    assert token not in stored and crypto.token_hash(token) in stored


def test_logout_invalidates_session(client, user):
    s = login(client)
    token = client.cookies.get("lotse_session")
    assert s.post("/api/auth/logout").status_code == 200
    client.cookies.set("lotse_session", token)
    assert client.get("/api/mail-accounts").status_code == 401


def test_idle_timeout(client, user, db):
    login(client)
    sess = db.execute(select(UserSession)).scalar_one()
    sess.last_seen = datetime.now(timezone.utc) - timedelta(hours=2)
    db.commit()
    assert client.get("/api/mail-accounts").status_code == 401


def test_csrf_token_required(client, user):
    s = login(client)
    r = client.post("/api/scans", json={"account_id": 1}, headers=H)
    assert r.status_code == 403
    r = client.post("/api/scans", json={"account_id": 1}, headers={**H, "X-CSRF-Token": "falsch"})
    assert r.status_code == 403
    assert s.post("/api/scans", json={"account_id": 1}).status_code == 404  # Token ok, Postfach existiert nicht


def test_brute_force_lockout(client, user):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "anna", "password": "falsch-falsch-falsch"}, headers=H)
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}, headers=H)
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0


def test_successful_logins_do_not_count_towards_ip_limit(client, user):
    for _ in range(25):
        login(client)


def test_ip_rate_limit_against_password_spraying(client, db):
    for i in range(20):
        client.post("/api/auth/login", json={"username": f"user{i}", "password": "irgendwas-langes"}, headers=H)
    r = client.post("/api/auth/login", json={"username": "neu", "password": "irgendwas-langes"}, headers=H)
    assert r.status_code == 429


def test_validation_errors_do_not_echo_input(client):
    r = client.post("/api/auth/login", json={"username": "", "password": "GEHEIM-passwort-123"}, headers=H)
    assert r.status_code == 422 and "GEHEIM" not in r.text


def test_password_never_logged(client, user, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/api/auth/login", json={"username": "anna", "password": "Sehr-Geheim-987654"}, headers=H)
    client.get("/api/oauth/google/callback?code=GEHEIMER-CODE&state=abc")
    # Nur Logs der Anwendung (nicht die des Test-HTTP-Clients) betrachten
    app_logs = "\n".join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert "Sehr-Geheim" not in app_logs
    assert "GEHEIMER-CODE" not in app_logs


# ---------------------------------------------------------------- Zwei-Faktor

def _enable_totp(s: Session) -> str:
    secret = s.post("/api/security/totp/setup").json()["secret"]
    code = pyotp.TOTP(secret).now()
    assert s.post("/api/security/totp/enable", json={"code": code}).status_code == 200
    return secret


def test_totp_flow_and_replay_protection(client, user, db):
    s = login(client)
    secret = _enable_totp(s)
    s.post("/api/auth/logout")

    r = client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}, headers=H)
    assert r.json() == {"mfa_required": True}
    # Halbe Anmeldung gewährt keinen Zugriff
    assert client.get("/api/mail-accounts").status_code == 401
    assert client.post("/api/auth/totp", json={"code": "000000"}, headers=H).status_code == 401
    # Der bei der Aktivierung benutzte Code darf nicht erneut funktionieren → nächsten Zeitschritt nehmen
    code = pyotp.TOTP(secret).at(time.time() + 30)
    r = client.post("/api/auth/totp", json={"code": code}, headers=H)
    assert r.status_code == 200
    assert client.get("/api/mail-accounts").status_code == 200
    # Wiederverwendung desselben Codes wird abgelehnt
    client.post("/api/auth/logout", json={}, headers={**H, "X-CSRF-Token": r.json()["csrf_token"]})
    client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}, headers=H)
    assert client.post("/api/auth/totp", json={"code": code}, headers=H).status_code == 401


def test_totp_rate_limited(client, user):
    s = login(client)
    _enable_totp(s)
    s.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "anna", "password": PASSWORD}, headers=H)
    codes = [client.post("/api/auth/totp", json={"code": "111111"}, headers=H).status_code for _ in range(6)]
    assert codes[-1] == 429


def test_totp_secret_encrypted(client, user, db):
    s = login(client)
    secret = _enable_totp(s)
    db.refresh(user)
    assert secret not in (user.totp_secret_enc or "")
    assert user.totp_secret_enc.startswith("v1:")


# ---------------------------------------------------------------- Passwörter

def test_password_change_rules_and_session_revocation(client, user):
    other = TestClient(client.app)
    login(other)
    s = login(client)
    assert s.post("/api/security/password", json={"current_password": "falsch", "new_password": "x" * 20}).status_code == 400
    assert s.post("/api/security/password", json={"current_password": PASSWORD, "new_password": "kurz"}).status_code == 400
    r = s.post("/api/security/password", json={"current_password": PASSWORD, "new_password": "ein-neues-langes-passwort"})
    assert r.status_code == 200 and r.json()["other_sessions_revoked"] == 1
    assert other.get("/api/mail-accounts").status_code == 401
    assert client.get("/api/mail-accounts").status_code == 200


def test_password_hash_is_argon2id(user):
    assert user.password_hash.startswith("$argon2id$")


# ---------------------------------------------------------------- Mandantentrennung

def test_users_cannot_access_foreign_data(client, db):
    a = make_user(db, "anna")
    make_user(db, "bert")
    acc = MailAccount(user_id=a.id, provider="imap", label="Annas Postfach", imap_host="mail.example.org")
    acc.secret_enc = encrypt("x", "dummy")
    db.add(acc)
    db.commit()
    svc = Service(user_id=a.id, key="domain:example.org", display_name="Example", domains=[], sources={}, signals={})
    db.add(svc)
    db.add(ScanJob(user_id=a.id, account_id=acc.id))
    db.commit()

    bert = login(client, "bert")
    assert bert.get("/api/mail-accounts").json() == []
    assert bert.get("/api/services").json() == []
    assert bert.get(f"/api/mail/{acc.id}/folders").status_code == 404
    assert bert.get(f"/api/mail/{acc.id}/messages?folder=INBOX").status_code == 404
    assert bert.post(f"/api/mail/{acc.id}/delete", json={"folder": "INBOX", "mode": "selected", "ids": ["1"]}).status_code == 404
    assert bert.post(f"/api/mail-accounts/{acc.id}/test").status_code == 404
    assert bert.delete(f"/api/mail-accounts/{acc.id}").status_code == 404
    assert bert.post("/api/scans", json={"account_id": acc.id}).status_code == 404
    assert bert.get("/api/scans/1").status_code == 404
    assert bert.patch(f"/api/services/{svc.id}", json={"status": "geloescht"}).status_code == 404
    assert bert.post("/api/services/bulk-status", json={"ids": [svc.id], "status": "geloescht"}).status_code == 404
    db.refresh(svc)
    assert svc.status == "offen"
    assert db.get(MailAccount, acc.id) is not None


# ---------------------------------------------------------------- Verschlüsselung

def test_encryption_roundtrip_and_binding():
    token = encrypt("geheim", "mail_account:1:imap:secret")
    assert "geheim" not in token
    assert decrypt(token, "mail_account:1:imap:secret") == "geheim"
    with pytest.raises(DecryptionError):
        decrypt(token, "mail_account:2:imap:secret")  # anderer Nutzer
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(DecryptionError):
        decrypt(tampered, "mail_account:1:imap:secret")


def test_key_rotation(settings_env):
    import base64
    old_key = base64.b64encode(b"k" * 32).decode()
    token = encrypt("geheim", "p")
    settings_env(encryption_key=base64.b64encode(b"n" * 32).decode(), encryption_keys_old=old_key)
    assert decrypt(token, "p") == "geheim"
    assert crypto.needs_reencrypt(token)


def test_audit_never_stores_secrets(db):
    from app import audit
    audit.record(db, "test", None, None, password="x", token="y", subject="z", count=3)
    row = db.execute(select(AuditLog)).scalar_one()
    assert row.detail == {"count": 3}


def test_no_plaintext_credentials_in_database(client, auth, db, monkeypatch):
    from contextlib import contextmanager

    from app.mail import imap_client

    @contextmanager
    def fake_connect(host, port, username, password):
        class C:
            def list(self):
                return "OK", [b'(\\HasNoChildren) "/" INBOX']
        yield C()

    monkeypatch.setattr(imap_client, "connect", fake_connect)
    monkeypatch.setattr("app.routers.accounts.normalize_host", lambda h: h)
    r = auth.post("/api/mail-accounts/imap", json={"label": "Test", "host": "mail.example.org", "port": 993,
                                                    "username": "ich@example.org", "password": "Klartext-Passwort-1"})
    assert r.status_code == 201, r.text
    assert "Klartext" not in r.text
    dump = " ".join(str(v) for row in db.execute(text("SELECT * FROM mail_accounts")).all() for v in row)
    assert "Klartext-Passwort-1" not in dump


def test_connection_tests_rate_limited(client, auth, monkeypatch):
    from app.routers import accounts
    calls = []
    monkeypatch.setattr(accounts, "_test_imap", lambda *a: calls.append(a))
    body = {"label": "x", "host": "mail.example.org", "port": 993, "username": "u", "password": "p"}
    codes = [auth.post("/api/mail-accounts/imap", json=body).status_code for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429 and len(calls) == 10
