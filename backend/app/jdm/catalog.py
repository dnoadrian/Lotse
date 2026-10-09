"""JustDeleteMe-Katalog (https://github.com/jdm-contrib/jdm, MIT-Lizenz).

Datenstruktur von _data/sites.json – eine Liste von Objekten:
  name        Anzeigename des Dienstes                     (immer vorhanden)
  url         offizielle Seite zur Kontolöschung            (immer vorhanden)
  difficulty  easy | medium | hard | impossible | limited  (immer vorhanden)
  domains     Liste der zugehörigen Domains                 (immer vorhanden)
  notes       Anleitung (englisch), notes_<lang> übersetzt  (optional)
  url_<lang>  sprachspezifische Lösch-URL                  (optional)
  email, email_subject, email_body  Löschung per E-Mail    (optional)

Lotse übernimmt ausschließlich diese Felder. Es werden keine Links erzeugt oder erraten:
Ohne Treffer im Katalog gibt es keinen Lösch-Link.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from ..config import get_settings

DIFFICULTIES = {"easy", "medium", "hard", "impossible", "limited"}
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass(frozen=True)
class JdmEntry:
    name: str
    url: str
    url_de: str | None
    difficulty: str
    domains: tuple[str, ...]
    notes: str | None
    notes_de: str | None
    email: str | None
    email_subject: str | None
    email_body: str | None

    @property
    def delete_url(self) -> str:
        return self.url_de or self.url

    @property
    def instructions(self) -> str | None:
        return self.notes_de or self.notes


def _safe_url(value) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    p = urlparse(value.strip())
    if p.scheme not in ("https", "http") or not p.netloc or "@" in p.netloc:
        return None
    return value.strip()


def _text(value, limit: int = 4000) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:limit]


class Catalog:
    def __init__(self, entries: list[JdmEntry], version: dict):
        self.entries = entries
        self.version = version
        self._by_name = {e.name: e for e in entries}
        self._by_domain: dict[str, JdmEntry] = {}
        for e in entries:
            for d in e.domains:
                # Bei Mehrfachbelegung gewinnt der erste Eintrag (Datei ist alphabetisch sortiert)
                self._by_domain.setdefault(d, e)

    def __len__(self) -> int:
        return len(self.entries)

    def by_name(self, name: str | None) -> JdmEntry | None:
        return self._by_name.get(name) if name else None

    def match_host(self, host: str) -> JdmEntry | None:
        """Sucht den Host und dann schrittweise seine übergeordneten Domains (mail.github.com → github.com)."""
        host = host.lower().rstrip(".")
        labels = host.split(".")
        for i in range(len(labels) - 1):
            candidate = ".".join(labels[i:])
            hit = self._by_domain.get(candidate)
            if hit:
                return hit
            hit = self._by_domain.get("www." + candidate)
            if hit:
                return hit
        return None


def load_catalog(data_dir: str | Path) -> Catalog:
    data_dir = Path(data_dir)
    raw = json.loads((data_dir / "sites.json").read_text(encoding="utf-8"))
    version = {}
    vf = data_dir / "VERSION.json"
    if vf.exists():
        version = json.loads(vf.read_text(encoding="utf-8"))
    entries: list[JdmEntry] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 200)
        url = _safe_url(item.get("url"))
        difficulty = item.get("difficulty")
        domains = item.get("domains")
        if not name or not url or difficulty not in DIFFICULTIES or not isinstance(domains, list):
            continue
        clean_domains = tuple(
            d.strip().lower().rstrip(".") for d in domains if isinstance(d, str) and re.fullmatch(r"[A-Za-z0-9.-]{3,253}", d.strip())
        )
        email = item.get("email") if isinstance(item.get("email"), str) and _EMAIL.match(item.get("email", "")) else None
        entries.append(
            JdmEntry(
                name=name,
                url=url,
                url_de=_safe_url(item.get("url_de")),
                difficulty=difficulty,
                domains=clean_domains,
                notes=_text(item.get("notes")),
                notes_de=_text(item.get("notes_de")),
                email=email,
                email_subject=_text(item.get("email_subject"), 300),
                email_body=_text(item.get("email_body")),
            )
        )
    return Catalog(entries, version)


@lru_cache
def get_catalog() -> Catalog:
    return load_catalog(get_settings().jdm_data_dir)
