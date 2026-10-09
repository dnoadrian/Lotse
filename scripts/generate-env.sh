#!/usr/bin/env bash
# Erzeugt .env aus .env.example mit frischen Zufallsgeheimnissen.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -e .env ]; then
  echo ".env existiert bereits – nichts überschrieben." >&2
  exit 1
fi

domain="${1:-}"
tls="${2:-}"
if [ -z "$domain" ]; then read -rp "Domain (z. B. quitly.example.org): " domain; fi
if [ -z "$tls" ]; then read -rp "Let's-Encrypt-E-Mail oder 'internal': " tls; fi

umask 077
sed \
  -e "s|^QUITLY_DOMAIN=.*|QUITLY_DOMAIN=${domain}|" \
  -e "s|^QUITLY_TLS=.*|QUITLY_TLS=${tls}|" \
  -e "s|^QUITLY_SECRET_KEY=.*|QUITLY_SECRET_KEY=$(openssl rand -base64 32)|" \
  -e "s|^QUITLY_ENCRYPTION_KEY=.*|QUITLY_ENCRYPTION_KEY=$(openssl rand -base64 32)|" \
  -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(openssl rand -hex 24)|" \
  .env.example > .env
chmod 600 .env
echo ".env erstellt (Rechte 600). Sichere QUITLY_ENCRYPTION_KEY getrennt vom Server-Backup."
