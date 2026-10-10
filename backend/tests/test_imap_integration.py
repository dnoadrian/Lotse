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


def html_msg(sender: str, subject: str, days_ago: int) -> bytes:
    date = format_datetime(datetime.now(timezone.utc) - timedelta(days=days_ago))
    html = ('<html><head><script>alert(1)</script><style>body{color:red}</style></head><body>'
            '<h1 onclick="steal()">Willkommen bei Netflix</h1><p>Hallo &amp; danke.</p>'
            '<img src="https://tracker.example/pixel.gif" onerror="alert(2)">'
            '<a href="javascript:alert(3)">Klick</a> <a href="https://help.netflix.com/">Hilfe</a>'
            '<form action="https://evil.example"><input name="pw"></form><iframe src="https://evil.example"></iframe>'
            '</body></html>')
    return (f"From: Netflix <info@mailer.netflix.com>\r\nTo: {USER}\r\nSubject: {subject}\r\nDate: {date}\r\n"
            "List-Unsubscribe: <https://www.netflix.com/unsubscribe?x=1>, <mailto:unsub@netflix.com>\r\n"
            f"Message-ID: <{time.time_ns()}@test>\r\nMIME-Version: 1.0\r\n"
            "Content-Type: multipart/alternative; boundary=b1\r\n\r\n"
            "--b1\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nWillkommen bei Netflix. Hallo & danke.\r\n"
            "--b1\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html + "\r\n--b1--\r\n").encode()


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
INBOX_TOTAL = len(SEED_INBOX) + 1  # + eine HTML-Mail (Netflix)
# Registrierungs-Mails landen oft im Spam – auch dort wird gesucht
SEED_JUNK = [
    ("Cloudflare <noreply@notify.cloudflare.com>", "[Cloudflare]: Please verify your email address", 900),
    ("Discord <noreply@discord.com>", "Verify Email Address for Discord", 1200),
    ("Discord <noreply@discord.com>", "Your Discord account is scheduled for deletion", 3),
    ("Canva <no-reply@canva.com>", "Welcome to Canva", 1000),
    ("Canva <no-reply@canva.com>", "Your email address has been changed", 2),
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
    for sender, subject, days in SEED_JUNK:
        c.append("Junk", None, None, msg(sender, subject, days))
    c.append("INBOX", None, None, html_msg("Netflix", "Willkommen bei Netflix", 50))
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
    assert job["messages_seen"] == INBOX_TOTAL + len(SEED_ARCHIVE) + len(SEED_JUNK)

    services = {s["name"]: s for s in auth.get("/api/services").json()}
    assert {"GitHub", "Spotify", "Dropbox", "Adobe"} <= services.keys()
    # Persönliche Freemail-Absender und reine Newsletter sind keine Dienste
    assert not any("gmail" in d for s in services.values() for d in s["domains"])
    # Nur sichere Konten: ein reiner Newsletter-Absender ist kein Konto
    assert not any("kulturverein-beispiel.at" in s["domains"] for s in services.values())

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
    assert folders["INBOX"]["count"] == INBOX_TOTAL and folders["INBOX"]["special"] == "inbox"
    assert folders["Trash"]["special"] == "trash" and folders["Archiv"]["count"] == 1

    r = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "page_size": 10}).json()
    assert r["total"] == INBOX_TOTAL and r["uidvalidity"]
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
    assert count("INBOX") == INBOX_TOTAL - 1 and count("Trash") == 1


def test_bulk_delete_requires_confirmation(auth, account):
    lst = _listing(auth, account)
    ids = [m["id"] for m in lst["items"][:2]]
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": ids})
    assert r.status_code == 400 and "LÖSCHEN" in r.json()["detail"]
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": ids,
                                                             "confirmation": "löschen"})
    assert r.status_code == 200 and r.json()["deleted"] == 2
    assert count("INBOX") == INBOX_TOTAL - 2


def test_permanent_delete_requires_confirmation_even_for_one(auth, account):
    lst = _listing(auth, account)
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "selected", "ids": [lst["items"][0]["id"]], "permanent": True})
    assert r.status_code == 400


def test_delete_all_checks_expected_count(auth, account):
    r = auth.post(f"/api/mail/{account['id']}/delete", json={
        "folder": "INBOX", "mode": "all", "expected_count": 3, "confirmation": "LÖSCHEN"})
    assert r.status_code == 409
    assert count("INBOX") == INBOX_TOTAL  # nichts gelöscht


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
    assert count("INBOX") == INBOX_TOTAL


@pytest.mark.parametrize("bad", ["1:*", "1,2", "-1", "abc", "0"])
def test_invalid_uids_rejected(auth, account, bad):
    r = auth.post(f"/api/mail/{account['id']}/delete", json={"folder": "INBOX", "mode": "selected", "ids": [bad]})
    assert r.status_code == 400
    assert count("INBOX") == INBOX_TOTAL


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


# ---------------------------------------------------------------- Neue Erkennung, Gedächtnis, Lesen

