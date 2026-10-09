"""Ordnet Absender-Domains einem Dienst zu und fasst Duplikate zusammen."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import tldextract

from ..jdm.catalog import Catalog
from .classifier import FREEMAIL

# Offline: nur die mitgelieferte Public-Suffix-Liste, keine Netzwerkzugriffe, kein Cache auf Platte
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


@lru_cache(maxsize=50000)
def registrable_domain(host: str) -> str:
    r = _extract(host)
    if not r.suffix or not r.domain:
        return ""
    return f"{r.domain}.{r.suffix}".lower()


@dataclass(frozen=True)
class ServiceIdentity:
    key: str
    display_name: str
    jdm_name: str | None
    domain: str


def identify(host: str, catalog: Catalog, display_name: str = "") -> ServiceIdentity | None:
    host = (host or "").lower()
    reg = registrable_domain(host)
    if not reg or reg in FREEMAIL:
        return None
    # 1. Domain (inkl. übergeordneter Domains) im JDM-Katalog  2. Markenname aus Absendername/Domain
    entry = catalog.match_host(host) or catalog.match_brand(display_name, reg.split(".", 1)[0])
    if entry is not None:
        # Mehrere Domains desselben Dienstes (z. B. e.foundation, ecloud.global) → ein Dienst
        return ServiceIdentity(key=f"jdm:{entry.name}", display_name=entry.name, jdm_name=entry.name, domain=reg)
    label = reg.split(".", 1)[0]
    pretty = label.replace("-", " ").title() if label.isascii() else label
    return ServiceIdentity(key=f"domain:{reg}", display_name=pretty, jdm_name=None, domain=reg)
