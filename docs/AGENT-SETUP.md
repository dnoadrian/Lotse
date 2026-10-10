# Auftrag für einen Agenten: Quitly lokal einrichten und starten

Richte die Web-App **Quitly** auf diesem Rechner ein, sodass sie unter **https://quitly.at** im Browser läuft
(nur lokal auf diesem Rechner). Arbeite selbstständig, frag mich nur, wo unten „FRAGEN“ steht.

## Regeln
- Schalte niemals TLS- oder Zertifikatsprüfungen ab und lege keine Geheimnisse in Git ab.
- Erfinde keine Passwörter für mich. Mein Quitly-Passwort tippe ich selbst ein.
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

3. **Code holen** (in den Benutzerordner, z. B. `~/Quitly`):
   ```
   git clone -b claude/charming-darwin-oxp12o https://github.com/dnoadrian/Quitly.git ~/Quitly
   ```
   Ohne git: ZIP von https://github.com/dnoadrian/Quitly/archive/refs/heads/claude/charming-darwin-oxp12o.zip
   laden und entpacken.

4. **Ports prüfen:** 80 und 443 müssen frei sein (anderer Webserver, IIS, Skype o. Ä.). Sind sie belegt: FRAGEN.

5. **Starten** über die mitgelieferte Startdatei im Projektordner:
   - Windows: `Quitly starten.bat` (bzw. `powershell -ExecutionPolicy Bypass -File scripts\quitly-start.ps1`)
   - macOS/Linux: `./quitly-starten.sh`

   Die Datei erledigt Folgendes:
   - `.env` mit Zufallsschlüsseln erzeugen
   - `127.0.0.1 quitly.at` in die hosts-Datei eintragen
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
   - `curl -s https://quitly.at/api/health` liefert `{"ok":true}`, ohne `-k`, also mit vertrautem Zertifikat.
   - Öffne https://quitly.at im Browser. Die Anmeldeseite von Quitly muss ohne Zertifikatswarnung erscheinen.

   Bei Firefox: Zeigt er eine Warnung, die Datei `.quitly-root.crt` im Projektordner unter
   Einstellungen → Zertifikate → Zertifizierungsstellen importieren („Websites identifizieren“).

7. **Sicherheit:** Sag mir, dass ich `QUITLY_ENCRYPTION_KEY` aus `.env` getrennt sichern soll. Ohne ihn sind
   gespeicherte Postfach-Zugänge nach einem Datenverlust unbrauchbar. Zeig mir den Wert nicht im Chat.

## Fehlersuche
- Logs ansehen: `docker compose logs --tail=100 caddy backend`
- „Unsichere Konfiguration“ beim Start → `.env` unvollständig: Datei löschen und Startdatei erneut ausführen
  (nur beim allerersten Einrichten, sonst gehen gespeicherte Zugänge verloren).
- `quitly.at` öffnet die echte Website → hosts-Eintrag fehlt oder der DNS-Cache ist veraltet
  (Windows: `ipconfig /flushdns`, macOS: `sudo killall -HUP mDNSResponder`).
- Beenden: `docker compose stop` (Daten bleiben erhalten). Neu starten: Startdatei erneut ausführen.

## Danach (macht der Mensch in der Oberfläche)
- **Verbindungen:** Mailcow mit Server, Port 993, E-Mail-Adresse und einem Mailcow-App-Passwort verbinden,
  dann „Scan starten“.
- **Sicherheit:** Zwei-Faktor-Anmeldung aktivieren.
