# syntax=docker/dockerfile:1.7
# Stufe 1: Frontend bauen
FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
# Optional: eigene CA für Firmen-Proxys beim Build (docker build --secret id=ca,src=ca.pem)
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stufe 2: Caddy liefert die statischen Dateien aus und terminiert TLS
FROM caddy:2.8-alpine
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/dist /srv
