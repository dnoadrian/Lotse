"""Integrationstests gegen einen echten IMAPS-Server (Dovecot, Testpostfach).

Start des Testservers: sudo scripts/test-imap/start.sh
Ohne laufenden Server werden diese Tests übersprungen (nicht als bestanden gewertet).
Destruktive Tests laufen ausschließlich gegen dieses Testpostfach.
"""
from __future__ import annotations

import imaplib
import os
import socket
import ssl
import time
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import pytest

HOST = os.environ.get("QUITLY_TEST_IMAP_HOST", "imap.quitly.test")
PORT = int(os.environ.get("QUITLY_TEST_IMAP_PORT", "10993"))
USER = "test@quitly.test"
PASS = "test-passwort-123"
CA = os.environ.get("QUITLY_TEST_IMAP_CA", "/tmp/quitly-test-imap/ca.pem")


def _server_up() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=1):
            return os.path.exists(CA)
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not _server_up(), reason="IMAP-Testserver läuft nicht (scripts/test-imap/start.sh)")


def raw_imap() -> imaplib.IMAP4_SSL:
    c = imaplib.IMAP4_SSL(HOST, PORT, ssl_context=ssl.create_default_context(cafile=CA))
    c.login(USER, PASS)
    return c


def msg(sender: str, subject: str, days_ago: int, unsub: bool = False) -> bytes:
    date = format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))
    extra = "List-Unsubscribe: <mailto:unsubscribe@example.com>\r\n" if unsub else ""
    return (f"From: {sender}\r\nTo: {USER}\r\nSubject: {subject}\r\nDate: {date}\r\n{extra}"
            f"Message-ID: <{time.time_ns()}@test>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nTestinhalt\r\n").encode()


SEED_INBOX = [
    ("GitHub <noreply@github.com>", "Welcome to GitHub!", 2000),
    ("GitHub <notifications@github.com>", "[GitHub] Please verify your email address", 2000),
    ("GitHub <notifications@github.com>", "Weekly digest", 10),
    ("Spotify <no-reply@spotify.com>", "Bitte bestätige deine E-Mail-Adresse", 1500),
    ("Dropbox <no-reply@dropbox.com>", "Willkommen bei Dropbox", 3000),
    ("Dropbox <no-reply@dropbox.com>", "Your account has been deleted", 5),
    ("Kulturverein <news@kulturverein-beispiel.at>", "Programm im Oktober", 3, True),
    ("Bäckerei Muster <bestellung@baeckerei-muster.at>", "Willkommen in unserem Webshop", 400),
    ("Freundin <freundin@gmail.com>", "Willkommen zurück aus dem Urlaub!", 30),
]
SEED_ARCHIVE = [
    ("Adobe <mail@mail.adobe.com>", "Ihre Adobe ID wurde erstellt", 2500),
]


@pytest.fixture
def mailbox():
    """Setzt das Testpostfach auf einen definierten Zustand zurück."""
    c = raw_imap()
    _, folders = c.list()
    for line in folders:
        name = line.decode().split(' "/" ')[-1].strip('"')
        if name not in ("INBOX", "Trash", "Sent", "Junk"):
            c.delete(f'"{name}"')
    for name in ("INBOX", "Trash", "Sent", "Junk"):
        _, data = c.select(f'"{name}"')
        if int(data[0]):
            c.store("1:*", "+FLAGS.SILENT", r"(\Deleted)")
            c.expunge()
    c.create('"Archiv"')
    for sender, subject, days, *unsub in SEED_INBOX:
        c.append("INBOX", None, None, msg(sender, subject, days, bool(unsub and unsub[0])))
    for sender, subject, days in SEED_ARCHIVE:
        c.append('"Archiv"', None, None, msg(sender, subject, days))
    c.logout()
    yield


def count(folder: str) -> int:
    c = raw_imap()
    typ, data = c.select(f'"{folder}"', readonly=True)
    c.logout()
    return int(data[0])


@pytest.fixture
def imap_env(settings_env, app):
    settings_env(imap_allowed_hosts=HOST, imap_allowed_ports=str(PORT), imap_ca_file=CA)


@pytest.fixture
def account(auth, imap_env, mailbox):
    r = auth.post("/api/mail-accounts/imap", json={"label": "Mailcow Test", "host": HOST, "port": PORT,
                                                    "username": USER, "password": PASS})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- Verbindung

def test_wrong_password_is_reported_without_details(auth, imap_env, mailbox):
    r = auth.post("/api/mail-accounts/imap", json={"label": "x", "host": HOST, "port": PORT,
                                                    "username": USER, "password": "falsch"})
    assert r.status_code == 400 and "Anmeldung am Mailserver fehlgeschlagen" in r.json()["detail"]


