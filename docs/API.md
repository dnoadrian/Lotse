# Quitly – HTTP-API

Alle Endpunkte liegen unter `/api`. Antworten sind JSON, Fehler haben die Form `{"detail": "<deutsche Meldung>"}`.

## Pflicht-Header

| Wann | Header |
|---|---|
| Jede ändernde Anfrage (POST/PUT/PATCH/DELETE) | `X-Quitly-Request: 1` und `Content-Type: application/json` |
| Jede ändernde Anfrage nach dem Login | zusätzlich `X-CSRF-Token: <csrf_token>` |

Den `csrf_token` liefern `POST /api/auth/login`, `POST /api/auth/totp` und `GET /api/auth/session`.
Das Sitzungs-Cookie ist HttpOnly und wird vom Browser automatisch mitgeschickt (`credentials: "same-origin"`).

Statuscodes: `401` = nicht angemeldet (→ zur Anmeldung), `403` = CSRF/Origin, `404` = nicht gefunden oder nicht
der eigene Datensatz, `409` = Konflikt (Daten haben sich geändert), `422` = ungültige Eingabe, `429` = Rate-Limit
(`Retry-After`-Header), `502` = Mailserver-Fehler (Meldung ist für Nutzer verständlich).

## Anmeldung

- `GET /api/auth/session` → `{authenticated, mfa_pending, csrf_token?, user?: {username, totp_enabled}}`
- `POST /api/auth/login` `{username, password}` → `{mfa_required: true}` oder `{mfa_required: false, csrf_token}`
- `POST /api/auth/totp` `{code: "123456"}` → `{csrf_token}` (nur nach Login mit `mfa_required`)
- `POST /api/auth/logout` → `{ok: true}`

## Sicherheit

- `GET /api/security/overview` → `{totp_enabled, sessions: [{id, created_at, last_seen, ip, user_agent, current}]}`
- `POST /api/security/totp/setup` → `{secret, otpauth_uri, qr_svg_base64}` (QR als `data:image/svg+xml;base64,…` anzeigen)
- `POST /api/security/totp/enable` `{code}` → `{ok}`
- `POST /api/security/totp/disable` `{password, code}` → `{ok}`
- `POST /api/security/password` `{current_password, new_password}` → `{ok, other_sessions_revoked}`
- `DELETE /api/security/sessions/{id}` → `{ok}`
- `GET /api/security/audit?limit=100` → `[{id, ts, action, detail, ip}]`
  Aktionen: `login`, `login_failed`, `totp_failed`, `logout`, `totp_enabled`, `totp_disabled`, `password_changed`,
  `session_revoked`, `account_added`, `account_updated`, `account_removed`, `scan_started`, `service_status`,
  `service_status_bulk`, `mail_delete`, `mail_delete_failed`

## Konfiguration

- `GET /api/config` → `{imap_allowed_ports: [993], jdm: {entries, commit, date, source}}`

## Postfächer

- `GET /api/mail-accounts` → `[Account]`
  `Account = {id, provider: "imap", label, email_address, imap_host, imap_port, status: "ok"|"error", last_error, created_at, last_scan_at}`
- `POST /api/mail-accounts/imap` `{label, host, port, username, password}` → `Account` (testet die Verbindung vorher)
- `PUT /api/mail-accounts/{id}/imap` `{label?, host?, port?, username?, password?}` → `Account`
- `POST /api/mail-accounts/{id}/test` → `Account` (Status aktualisiert)
- `DELETE /api/mail-accounts/{id}` → `{ok}`

## Scans

- `POST /api/scans` `{account_id, since_days?}` → `Job` (202)
- `GET /api/scans` → `[Job]` (letzter Scan je Postfach)
- `GET /api/scans/{id}` → `Job`
- `POST /api/scans/{id}/cancel` → `Job`
  `Job = {id, account_id, status: "queued"|"running"|"done"|"error"|"cancelled", step: "fetch"|"classify"|"merge"|"jdm", progress: 0..1, messages_total, messages_seen, signals_found, error, started_at, finished_at}`

## Dienste (erkannte Konten)

