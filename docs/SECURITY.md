# Sicherheitskonzept und Bedrohungsanalyse

Quitly verarbeitet besonders schützenswerte Daten: Zugangsdaten zu Postfächern sowie
Metadaten und – beim Lesen – Inhalte privater E-Mails. Dieses Dokument beschreibt, wovor Quitly schützt, wie, und wo die
Grenzen liegen. **Keine Software ist absolut sicher** – auch Quitly nicht. Das Konzept reduziert
Risiken in mehreren Schichten. Es ersetzt keine Wartung des Servers, keine Updates und keine Backups.

## 1. Schutzziele und Werte

| Wert | Schutzbedarf | Wo gespeichert |
|---|---|---|
| IMAP-Passwort bzw. App-Passwort | sehr hoch | `mail_accounts.secret_enc`, AES-256-GCM |
| Quitly-Passwort | hoch | `users.password_hash`, Argon2id |
| TOTP-Geheimnis | hoch | `users.totp_secret_enc`, AES-256-GCM |
| Sitzungstoken | hoch | nur SHA-256-Hash in `sessions.token_hash` |
| Mail-Metadaten und -Inhalte | hoch | **nicht gespeichert**, nur live angezeigt bzw. im Arbeitsspeicher ausgewertet |
| Favicons der Dienste | niedrig | `favicons` (öffentliche Bilder, keine Nutzerzuordnung) |
| Erkannte Dienste, Löschstatus | mittel | `services`, `evidence` (Ordner, UID, Kategorie, Absender-Domain) |
| Audit-Protokoll | mittel | `audit_log`, ohne Inhalte und ohne Geheimnisse |

## 2. Architektur und Vertrauensgrenzen

```
Browser ──HTTPS──▶ Caddy (TLS, Security-Header) ──HTTP intern──▶ Backend (FastAPI) ──▶ PostgreSQL (internes Netz)
                                                                   │
                                                                   ├──IMAPS (TLS, Zertifikat geprüft)──▶ IMAP-Server des Nutzers
                                                                   └──HTTPS (nur öffentliche IPs)──▶ Websites der Dienste (Favicons)
```

Vertrauensgrenzen: (1) Internet ↔ Caddy, (2) Backend ↔ fremde Mailserver (vom Nutzer angegeben),
(3) Backend ↔ Websites der Dienste (Favicons), (4) Inhalte fremder E-Mails (vollständig nicht vertrauenswürdig),
(5) JustDeleteMe-Datensatz (Drittdaten).

## 3. Bedrohungsanalyse (STRIDE)