def test_untrusted_certificate_rejected(auth, settings_env, app, mailbox):
    settings_env(imap_allowed_hosts=HOST, imap_allowed_ports=str(PORT), imap_ca_file="")
    r = auth.post("/api/mail-accounts/imap", json={"label": "x", "host": HOST, "port": PORT,
                                                    "username": USER, "password": PASS})
    assert r.status_code == 400 and "Zertifikat" in r.json()["detail"]


def test_hostname_mismatch_rejected(auth, settings_env, app, mailbox):
    settings_env(imap_allowed_hosts="falsch.quitly.test", imap_allowed_ports=str(PORT), imap_ca_file=CA)
    r = auth.post("/api/mail-accounts/imap", json={"label": "x", "host": "falsch.quitly.test", "port": PORT,
                                                    "username": USER, "password": PASS})
    assert r.status_code == 400 and "Zertifikat" in r.json()["detail"]


def test_loopback_blocked_without_allowlist(auth, settings_env, app, mailbox):
    settings_env(imap_allowed_hosts="", imap_allowed_ports=str(PORT), imap_ca_file=CA)
    r = auth.post("/api/mail-accounts/imap", json={"label": "x", "host": HOST, "port": PORT,
                                                    "username": USER, "password": PASS})
    assert r.status_code == 400 and "interne Adresse" in r.json()["detail"]


# ---------------------------------------------------------------- Erkennung

def test_scan_detects_and_merges_services(auth, account):
    r = auth.post("/api/scans", json={"account_id": account["id"]})
    assert r.status_code == 202
    job = auth.get(f"/api/scans/{r.json()['id']}").json()
    assert job["status"] == "done", job
    assert job["messages_seen"] == len(SEED_INBOX) + len(SEED_ARCHIVE)

    services = {s["name"]: s for s in auth.get("/api/services").json()}
    assert {"GitHub", "Spotify", "Dropbox", "Adobe"} <= services.keys()
    # Persönliche Freemail-Absender und reine Newsletter sind keine Dienste
    assert not any("gmail" in d for s in services.values() for d in s["domains"])
    # Jede Mail zählt: auch reine Newsletter-Absender erscheinen – aber nur als "mögliches" Konto
    kultur = next(s for s in services.values() if "kulturverein-beispiel.at" in s["domains"])
    assert kultur["quality"] == "niedrig" and kultur["jdm"] is None

    gh = services["GitHub"]
    assert gh["jdm"] and gh["jdm"]["url"].startswith("https://")
    assert gh["message_count"] == 3 and gh["signal_count"] == 3  # jede Mail ist ein Beleg
    assert gh["signals"]["welcome"] == 1 and gh["signals"]["verification"] == 1
    assert gh["quality"] == "hoch" and gh["confidence"] >= 0.85
    assert gh["sender_count"] == 2  # zwei Absender zusammengeführt

    dropbox = services["Dropbox"]
    assert dropbox["deletion_detected"] is True and dropbox["status"] == "geloescht"

    bakery = [s for s in services.values() if "baeckerei-muster.at" in s["domains"]][0]
    assert bakery["jdm"] is None  # kein erfundener Link

    # Rescan ist idempotent
    auth.post("/api/scans", json={"account_id": account["id"]})
    again = {s["name"]: s for s in auth.get("/api/services").json()}
    assert again["GitHub"]["signal_count"] == 3 and len(again) == len(services)


def test_folders_and_message_listing(auth, account):
    folders = {f["id"]: f for f in auth.get(f"/api/mail/{account['id']}/folders").json()}
    assert folders["INBOX"]["count"] == len(SEED_INBOX) and folders["INBOX"]["special"] == "inbox"
    assert folders["Trash"]["special"] == "trash" and folders["Archiv"]["count"] == 1

    r = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "page_size": 10}).json()
    assert r["total"] == len(SEED_INBOX) and r["uidvalidity"]
    subjects = [m["subject"] for m in r["items"]]
    assert "Welcome to GitHub!" in subjects


