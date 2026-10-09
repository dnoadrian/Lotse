# Tests und Prüfprotokoll

Stand: 09.10.2026. Alle Ergebnisse wurden tatsächlich ausgeführt; nichts davon ist simuliert,
außer wo ausdrücklich angegeben (Gmail-API).

## Ergebnisse

| Bereich | Werkzeug | Ergebnis |
|---|---|---|
| Backend: Sicherheit, API, Erkennung, JDM, SSRF | pytest (SQLite) | **157 bestanden** |
| Dieselben Tests gegen PostgreSQL 16 | pytest mit `LOTSE_TEST_DATABASE_URL` | **157 bestanden** |
| davon IMAP-Integration gegen echten Dovecot-IMAPS-Server | pytest | **26 bestanden** |
| davon Gmail gegen simulierte Google-API | pytest + respx | **13 bestanden** |
| Frontend: API-Client, Status-/Lösch-Logik | vitest | **43 bestanden** |
| Frontend: Typprüfung | `tsc --noEmit` | fehlerfrei |
| Ende-zu-Ende im Browser gegen den Docker-Stack (HTTPS, Caddy, PostgreSQL, Dovecot) | Playwright/Chromium | **5 bestanden**, 3 Läufe hintereinander stabil |
| Statische Sicherheitsanalyse Backend | bandit | **0 Befunde** (nach Behebung, siehe SECURITY.md) |
| Bekannte Schwachstellen Python-Abhängigkeiten | pip-audit | **0** |
| Bekannte Schwachstellen npm (Frontend, E2E) | npm audit | **0** |
| Container-Härtung | manuell | Backend läuft als UID 10001, Dateisystem schreibgeschützt, keine Capabilities |
| Startskript (Linux) | manuell | Stack startet, lokale CA wird vertraut, `https://lotse.at` ohne Warnung |

## Was die Tests abdecken

**Integrationen**
- IMAP gegen echten Dovecot mit eigener Test-CA: Verbindung, falsches Passwort, nicht vertrauenswürdiges
  Zertifikat, falscher Hostname, Loopback ohne Allowlist, Ordner, Nachrichtenliste, Lesen setzt kein `\Seen`.
- Gmail (simuliert): OAuth mit PKCE (Prüfung der Challenge), State einmalig und an Sitzung gebunden,
  Abbruch, verschlüsselte Token-Speicherung, Scan, Labels, Papierkorb mit Überprüfung, Teilfehler,
  Ablehnung endgültigen Löschens, Widerruf beim Entfernen.

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
LOTSE_TEST_DATABASE_URL=postgresql+psycopg://user:pw@127.0.0.1/lotse_test pytest   # optional PostgreSQL

# Frontend
cd frontend && npm ci && npm run typecheck && npm test

# Ende-zu-Ende (Stack muss laufen, Testserver auf allen Schnittstellen)
sudo LOTSE_TEST_IMAP_LISTEN='*' scripts/test-imap/start.sh
docker compose -f docker-compose.yml -f scripts/test-imap/compose.e2e.yml up -d --build
docker compose exec backend python -m app.cli create-user adrian
cd e2e && npm ci && LOTSE_E2E_URL=https://lotse.at LOTSE_E2E_PASS=… npx playwright test
```

Destruktive Tests laufen ausschließlich gegen das Testpostfach `test@lotse.test` auf `imap.lotse.test`;
`scripts/test-imap/seed.py` verweigert jeden anderen Host.

## Nicht automatisch getestet

- **Echtes Gmail:** Es liegen keine Google-OAuth-Zugangsdaten vor. Getestet ist das Protokollverhalten gegen
  eine simulierte API. Für einen echten Test: OAuth-Client nach [GMAIL.md](GMAIL.md) einrichten.
- **Echter Mailcow-Server:** Getestet gegen Dovecot, den IMAP-Server, den Mailcow selbst verwendet.
- **Windows- und macOS-Startdatei:** Unter Linux ausgeführt und getestet; die Windows- (PowerShell) und
  macOS-Variante folgen derselben Logik, konnten hier aber nicht auf echten Geräten laufen.
- **Let's Encrypt:** braucht eine öffentlich erreichbare Domain; lokal getestet mit Caddys interner CA.

## Screenshots

`docs/screenshots/` – erzeugt durch den E2E-Test: Anmeldung, Konten (hell/dunkel), Verbindungen,
E-Mails, Löschdialog sowie Mobilansichten.
