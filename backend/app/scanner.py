"""Konten-Scan im Hintergrund: Kopfzeilen lesen → klassifizieren → zusammenführen → JDM-Abgleich."""
from __future__ import annotations

import logging
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from . import db as dbmod
from .detection.classifier import ACCOUNT_CATEGORIES, classify, combine
from .detection.headers import body_text, parse_raw
from .detection.resolver import identify
from .jdm.catalog import get_catalog
from .mail import imap_client
from .mail.accounts import credentials
from .models import Evidence, MailAccount, ScanJob, Service, utcnow

log = logging.getLogger("quitly.scan")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scan")
_lock = threading.Lock()

# Alle Ordner werden gescannt – auch Spam und Papierkorb (dort liegen oft alte Registrierungs-Mails)
SKIP_SPECIAL: set[str] = set()


class Cancelled(Exception):
    pass


@dataclass
class _Agg:
    display_name: str
    jdm_name: str | None
    domains: set[str] = field(default_factory=set)
    senders: set[str] = field(default_factory=set)
    names: Counter = field(default_factory=Counter)
    messages: int = 0
    evidence: list[dict] = field(default_factory=list)
    first: datetime | None = None
    last: datetime | None = None


def submit(job_id: int) -> None:
    _executor.submit(_run_safe, job_id)


def _run_safe(job_id: int) -> None:
    try:
        run(job_id)
    except Exception:  # Fehlerdetails nur generisch speichern – keine Server-Antworten mit evtl. Daten
        log.exception("scan job %s failed", job_id)
        with dbmod.new_session() as db:
            job = db.get(ScanJob, job_id)
            if job and job.status not in ("done", "cancelled"):
                job.status = "error"
                job.error = job.error or "Unerwarteter Fehler beim Scan."
                job.finished_at = utcnow()
                db.commit()


def _update(job_id: int, **fields) -> None:
    with dbmod.new_session() as db:
        job = db.get(ScanJob, job_id)
        if job is None:
            raise Cancelled()
        for k, v in fields.items():
            setattr(job, k, v)
        db.commit()
        if job.cancel_requested:
            raise Cancelled()


def _touch(agg: _Agg, when: datetime | None) -> None:
    if when is None:
        return
    if agg.first is None or when < agg.first:
        agg.first = when
    if agg.last is None or when > agg.last:
        agg.last = when


def run(job_id: int) -> None:
    with dbmod.new_session() as db:
        job = db.get(ScanJob, job_id)
        if job is None:
            return
        account = db.get(MailAccount, job.account_id)
        if account is None or account.user_id != job.user_id:
            job.status = "error"
            job.error = "Postfach nicht gefunden."
            db.commit()
            return
        creds = credentials(account)
        user_id, account_id, since_days = job.user_id, account.id, job.since_days
        host, port = account.imap_host, account.imap_port

    _update(job_id, status="running", step="fetch", progress=0.02)
    catalog = get_catalog()
    aggs: dict[str, _Agg] = {}
    seen = 0
    signals = 0
    try:
        since = None
        if since_days:
            since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
        with imap_client.connect(host, port, creds["username"], creds["secret"]) as client:
            folders = [f for f in imap_client.list_folders(client) if f.selectable and f.special not in SKIP_SPECIAL]
            plan = []
            for f in folders:
                _, uidvalidity = imap_client.select(client, f, readonly=True)
                uids = imap_client.search_uids(client, since)
                plan.append((f, uidvalidity, uids))
            total = sum(len(p[2]) for p in plan) or 1
            _update(job_id, messages_total=total, step="classify", progress=0.08)
            for f, uidvalidity, uids in plan:
                if not uids:
                    continue
                imap_client.select(client, f, readonly=True)
                for uid, head, body in imap_client.fetch_for_scan(client, uids):
                    seen += 1
                    h = parse_raw(head)
                    # Text nur im Speicher auswerten – wird nicht gespeichert
                    signals += _ingest(aggs, catalog, h, f.raw, uidvalidity, str(uid), body_text(head, body))
                    if seen % 250 == 0:
                        _update(job_id, messages_seen=seen, signals_found=signals, progress=0.08 + 0.8 * seen / total)
    except Cancelled:
        _finish(job_id, "cancelled")
        return
    except imap_client.ImapError as exc:
        _finish(job_id, "error", str(exc))
        with dbmod.new_session() as db:
            acc = db.get(MailAccount, account_id)
            if acc:
                acc.status, acc.last_error = "error", str(exc)[:300]
                db.commit()
        return

    _update(job_id, messages_seen=seen, signals_found=signals, step="merge", progress=0.9)
    _merge(user_id, account_id, aggs)
    _update(job_id, step="jdm", progress=0.97)
    with dbmod.new_session() as db:
        acc = db.get(MailAccount, account_id)
        if acc:
            acc.last_scan_at, acc.status, acc.last_error = utcnow(), "ok", ""
            db.commit()
    _finish(job_id, "done")


