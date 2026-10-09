"""Fester-Fenster-Rate-Limiter in der Datenbank – funktioniert über mehrere Worker hinweg."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import RateLimitBucket


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hit(db: Session, key: str, limit: int, window: timedelta) -> tuple[bool, int]:
    """Zählt einen Versuch. Gibt (erlaubt, Sekunden bis Freigabe) zurück."""
    now = _now()
    bucket = db.execute(select(RateLimitBucket).where(RateLimitBucket.key == key).with_for_update()).scalar_one_or_none()
    if bucket is None:
        bucket = RateLimitBucket(key=key, window_start=now, count=0)
        db.add(bucket)
    elif _aware(bucket.window_start) + window <= now:
        bucket.window_start = now
        bucket.count = 0
    bucket.count += 1
    db.commit()
    if bucket.count > limit:
        retry = int((_aware(bucket.window_start) + window - now).total_seconds()) + 1
        return False, max(retry, 1)
    return True, 0


def is_blocked(db: Session, key: str, limit: int, window: timedelta) -> int:
    """Prüft ohne zu zählen. Gibt Sekunden bis Freigabe zurück (0 = frei)."""
    bucket = db.get(RateLimitBucket, key)
    if bucket is None:
        return 0
    end = _aware(bucket.window_start) + window
    if end <= _now() or bucket.count < limit:
        return 0
    return int((end - _now()).total_seconds()) + 1


def reset(db: Session, key: str) -> None:
    db.execute(delete(RateLimitBucket).where(RateLimitBucket.key == key))
    db.commit()


def cleanup(db: Session, older_than: timedelta = timedelta(days=1)) -> None:
    db.execute(delete(RateLimitBucket).where(RateLimitBucket.window_start < _now() - older_than))
    db.commit()
