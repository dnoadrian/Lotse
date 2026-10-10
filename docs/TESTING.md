# Tests und Prüfprotokoll

Stand: 10.10.2026. Alle Ergebnisse wurden tatsächlich ausgeführt; nichts davon ist simuliert.

## Ergebnisse

| Bereich | Werkzeug | Ergebnis |
|---|---|---|
| Backend: Sicherheit, API, Erkennung, Mail-Ansicht, Favicons, JDM, SSRF | pytest (SQLite) | **204 bestanden** |
| Dieselben Tests gegen PostgreSQL 16 | pytest mit `QUITLY_TEST_DATABASE_URL` | **204 bestanden** |
| davon IMAP-Integration gegen echten Dovecot-IMAPS-Server | pytest | **32 bestanden** |
| Frontend: API-Client, Status-/Lösch-Logik, Zuordnungen | vitest | **41 bestanden** |
| Frontend: Typprüfung | `tsc --noEmit` | fehlerfrei |
| Ende-zu-Ende im Browser: Backend mit 2 Workern + PostgreSQL 16 + Dovecot, Render-ähnliche Variablen | Playwright/Chromium | **9 bestanden** (inkl. zwei Postfächer gleichzeitig, Postfach-Filter, Shift-Auswahl) |
| Statische Sicherheitsanalyse Backend | bandit | **1 Hinweis (niedrig)**: bewusstes `try/except/continue` beim Text-Auslesen kaputter Mail-Teile |
| Bekannte Schwachstellen Python-Abhängigkeiten | pip-audit | **0** |
| Bekannte Schwachstellen npm (Frontend, E2E) | npm audit | **0** |
| Container-Härtung, Startskript, Docker-Stack mit Caddy | manuell / Playwright | zuletzt am 09.10.2026 geprüft, seitdem nicht erneut |

## Was die Tests abdecken

**Integrationen**
- IMAP gegen echten Dovecot mit eigener Test-CA: Verbindung, falsches Passwort, nicht vertrauenswürdiges
  Zertifikat, falscher Hostname, Loopback ohne Allowlist, Ordner, Nachrichtenliste, Lesen setzt kein `\Seen`.
- Spam-Ordner wird gescannt (Cloudflare, Discord), Löschanfrage → „angefragt“, Adresswechsel → „gelöscht“,
  Gedächtnis nach dem Löschen der Mails, erkannte Mails je Dienst, Mail lesen (Text, bereinigtes HTML mit
  eigener CSP, Abmelde-Links), gelesen/ungelesen, verschieben, Volltextsuche inkl. Umlaute.

**E-Mail-Erkennung**
- 17 Betreff-Varianten in Deutsch, Englisch, Französisch (Willkommen, Bestätigung, Registrierung,
  Löschung, Hinweis), Negativbeispiele (Rechnung, Newsletter, Antworten), MIME-kodierte und rohe
  UTF-8/Latin-1-Kopfzeilen, kaputte Kopfzeilen, Bidi-/Steuerzeichen, Zusammenführen mehrerer Absender,
  Freemail-Ausschluss, idempotenter Rescan, automatische Löscherkennung.

**Löschfunktionen** (nur Testpostfach)
- Einzeln → Papierkorb, mehrere nur mit „LÖSCHEN“, endgültig nur mit Bestätigung, ganzer Ordner,
  nur Registrierungs-Mails, falsche erwartete Anzahl → 409 ohne Löschung, veraltete UIDVALIDITY → 409,
  bereits gelöschte Nachrichten, IMAP-Injection über Ordnernamen, ungültige UIDs (`1:*`, `-1`, …).

**Sicherheitsmechanismen**
- siehe [SECURITY.md](SECURITY.md), Abschnitt 5.

## Selbst ausführen

```bash
# Backend
cd backend && pip install -r requirements-dev.txt
sudo ../scripts/test-imap/start.sh      # echter IMAPS-Testserver (ohne ihn werden IMAP-Tests übersprungen)
pytest
QUITLY_TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1/quitly_test pytest   # optional PostgreSQL

# Frontend
cd frontend && npm ci && npm run typecheck && npm test

# Ende-zu-Ende (Stack muss laufen, Testserver auf allen Schnittstellen)
sudo QUITLY_TEST_IMAP_LISTEN='*' scripts/test-imap/start.sh
docker compose -f docker-compose.yml -f scripts/test-imap/compose.e2e.yml up -d --build
docker compose exec backend python -m app.cli create-user adrian
cd e2e && npm ci && QUITLY_E2E_URL=https://quitly.at QUITLY_E2E_PASS=… npx playwright test
```

Destruktive Tests laufen ausschließlich gegen das Testpostfach `test@quitly.test` auf `imap.quitly.test`;
`scripts/test-imap/seed.py` verweigert jeden anderen Host.

## Nicht automatisch getestet

- **Echter Mailserver deines Anbieters:** Getestet gegen Dovecot (den IMAP-Server u. a. von Mailcow).
- **Windows- und macOS-Startdatei:** Unter Linux ausgeführt und getestet; die Windows- (PowerShell) und
  macOS-Variante folgen derselben Logik, konnten hier aber nicht auf echten Geräten laufen.
- **Let's Encrypt:** braucht eine öffentlich erreichbare Domain; lokal getestet mit Caddys interner CA.

## Screenshots

`docs/screenshots/` – erzeugt durch den E2E-Test: Anmeldung, Konten (hell/dunkel), Verbindungen,
E-Mails, Löschdialog sowie Mobilansichten.
