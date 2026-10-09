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
from .detection.classifier import classify, combine
from .detection.headers import body_text, from_mapping, parse_raw
from .detection.resolver import identify
from .jdm.catalog import get_catalog
from .mail import gmail_client, imap_client
from .mail.accounts import credentials
from .models import Evidence, MailAccount, ScanJob, Service, utcnow

log = logging.getLogger("quitly.scan")

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="scan")
_lock = threading.Lock()

# Gmail: neueste Nachrichten (jede einzeln per API); Text-Anfang kommt aus dem "snippet"
GMAIL_LIMIT = 5000
SKIP_SPECIAL = {"trash", "junk"}


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
        provider, user_id, account_id, since_days = account.provider, job.user_id, account.id, job.since_days
        host, port = account.imap_host, account.imap_port

    _update(job_id, status="running", step="fetch", progress=0.02)
    catalog = get_catalog()
    aggs: dict[str, _Agg] = {}
    seen = 0
    signals = 0
    try:
        if provider == "imap":
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
        else:
            with gmail_client.GmailClient(creds["secret"]) as g:
                q = f"newer_than:{since_days}d" if since_days else None
                ids = list(g.iter_message_ids(query=q, limit=GMAIL_LIMIT))
                total = len(ids) or 1
                _update(job_id, messages_total=len(ids), step="classify", progress=0.08)
                for msg_id in ids:
                    m = g.metadata(msg_id)
                    seen += 1
                    h = from_mapping(m.headers)
                    if h.date is None and m.internal_date_ms:
                        h.date = datetime.fromtimestamp(m.internal_date_ms / 1000, tz=timezone.utc)
                    signals += _ingest(aggs, catalog, h, "ALL", "", m.id, m.snippet)
                    if seen % 50 == 0:
                        _update(job_id, messages_seen=seen, signals_found=signals, progress=0.08 + 0.8 * seen / total)
    except Cancelled:
        _finish(job_id, "cancelled")
        return
    except (imap_client.ImapError, gmail_client.GmailError) as exc:
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
        # Beitrag dieses Postfachs neu aufbauen (Rescans sind idempotent)
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
            if svc is None:
                svc = Service(user_id=user_id, key=key, display_name=agg.display_name, jdm_name=agg.jdm_name,
                              domains=[], sources={}, signals={}, status="offen")
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


def recompute(db, user_id: int) -> None:
    """Kennzahlen aller Dienste eines Nutzers aus Belegen und Postfach-Beiträgen neu berechnen."""
    existing = {s.key: s for s in db.execute(select(Service).where(Service.user_id == user_id)).scalars()}
    accounts = {str(a) for a in db.execute(select(MailAccount.id).where(MailAccount.user_id == user_id)).scalars()}
    for svc in existing.values():
        # Beiträge entfernter Postfächer verwerfen
        if any(k not in accounts for k in (svc.sources or {})):
            svc.sources = {k: v for k, v in (svc.sources or {}).items() if k in accounts}
    by_service: dict[int, list[Evidence]] = defaultdict(list)
    for ev in db.execute(select(Evidence).where(Evidence.user_id == user_id)).scalars():
        by_service[ev.service_id].append(ev)
    for svc in existing.values():
        evs = by_service.get(svc.id, [])
        src = svc.sources or {}
        svc.message_count = sum(int(v.get("messages", 0)) for v in src.values())
        svc.sender_count = sum(int(v.get("senders", 0)) for v in src.values())
        svc.signal_count = len(evs)
        counts: dict[str, int] = defaultdict(int)
        for ev in evs:
            counts[ev.category] += 1
        svc.signals = dict(counts)
        # Stärkste Hinweise je Kategorie kombinieren (gleiche Kategorie zählt nur begrenzt mehrfach)
        best: dict[str, list[float]] = defaultdict(list)
        for ev in sorted(evs, key=lambda x: -x.score):
            limit = 1 if ev.category in WEAK_CATEGORIES else 2
            if len(best[ev.category]) < limit:
                best[ev.category].append(ev.score * (1.0 if not best[ev.category] else 0.5))
        svc.confidence = combine([s for v in best.values() for s in v]) if evs else 0.0
        deletions = [ev for ev in evs if ev.category == "deletion"]
        others = [ev for ev in evs if ev.category != "deletion" and ev.received_at]
        if deletions:
            last_del = max((_aware(d.received_at) for d in deletions if d.received_at), default=None)
            last_other = max((_aware(o.received_at) for o in others), default=None)
            svc.deletion_detected = last_other is None or (last_del is not None and last_del >= last_other)
        else:
            svc.deletion_detected = False
        if svc.deletion_detected and svc.status == "offen":
            svc.status = "geloescht"
            svc.status_changed_at = utcnow()
        if not src and svc.status == "offen":
            db.delete(svc)  # keine Belege mehr und nie bearbeitet → verwerfen


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
