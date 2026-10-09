# Auftrag für einen Agenten: Lotse lokal einrichten und starten

Richte die Web-App **Lotse** auf diesem Rechner ein, sodass sie unter **https://lotse.at** im Browser läuft
(nur lokal auf diesem Rechner). Arbeite selbstständig, frag mich nur, wo unten „FRAGEN“ steht.

## Regeln
- Schalte niemals TLS- oder Zertifikatsprüfungen ab und lege keine Geheimnisse in Git ab.
- Erfinde keine Passwörter für mich. Mein Lotse-Passwort tippe ich selbst ein.
- Zeige mir am Ende nur das Ergebnis, keine geheimen Werte aus `.env`.

## Schritte

1. **Betriebssystem erkennen** (Windows, macOS oder Linux).

2. **Docker prüfen:** `docker info` und `docker compose version` müssen funktionieren.
   - Fehlt Docker: installieren
     - Windows: `winget install -e --id Docker.DockerDesktop`
     - macOS: `brew install --cask docker`
     - Linux: Docker Engine + Compose-Plugin nach https://docs.docker.com/engine/install/
   - Läuft Docker nicht: Docker Desktop starten und warten, bis `docker info` klappt.
   - Muss dafür neu gestartet oder etwas bestätigt werden: FRAGEN.

3. **Code holen** (in den Benutzerordner, z. B. `~/Lotse`):
   ```
   git clone -b claude/charming-darwin-oxp12o https://github.com/dnoadrian/Lotse.git ~/Lotse
   ```
   Ohne git: ZIP von https://github.com/dnoadrian/Lotse/archive/refs/heads/claude/charming-darwin-oxp12o.zip
   laden und entpacken.

4. **Ports prüfen:** 80 und 443 müssen frei sein (anderer Webserver, IIS, Skype o. Ä.). Sind sie belegt: FRAGEN.

5. **Starten** über die mitgelieferte Startdatei im Projektordner:
   - Windows: `Lotse starten.bat` (bzw. `powershell -ExecutionPolicy Bypass -File scripts\lotse-start.ps1`)
   - macOS/Linux: `./lotse-starten.sh`

   Die Datei erledigt Folgendes:
   - `.env` mit Zufallsschlüsseln erzeugen
   - `127.0.0.1 lotse.at` in die hosts-Datei eintragen
   - `docker compose up -d --build` ausführen
   - der lokalen HTTPS-CA von Caddy vertrauen

   Sie fragt dabei nach Admin-Rechten. Dann fordert sie zum Anlegen des ersten Benutzers auf:
   **FRAGEN**, welchen Benutzernamen ich möchte. Das Passwort (mindestens 4 Zeichen) gebe ich selbst ein.
   Kannst du keine interaktive Eingabe weiterreichen, gib mir diesen Befehl zum Selbst-Ausführen im Projektordner:
   ```
   docker compose exec backend python -m app.cli create-user <name>
   ```

6. **Prüfen:**
   - `docker compose ps` → `caddy`, `backend` und `db` laufen; `backend` und `db` sind „healthy“.
   - `curl -s https://lotse.at/api/health` liefert `{"ok":true}`, ohne `-k`, also mit vertrautem Zertifikat.
   - Öffne https://lotse.at im Browser. Die Anmeldeseite von Lotse muss ohne Zertifikatswarnung erscheinen.

   Bei Firefox: Zeigt er eine Warnung, die Datei `.lotse-root.crt` im Projektordner unter
   Einstellungen → Zertifikate → Zertifizierungsstellen importieren („Websites identifizieren“).

7. **Sicherheit:** Sag mir, dass ich `LOTSE_ENCRYPTION_KEY` aus `.env` getrennt sichern soll. Ohne ihn sind
   gespeicherte Postfach-Zugänge nach einem Datenverlust unbrauchbar. Zeig mir den Wert nicht im Chat.

## Fehlersuche
- Logs ansehen: `docker compose logs --tail=100 caddy backend`
- „Unsichere Konfiguration“ beim Start → `.env` unvollständig: Datei löschen und Startdatei erneut ausführen
  (nur beim allerersten Einrichten, sonst gehen gespeicherte Zugänge verloren).
- `lotse.at` öffnet die echte Website → hosts-Eintrag fehlt oder der DNS-Cache ist veraltet
  (Windows: `ipconfig /flushdns`, macOS: `sudo killall -HUP mDNSResponder`).
- Beenden: `docker compose stop` (Daten bleiben erhalten). Neu starten: Startdatei erneut ausführen.

## Danach (macht der Mensch in der Oberfläche)
- **Verbindungen:** Mailcow mit Server, Port 993, E-Mail-Adresse und einem Mailcow-App-Passwort verbinden,
  dann „Scan starten“.
- **Sicherheit:** Zwei-Faktor-Anmeldung aktivieren.
- **Gmail (optional):** braucht einen eigenen Google-OAuth-Client, siehe `docs/GMAIL.md`.
  Bei Gmail-Wunsch: FRAGEN, dann die Einträge in `.env` nach dieser Anleitung ergänzen und neu starten.
