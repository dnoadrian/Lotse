"""Befüllt das lokale Dovecot-TESTPOSTFACH mit erfundenen Beispielmails (für E2E-Tests und Screenshots).

Achtung: leert vorher alle Ordner des Testpostfachs. Niemals gegen ein echtes Postfach ausführen –
das Skript verweigert jeden anderen Host als imap.quitly.test.

Aufruf: python3 -I scripts/test-imap/seed.py
"""
from __future__ import annotations

import imaplib
import ssl
import sys
import time
from datetime import datetime, timedelta, timezone
from email.header import Header
from email.utils import format_datetime

HOST, PORT = "imap.quitly.test", 10993
USER, PASS = "test@quitly.test", "test-passwort-123"
CA = "/tmp/quitly-test-imap/ca.pem"

INBOX = [
    ("GitHub", "noreply@github.com", "Welcome to GitHub, test!", 2400),
    ("GitHub", "noreply@github.com", "[GitHub] Please verify your email address", 2400),
    ("GitHub", "notifications@github.com", "[GitHub] A new SSH key was added", 300),
    ("Spotify", "no-reply@spotify.com", "Bitte bestätige deine E-Mail-Adresse", 1800),
    ("Spotify", "no-reply@spotify.com", "Willkommen bei Spotify", 1800),
    ("Dropbox", "no-reply@dropbox.com", "Willkommen bei Dropbox", 3000),
    ("Dropbox", "no-reply@dropbox.com", "Dein Dropbox-Konto wurde gelöscht", 20),
    ("LinkedIn", "security-noreply@linkedin.com", "Bitte bestätigen Sie Ihre E-Mail-Adresse", 3500),
    ("LinkedIn", "messages-noreply@linkedin.com", "Willkommen bei LinkedIn", 3500),
    ("Duolingo", "hello@duolingo.com", "Willkommen bei Duolingo!", 900),
    ("Strava", "no-reply@strava.com", "Welcome to Strava", 700),
    ("Twitch", "no-reply@twitch.tv", "Verify your Twitch account", 1200),
    ("Netflix", "info@account.netflix.com", "Willkommen bei Netflix", 1600),
    ("Airbnb", "automated@airbnb.com", "Bitte bestätige deine E-Mail-Adresse", 1400),
    ("eBay", "ebay@ebay.com", "Willkommen bei eBay", 2900),
    ("Zalando", "info@service-mail.zalando.de", "Willkommen bei Zalando", 2000),
    ("Canva", "start@engage.canva.com", "Welcome to Canva", 500),
    ("Notion", "team@makenotion.com", "Welcome to Notion", 450),
    ("Slack", "feedback@slack.com", "Confirm your email address on Slack", 1100),
    ("Trello", "do-not-reply@trello.com", "Welcome to Trello!", 1300),
    ("Pinterest", "pinbot@account.pinterest.com", "Willkommen bei Pinterest", 2600),
    ("Reddit", "noreply@reddit.com", "Verify your Reddit email address", 1000),
    ("Discord", "noreply@discord.com", "Verify Email Address for Discord", 800),
    ("Booking.com", "noreply@booking.com", "Ihr Konto wurde erstellt", 1700),
    ("Bäckerei Muster", "bestellung@baeckerei-muster.at", "Willkommen in unserem Webshop", 400),
    ("Fitnessstudio Beispiel", "noreply@fitness-beispiel.at", "Dein Konto ist bereit", 250),
    ("Kulturverein", "news@kulturverein-beispiel.at", "Programm im Oktober", 3),
    ("Kulturverein", "news@kulturverein-beispiel.at", "Programm im September", 33),
    ("Freundin", "freundin@gmail.com", "Fotos vom Wochenende", 6),
    ("Kollege", "kollege@gmx.at", "Re: Termin nächste Woche", 2),
]
ARCHIVE = [
    ("Adobe", "mail@mail.adobe.com", "Ihre Adobe ID wurde erstellt", 2500),
    ("Udemy", "no-reply@e.udemy.com", "Welcome to Udemy!", 2100),
    ("Steam", "noreply@steampowered.com", "Neues Steam-Konto – E-Mail-Adresse bestätigen", 3800),
]
NEWSLETTER = [
    ("Wetterdienst", "news@wetter-beispiel.at", f"Wochenausblick KW {i}", 7 * i) for i in range(1, 8)
]


def message(name: str, addr: str, subject: str, days: int) -> bytes:
    date = format_datetime(datetime.now(timezone.utc) - timedelta(days=days))
    sender = f"{Header(name, 'utf-8').encode()} <{addr}>"
    return (f"From: {sender}\r\nTo: {USER}\r\nSubject: {Header(subject, 'utf-8').encode()}\r\nDate: {date}\r\n"
            f"Message-ID: <{time.time_ns()}@seed.quitly.test>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"
            f"Erfundene Testnachricht.\r\n").encode()


def main() -> int:
    if HOST != "imap.quitly.test":
        print("Verweigert: nur für das Testpostfach.")
        return 1
    c = imaplib.IMAP4_SSL(HOST, PORT, ssl_context=ssl.create_default_context(cafile=CA))
    c.login(USER, PASS)
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
    c.create('"Newsletter"')
    for folder, items in (("INBOX", INBOX), ('"Archiv"', ARCHIVE), ('"Newsletter"', NEWSLETTER)):
        for item in items:
            c.append(folder, None, None, message(*item))
    c.logout()
    print(f"{len(INBOX) + len(ARCHIVE) + len(NEWSLETTER)} Testnachrichten angelegt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
