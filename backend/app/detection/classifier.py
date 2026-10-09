"""Regelbasierte Erkennung von Konto-Hinweisen in jeder einzelnen Mail.

Geprüft werden Absender, Betreff und – falls vorhanden – der Anfang des Textes.
Jede Mail eines Dienstes ist mindestens ein schwacher Hinweis ("Mail erhalten"): Wer von einem
Dienst Mails bekommt, hat dort möglicherweise ein Konto.

Kategorien (Basiswert = Wahrscheinlichkeit, dass ein Konto existiert, wenn der Betreff passt):
- deletion      0.75  Konto gelöscht / geschlossen
- verification  0.62  E-Mail-Adresse bestätigen / Konto aktivieren
- welcome       0.60  Willkommensnachricht
- registration  0.58  Registrierung / Konto erstellt
- security      0.55  Passwort zurücksetzen, neue Anmeldung, Einmalcode
- subscription  0.50  Abo, Testphase, Zahlung
- order         0.45  Bestellung, Rechnung, Buchung
- account       0.40  allgemeiner Konto-Hinweis ("dein Konto")
- newsletter    0.28  Newsletter (Abmelde-Link)
- contact       0.10–0.18  nur Mail erhalten
Treffer nur im Text zählen 0.1 weniger als im Betreff.
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
    ("security", 0.55, _P(
        r"\b(password reset|reset your password|passwort zurücksetzen|passwort vergessen|neues passwort|change your password)\b",
        r"\b(new (sign-?in|login)|neue anmeldung|anmeldung von einem neuen gerät|security alert|sicherheitswarnung|sign-?in attempt)\b",
        r"\b(verification code|bestätigungscode|sicherheitscode|anmeldecode|login code|einmalcode|one-?time (code|password)|2fa|two-factor|zwei-faktor)\b",
        r"\b(magic link|login link|anmeldelink)\b",
    )),
    ("subscription", 0.5, _P(
        r"\b(your|dein|ihr) (subscription|abo|abonnement|plan|membership|mitgliedschaft)\b",
        r"\b(free trial|trial (ends|expires|started)|testphase|probezeitraum|probeabo)\b",
        r"\b(subscription|abonnement|abo|mitgliedschaft) (renewed|verlängert|bestätigt|confirmed|cancel+ed|gekündigt|ends|endet)\b",
        r"\b(payment (failed|received)|zahlung (fehlgeschlagen|erhalten)|billing)\b",
    )),
    ("order", 0.45, _P(
        r"\b(order|bestellung|auftrag|commande|pedido|ordine)\b.{0,25}\b(confirm\w*|bestätig\w*|received|eingegangen|shipped|versandt|versendet|unterwegs|#?\d{4,})",
        r"\b(your|deine|ihre) (order|bestellung|rechnung|invoice|receipt|quittung|buchung|booking|reservation|reservierung)\b",
        r"\b(bestellnummer|order number|order no\.?|rechnungsnummer|invoice number|buchungsnummer)\b",
        r"\b(receipt|quittung|kaufbeleg|zahlungsbestätigung|payment confirmation)\b",
    )),
    ("account", 0.4, _P(
        r"\b(your account|dein konto|ihr konto|dein account|ihr account|kundenkonto|benutzerkonto|my account|mein konto)\b",
        r"\b(log ?in|sign ?in|anmelden|einloggen) (to|bei|in) (your|dein|ihr)\b",
        r"\b(profile|profil) (updated|aktualisiert|completed|vervollständig\w*)\b",
    )),
]

# Nur im Text gesuchte Hinweise (zusätzlich zu den obigen Regeln)
BODY_ONLY: list[tuple[str, float, re.Pattern]] = [
    ("newsletter", 0.28, _P(
        r"\b(unsubscribe|abmelden vom newsletter|newsletter abbestellen|abbestellen|manage (your )?(email )?preferences|e-mail-einstellungen|désabonner|darse de baja)\b",
        r"\byou('re| are) receiving this (email|message) because\b",
        r"\bsie erhalten diese (e-mail|nachricht)\b",
        r"\bdu erhältst diese (e-mail|nachricht)\b",
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


LABELS = {
    "deletion": "Kontolöschung", "verification": "Bestätigung", "welcome": "Willkommen",
    "registration": "Registrierung", "security": "Sicherheit/Anmeldung", "subscription": "Abo/Zahlung",
    "order": "Bestellung/Rechnung", "account": "Konto-Hinweis", "newsletter": "Newsletter",
    "contact": "Mail erhalten", "notice": "Hinweis",
}
# Kategorien, die eine Registrierung/Kontoänderung belegen (für "nur Registrierungs-Mails löschen")
REGISTRATION_CATEGORIES = ("welcome", "verification", "registration", "deletion")
BODY_PENALTY = 0.1


@dataclass(frozen=True)
class Classification:
    category: str
    score: float
    reasons: tuple[str, ...] = ()


def _adjust(category: str, base: float, h: MailHeaders, automated: bool) -> float:
    score = base
    if automated and category not in ("contact", "newsletter"):
        score += 0.06
    if h.auto_submitted:
        score += 0.03
    if h.list_unsubscribe and category in ("welcome", "account"):
        # Newsletter-Kennzeichen: Willkommens-Mails von Newslettern sind häufig keine Konten
        score -= 0.06
    return max(0.05, min(score, 0.95))


def is_automated(h: MailHeaders) -> bool:
    local = h.from_addr.split("@", 1)[0]
    return bool(_ACCOUNT_SENDER.match(local)) or h.auto_submitted


def classify(h: MailHeaders, text: str = "") -> Classification | None:
    """Bewertet eine einzelne Mail. None nur, wenn kein Absender erkennbar ist."""
    if not h.from_domain:
        return None
    automated = is_automated(h)
    hits: list[tuple[float, str, str]] = []  # (score, category, reason)
    for category, base, pattern in RULES:
        if h.subject and pattern.search(h.subject):
            hits.append((_adjust(category, base, h, automated), category, f"Betreff: {LABELS[category]}"))
        elif text and pattern.search(text):
            hits.append((_adjust(category, base - BODY_PENALTY, h, automated), category, f"Text: {LABELS[category]}"))
    for category, base, pattern in BODY_ONLY:
        if text and pattern.search(text):
            hits.append((base, category, f"Text: {LABELS[category]}"))
    if h.list_unsubscribe and not any(c == "newsletter" for _, c, _ in hits):
        hits.append((0.28, "newsletter", "Newsletter-Kennzeichen (Abmelde-Link)"))
    contact = 0.18 if automated else 0.1
    hits.append((contact, "contact", "Mail von diesem Absender"))

    hits.sort(key=lambda x: -x[0])
    best_score, best_cat, _ = hits[0]
    reasons = []
    for _, _, reason in hits:
        if reason not in reasons:
            reasons.append(reason)
    if automated:
        reasons.append("Absender: automatisiert")
    return Classification(best_cat, round(best_score, 3), tuple(reasons[:6]))


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
