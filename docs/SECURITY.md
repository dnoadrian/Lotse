# Sicherheitskonzept und Bedrohungsanalyse

Lotse verarbeitet besonders schützenswerte Daten: Zugangsdaten zu Postfächern, Gmail-Tokens und
Metadaten privater E-Mails. Dieses Dokument beschreibt, wovor Lotse schützt, wie, und wo die
Grenzen liegen. **Keine Software ist absolut sicher** – auch Lotse nicht. Das Konzept reduziert
Risiken in mehreren Schichten. Es ersetzt keine Wartung des Servers, keine Updates und keine Backups.

## 1. Schutzziele und Werte

| Wert | Schutzbedarf | Wo gespeichert |
|---|---|---|
| IMAP-Passwort (Mailcow-App-Passwort) | sehr hoch | `mail_accounts.secret_enc`, AES-256-GCM |
| Gmail-Refresh-Token | sehr hoch | `mail_accounts.secret_enc`, AES-256-GCM |
| Lotse-Passwort | hoch | `users.password_hash`, Argon2id |
| TOTP-Geheimnis | hoch | `users.totp_secret_enc`, AES-256-GCM |
| Sitzungstoken | hoch | nur SHA-256-Hash in `sessions.token_hash` |
| Mail-Metadaten (Absender, Betreff) | hoch | **nicht gespeichert**, nur live angezeigt |
| Erkannte Dienste, Löschstatus | mittel | `services`, `evidence` (Ordner, UID, Kategorie, Absender-Domain) |
| Audit-Protokoll | mittel | `audit_log`, ohne Inhalte und ohne Geheimnisse |

## 2. Architektur und Vertrauensgrenzen

```
Browser ──HTTPS──▶ Caddy (TLS, Security-Header) ──HTTP intern──▶ Backend (FastAPI) ──▶ PostgreSQL (internes Netz)
                                                                   │
                                                                   ├──IMAPS (TLS, Zertifikat geprüft)──▶ Mailcow / IMAP-Server
                                                                   └──HTTPS──▶ Google OAuth / Gmail API (feste Endpunkte)
```

Vertrauensgrenzen: (1) Internet ↔ Caddy, (2) Backend ↔ fremde Mailserver (vom Nutzer angegeben),
(3) Backend ↔ Google, (4) Inhalte fremder E-Mails (vollständig nicht vertrauenswürdig),
(5) JustDeleteMe-Datensatz (Drittdaten).

## 3. Bedrohungsanalyse (STRIDE)

