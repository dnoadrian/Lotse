# Gmail einrichten (optional)

Quitly greift über die **offizielle Gmail-API** zu (OAuth 2.0 mit PKCE). Dein Google-Passwort sieht
Quitly nie. Dafür brauchst du einen eigenen OAuth-Client in der Google Cloud Console – diese
Zugangsdaten können nicht mitgeliefert werden.

## Schritte

1. <https://console.cloud.google.com/> öffnen, ein Projekt anlegen (z. B. „Quitly“).
2. **APIs & Dienste → Bibliothek →** „Gmail API“ aktivieren.
3. **OAuth-Zustimmungsbildschirm** konfigurieren:
   - Nutzertyp „Extern“ (oder „Intern“ bei Google Workspace)
   - Bereich hinzufügen: `https://www.googleapis.com/auth/gmail.modify`
   - Unter „Testnutzer“ die eigene Gmail-Adresse eintragen (solange die App im Testmodus ist)
4. **Anmeldedaten → Anmeldedaten erstellen → OAuth-Client-ID**:
   - Anwendungstyp: **Webanwendung**
   - Autorisierte Weiterleitungs-URI: `https://<QUITLY_DOMAIN>/api/oauth/google/callback`
5. Client-ID und Client-Secret in `.env` eintragen:
   ```
   QUITLY_GOOGLE_CLIENT_ID=….apps.googleusercontent.com
   QUITLY_GOOGLE_CLIENT_SECRET=…
   ```
6. `docker compose up -d` – unter **Verbindungen** erscheint „Mit Google anmelden“.

## Berechtigungen

| Scope | Wofür |
|---|---|
| `gmail.modify` | Absender/Betreff/Datum lesen (Erkennung, Liste), Nachrichten in den Papierkorb verschieben |

Quitly fordert **nicht** den Vollzugriff `https://mail.google.com/` an. Deshalb verschiebt Quitly
Gmail-Nachrichten nur in den Papierkorb; Google löscht sie dort nach 30 Tagen endgültig.

Hinweis: `gmail.modify` gilt bei Google als „eingeschränkter Bereich“. Für die private Nutzung im
Testmodus genügt es, sich selbst als Testnutzer einzutragen. Im Testmodus laufen Refresh-Tokens nach
7 Tagen ab – dann in Quitly einfach erneut mit Google anmelden.

## Zugriff widerrufen

- In Quitly: Postfach entfernen (das Token wird bei Google widerrufen und gelöscht)
- Bei Google: <https://myaccount.google.com/permissions>
