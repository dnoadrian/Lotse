# Installation auf dem eigenen Linux-Server

## Voraussetzungen

- Linux-Server mit Docker Engine ≥ 24 und dem Compose-Plugin (`docker compose version`)
- Eine Domain (z. B. `lotse.example.org`), deren DNS-A/AAAA-Eintrag auf den Server zeigt
- Offene Ports 80 und 443 (Let's Encrypt benötigt Port 80 für die Zertifikatsausstellung)
- Für Mailcow: ein App-Passwort mit IMAP-Berechtigung (Mailcow → Mailbox → App-Passwörter)

## 1. Code holen und konfigurieren

```bash
git clone <dieses-repository> lotse && cd lotse
./scripts/generate-env.sh lotse.example.org admin@example.org
# oder: cp .env.example .env && nano .env   (Schlüssel mit openssl rand -base64 32 erzeugen)
```

`generate-env.sh` erzeugt `LOTSE_SECRET_KEY`, `LOTSE_ENCRYPTION_KEY` und `POSTGRES_PASSWORD`
zufällig und setzt die Dateirechte auf 600. **Sichere `LOTSE_ENCRYPTION_KEY` getrennt vom Server-Backup** –
ohne ihn sind gespeicherte Postfach-Zugangsdaten unbrauchbar.

Betrieb nur im LAN ohne öffentliche Domain: `LOTSE_DOMAIN=lotse.lan` und `LOTSE_TLS=internal`.
Caddy erzeugt dann eine eigene CA; deren Wurzelzertifikat liegt im Volume `caddy_data`
(`docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt .`) und kann auf den Geräten als
vertrauenswürdig importiert werden.

## 2. Starten

```bash
docker compose up -d --build
docker compose ps          # alle drei Dienste "healthy"/"running"
```

## 3. Ersten Benutzer anlegen

Jeder kann sich auf der Anmeldeseite über „Konto erstellen“ ein eigenes Konto anlegen; jedes Konto sieht nur
seine eigenen Postfächer und Daten. Soll das nicht möglich sein, `LOTSE_OPEN_REGISTRATION=false` in `.env`
setzen. Benutzer lassen sich außerdem über die Kommandozeile anlegen:

```bash
docker compose exec backend python -m app.cli create-user dein-name
```

Weitere Befehle: `list-users`, `reset-password <name>`, `disable-2fa <name>`.

Danach `https://lotse.example.org` öffnen, anmelden und unter **Sicherheit** die Zwei-Faktor-Anmeldung aktivieren.

## 4. Postfächer verbinden

**Mailcow / IMAP:** Unter **Verbindungen** Server (z. B. `mail.example.org`), Port 993, Benutzer und
App-Passwort eintragen. Lotse prüft Zertifikat und Hostname und testet die Anmeldung, bevor gespeichert wird.

Läuft Mailcow im selben Netz und löst auf eine private IP auf, muss der Hostname ausdrücklich erlaubt werden:
`LOTSE_IMAP_ALLOWED_HOSTS=mail.example.org` (SSRF-Schutz). Nutzt der Mailserver ein selbst signiertes
Zertifikat, die CA einbinden (siehe Kommentar in `docker-compose.yml`) und `LOTSE_IMAP_CA_FILE` setzen.

**Gmail (optional):** siehe [GMAIL.md](GMAIL.md).

## 5. Aktualisieren

```bash
git pull
docker compose build --pull
docker compose up -d
```

JustDeleteMe-Daten aktualisieren: `./scripts/update-jdm.sh`, danach neu bauen.

## 6. Sichern und Wiederherstellen

```bash
docker compose exec -T db pg_dump -U lotse lotse | gzip > lotse-$(date +%F).sql.gz
# Wiederherstellen:
gunzip -c lotse-DATUM.sql.gz | docker compose exec -T db psql -U lotse lotse
```

Backups enthalten verschlüsselte Zugangsdaten – zusammen mit `.env` sind sie entschlüsselbar.
Bewahre beides getrennt und verschlüsselt auf.

## 7. Härtung des Hosts (empfohlen)

- Firewall: nur 22 (SSH, idealerweise nur Schlüssel), 80 und 443 öffnen
- Automatische Sicherheitsupdates des Betriebssystems aktivieren
- Docker-Images regelmäßig neu bauen (`--pull`)
- Zwei-Faktor-Anmeldung für alle Lotse-Benutzer

## Fehlersuche

| Problem | Lösung |
|---|---|
| `Unsichere Konfiguration: …` beim Start | Fehlende/zu kurze Schlüssel in `.env` ergänzen |
| Zertifikat wird nicht ausgestellt | DNS prüfen, Port 80 erreichbar? `docker compose logs caddy` |
| „Der Server löst auf eine interne Adresse auf“ | Mailserver in `LOTSE_IMAP_ALLOWED_HOSTS` eintragen |
| „TLS-Zertifikat … ungültig“ | Zertifikat des Mailservers erneuern oder eigene CA einbinden |
| Gmail-Button fehlt | `LOTSE_GOOGLE_CLIENT_ID/SECRET` setzen, siehe GMAIL.md |