| # | Bedrohung | Kategorie | Gegenmaßnahmen | Restrisiko |
|---|---|---|---|---|
| T1 | Passwort raten / Credential Stuffing | Spoofing | Argon2id; 5 Fehlversuche pro Benutzer/15 min, 20 Versuche pro IP/15 min (DB-basiert, gilt über alle Worker); gleiche Fehlermeldung und gleiche Laufzeit für unbekannte Benutzer; optionale TOTP-Zwei-Faktor-Anmeldung | Verteilte Angriffe aus vielen IPs werden nur pro Benutzer gebremst → 2FA aktivieren |
| T2 | Session-Hijacking | Spoofing | 256-Bit-Zufallstoken, in der DB nur gehasht; Cookie `__Host-`, `HttpOnly`, `Secure`, `SameSite=Strict`; Leerlauf-Timeout 30 min, absolut 12 h; Abmelden löscht serverseitig; Sitzungen einsehbar und beendbar | Schadsoftware auf dem Endgerät des Nutzers |
| T3 | Session Fixation | Spoofing | Neues Token bei Login **und** nach der 2FA-Prüfung; alte Sitzung des Browsers wird verworfen | – |
| T4 | CSRF | Tampering | `SameSite=Strict`; CSRF-Token (HMAC über Sitzungs-ID) als Header; Pflicht-Header `X-Lotse-Request` (erzwingt CORS-Preflight, CORS ist nicht freigegeben); `Origin`-Prüfung; nur JSON wird angenommen | – |
| T5 | XSS über Mail-Betreffe, Absender, JDM-Texte | Tampering | React rendert nur Text (kein `dangerouslySetInnerHTML`); Steuer- und Bidi-Zeichen werden serverseitig entfernt; strikte CSP ohne `unsafe-inline`/`unsafe-eval`; Links aus JDM nur mit `http(s)://`, Öffnen mit `noopener noreferrer` | Fehler in Browser/Bibliotheken |
| T6 | SQL-Injection | Tampering | Ausschließlich SQLAlchemy mit gebundenen Parametern; kein dynamisches SQL | – |
| T7 | NoSQL-/Command-Injection, IMAP-Injection | Tampering | Keine NoSQL-DB, keine Shell-Aufrufe; Ordnernamen werden nur akzeptiert, wenn der Server sie per `LIST` geliefert hat, dann korrekt gequotet; UIDs als Ganzzahlen validiert; Gmail-IDs/Labels per Regex validiert | – |
| T8 | SSRF über frei wählbaren Mailserver | Elevation | Nur erlaubte Ports (Standard 993); DNS-Auflösung vorab, alle IPs müssen öffentlich sein (kein Loopback, privat, Link-Local inkl. Cloud-Metadaten 169.254.169.254, CGNAT, IPv4-mapped IPv6); Verbindung zur geprüften IP (kein DNS-Rebinding); interne Server nur per expliziter Allowlist; Gmail nur über feste Google-URLs; keine Redirects | Allowlist bewusst konfigurierter Hosts |
| T9 | Man-in-the-Middle zum Mailserver | Information Disclosure | Nur IMAPS, TLS ≥ 1.2, Zertifikat und Hostname werden **immer** geprüft, keine Abschaltoption; eigene CA nur zusätzlich einbindbar | Kompromittierte CA |
| T10 | Diebstahl der Datenbank / Backups | Information Disclosure | Zugangsdaten und TOTP AES-256-GCM-verschlüsselt, Associated Data bindet jedes Chiffrat an Nutzer und Feld; Schlüssel liegt nicht in der DB; Passwörter Argon2id; Sitzungen nur gehasht; keine Mail-Inhalte gespeichert | Wer DB **und** `.env` erbeutet, kann Zugangsdaten entschlüsseln → `.env` getrennt sichern, Rechte 600 |
| T11 | Zugriff auf fremde Postfächer/Daten (IDOR) | Elevation | Jede Abfrage filtert nach `user_id`; fremde und nicht existierende IDs liefern identisch 404; automatischer Test prüft, dass jede API-Route Anmeldung verlangt; Tests für alle Ressourcen-Endpunkte mit zweitem Nutzer | – |
| T12 | Versehentliche oder untergeschobene Massenlöschung | Tampering | Bestätigungswort „LÖSCHEN“ bei mehr als einer Mail, ganzem Ordner oder endgültigem Löschen (serverseitig erzwungen); `expected_count` und `UIDVALIDITY` müssen mit dem Server übereinstimmen, sonst 409; Standard ist Papierkorb; Rate-Limit 30 Löschvorgänge/min; Audit-Eintrag | Bewusste Fehlbedienung |
| T13 | Falsch gemeldeter Löscherfolg | Repudiation | Nach jeder Löschung prüft Lotse auf dem Server (IMAP `UID SEARCH`, Gmail-Label `TRASH`), ob die Nachrichten weg sind; Fehler werden einzeln gemeldet | – |
| T14 | Bösartige E-Mails (Parser-Angriffe, Anhänge) | Tampering/DoS | Es werden nur ausgewählte Kopfzeilen per `BODY.PEEK[HEADER.FIELDS …]` gelesen, nie Bodies oder Anhänge; Größenlimit 16 KB; defensives Parsen mit Fehlerbehandlung; kein HTML-Rendering | – |
| T15 | Datenabfluss über Logs | Information Disclosure | Eigenes Access-Log ohne Query-String, ohne Body, ohne Cookies; uvicorn-Access-Log aus; Caddy-Log filtert Query, Cookies und CSRF-Header; httpx-Logs gedrosselt; Validierungsfehler spiegeln keine Eingaben; Audit-Log verwirft Felder wie `password`, `token`, `subject` (getestet) | – |
| T16 | Manipulierter JDM-Datensatz | Tampering | Datei ist im Repository versioniert (Commit-Hash in `VERSION.json`); beim Laden werden nur `http(s)`-URLs ohne Userinfo akzeptiert, ungültige Einträge verworfen; Lotse erzeugt keine eigenen Links | Inhalt der Löschseiten liegt beim jeweiligen Anbieter |
| T17 | OAuth-Angriffe (Code-Diebstahl, Login-CSRF, Account-Injection) | Spoofing | Authorization Code + PKCE (S256); `state` 256 Bit, nur gehasht gespeichert, einmalig, 10 min gültig und an die Browser-Sitzung gebunden; minimaler Scope `gmail.modify`; Token-Widerruf beim Entfernen | – |
| T18 | Denial of Service | DoS | Body-Limit (Caddy 1 MB, App 256 KB); Zeitlimits für IMAP/HTTP; Scans im Hintergrund mit begrenztem Pool; Gmail-Bulk-Limit 1000 pro Vorgang | Volumetrische Angriffe → vorgelagerter Schutz |
| T19 | Clickjacking, MIME-Sniffing, Referrer-Lecks | Tampering/Disclosure | `frame-ancestors 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP, HSTS | – |
| T20 | Container-Ausbruch / laterale Bewegung | Elevation | Backend als Nicht-Root (UID 10001), Dateisystem schreibgeschützt, alle Capabilities entfernt, `no-new-privileges`; Datenbank nur im internen Netz ohne Internet und ohne offene Ports | Kernel-Lücken des Hosts |
| T21 | Schwache Konfiguration | – | Start bricht ab, wenn Schlüssel fehlen/zu kurz sind, `PUBLIC_URL` kein HTTPS ist oder `COOKIE_SECURE` in Produktion aus ist; API-Doku in Produktion abgeschaltet; keine offene Registrierung (Benutzer nur per CLI) | – |
| T22 | CSV-Formel-Injection beim Export | Tampering | Zellen, die mit `= + - @` beginnen, werden mit `'` entschärft (getestet) | – |

