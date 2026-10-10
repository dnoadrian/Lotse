# Quitly

**Quitly findet deine Online-Konten anhand deiner E-Mails und hilft dir, sie zu löschen.**

Quitly verbindet sich per IMAP mit deinem Postfach (z. B. Mailcow, Dovecot oder jeder andere IMAP-Server),
erkennt Registrierungs-, Willkommens-, Bestätigungs-, Lösch- und Adresswechsel-Mails, fasst gefundene Dienste zusammen
und ordnet sie den offiziellen Löschseiten aus dem [JustDeleteMe](https://github.com/jdm-contrib/jdm)-Datensatz zu.
Außerdem kannst du einzelne, ausgewählte oder alle E-Mails eines Ordners löschen – mit Bestätigung
und anschließender Überprüfung auf dem Server.

Selbst gehostet auf deinem eigenen Linux-Server mit Docker Compose und HTTPS.

## Funktionen

- **Konten finden:** Jede Mail in allen Ordnern (auch Spam und Papierkorb) wird geprüft – Kopfzeilen und der
  Anfang des Textes, nur im Arbeitsspeicher, nie Anhänge. Erkennung in Deutsch, Englisch und weiteren Sprachen;
  in der Liste stehen nur **sichere** Konten. Erkennungsqualität in Prozent mit nachvollziehbarer Herleitung.
- **Gedächtnis:** Einmal erkannte Konten bleiben bekannt, auch wenn du die Mails später löschst.
- **Lebenszyklus:** Löschanfrage erkannt → „angefragt“; Löschung oder Wechsel der E-Mail-Adresse weg von diesem
  Postfach → „gelöscht“. Kommt nach einer Löschanfrage 14 Tage lang keine Mail mehr, fragt Quitly nach.
- **Mails lesen:** Erkannte Mails direkt aus der Kontoansicht öffnen; HTML-Mails laufen bereinigt in einer
  abgeschotteten Ansicht ohne Skripte, externe Bilder (Tracking) erst auf Wunsch. Gelesen/ungelesen,
  verschieben, abmelden, Suche im ganzen Ordner.
- **Favicons:** Symbole der Dienste lädt der Server (geprüft, zwischengespeichert) – dein Browser fragt keine
  fremden Seiten an.
- **JustDeleteMe:** Lösch-Link, Schwierigkeit, Anleitung und ggf. Lösch-E-Mail-Adresse direkt aus dem
  Datensatz (2.665 Dienste, Stand siehe `backend/app/data/jdm/VERSION.json`). Gibt es keinen Eintrag,
  zeigt Quitly keinen Link an – es werden keine Links erfunden.
- **Dashboard:** Suche, Filter (Status, Qualität, mit/ohne Löschlink), Checkboxen, Massenaktionen,
  manueller Löschstatus (offen, angefragt, gelöscht, behalten), CSV-Export.
- **E-Mail-Verwaltung:** Einzelne, ausgewählte, alle Mails eines Ordners oder nur erkannte
  Registrierungs-Mails löschen; Papierkorb oder endgültig (IMAP); Bestätigung mit „LÖSCHEN“;
  Prüfung, ob der Ordner sich zwischenzeitlich geändert hat; überprüftes Ergebnis mit Fehlerliste.
- **Sicherheit:** Argon2id, optionale Zwei-Faktor-Anmeldung (TOTP), serverseitige Sitzungen, CSRF-Schutz,
  Rate-Limits, AES-256-GCM für gespeicherte Zugangsdaten, SSRF-Schutz, strikte CSP, Audit-Protokoll.
  Details und Bedrohungsanalyse: [docs/SECURITY.md](docs/SECURITY.md).
- **Design:** helles (Standard) und dunkles Design, responsiv bis Smartphone-Breite.

## Start per Doppelklick (lokal)

1. [Docker Desktop](https://www.docker.com/products/docker-desktop/) installieren und einmal öffnen.
2. Dieses Projekt herunterladen (grüner Knopf „Code“ → „Download ZIP“) und entpacken.
3. Doppelklick auf
   - **Windows:** `Quitly starten.bat`
   - **macOS:** `Quitly starten.command` (beim ersten Mal: Rechtsklick → „Öffnen“)
   - **Linux:** `quitly-starten.sh`

Beim ersten Start richtet die Datei alles ein: Zufallsschlüssel, `quitly.at` zeigt auf deinen Rechner,
die lokale HTTPS-Zertifizierungsstelle wird vertraut (dafür fragt das System einmal nach deinem Passwort)
und du legst deinen Benutzer an. Danach öffnet sich `https://quitly.at` im Browser.
Beenden mit `Quitly beenden.bat` bzw. `Quitly beenden.command`.

Hinweis: `quitly.at` zeigt dann **nur auf deinem Rechner** auf Quitly (Eintrag in der hosts-Datei).
Andere Namen gehen auch: Umgebungsvariable `QUITLY_LOCAL_DOMAIN` vor dem Start setzen.

## Schnellstart (Server)

```bash
./scripts/generate-env.sh quitly.example.org admin@example.org   # erzeugt .env mit Zufallsschlüsseln
docker compose up -d --build
docker compose exec backend python -m app.cli create-user dein-name
```

Danach `https://quitly.example.org` öffnen.

**Nur lokal auf dem eigenen Rechner** (ohne Domain, mit lokaler HTTPS-CA):

```bash
./scripts/generate-env.sh localhost internal
docker compose up -d --build
docker compose exec backend python -m app.cli create-user dein-name
```

Dann `https://localhost` öffnen (die Browser-Warnung verschwindet, wenn du Caddys lokale CA vertraust, siehe
[docs/INSTALL.md](docs/INSTALL.md)). Ausführlich: [docs/INSTALL.md](docs/INSTALL.md).

## Aufbau

| Teil | Technik | Ordner |
|---|---|---|
| Frontend | React, TypeScript, Vite | `frontend/` |
| Backend | Python 3.12, FastAPI, SQLAlchemy | `backend/` |
| Datenbank | PostgreSQL 16 | Docker-Volume `db_data` |
| HTTPS / Webserver | Caddy 2 (Let's Encrypt oder interne CA) | `deploy/caddy/` |

API-Beschreibung: [docs/API.md](docs/API.md) · Tests und Prüfprotokoll: [docs/TESTING.md](docs/TESTING.md)

## Entwicklung

```bash
# Backend
cd backend && python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
pytest                                   # Unit-, API- und Sicherheitstests
sudo ../scripts/test-imap/start.sh       # optional: echter IMAPS-Testserver (Dovecot) für Integrationstests
pytest                                   # nun inkl. IMAP-Integrationstests

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173, /api → 127.0.0.1:8000
```

Zum lokalen Starten des Backends ohne HTTPS (nur Entwicklung):

```bash
QUITLY_ENVIRONMENT=development QUITLY_COOKIE_SECURE=false QUITLY_PUBLIC_URL=http://localhost:5173 \
QUITLY_DATABASE_URL=sqlite:///./dev.db QUITLY_SECRET_KEY=$(openssl rand -base64 32) \
QUITLY_ENCRYPTION_KEY=$(openssl rand -base64 32) uvicorn app.main:create_app --factory --port 8000
```

## Lizenz und Daten

Der JustDeleteMe-Datensatz steht unter der MIT-Lizenz (© Robb Lewis, The JDM Contrib Team & Mitwirkende),
siehe `backend/app/data/jdm/LICENSE`.