| # | Bedrohung | Kategorie | Gegenmaßnahmen | Restrisiko |
|---|---|---|---|---|
| T1 | Passwort raten / Credential Stuffing | Spoofing | Argon2id; 5 Fehlversuche pro Benutzer/15 min, 20 Versuche pro IP/15 min (DB-basiert, gilt über alle Worker); gleiche Fehlermeldung und gleiche Laufzeit für unbekannte Benutzer; optionale TOTP-Zwei-Faktor-Anmeldung | Verteilte Angriffe aus vielen IPs werden nur pro Benutzer gebremst → 2FA aktivieren |
| T2 | Session-Hijacking | Spoofing | 256-Bit-Zufallstoken, in der DB nur gehasht; Cookie `__Host-`, `HttpOnly`, `Secure`, `SameSite=Strict`; Leerlauf-Timeout 30 min, absolut 12 h; Abmelden löscht serverseitig; Sitzungen einsehbar und beendbar | Schadsoftware auf dem Endgerät des Nutzers |
| T3 | Session Fixation | Spoofing | Neues Token bei Login **und** nach der 2FA-Prüfung; alte Sitzung des Browsers wird verworfen | – |
| T4 | CSRF | Tampering | `SameSite=Strict`; CSRF-Token (HMAC über Sitzungs-ID) als Header; Pflicht-Header `X-Quitly-Request` (erzwingt CORS-Preflight, CORS ist nicht freigegeben); `Origin`-Prüfung; nur JSON wird angenommen | – |
| T5 | XSS über Mail-Betreffe, Absender, JDM-Texte | Tampering | React rendert nur Text (kein `dangerouslySetInnerHTML`); Steuer- und Bidi-Zeichen werden serverseitig entfernt; strikte CSP ohne `unsafe-inline`/`unsafe-eval`; Links aus JDM nur mit `http(s)://`, Öffnen mit `noopener noreferrer` | Fehler in Browser/Bibliotheken |
| T6 | SQL-Injection | Tampering | Ausschließlich SQLAlchemy mit gebundenen Parametern; kein dynamisches SQL | – |
| T7 | NoSQL-/Command-Injection, IMAP-Injection | Tampering | Keine NoSQL-DB, keine Shell-Aufrufe; Ordnernamen werden nur akzeptiert, wenn der Server sie per `LIST` geliefert hat, dann korrekt gequotet; UIDs als Ganzzahlen validiert; Suchbegriffe als IMAP-Literal (keine Injection, kein CR/LF) | – |
| T8 | SSRF über frei wählbaren Mailserver | Elevation | Nur erlaubte Ports (Standard 993); DNS-Auflösung vorab, alle IPs müssen öffentlich sein (kein Loopback, privat, Link-Local inkl. Cloud-Metadaten 169.254.169.254, CGNAT, IPv4-mapped IPv6); Verbindung zur geprüften IP (kein DNS-Rebinding); interne Server nur per expliziter Allowlist; keine Redirects | Allowlist bewusst konfigurierter Hosts |
| T9 | Man-in-the-Middle zum Mailserver | Information Disclosure | Nur IMAPS, TLS ≥ 1.2, Zertifikat und Hostname werden **immer** geprüft, keine Abschaltoption; eigene CA nur zusätzlich einbindbar | Kompromittierte CA |
| T10 | Diebstahl der Datenbank / Backups | Information Disclosure | Zugangsdaten und TOTP AES-256-GCM-verschlüsselt, Associated Data bindet jedes Chiffrat an Nutzer und Feld; Schlüssel liegt nicht in der DB; Passwörter Argon2id; Sitzungen nur gehasht; keine Mail-Inhalte gespeichert | Wer DB **und** `.env` erbeutet, kann Zugangsdaten entschlüsseln → `.env` getrennt sichern, Rechte 600 |
| T11 | Zugriff auf fremde Postfächer/Daten (IDOR) | Elevation | Jede Abfrage filtert nach `user_id`; fremde und nicht existierende IDs liefern identisch 404; automatischer Test prüft, dass jede API-Route Anmeldung verlangt; Tests für alle Ressourcen-Endpunkte mit zweitem Nutzer | – |
| T12 | Versehentliche oder untergeschobene Massenlöschung | Tampering | Bestätigungswort „LÖSCHEN“ bei mehr als einer Mail, ganzem Ordner oder endgültigem Löschen (serverseitig erzwungen); `expected_count` und `UIDVALIDITY` müssen mit dem Server übereinstimmen, sonst 409; Standard ist Papierkorb; Rate-Limit 30 Löschvorgänge/min; Audit-Eintrag | Bewusste Fehlbedienung |
| T13 | Falsch gemeldeter Löscherfolg | Repudiation | Nach jeder Löschung prüft Quitly auf dem Server (IMAP `UID SEARCH`), ob die Nachrichten weg sind; Fehler werden einzeln gemeldet | – |
| T14 | Bösartige E-Mails (Parser-Angriffe, Anhänge) | Tampering/DoS | Gelesen werden ausgewählte Kopfzeilen per `BODY.PEEK[HEADER.FIELDS …]` und höchstens die ersten 8 KB des Textes (`BODY.PEEK[TEXT]<0.8192>`), nie Anhänge; der Text wird nur im Arbeitsspeicher ausgewertet und nicht gespeichert; Kopfzeilen höchstens 16 KB; defensives Parsen mit Fehlerbehandlung. Zum Lesen wird eine Mail ganz geladen (max. 4 MB, `BODY.PEEK[]`), nur im Arbeitsspeicher; Anhänge werden nur aufgelistet, nie ausgeliefert | – |
| T15 | Datenabfluss über Logs | Information Disclosure | Eigenes Access-Log ohne Query-String, ohne Body, ohne Cookies; uvicorn-Access-Log aus; Caddy-Log filtert Query, Cookies und CSRF-Header; httpx-Logs gedrosselt; Validierungsfehler spiegeln keine Eingaben; Audit-Log verwirft Felder wie `password`, `token`, `subject` (getestet) | – |
| T16 | Manipulierter JDM-Datensatz | Tampering | Datei ist im Repository versioniert (Commit-Hash in `VERSION.json`); beim Laden werden nur `http(s)`-URLs ohne Userinfo akzeptiert, ungültige Einträge verworfen; Quitly erzeugt keine eigenen Links | Inhalt der Löschseiten liegt beim jeweiligen Anbieter |
| T17 | Bösartiges HTML in Mails (Skripte, Formulare, Phishing-Links, CSS-Tricks) | Tampering/Spoofing | Serverseitig mit nh3 bereinigt (Allowlist für Tags und Attribute, keine Event-Handler, kein `javascript:`/`data:` in Links); Ausgabe als eigenes Dokument mit eigener CSP (`default-src 'none'`, kein Script, `form-action 'none'`, `sandbox`) in einem `<iframe sandbox>` ohne `allow-scripts` und ohne `allow-same-origin`; Links öffnen in neuem Tab mit `noopener noreferrer` | Gefälschte Inhalte innerhalb der Mail (Phishing-Text) erkennt Quitly nicht |
| T23 | Tracking-Pixel und Lesebestätigungen | Information Disclosure | Externe Bilder sind per CSP (`img-src data:`) blockiert, bis der Nutzer sie ausdrücklich lädt; eingebettete Bilder (`cid:`) werden lokal eingesetzt; `Referrer-Policy: no-referrer` | Nach „Bilder laden“ sieht der Absender den Abruf |
| T24 | Abmelde-Links (List-Unsubscribe) | SSRF/Spoofing | Werden nie vom Server aufgerufen; nur `https:`- und `mailto:`-Ziele werden angezeigt, Öffnen nur durch den Nutzer | – |
| T25 | SSRF über Favicon-Abruf (Absender-Domains sind fremd kontrolliert) | Elevation | Nur `https` auf Port 443, keine IP-Literale; DNS-Auflösung vorab, alle Adressen müssen öffentlich sein; Verbindung zur geprüften IP mit TLS-Prüfung des Namens (kein DNS-Rebinding); jede Weiterleitung (max. 3) wird erneut geprüft; Zeitlimit 5 s je Abruf und 9 s je Stufe, eigener Thread-Pool (blockiert die übrige API nicht), max. 512 KB; nur Bilder anhand der Datei-Signatur (PNG/ICO/GIF/JPEG/WebP/AVIF, SVG nur ohne Skripte/Event-Handler; kein HTML); Auslieferung mit `nosniff` und `sandbox`-CSP; nur für eigene Dienste abrufbar. Reihenfolge: `/favicon.ico` der Seite, Symbol-Link der Startseite, jeweils auch unter `www.`, dann die Favicon-Dienste von DuckDuckGo und Google (für Seiten mit Bot-Schutz). Optionale Diagnose `QUITLY_FAVICON_DEBUG=true` protokolliert nur Domain und Fehlerart | Der Anbieter bzw. DuckDuckGo/Google sehen die Domain und die Server-IP – nie den Nutzer |
| T18 | Denial of Service | DoS | Body-Limit (Caddy 1 MB, App 256 KB); Zeitlimits für IMAP/HTTP; Scans im Hintergrund mit begrenztem Pool; Größenlimits beim Lesen und Favicon-Abruf; Rate-Limits für Löschen und Verschieben | Volumetrische Angriffe → vorgelagerter Schutz |
| T19 | Clickjacking, MIME-Sniffing, Referrer-Lecks | Tampering/Disclosure | `frame-ancestors 'none'`, `X-Frame-Options: DENY` (einzige Ausnahme: die bereinigte Mail-Ansicht mit `frame-ancestors 'self'`), `nosniff`, `Referrer-Policy: no-referrer`, COOP/CORP, HSTS | – |
| T20 | Container-Ausbruch / laterale Bewegung | Elevation | Backend als Nicht-Root (UID 10001), Dateisystem schreibgeschützt, alle Capabilities entfernt, `no-new-privileges`; Datenbank nur im internen Netz ohne Internet und ohne offene Ports | Kernel-Lücken des Hosts |
| T21 | Schwache Konfiguration | – | Start bricht ab, wenn Schlüssel fehlen/zu kurz sind, `PUBLIC_URL` kein HTTPS ist oder `COOKIE_SECURE` in Produktion aus ist; API-Doku in Produktion abgeschaltet; offene Registrierung ist pro IP begrenzt (5/Stunde) und mit `QUITLY_OPEN_REGISTRATION=false` abschaltbar; jedes Konto sieht ausschließlich eigene Daten | – |
| T22 | CSV-Formel-Injection beim Export | Tampering | Zellen, die mit `= + - @` beginnen, werden mit `'` entschärft (getestet) | – |