- `GET /api/services` → `[Service]`
  ```
  Service = {
    id, name, domains: [str],
    jdm: null | {name, url, difficulty: "easy"|"medium"|"hard"|"impossible"|"limited", instructions, email, email_subject, email_body, domains},
    sources: [{account_id, label, provider, messages, signals}],
    message_count, signal_count, sender_count,
    signals: {welcome?: n, verification?: n, registration?: n, deletion?: n, notice?: n},
    confidence: 0..1, quality: "hoch"|"mittel"|"niedrig",
    first_seen, last_seen, deletion_detected: bool,
    status: "offen"|"angefragt"|"geloescht"|"behalten", status_changed_at
  }
  ```
  `jdm` ist `null`, wenn der Dienst nicht im JustDeleteMe-Katalog steht – dann gibt es **keinen** Lösch-Link.
- `PATCH /api/services/{id}` `{status}` → `Service`
- `POST /api/services/bulk-status` `{ids: [int], status}` → `{updated}`
- `GET /api/services/export.csv` → CSV-Download
- `GET /api/services/{id}/mails` → `{items: [{id, account_id, account_label, folder, folder_name, msg_ref, category,
  label, score, reasons, received_at, sender_domain, subject, from_name, from_addr, seen, still_in_mailbox}],
  explanation: [{category, label, count, best, first, last}], confidence, memory_only, warnings}` – Betreffe werden
  live vom Mailserver gelesen, nicht gespeichert.
- `GET /api/services/{id}/favicon` → PNG/ICO/GIF/JPEG/WebP oder `404`. Vom Server geladen (nur öffentliche
  Adressen, HTTPS, max. 256 KB, Signaturprüfung), 14 Tage zwischengespeichert.

## E-Mails

- `GET /api/mail/{account_id}/folders` → `[{id, name, special: "inbox"|"sent"|"archive"|"drafts"|"junk"|"trash"|"all"|"", count}]`
  `id` ist der Ordnername vom Server und wird unverändert zurückgeschickt (nur gemeldete Ordner werden akzeptiert).
- `GET /api/mail/{account_id}/messages?folder=<id>&page=1&page_size=50&only_registration=false&q=`
  → `{items: [{id, from_name, from_addr, subject, date, category, seen}], total, page, page_size, uidvalidity}`
  `q` (max. 100 Zeichen): Volltextsuche auf dem Server (Kopf und Text, `UID SEARCH CHARSET UTF-8 TEXT`).
- `GET /api/mail/{account_id}/message?folder=<id>&uid=<id>` → `{id, folder, folder_name, uidvalidity, seen, from, to, cc,
  date, subject, category, text, has_html, truncated, attachments: [{name, content_type, size}],
  unsubscribe: {https, mailto}}` – liest mit `BODY.PEEK` (setzt kein `\Seen`), nichts wird gespeichert.
- `GET /api/mail/{account_id}/message/html?folder=<id>&uid=<id>&images=false` → bereinigtes HTML (nh3) als
  eigenes Dokument für ein `<iframe sandbox="allow-popups allow-popups-to-escape-sandbox">`. Eigene CSP:
  `default-src 'none'; style-src 'unsafe-inline'; img-src data:` (mit `images=true` zusätzlich `https:`),
  `form-action 'none'`, `frame-ancestors 'self'`, `sandbox`. Anhänge werden nie ausgeliefert.
- `POST /api/mail/{account_id}/flags` `{folder, ids, seen}` → `{updated, seen}`
- `POST /api/mail/{account_id}/move` `{folder, ids, target}` → `{requested, moved, failed, verified}`
  (Ziel muss ein vom Server gemeldeter Ordner sein; danach wird geprüft, ob die Nachrichten weg sind)
- `POST /api/mail/{account_id}/delete`
  ```
  {folder, mode: "selected"|"all"|"registration", ids: [str], permanent: bool,
   expected_count: int (Pflicht bei all/registration), uidvalidity: str (aus der Liste), confirmation: "LÖSCHEN"}
  ```
  `confirmation` ist Pflicht, sobald mehr als eine Nachricht, ein ganzer Ordner oder endgültig gelöscht wird.
  → `{requested, deleted, already_missing, failed, failed_ids, moved_to_trash, verified, remaining}`
  `409`: Ordner hat sich geändert → Liste neu laden und erneut bestätigen.
