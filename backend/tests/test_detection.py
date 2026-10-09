"""Erkennung von Registrierungs-Mails, Kopfzeilen-Parsing und Dienst-Zuordnung."""
from __future__ import annotations

import pytest

from app.detection.classifier import classify, combine, quality_label
from app.detection.headers import clean_text, from_mapping, parse_raw
from app.detection.resolver import identify, registrable_domain
from app.jdm.catalog import get_catalog


def h(subject, sender="noreply@github.com", unsub=False):
    d = {"from": f"Absender <{sender}>", "subject": subject, "date": "Tue, 12 Mar 2019 10:00:00 +0000"}
    if unsub:
        d["list-unsubscribe"] = "<mailto:u@x>"
    return from_mapping(d)


@pytest.mark.parametrize("subject,category", [
    ("Welcome to GitHub!", "welcome"),
    ("Willkommen bei Spotify", "welcome"),
    ("Bienvenue sur Deezer", "welcome"),
    ("Thanks for signing up for Notion", "welcome"),
    ("Dein Konto wurde erstellt", "welcome"),
    ("Please confirm your email address", "verification"),
    ("Bitte bestätige deine E-Mail-Adresse", "verification"),
    ("E-Mail-Adresse bestätigen", "verification"),
    ("Activate your account", "verification"),
    ("Registrierung erfolgreich abgeschlossen", "registration"),
    ("Ihre Adobe ID wurde erstellt", "registration"),
    ("Your Apple ID has been created", "registration"),
    ("You have successfully registered", "registration"),
    ("Your account has been deleted", "deletion"),
    ("Dein Konto wurde gelöscht", "deletion"),
    ("Bestätigung der Kontolöschung", "deletion"),
    ("Passwort zurücksetzen", "security"),
    ("Neue Anmeldung bei deinem Konto", "security"),
    ("Dein Abo wurde verlängert", "subscription"),
    ("Ihre Bestellung #123456 wurde versendet", "order"),
    ("Ihre Rechnung für März", "order"),
])
def test_classifier_categories(subject, category):
    c = classify(h(subject))
    assert c is not None and c.category == category, (subject, c)


@pytest.mark.parametrize("subject", [
    "Unser Newsletter im Oktober",
    "Re: Treffen am Freitag",
    "50 % Rabatt nur heute",
    "",
])
def test_unrelated_mail_is_only_weak_contact_signal(subject):
    c = classify(h(subject))
    assert c.category == "contact" and c.score <= 0.18


def test_every_mail_counts_but_personal_senders_weaker():
    auto = classify(h("Hallo", sender="noreply@shop.example"))
    person = classify(h("Hallo", sender="maria@firma.example"))
    assert auto.category == person.category == "contact" and person.score < auto.score


def test_body_text_detects_account_when_subject_does_not():
    """Beispiel Render: Betreff ohne Hinweis, im Text 'Thanks for joining us!'."""
    mail = from_mapping({"from": "Stephen from Render <hello@render.com>", "subject": "Ready to ship with Render?",
                         "list-unsubscribe": "<mailto:u@render.com>"})
    assert classify(mail).category == "newsletter"
    c = classify(mail, "Hi Adrian, Thanks for joining us! Let's get you up and running quickly. Unsubscribe")
    assert c.category == "welcome" and c.score >= 0.45
    assert "Text: Willkommen" in c.reasons and "Text: Newsletter" in c.reasons


def test_subject_match_beats_body_match():
    subj = classify(h("Welcome to Example"))
    body = classify(h("Hallo"), "Welcome to Example")
    assert subj.score > body.score


def test_newsletter_welcome_penalized():
    plain = classify(h("Welcome to our newsletter"))
    news = classify(h("Welcome to our newsletter", unsub=True))
    assert news.score < plain.score


def test_account_sender_boost():
    a = classify(h("Welcome to Example", sender="noreply@example.com"))
    b = classify(h("Welcome to Example", sender="peter@example.com"))
    assert a.score > b.score


def test_combine_and_quality():
    assert combine([]) == 0.0
    assert combine([0.6]) == 0.6
    assert combine([0.6, 0.6]) == pytest.approx(0.84)
    assert combine([0.99, 0.99, 0.99]) <= 0.99
    assert quality_label(0.9) == "hoch" and quality_label(0.7) == "mittel" and quality_label(0.3) == "niedrig"


def test_encoded_headers_and_sanitizing():
    raw = (b"From: =?UTF-8?B?U3BvdGlmeQ==?= <no-reply@spotify.com>\r\n"
           b"Subject: =?UTF-8?Q?Willkommen_bei_Spotify_=E2=80=AE_txt?=\r\n"
           b"Date: Tue, 04 Aug 2020 10:00:00 +0200\r\n\r\n")
    m = parse_raw(raw)
    assert m.from_name == "Spotify" and m.from_domain == "spotify.com"
    assert "‮" not in m.subject and m.subject.startswith("Willkommen bei Spotify")
    assert m.date.year == 2020


def test_raw_utf8_and_latin1_headers():
    utf8 = "From: x@spotify.com\r\nSubject: Bitte bestätige deine E-Mail-Adresse\r\n\r\n".encode("utf-8")
    latin = "From: x@shop.example\r\nSubject: Bestätigung\r\n\r\n".encode("latin-1")
    assert parse_raw(utf8).subject == "Bitte bestätige deine E-Mail-Adresse"
    assert parse_raw(latin).subject == "Bestätigung"


def test_malformed_headers_do_not_crash():
    m = parse_raw(b"From: <<<>>>\r\nSubject: \x00\x01kaputt\r\nDate: gestern\r\n\r\n")
    assert m.from_domain == "" and m.date is None and "\x00" not in m.subject
    assert classify(m) is None


def test_clean_text_limits():
    assert len(clean_text("a" * 1000)) == 300
    assert clean_text("a\r\nb\tc") == "a b c"


def test_registrable_domain():
    assert registrable_domain("mail.notifications.github.com") == "github.com"
    assert registrable_domain("shop.example.co.uk") == "example.co.uk"
    assert registrable_domain("x") == ""


def test_identify_uses_jdm_and_merges_domains():
    cat = get_catalog()
    a = identify("noreply.github.com", cat)
    b = identify("github.blog", cat)
    assert a.key == b.key == "jdm:GitHub" and a.jdm_name == "GitHub"


def test_identify_unknown_domain_has_no_jdm():
    ident = identify("newsletter.baeckerei-muster.at", get_catalog())
    assert ident.key == "domain:baeckerei-muster.at" and ident.jdm_name is None


def test_identify_ignores_freemail():
    assert identify("gmail.com", get_catalog()) is None
    assert identify("gmx.at", get_catalog()) is None


@pytest.mark.parametrize("host,name,expected", [
    ("makenotion.com", "Notion Team", "Notion"),          # Domain nicht im Katalog, Absendername schon
    ("makenotion.com", "", "Notion"),                     # Präfix "make" + Markenname
    ("render.com", "Stephen from Render", "Render"),      # direkte Domain
    ("mail.render.com", "", "Render"),                    # Subdomain
    ("e.udemy.com", "Udemy", "Udemy"),
])
def test_jdm_matching_by_domain_and_brand(host, name, expected):
    ident = identify(host, get_catalog(), name)
    assert ident.jdm_name == expected


def test_brand_matching_does_not_guess_short_or_unknown_names():
    assert identify("box-beispiel.at", get_catalog(), "Box").jdm_name is None
    assert identify("baeckerei-muster.at", get_catalog(), "Bäckerei Muster").jdm_name is None