def test_scan_finds_spam_folder_deletion_requests_and_email_changes(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    services = {s["name"]: s for s in auth.get("/api/services").json()}
    assert {"Cloudflare", "Discord", "Canva", "Netflix"} <= services.keys()
    assert services["Cloudflare"]["jdm"] is not None
    # Discord kündigt die Löschung an → angefragt, noch nicht gelöscht
    assert services["Discord"]["status"] == "angefragt" and not services["Discord"]["deletion_detected"]
    assert services["Discord"]["lifecycle"] in ("waiting", "likely_deleted")
    # Canva: Adresse weg von diesem Postfach geändert → gilt als gelöscht
    assert services["Canva"]["deletion_detected"] and services["Canva"]["status"] == "geloescht"
    assert services["Canva"]["deletion_kind"] == "email_changed"
    assert services["Dropbox"]["deletion_kind"] == "deleted"


def test_memory_keeps_accounts_after_mails_are_deleted(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    gh = next(s for s in auth.get("/api/services").json() if s["name"] == "GitHub")
    c = raw_imap()
    c.select("INBOX")
    _, data = c.search(None, "FROM", "github.com")
    c.store(b",".join(data[0].split()).decode(), "+FLAGS.SILENT", r"(\Deleted)")
    c.expunge()
    c.logout()
    auth.post("/api/scans", json={"account_id": account["id"]})
    again = next(s for s in auth.get("/api/services").json() if s["name"] == "GitHub")
    assert again["id"] == gh["id"] and again["memory_only"] is True
    assert again["confidence"] >= 0.85  # das Gedächtnis hält die Erkennung


def test_service_mails_lists_recognized_mails(auth, account):
    auth.post("/api/scans", json={"account_id": account["id"]})
    gh = next(s for s in auth.get("/api/services").json() if s["name"] == "GitHub")
    r = auth.get(f"/api/services/{gh['id']}/mails").json()
    subjects = {i["subject"] for i in r["items"]}
    assert "Welcome to GitHub!" in subjects and all(i["msg_ref"].isdigit() for i in r["items"])
    assert all(i["account_id"] == account["id"] and i["folder"] == "INBOX" for i in r["items"])
    assert r["explanation"] and r["explanation"][0]["label"]
    assert auth.get("/api/services/999999/mails").status_code == 404


def _uid_of(auth, account, subject, folder="INBOX"):
    items = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": folder, "page_size": 100}).json()["items"]
    return next(i["id"] for i in items if i["subject"] == subject)


def test_read_message_text_and_sanitized_html(auth, account):
    uid = _uid_of(auth, account, "Willkommen bei Netflix")
    m = auth.get(f"/api/mail/{account['id']}/message", params={"folder": "INBOX", "uid": uid})
    assert m.status_code == 200
    body = m.json()
    assert "Willkommen bei Netflix" in body["text"] and body["has_html"] and body["seen"] is False
    assert body["unsubscribe"] == {"https": "https://www.netflix.com/unsubscribe?x=1", "mailto": "mailto:unsub@netflix.com"}
    assert "_html" not in body

    h = auth.get(f"/api/mail/{account['id']}/message/html", params={"folder": "INBOX", "uid": uid})
    assert h.status_code == 200 and h.headers["content-type"].startswith("text/html")
    html = h.text.lower()
    for bad in ("<script", "alert(", "onclick", "onerror", "javascript:", "<form", "<iframe", "<input"):
        assert bad not in html, bad
    assert 'href="https://help.netflix.com/"' in h.text and 'rel="noopener noreferrer nofollow"' in h.text
    csp = h.headers["content-security-policy"]
    assert "sandbox" in csp and "script-src" not in csp and "img-src data:;" in csp
    assert h.headers["x-frame-options"] == "SAMEORIGIN"
    with_images = auth.get(f"/api/mail/{account['id']}/message/html", params={"folder": "INBOX", "uid": uid, "images": "true"})
    assert "img-src data: https:" in with_images.headers["content-security-policy"]
    # Lesen setzt kein \Seen
    c = raw_imap()
    c.select("INBOX", readonly=True)
    _, data = c.search(None, "SEEN")
    c.logout()
    assert data[0] == b""


def test_mark_read_unread_and_move(auth, account):
    uid = _uid_of(auth, account, "Weekly digest")
    r = auth.post(f"/api/mail/{account['id']}/flags", json={"folder": "INBOX", "ids": [uid], "seen": True})
    assert r.status_code == 200
    items = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "page_size": 100}).json()["items"]
    assert next(i for i in items if i["id"] == uid)["seen"] is True
    r = auth.post(f"/api/mail/{account['id']}/move", json={"folder": "INBOX", "ids": [uid], "target": "Archiv"})
    assert r.status_code == 200 and r.json()["moved"] == 1
    assert count("INBOX") == INBOX_TOTAL - 1 and count("Archiv") == 2
    bad = auth.post(f"/api/mail/{account['id']}/move", json={"folder": "INBOX", "ids": ["1"], "target": "Gibt\"Es Nicht"})
    assert bad.status_code in (400, 502)


def test_server_side_search(auth, account):
    r = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "q": "Dropbox"}).json()
    assert r["total"] == 2 and all("Dropbox" in i["from_name"] for i in r["items"])
    umlaut = auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "q": "Bäckerei"}).json()
    assert umlaut["total"] == 1
    assert auth.get(f"/api/mail/{account['id']}/messages", params={"folder": "INBOX", "q": "a\r\nX"}).status_code == 400
