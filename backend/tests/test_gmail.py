"""Gmail-Integration gegen eine simulierte Google-API (respx).

Echte Google-Zugangsdaten sind für automatische Tests nicht vorhanden; getestet wird daher das
Protokollverhalten von Lotse (OAuth mit PKCE und State, Token-Speicherung, API-Aufrufe, Überprüfung).
"""
from __future__ import annotations

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.mail import gmail_client as gc

from .conftest import login

API = gc.API


@pytest.fixture
def gmail_env(settings_env, app):
    settings_env(google_client_id="test-client.apps.googleusercontent.com", google_client_secret="test-secret")


class FakeGmail:
    def __init__(self):
        self.messages = {
            "a1b2c3d4e5f60001": ("GitHub <noreply@github.com>", "Welcome to GitHub!", ["INBOX"]),
            "a1b2c3d4e5f60002": ("Spotify <no-reply@spotify.com>", "Bitte bestätige deine E-Mail-Adresse", ["INBOX"]),
            "a1b2c3d4e5f60003": ("Shop <news@shop-beispiel.at>", "Neue Angebote", ["INBOX"]),
        }
        self.trashed: list[str] = []
        self.refuse_trash: set[str] = set()
        self.token_requests: list[dict] = []
        self.revoked: list[str] = []

    def token(self, request: httpx.Request):
        form = parse_qs(request.content.decode())
        self.token_requests.append(form)
        if form["grant_type"] == ["authorization_code"]:
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-GEHEIM", "expires_in": 3600,
                                             "scope": gc.SCOPE})
        return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})

    def list_messages(self, request: httpx.Request):
        ids = [i for i, m in self.messages.items() if i not in self.trashed]
        return httpx.Response(200, json={"messages": [{"id": i} for i in ids], "resultSizeEstimate": len(ids)})

    def get_message(self, request: httpx.Request, msg_id: str):
        if msg_id not in self.messages:
            return httpx.Response(404)
        sender, subject, labels = self.messages[msg_id]
        labels = (["TRASH"] if msg_id in self.trashed else labels)
        return httpx.Response(200, json={
            "id": msg_id, "labelIds": labels, "internalDate": "1600000000000",
            "payload": {"headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject},
                                    {"name": "Date", "value": "Sun, 13 Sep 2020 12:26:40 +0000"}]},
        })

    def trash(self, request: httpx.Request, msg_id: str):
        if msg_id not in self.refuse_trash:
            self.trashed.append(msg_id)
        return httpx.Response(200, json={"id": msg_id})


@pytest.fixture
def google():
    fake = FakeGmail()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(gc.TOKEN_URL).mock(side_effect=fake.token)
        mock.post(gc.REVOKE_URL).mock(side_effect=lambda req: (fake.revoked.append(parse_qs(req.content.decode())["token"][0]),
                                                               httpx.Response(200))[1])
        mock.get(f"{API}/profile").mock(return_value=httpx.Response(200, json={"emailAddress": "ich@gmail.com"}))
        mock.get(f"{API}/labels").mock(return_value=httpx.Response(200, json={"labels": [
            {"id": "INBOX", "type": "system"}, {"id": "TRASH", "type": "system"}, {"id": "Label_1", "name": "Privat", "type": "user"}]}))
        mock.get(url__regex=rf"{API}/labels/[A-Za-z0-9_]+").mock(return_value=httpx.Response(200, json={"messagesTotal": 3}))
        mock.get(f"{API}/messages").mock(side_effect=fake.list_messages)
        mock.post(url__regex=rf"{API}/messages/(?P<msg_id>[^/]+)/trash").mock(side_effect=fake.trash)
        mock.get(url__regex=rf"{API}/messages/(?P<msg_id>[^/?]+)").mock(side_effect=fake.get_message)
        yield fake


