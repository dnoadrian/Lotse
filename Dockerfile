# syntax=docker/dockerfile:1.7
# Ein einziges Image für Plattformen wie Render: Backend liefert API und gebautes Frontend aus.
# (Für den eigenen Server mit Caddy siehe docker-compose.yml.)

FROM node:22-alpine AS frontend
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
# Optional: eigene CA für Firmen-Proxys beim Build (docker build --secret id=ca,src=ca.pem)
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    QUITLY_STATIC_DIR=/app/static

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin quitly
WORKDIR /app
COPY backend/requirements.txt .
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install -r requirements.txt
COPY backend/app ./app
COPY --from=frontend /src/dist ./static

USER quitly
# Render setzt PORT; lokal 8000
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port ${PORT} --workers 2 --no-access-log --no-server-header"]
