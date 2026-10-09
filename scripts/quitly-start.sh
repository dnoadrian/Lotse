#!/usr/bin/env bash
# Startet Quitly lokal (macOS und Linux) und öffnet die Webseite.
# Beim ersten Start: .env mit Zufallsschlüsseln, Eintrag für quitly.at, Vertrauen in die lokale
# HTTPS-Zertifizierungsstelle und erster Benutzer. Admin-Rechte werden nur dafür kurz abgefragt.
set -euo pipefail

DOMAIN="${QUITLY_LOCAL_DOMAIN:-quitly.at}"
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
OS="$(uname -s)"

say()  { printf '\n\033[1;34m▸\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m✗ %s\033[0m\n' "$*"; read -rp "Enter zum Schließen …" _ || true; exit 1; }
open_url() { if [ "$OS" = "Darwin" ]; then open "$1"; else xdg-open "$1" >/dev/null 2>&1 || echo "Bitte öffnen: $1"; fi; }

# 1. Docker vorhanden und gestartet?
if ! command -v docker >/dev/null 2>&1; then
  open_url "https://www.docker.com/products/docker-desktop/"
  fail "Docker ist nicht installiert. Bitte Docker Desktop installieren und danach erneut starten."
fi
if ! docker info >/dev/null 2>&1; then
  say "Docker wird gestartet …"
  if [ "$OS" = "Darwin" ]; then open -a Docker || true; else (systemctl --user start docker-desktop 2>/dev/null || sudo systemctl start docker) || true; fi
  for _ in $(seq 1 90); do docker info >/dev/null 2>&1 && break; sleep 2; done
  docker info >/dev/null 2>&1 || fail "Docker läuft nicht. Bitte Docker Desktop öffnen und erneut versuchen."
fi
docker compose version >/dev/null 2>&1 || fail "Docker Compose fehlt (docker compose). Bitte Docker aktualisieren."

# 2. Konfiguration
if [ ! -f .env ]; then
  say "Erster Start: Konfiguration mit neuen Zufallsschlüsseln wird erstellt …"
  ./scripts/generate-env.sh "$DOMAIN" internal
fi

# 3. quitly.at auf diesen Rechner zeigen lassen (nur lokal, nur in /etc/hosts)
if ! grep -Eq "^[^#]*[[:space:]]${DOMAIN//./\\.}([[:space:]]|$)" /etc/hosts; then
  say "Damit https://$DOMAIN auf diesen Rechner zeigt, wird /etc/hosts ergänzt (Passwort nötig)."
  echo "127.0.0.1 $DOMAIN" | sudo tee -a /etc/hosts >/dev/null
fi

# 4. Starten
say "Quitly wird gebaut und gestartet (beim ersten Mal einige Minuten) …"
if [ -n "${QUITLY_NO_BUILD:-}" ]; then docker compose up -d --no-build; else docker compose up -d --build; fi

say "Warte, bis Quitly bereit ist …"
ok=""
for _ in $(seq 1 90); do
  if curl -fsk --noproxy "$DOMAIN" --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/health" >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ -n "$ok" ] || fail "Quitly antwortet nicht. Details: docker compose logs"

# 5. Lokaler HTTPS-Zertifizierungsstelle von Caddy vertrauen (einmalig, keine Browser-Warnung mehr)
if [ ! -f .quitly-ca-trusted ]; then
  say "Einmalig: Zertifikat der lokalen Quitly-CA wird als vertrauenswürdig eingetragen (Passwort nötig) …"
  docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt "$ROOT/.quitly-root.crt" >/dev/null
  if [ "$OS" = "Darwin" ]; then
    sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$ROOT/.quitly-root.crt" && touch .quitly-ca-trusted
  elif [ -d /usr/local/share/ca-certificates ]; then
    sudo cp "$ROOT/.quitly-root.crt" /usr/local/share/ca-certificates/quitly-local.crt && sudo update-ca-certificates >/dev/null && touch .quitly-ca-trusted
    if command -v certutil >/dev/null 2>&1 && [ -d "$HOME/.pki/nssdb" ]; then
      certutil -d "sql:$HOME/.pki/nssdb" -A -t "C,," -n "Quitly lokal" -i "$ROOT/.quitly-root.crt" || true
    fi
  else
    echo "Hinweis: Bitte $ROOT/.quitly-root.crt im Browser als vertrauenswürdige Zertifizierungsstelle importieren."
  fi
fi

# 6. Erster Benutzer
if [ -z "$(docker compose exec -T backend python -m app.cli list-users 2>/dev/null)" ]; then
  say "Lege deinen Quitly-Benutzer an (Passwort mind. 4 Zeichen):"
  read -rp "Benutzername: " name
  docker compose exec backend python -m app.cli create-user "$name"
fi

say "Quitly läuft: https://$DOMAIN"
open_url "https://$DOMAIN"
echo "Beenden mit „Quitly beenden“ oder: docker compose stop"
sleep 3