def _ingest(aggs: dict[str, _Agg], catalog, h, folder: str, uidvalidity: str, ref: str, text: str = "") -> int:
    ident = identify(h.from_domain, catalog, h.from_name)
    if ident is None:
        return 0
    agg = aggs.get(ident.key)
    if agg is None:
        agg = aggs[ident.key] = _Agg(display_name=ident.display_name, jdm_name=ident.jdm_name)
    agg.domains.add(ident.domain)
    agg.senders.add(h.from_addr)
    agg.messages += 1
    c = classify(h, text)
    if c is None:
        return 0
    _touch(agg, h.date)
    if _usable_name(h.from_name):
        agg.names[h.from_name] += 1
    agg.evidence.append({
        "folder": folder, "uidvalidity": uidvalidity, "msg_ref": ref, "category": c.category,
        "score": c.score, "sender_domain": h.from_domain, "received_at": h.date, "reasons": list(c.reasons),
    })
    return 1 if c.category not in WEAK_CATEGORIES else 0


_GENERIC_NAMES = {"noreply", "no-reply", "no reply", "info", "support", "team", "service", "newsletter", "admin"}


def _usable_name(name: str) -> bool:
    n = name.strip().lower()
    return 2 <= len(n) <= 60 and "@" not in n and n not in _GENERIC_NAMES and not n.startswith(("re:", "fwd:"))


WEAK_CATEGORIES = ("contact", "newsletter")
MAX_STRONG_EVIDENCE = 300
MAX_WEAK_EVIDENCE = 30


def _keep_evidence(evidence: list[dict]) -> list[dict]:
    """Alle aussagekräftigen Belege behalten, schwache (nur Mail/Newsletter) auf die neuesten begrenzen."""
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    by_date = sorted(evidence, key=lambda e: e["received_at"] or epoch, reverse=True)
    strong = [e for e in by_date if e["category"] not in WEAK_CATEGORIES][:MAX_STRONG_EVIDENCE]
    weak = [e for e in by_date if e["category"] in WEAK_CATEGORIES][:MAX_WEAK_EVIDENCE]
    return strong + weak


def _merge(user_id: int, account_id: int, aggs: dict[str, _Agg]) -> None:
    with dbmod.new_session() as db:
        # Beitrag dieses Postfachs neu aufbauen (Rescans sind idempotent); das Gedächtnis der Dienste bleibt
        db.execute(delete(Evidence).where(Evidence.account_id == account_id))
        existing = {s.key: s for s in db.execute(select(Service).where(Service.user_id == user_id)).scalars()}
        for svc in existing.values():
            if str(account_id) in (svc.sources or {}):
                src = dict(svc.sources)
                src.pop(str(account_id))
                svc.sources = src
        db.flush()

        for key, agg in aggs.items():
            svc = existing.get(key)
            sure = any(e["category"] in ACCOUNT_CATEGORIES for e in agg.evidence)
            if svc is None:
                if not sure:
                    continue  # nur sichere Hinweise legen einen Dienst an
                svc = Service(user_id=user_id, key=key, display_name=agg.display_name, jdm_name=agg.jdm_name,
                              domains=[], sources={}, signals={}, memory={}, status="offen")
                db.add(svc)
                db.flush()
                existing[key] = svc
            if not svc.jdm_name and agg.names:
                # Ohne JDM-Eintrag: häufigster Absendername ("Notion" statt "Makenotion")
                svc.display_name = agg.names.most_common(1)[0][0][:120]
            svc.domains = sorted(set(svc.domains or []) | agg.domains)
            src = dict(svc.sources or {})
            src[str(account_id)] = {"messages": agg.messages, "signals": len(agg.evidence), "senders": len(agg.senders)}
            svc.sources = src
            for e in _keep_evidence(agg.evidence):
                db.add(Evidence(user_id=user_id, account_id=account_id, service_id=svc.id, **e))
            if agg.first and (svc.first_seen is None or agg.first < _aware(svc.first_seen)):
                svc.first_seen = agg.first
            if agg.last and (svc.last_seen is None or agg.last > _aware(svc.last_seen)):
                svc.last_seen = agg.last
        db.flush()

        recompute(db, user_id)
        db.commit()


