"""Regelbasierte Erkennung von Konto-Mails anhand von Betreff und Absender.

Kategorien:
- welcome       Willkommensnachricht nach Registrierung
- verification  E-Mail-Adresse bestätigen / Konto aktivieren
- registration  Registrierung / Anmeldung abgeschlossen
- deletion      Konto gelöscht / geschlossen
- notice        Konto-Hinweis (Passwort, neue Anmeldung) – schwaches Signal

Die Regeln sind absichtlich konservativ: lieber ein Konto übersehen als Newsletter
fälschlich als Konto zu melden. Die Qualität wird als Wahrscheinlichkeit 0–1 ausgegeben.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .headers import MailHeaders

_P = lambda *xs: re.compile("|".join(xs), re.IGNORECASE)  # noqa: E731

RULES: list[tuple[str, float, re.Pattern]] = [
    ("deletion", 0.75, _P(
        r"\b(account|konto|profil|profile)\b.{0,40}\b(deleted|gelöscht|geloescht|closed|geschlossen|removed|entfernt|deactivated|deaktiviert)",
        r"\b(deleted|closed|removed)\b.{0,20}\byour (account|profile)\b",
        r"\b(kontolöschung|account deletion|löschung (deines|ihres|des) (kontos|accounts|profils))\b",
        r"\bwe('| a)re sorry to see you go\b",
        r"\bschade, dass du (gehst|uns verlässt)\b",
        r"\b(suppression de (votre|ton) compte|compte supprimé|cuenta eliminada|account eliminato)\b",
    )),
    ("verification", 0.62, _P(
        r"\b(confirm|verify|validate|activate)\b.{0,25}\b(e-?mail|email address|account|registration|sign ?up)\b",
        r"\b(bestätig\w*|verifizier\w*|aktivier\w*)\b.{0,30}\b(e-?mail|e-mail-adresse|konto|account|registrierung|anmeldung)\b",
        r"\b(e-?mail|konto|account)\b.{0,25}\b(bestätigen|verifizieren|aktivieren)\b",
        r"\b(confirmez|vérifiez|confirma|verifica|conferma)\b.{0,25}\b(e-?mail|adresse|cuenta|compte|account|correo|indirizzo)\b",
        r"\bdouble opt-?in\b",
        r"\bplease confirm your (subscription|account)\b",
    )),
    ("welcome", 0.6, _P(
        r"^\s*(\W*)?(welcome|willkommen|bienvenue|bienvenido|bienvenida|benvenut[oa]|welkom|bem-vindo|witamy|välkommen|velkommen)\b",
        r"\b(welcome|willkommen|bienvenue|bienvenido|benvenuto|welkom)\b.{0,10}\b(to|bei|zu|auf|in|à|a|en|bij|an bord)\b",
        r"\bthanks? (you )?for (signing up|joining|registering|creating)\b",
        r"\b(danke|vielen dank)\b.{0,30}\b(registrierung|anmeldung|registriert|angemeldet)\b",
        r"\byour (new )?account (is ready|has been created|was created)\b",
        r"\b(dein|ihr) (neues )?(konto|account|profil) (ist (bereit|eingerichtet|erstellt)|wurde (erstellt|eingerichtet|angelegt))\b",
        r"\bget(ting)? started with\b",
        r"\bmerci (de|pour) (votre|ton) inscription\b",
        r"\bgracias por (registrarte|unirte)\b",
    )),
    ("registration", 0.55, _P(
        r"\b(registration|registrierung|sign-?up|inscription|registro|registrazione)\b.{0,30}\b(complete|successful|erfolgreich|abgeschlossen|confirmed|bestätigt|réussie|completad[oa])\b",
        r"\b(account|konto|benutzerkonto|kundenkonto) (created|erstellt|angelegt|eröffnet|eingerichtet)\b",
        r"\b(id|konto|account|profil|benutzerkonto|kundenkonto)\b.{0,15}\bwurde (erfolgreich )?(erstellt|angelegt|eingerichtet|eröffnet)\b",
        r"\b(id|account|profile)\b.{0,15}\b(has been|was) (successfully )?created\b",
        r"\b(new account|neues (kunden)?konto)\b",
        r"\byou('ve| have) (successfully )?(registered|signed up|created an account)\b",
        r"\bdu hast dich (erfolgreich )?(registriert|angemeldet)\b",
        r"\bihre registrierung\b",
    )),
    ("notice", 0.32, _P(
        r"\b(password reset|reset your password|passwort zurücksetzen|passwort vergessen|neues passwort)\b",
        r"\b(new (sign-?in|login)|neue anmeldung|anmeldung von einem neuen gerät|security alert|sicherheitswarnung)\b",
        r"\b(your account|dein konto|ihr konto|dein account|ihr account)\b",
        r"\b(verification code|bestätigungscode|sicherheitscode|anmeldecode|login code)\b",
    )),
]

_ACCOUNT_SENDER = re.compile(
    r"^(no-?reply|do-?not-?reply|donotreply|accounts?|account-security|security|support|hello|hi|team|welcome|info|notifications?|service|kundenservice|registration|signup|verify|confirm)([+._-].*)?$",
    re.IGNORECASE,
)

# Persönliche Freemail-Domains erzeugen keine "Dienste"
FREEMAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com", "yahoo.de",
    "icloud.com", "me.com", "mac.com", "gmx.de", "gmx.at", "gmx.net", "gmx.ch", "web.de", "aon.at", "a1.net",
    "t-online.de", "freenet.de", "posteo.de", "posteo.net", "mailbox.org", "protonmail.com", "proton.me",
    "pm.me", "tutanota.com", "tuta.io", "yandex.ru", "mail.ru", "aol.com", "zoho.com", "chello.at", "kabsi.at",
}


@dataclass(frozen=True)
class Classification:
    category: str
    score: float


def classify(h: MailHeaders) -> Classification | None:
    """Gibt die stärkste Kategorie zurück oder None, wenn die Mail kein Konto-Signal trägt."""
    if not h.from_domain or not h.subject:
        return None
    best: Classification | None = None
    for category, base, pattern in RULES:
        if pattern.search(h.subject):
            score = base
            local = h.from_addr.split("@", 1)[0]
            if _ACCOUNT_SENDER.match(local):
                score += 0.08
            if h.auto_submitted:
                score += 0.04
            if h.list_unsubscribe and category in ("welcome", "notice"):
                # Newsletter-Kennzeichen: Willkommens-Mails von Newslettern sind häufig keine Konten
                score -= 0.12
            score = max(0.05, min(score, 0.95))
            if best is None or score > best.score:
                best = Classification(category, round(score, 3))
    return best


def combine(scores: list[float]) -> float:
    """Mehrere unabhängige Hinweise kombinieren: 1 - Π(1 - s)."""
    p = 1.0
    for s in scores:
        p *= 1.0 - max(0.0, min(s, 0.99))
    return round(min(1.0 - p, 0.99), 3)


def quality_label(confidence: float) -> str:
    if confidence >= 0.85:
        return "hoch"
    if confidence >= 0.6:
        return "mittel"
    return "niedrig"