## 4. Umgesetzte Maßnahmen im Überblick

- **Authentifizierung:** Argon2id (RFC 9106), Mindestlänge 12, optional TOTP (RFC 6238) mit Replay-Schutz.
- **Sitzungen:** serverseitig, gehasht, rotierend, mit Leerlauf- und absolutem Ablauf.
- **Transport:** HTTPS über Caddy (Let's Encrypt oder interne CA), HSTS, HTTP→HTTPS-Umleitung.
- **Eingaben:** Pydantic-Schemas mit Längen- und Mustergrenzen, Allowlists für Ordner und IDs.
- **Ausgaben:** CSP, Text-Rendering, Bereinigung von Steuerzeichen.
- **Geheimnisse:** AES-256-GCM mit Schlüsselrotation (`LOTSE_ENCRYPTION_KEYS_OLD`), nie im Klartext gespeichert oder geloggt.
- **Berechtigungen:** strikte Mandantentrennung nach `user_id`, 404 statt 403.
- **Nachvollziehbarkeit:** Audit-Protokoll je Nutzer, in der Oberfläche einsehbar.

## 5. Durchgeführte Sicherheitsprüfungen

| Prüfung | Ergebnis |
|---|---|
| Automatische Tests (`backend/tests`): Header, CSRF, Origin, Body-Limit, Brute-Force, IP-Limit, TOTP inkl. Replay, Session-Rotation/-Ablauf, Mandantentrennung, Verschlüsselung/Manipulation/Rotation, Logs ohne Geheimnisse, SSRF (12 interne Adressbereiche, Ports, Hostnamen, IP-Pinning), IMAP-Injection, ungültige UIDs, Zertifikats- und Hostnamenprüfung gegen echten TLS-Server, OAuth-State-Bindung | siehe `docs/TESTING.md` |
| Abhängigkeiten: `pip-audit` (Backend), `npm audit` (Frontend) | siehe `docs/TESTING.md` |
| Statische Analyse: `bandit` (Backend) | siehe `docs/TESTING.md` |
| Manuelle Code-Durchsicht aller Endpunkte auf Autorisierung, Injection und Logging | gefundene Punkte behoben, siehe unten |

### Während der Prüfung gefundene und behobene Schwachstellen

1. **OAuth-Code im Log:** Der HTTP-Client (httpx) protokollierte Request-URLs → Logger auf WARNING gesetzt, eigenes Access-Log ohne Query-String; Test ergänzt.
2. **8-Bit-Kopfzeilen falsch dekodiert:** UTF-8-Betreffe ohne MIME-Kodierung wurden mit Ersatzzeichen gelesen → Erkennung verfehlte Konten. Dekodierung korrigiert, Test ergänzt.
3. **Strenge X.509-Prüfung:** Test-CA ohne `keyUsage` wurde (korrekt) abgelehnt – Lotse schwächt die Prüfung nicht ab; stattdessen Test-CA korrigiert.

## 6. Bekannte Grenzen und Empfehlungen

- Lotse schützt nicht vor kompromittierten Endgeräten oder einem kompromittierten Server-Root.
- Wer die Datenbank **und** die `.env` erbeutet, kann gespeicherte Zugangsdaten entschlüsseln. Nutze
  in Mailcow ein **App-Passwort nur mit IMAP-Berechtigung**, damit es jederzeit widerrufbar ist.
- Gmail: Endgültiges Löschen ist bewusst nicht möglich (würde Vollzugriff erfordern); Google leert den
  Papierkorb nach 30 Tagen.
- Die Erkennung ist regelbasiert und kann Konten übersehen oder falsch zuordnen; die Qualität wird angezeigt.
- Regelmäßig aktualisieren: `docker compose pull && docker compose build --pull && docker compose up -d`.
- Zwei-Faktor-Anmeldung aktivieren, Server-Firewall auf 80/443 beschränken, Backups verschlüsseln.

Sicherheitslücken bitte nicht öffentlich melden, sondern direkt an den Betreiber der Instanz.