def _iso(dt: datetime | None) -> str | None:
    return _aware(dt).isoformat() if dt else None


def _from_iso(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        return _aware(datetime.fromisoformat(v))
    except ValueError:
        return None


def _remember(memory: dict, evs: list[Evidence]) -> dict:
    """Gedächtnis je Kategorie: Anzahl, bester Wert, erstes/letztes Datum. Wächst nur – gelöschte Mails
    lassen ein einmal erkanntes Konto nicht verschwinden."""
    mem = {k: dict(v) for k, v in (memory or {}).items()}
    current: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evs:
        current[ev.category].append(ev)
    for cat, items in current.items():
        m = mem.get(cat, {"count": 0, "best": 0.0, "first": None, "last": None})
        dates = [_aware(e.received_at) for e in items if e.received_at]
        m["count"] = max(int(m.get("count", 0)), len(items))
        m["best"] = round(max(float(m.get("best", 0.0)), max(e.score for e in items)), 3)
        if dates:
            first, last = min(dates), max(dates)
            old_first, old_last = _from_iso(m.get("first")), _from_iso(m.get("last"))
            m["first"] = _iso(min(first, old_first) if old_first else first)
            m["last"] = _iso(max(last, old_last) if old_last else last)
        mem[cat] = m
    return mem


def memory_confidence(memory: dict) -> float:
    scores = []
    for cat, m in (memory or {}).items():
        best = float(m.get("best", 0.0))
        scores.append(best)
        if cat not in WEAK_CATEGORIES and int(m.get("count", 0)) >= 2:
            scores.append(best * 0.5)
    return combine(scores) if scores else 0.0


def is_sure(memory: dict) -> bool:
    return any(cat in ACCOUNT_CATEGORIES for cat in (memory or {}))


LEAVING_CATEGORIES = ("deletion", "email_change")


def _last(memory: dict, cat: str) -> datetime | None:
    return _from_iso((memory.get(cat) or {}).get("last"))


def deletion_kind(memory: dict) -> str:
    """Woran das Ende erkannt wurde: echte Löschung oder Wechsel der E-Mail-Adresse weg von diesem Postfach."""
    d, e = _last(memory or {}, "deletion"), _last(memory or {}, "email_change")
    if "deletion" not in (memory or {}):
        return "email_changed"
    if e and (d is None or e > d):
        return "email_changed"
    return "deleted"


def leaving_detected(memory: dict) -> bool:
    """Gelöscht bzw. Adresse gewechselt – und danach kam keine aussagekräftige Konto-Mail mehr."""
    mem = memory or {}
    if not any(c in mem for c in LEAVING_CATEGORIES):
        return False
    leave_last = max((d for c in LEAVING_CATEGORIES for d in [_last(mem, c)] if d), default=None)
    other_last = max(
        (d for cat in mem if cat not in LEAVING_CATEGORIES and cat != "deletion_request" and cat not in WEAK_CATEGORIES
         for d in [_last(mem, cat)] if d),
        default=None,
    )
    if other_last is None:
        return True
    return leave_last is not None and leave_last >= other_last


CONFIRMING_CATEGORIES = tuple(c for c in ACCOUNT_CATEGORIES if c != "verification")


def unconfirmed(memory: dict) -> bool:
    """Nur eine Aufforderung zur Bestätigung kam – aber nie Willkommen, Login, Bestellung o. Ä.
    → vermutlich wurde die Registrierung nie abgeschlossen."""
    mem = memory or {}
    return "verification" in mem and not any(c in mem for c in CONFIRMING_CATEGORIES)


def _last_any(memory: dict) -> datetime | None:
    return max((d for cat in memory for d in [_last(memory, cat)] if d), default=None)


def _leave_at(memory: dict) -> datetime | None:
    return max((d for c in LEAVING_CATEGORIES for d in [_last(memory, c)] if d), default=None)


def _per_account(svc: Service) -> dict[str, dict]:
    return {k: v for k, v in (svc.account_memory or {}).items() if v}


def service_left(svc: Service) -> bool:
    """Pro Postfach statt global: Wechselt die Adresse von Postfach A nach B, ist das Konto bei A "gewechselt",
    bei B aber aktiv – insgesamt also nicht gelöscht. Erst wenn kein Postfach mehr aktiv ist, gilt es als beendet."""
    per = _per_account(svc)
    if not per:
        return leaving_detected(svc.memory or {})
    left = {k: leaving_detected(m) for k, m in per.items()}
    if not any(left.values()):
        return False
    leave_at = max((d for k, m in per.items() if left[k] for d in [_leave_at(m)] if d), default=None)
    for k, m in per.items():
        if left[k]:
            continue
        if is_sure(m):
            return False  # dort gibt es ein eigenes, aktives Konto (z. B. die neue Adresse)
        last = _last_any(m)
        if last and leave_at and last > leave_at:
            return False  # nach dem Wechsel kommen dort weiter Mails an
    return True


def service_leaving_kind(svc: Service) -> str:
    per = _per_account(svc)
    if not per:
        return deletion_kind(svc.memory or {})
    kinds = {deletion_kind(m) for m in per.values() if leaving_detected(m)}
    return "deleted" if "deleted" in kinds or not kinds else "email_changed"


def recompute(db, user_id: int) -> None:
    """Kennzahlen aller Dienste aus aktuellen Belegen + Gedächtnis neu berechnen."""
    existing = {s.key: s for s in db.execute(select(Service).where(Service.user_id == user_id)).scalars()}
    accounts = {str(a) for a in db.execute(select(MailAccount.id).where(MailAccount.user_id == user_id)).scalars()}
    by_service: dict[int, list[Evidence]] = defaultdict(list)
    by_account: dict[int, dict[str, list[Evidence]]] = defaultdict(lambda: defaultdict(list))
    for ev in db.execute(select(Evidence).where(Evidence.user_id == user_id)).scalars():
        by_service[ev.service_id].append(ev)
        by_account[ev.service_id][str(ev.account_id)].append(ev)
    now = utcnow()
    for svc in existing.values():
        if any(k not in accounts for k in (svc.sources or {})):
            svc.sources = {k: v for k, v in (svc.sources or {}).items() if k in accounts}
        evs = by_service.get(svc.id, [])
        svc.memory = _remember(svc.memory or {}, evs)
        old = {k: v for k, v in (svc.account_memory or {}).items() if k in accounts}
        current = by_account.get(svc.id, {})
        if svc.account_memory is None:
            # Erstes Mal (ältere Installation): bei genau einem Postfach gehört das bisherige Gedächtnis dorthin
            keys = (set(svc.sources or {}) | set(current)) & accounts
            if len(keys) == 1:
                old = {next(iter(keys)): dict(svc.memory or {})}
        svc.account_memory = {k: _remember(old.get(k, {}), current.get(k, [])) for k in set(old) | set(current)}
        src = svc.sources or {}
        svc.message_count = sum(int(v.get("messages", 0)) for v in src.values())
        svc.sender_count = sum(int(v.get("senders", 0)) for v in src.values())
        svc.signal_count = len(evs)
        svc.signals = {cat: int(m.get("count", 0)) for cat, m in svc.memory.items()}
        svc.confidence = memory_confidence(svc.memory)

        mem = svc.memory
        svc.deletion_detected = service_left(svc)
        if svc.deletion_detected and svc.status in ("offen", "angefragt"):
            svc.status, svc.status_changed_at, svc.status_auto = "geloescht", now, True
        elif not svc.deletion_detected and svc.status == "geloescht" and svc.status_auto:
            # automatisch gesetzt, trifft aber nicht mehr zu (z. B. Konto unter der neuen Adresse aktiv)
            svc.status = "angefragt" if "deletion_request" in mem else "offen"
            svc.status_changed_at = now
        elif "deletion_request" in mem and svc.status == "offen":
            svc.status, svc.status_changed_at, svc.status_auto = "angefragt", now, True

        if not is_sure(mem) and svc.status == "offen":
            # nie sicher erkannt (nur Newsletter/Kontakt) → verwerfen; Belege hängen per Fremdschlüssel daran
            db.execute(delete(Evidence).where(Evidence.service_id == svc.id))
            db.delete(svc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _finish(job_id: int, status: str, error: str = "") -> None:
    with dbmod.new_session() as db:
        job = db.get(ScanJob, job_id)
        if job:
            job.status = status
            job.error = error[:300]
            job.finished_at = utcnow()
            if status == "done":
                job.progress = 1.0
            db.commit()