## 4. Umgesetzte Maßnahmen im Überblick

- **Authentifizierung:** Argon2id (RFC 9106), Mindestlänge 4 (bewusst niedrig gewählt; Schutz vor Raten über Rate-Limits und optionale 2FA), optional TOTP (RFC 6238) mit Replay-Schutz.
- **Sitzungen:** serverseitig, gehasht, rotierend, mit Leerlauf- und absolutem Ablauf.
- **Transport:** HTTPS über Caddy (Let's Encrypt oder interne CA), HSTS, HTTP→HTTPS-Umleitung.
- **Eingaben:** Pydantic-Schemas mit Längen- und Mustergrenzen, Allowlists für Ordner und IDs.
- **Ausgaben:** CSP, Text-Rendering, Bereinigung von Steuerzeichen.
- **Geheimnisse:** AES-256-GCM mit Schlüsselrotation (`QUITLY_ENCRYPTION_KEYS_OLD`), nie im Klartext gespeichert oder geloggt.
- **Berechtigungen:** strikte Mandantentrennung nach `user_id`, 404 statt 403.
- **Nachvollziehbarkeit:** Audit-Protokoll je Nutzer, in der Oberfläche einsehbar.

## 5. Durchgeführte Sicherheitsprüfungen

| Prüfung | Ergebnis |
|---|---|
| Automatische Tests (`backend/tests`): Header, CSRF, Origin, Body-Limit, Brute-Force, IP-Limit, TOTP inkl. Replay, Session-Rotation/-Ablauf, Mandantentrennung, Verschlüsselung/Manipulation/Rotation, Logs ohne Geheimnisse, SSRF (12 interne Adressbereiche, Ports, Hostnamen, IP-Pinning), IMAP-Injection, ungültige UIDs, Zertifikats- und Hostnamenprüfung gegen echten TLS-Server, HTML-Bereinigung (Skripte, Event-Handler, `javascript:`/`data:`-Links, Formulare, Frames), Mail-CSP, Favicon-SSRF | siehe `docs/TESTING.md` |
| Abhängigkeiten: `pip-audit` (Backend), `npm audit` (Frontend) | siehe `docs/TESTING.md` |
| Statische Analyse: `bandit` (Backend) | siehe `docs/TESTING.md` |
| Manuelle Code-Durchsicht aller Endpunkte auf Autorisierung, Injection und Logging | gefundene Punkte behoben, siehe unten |

### Während der Prüfung gefundene und behobene Schwachstellen

1. **Code im Log:** Ein HTTP-Client protokollierte Request-URLs inkl. Query → eigenes Access-Log ohne Query-String; Test ergänzt. (Der Client wurde mit der Gmail-Unterstützung entfernt.)
2. **8-Bit-Kopfzeilen falsch dekodiert:** UTF-8-Betreffe ohne MIME-Kodierung wurden mit Ersatzzeichen gelesen → Erkennung verfehlte Konten. Dekodierung korrigiert, Test ergänzt.
3. **Strenge X.509-Prüfung:** Test-CA ohne `keyUsage` wurde (korrekt) abgelehnt – Quitly schwächt die Prüfung nicht ab; stattdessen Test-CA korrigiert.

## 6. Bekannte Grenzen und Empfehlungen

- Quitly schützt nicht vor kompromittierten Endgeräten oder einem kompromittierten Server-Root.
- Wer die Datenbank **und** die `.env` erbeutet, kann gespeicherte Zugangsdaten entschlüsseln. Nutze
  – wenn dein Anbieter das kann – ein **App-Passwort nur mit IMAP-Berechtigung**, damit es jederzeit widerrufbar ist.
- Die Mail-Ansicht ist abgeschottet, aber Inhalte bleiben nicht vertrauenswürdig: Links in Mails mit Vorsicht öffnen.
- Die Erkennung ist regelbasiert und kann Konten übersehen oder falsch zuordnen; die Qualität wird angezeigt.
- Regelmäßig aktualisieren: `docker compose pull && docker compose build --pull && docker compose up -d`.
- Zwei-Faktor-Anmeldung aktivieren, Server-Firewall auf 80/443 beschränken, Backups verschlüsseln.

Sicherheitslücken bitte nicht öffentlich melden, sondern direkt an den Betreiber der Instanz.
