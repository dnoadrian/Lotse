"""Gmail über die offizielle Gmail-API (OAuth 2.0 Authorization Code + PKCE).

Es werden ausschließlich feste Google-Endpunkte angesprochen (kein SSRF-Risiko).
Benötigter Scope: gmail.modify (Metadaten lesen, in den Papierkorb verschieben).
Endgültiges Löschen über die API würde den Vollzugriff-Scope https://mail.google.com/ erfordern –
den fordert Quitly bewusst nicht an.
"""
from __future__ import annotations

import base64
import hashlib
import time
from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from ..config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # nosec B105
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.modify"
METADATA_HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "Auto-Submitted"]

SYSTEM_LABELS = {
    "INBOX": "Posteingang",
    "SENT": "Gesendet",
    "SPAM": "Spam",
    "TRASH": "Papierkorb",
    "CATEGORY_PROMOTIONS": "Werbung",
    "CATEGORY_SOCIAL": "Soziale Netzwerke",
    "CATEGORY_UPDATES": "Benachrichtigungen",
    "CATEGORY_FORUMS": "Foren",
}


class GmailError(Exception):
    pass


def pkce_pair(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def authorization_url(state: str, verifier: str) -> str:
    s = get_settings()
    params = {
        "client_id": s.google_client_id,
        "redirect_uri": s.gmail_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "code_challenge": pkce_pair(verifier),
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _http() -> httpx.Client:
    # verify=True ist Standard; Zeitlimits verhindern hängende Worker
    return httpx.Client(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=False)


def exchange_code(code: str, verifier: str) -> dict:
    s = get_settings()
    with _http() as c:
        r = c.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "redirect_uri": s.gmail_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
        )
    if r.status_code != 200:
        raise GmailError("Google hat die Anmeldung abgelehnt.")
    data = r.json()
    if "refresh_token" not in data:
        raise GmailError("Google hat kein dauerhaftes Token geliefert. Bitte Zugriff in Google entfernen und erneut verbinden.")
    granted = set(data.get("scope", "").split())
    if SCOPE not in granted:
        raise GmailError("Die nötige Berechtigung wurde nicht erteilt.")
    return data


def revoke(token: str) -> None:
    try:
        with _http() as c:
            c.post(REVOKE_URL, data={"token": token})
    except httpx.HTTPError:
        pass


@dataclass
class GmailMessage:
    id: str
    headers: dict[str, str]
    internal_date_ms: int
    label_ids: list[str]
    snippet: str = ""


class GmailClient:
    def __init__(self, refresh_token: str):
        self._refresh_token = refresh_token
        self._access_token: str | None = None
        self._expires = 0.0
        self._client = _http()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GmailClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _token(self) -> str:
        if self._access_token and time.time() < self._expires - 60:
            return self._access_token
        s = get_settings()
        r = self._client.post(
            TOKEN_URL,
            data={
                "client_id": s.google_client_id,
                "client_secret": s.google_client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if r.status_code != 200:
            raise GmailError("Der Gmail-Zugriff ist abgelaufen oder wurde widerrufen. Bitte neu verbinden.")
        data = r.json()
        self._access_token = data["access_token"]
        self._expires = time.time() + int(data.get("expires_in", 3600))
        return self._access_token

    def _req(self, method: str, path: str, **kw) -> httpx.Response:
        for attempt in range(4):
            r = self._client.request(method, f"{API}{path}", headers={"Authorization": f"Bearer {self._token()}"}, **kw)
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            return r
        return r

    def _json(self, method: str, path: str, **kw) -> dict:
        r = self._req(method, path, **kw)
        if r.status_code == 401:
            raise GmailError("Der Gmail-Zugriff wurde widerrufen. Bitte neu verbinden.")
        if r.status_code >= 400:
            raise GmailError(f"Gmail-API-Fehler ({r.status_code}).")
        return r.json() if r.content else {}

    def profile(self) -> dict:
        return self._json("GET", "/profile")

    def labels(self) -> list[dict]:
        return self._json("GET", "/labels").get("labels", [])

    def label(self, label_id: str) -> dict:
        return self._json("GET", f"/labels/{label_id}")

    def iter_message_ids(self, label_id: str | None = None, query: str | None = None, limit: int | None = None) -> Iterator[str]:
        page = None
        n = 0
        while True:
            params: dict = {"maxResults": 500, "includeSpamTrash": "true" if label_id in ("SPAM", "TRASH") else "false"}
            if label_id:
                params["labelIds"] = label_id
            if query:
                params["q"] = query
            if page:
                params["pageToken"] = page
            data = self._json("GET", "/messages", params=params)
            for m in data.get("messages", []):
                yield m["id"]
                n += 1
                if limit and n >= limit:
                    return
            page = data.get("nextPageToken")
            if not page:
                return

    def list_page(self, label_id: str, page_token: str | None, size: int) -> tuple[list[str], str | None, int]:
        params: dict = {"maxResults": size, "labelIds": label_id, "includeSpamTrash": "true" if label_id in ("SPAM", "TRASH") else "false"}
        if page_token:
            params["pageToken"] = page_token
        data = self._json("GET", "/messages", params=params)
        return [m["id"] for m in data.get("messages", [])], data.get("nextPageToken"), int(data.get("resultSizeEstimate", 0))

    def metadata(self, msg_id: str) -> GmailMessage:
        data = self._json(
            "GET",
            f"/messages/{msg_id}",
            params=[("format", "metadata")] + [("metadataHeaders", h) for h in METADATA_HEADERS],
        )
        headers = {h["name"].lower(): h["value"][:2000] for h in data.get("payload", {}).get("headers", [])}
        return GmailMessage(
            id=data["id"],
            headers=headers,
            internal_date_ms=int(data.get("internalDate", 0)),
            label_ids=data.get("labelIds", []),
            snippet=str(data.get("snippet", ""))[:1000],
        )

    def trash(self, msg_id: str) -> bool:
        r = self._req("POST", f"/messages/{msg_id}/trash")
        return r.status_code == 200

    def is_trashed_or_gone(self, msg_id: str) -> bool:
        r = self._req("GET", f"/messages/{msg_id}", params={"format": "minimal"})
        if r.status_code == 404:
            return True
        if r.status_code != 200:
            return False
        return "TRASH" in r.json().get("labelIds", [])