def test_only_registration_filter(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    r = auth.get(f"/api/mail/{account['id']}/messages",
                 params={"folder": "INBOX", "only_registration": "true"}).json()
    subjects = {m["subject"] for m in r["items"]}
    assert "Welcome to GitHub!" in subjects and "Weekly digest" not in subjects
    assert "Willkommen zurück aus dem Urlaub!" not in subjects
    assert all(m["category"] for m in r["items"])


# ---------------------------------------------------------------- Löschen (nur Testpostfach)

def _listing(auth, account, folder="INBOX"):
    return auth.get(f"/api/mail/{account['id']}/messages", params={"folder": folder, "page_size": 100}).json()


def test_delete_single_moves_to_trash_and_verifies(auth, account):
    lst = _listing(auth, account)
    target = next(m for m in lst["items"] if m["subject"] == "Weekly digest")
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": [target["id"]], "uidvalidity": lst["uidvalidity"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res == {**res, "requested": 1, "deleted": 1, "failed": 0, "verified": True, "moved_to_trash": True}
    assert count("INBOX") == len(SEED_INBOX) - 1 and count("Trash") == 1


def test_bulk_delete_requires_confirmation(auth, account):
    lst = _listing(auth, account)
    ids = [m["id"] for m in lst["items"][:2]]
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": ids})
    assert r.status_code == 400 and "LÖSCHEN" in r.json()["detail"]
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": ids,
                                                             "confirmation": "löschen"})
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert count("INBOX") == len(SEED_INBOX) - 2


def test_permanent_delete_requires_confirmation_even_for_one(auth, account):
    lst = _listing(auth, account)
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": [lst["items"][0]["id"]], "permanent": True})
    assert r.status_code == 400


def test_delete_all_checks_expected_count(auth, account):
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "all", "expected_count": 3, "confirmation": "LÖSCHEN"})
    assert r.status_code == 409
    assert count("INBOX") == len(SEED_INBOX)  # nichts gelöscht


def test_delete_all_in_folder_permanently(auth, account):
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "Archiv", "mode": "all", "expected_count": 1, "permanent": True, "confirmation": "LÖSCHEN"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["deleted"] == 1 and res["failed"] == 0 and res["verified"] and not res["moved_to_trash"]
    assert count("Archiv") == 0 and count("Trash") == 0


def test_delete_only_registration_mails(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    reg = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "only_registration": "true"}).json()
    n = reg["total"]
    assert n >= 5
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "registration", "expected_count": n, "confirmation": "LÖSCHEN"})
    assert r.status_code == 200 and r.json()["deleted"] == n
    remaining = {m["subject"] for m in _listing(auth, account)["items"]}
    assert "Weekly digest" in remaining and "Programm im Oktober" in remaining
    assert "Welcome to GitHub!" not in remaining
    # Belege für gelöschte Mails sind entfernt
    again = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "only_registration": "true"}).json()
    assert again["total"] == 0


def test_stale_uidvalidity_rejected(auth, account):
    lst = _listing(auth, account)
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": [lst["items"][0]["id"]], "uidvalidity": "999"})
    assert r.status_code == 409


def test_already_deleted_messages_reported(auth, account):
    lst = _listing(auth, account)
    mid = lst["items"][0]["id"]
    body = {"folder": "INBOX", "mode": "selected", "ids": [mid]}
    assert auth.post(f"/api/mail/{account['id']}/delete", json=body).json()["deleted"] == 1
    res = auth.post(f"/api/mail/{account['id']}/delete", json=body).json()
    assert res["deleted"] == 0 and res["already_missing"] == 1 and res["failed"] == 0


@pytest.mark.parametrize("folder", ['INBOX" LOGOUT', "INBOX\r\nA1 LOGOUT", "../../etc", "Nicht vorhanden"])
def test_folder_injection_rejected(auth, account, folder):
    r = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": folder})
    assert r.status_code in (400, 502) and "Ordner" in r.json()["detail"]
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": folder, "mode": "all", "expected_count": 0,
                                                             "confirmation": "LÖSCHEN"})
    assert r.status_code in (400, 502)
    assert count("INBOX") == len(SEED_INBOX)


@pytest.mark.parametrize("bad", ["1:*", "1,2", "-1", "abc", "0"])
def test_invalid_uids_rejected(auth, account, bad):
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": [bad]})
    assert r.status_code == 400
    assert count("INBOX") == len(SEED_INBOX)


def test_reading_does_not_mark_as_seen(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    _listing(auth, account)
    c = raw_imap()
    c.select("INBOX", readonly=True)
    _, data = c.search(None, "SEEN")
    c.logout()
    assert data[0] == b""


def test_removing_account_updates_service_counts(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    assert auth.delete(f"/api/mail-accounts/{account['id']}").status_code == 200
    # Unbearbeitete Dienste verschwinden, bearbeitete bleiben ohne Mail-Zahlen erhalten
    services = auth.get("/api/services").json()
    assert all(s["status"] != "offen" for s in services)
    again = auth.post("/api/mail-accounts/imap", json={"label": "Neu", "host": HOST, "port": PORT,
                                                        "username": USER, "password": PASS}).json()
    auth.post("/api/scans", json={"account_id": again["id"]})
    gh = next(s for s in auth.get("/api/services").json() if s["name"] == "GitHub")
    assert gh["message_count"] == 3 and gh["sender_count"] == 2