def _connect(auth, client: TestClient) -> dict:
    r = auth.post("/api/mail-accounts/gmail/start", json={"label": "Mein Gmail"})
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["authorization_url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    r = client.get("/api/oauth/google/callback", params={"state": q["state"], "code": "auth-code-1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/verbindungen?gmail=ok", r.headers.get("location")
    return q


def test_gmail_disabled_without_client(auth):
    r = auth.post("/api/mail-accounts/gmail/start", json={"label": "x"})
    assert r.status_code == 400


def test_oauth_uses_pkce_state_and_minimal_scope(auth, client, gmail_env, google, db):
    q = _connect(auth, client)
    assert q["scope"] == gc.SCOPE and q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    exchange = google.token_requests[0]
    verifier = exchange["code_verifier"][0]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected
    accounts = auth.get("/api/mail-accounts").json()
    assert accounts[0]["provider"] == "gmail" and accounts[0]["email_address"] == "ich@gmail.com"
    dump = json.dumps([list(map(str, r)) for r in db.execute(text("SELECT * FROM mail_accounts")).all()])
    assert "rt-GEHEIM" not in dump


def test_oauth_state_single_use_and_session_bound(auth, client, gmail_env, google):
    r = auth.post("/api/mail-accounts/gmail/start", json={"label": "x"})
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    # Fremde Browser-Sitzung (anderer Nutzer) kann den State nicht einlösen
    other = TestClient(client.app)
    from app import db as dbmod
    from .conftest import make_user
    with dbmod.new_session() as s:
        make_user(s, "bert")
    login(other, "bert")
    r = other.get("/api/oauth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False)
    assert r.headers["location"].endswith("gmail=fehler")
    # Danach ist der State verbraucht – auch für den richtigen Nutzer
    r = client.get("/api/oauth/google/callback", params={"state": state, "code": "c"}, follow_redirects=False)
    assert r.headers["location"].endswith("gmail=fehler")
    assert auth.get("/api/mail-accounts").json() == []
    r = client.get("/api/oauth/google/callback", params={"state": "erfunden", "code": "c"}, follow_redirects=False)
    assert r.headers["location"].endswith("gmail=fehler")


def test_oauth_user_cancel(auth, client, gmail_env, google):
    r = auth.post("/api/mail-accounts/gmail/start", json={"label": "x"})
    state = parse_qs(urlparse(r.json()["authorization_url"]).query)["state"][0]
    r = client.get("/api/oauth/google/callback", params={"state": state, "error": "access_denied"}, follow_redirects=False)
    assert r.headers["location"].endswith("gmail=abgebrochen")


def test_gmail_scan_folders_and_listing(auth, client, gmail_env, google):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    job = auth.post("/api/scans", json={"account_id": acc["id"]}).json()
    assert auth.get(f"/api/scans/{job['id']}").json()["status"] == "done"
    names = {s["name"] for s in auth.get("/api/services").json()}
    assert {"GitHub", "Spotify"} <= names
    shop = next(s for s in auth.get("/api/services").json() if "shop-beispiel.at" in s["domains"])
    assert shop["quality"] == "niedrig"

    folders = {f["id"]: f for f in auth.get(f"/api/mail/{acc['id']}/folders").json()}
    assert folders["INBOX"]["name"] == "Posteingang" and folders["Label_1"]["name"] == "Privat"
    msgs = auth.get(f"/api/mail/{acc['id']}/messages", params={"folder": "INBOX"}).json()
    assert len(msgs["items"]) == 3
    reg = auth.get(f"/api/mail/{acc['id']}/messages", params={"folder": "INBOX", "only_registration": "true"}).json()
    assert {m["subject"] for m in reg["items"]} == {"Welcome to GitHub!", "Bitte bestätige deine E-Mail-Adresse"}


def test_gmail_delete_moves_to_trash_and_verifies(auth, client, gmail_env, google):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    google.refuse_trash.add("a1b2c3d4e5f60002")
    r = auth.post(f"/api/mail/{acc['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": ["a1b2c3d4e5f60001", "a1b2c3d4e5f60002"], "confirmation": "LÖSCHEN"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["requested"] == 2 and res["deleted"] == 1 and res["failed"] == 1
    assert res["failed_ids"] == ["a1b2c3d4e5f60002"] and res["verified"] and res["moved_to_trash"]
    assert google.trashed == ["a1b2c3d4e5f60001"]


def test_gmail_permanent_delete_refused(auth, client, gmail_env, google):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    r = auth.post(f"/api/mail/{acc['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": ["a1b2c3d4e5f60001"], "permanent": True, "confirmation": "LÖSCHEN"})
    assert r.status_code == 400 and not google.trashed


@pytest.mark.parametrize("bad", ["../profile", "a1b2/../../x", "x" * 40, "a1b2c3d4e5f6000Z"])
def test_gmail_rejects_invalid_ids(auth, client, gmail_env, google, bad):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    r = auth.post(f"/api/mail/{acc['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": [bad]})
    assert r.status_code == 400 and not google.trashed


def test_gmail_delete_all_checks_count(auth, client, gmail_env, google):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    r = auth.post(f"/api/mail/{acc['id']}/delete", json={"folder": "INBOX", "mode": "all", "expected_count": 2,
                                                         "confirmation": "LÖSCHEN"})
    assert r.status_code == 409 and not google.trashed
    r = auth.post(f"/api/mail/{acc['id']}/delete", json={"folder": "INBOX", "mode": "all", "expected_count": 3,
                                                         "confirmation": "LÖSCHEN"})
    assert r.status_code == 200 and r.json()["deleted"] == 3


def test_removing_gmail_account_revokes_token(auth, client, gmail_env, google):
    _connect(auth, client)
    acc = auth.get("/api/mail-accounts").json()[0]
    assert auth.delete(f"/api/mail-accounts/{acc['id']}").status_code == 200
    assert google.revoked == ["rt-GEHEIM"]
    assert auth.get("/api/mail-accounts").json() == []
