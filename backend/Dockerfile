# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin lotse
WORKDIR /app

COPY requirements.txt .
# Optional: eigene CA für Firmen-Proxys beim Build (docker build --secret id=ca,src=ca.pem)
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install -r requirements.txt

COPY --chown=root:root app ./app

USER lotse
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Kein Access-Log von uvicorn (würde Query-Strings mit OAuth-Codes enthalten) – Lotse loggt selbst datensparsam
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "2", "--no-access-log", "--no-server-header", "--timeout-graceful-shutdown", "20"]
