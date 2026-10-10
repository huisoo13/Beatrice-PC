"""Wednesday 06:00 Korea repetition reset; completion history is retained."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

KOREA = timezone(timedelta(hours=9))


def week_start(now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('시간대가 필요합니다.')
    local = now.astimezone(KOREA)
    start = local.replace(hour=6, minute=0, second=0, microsecond=0)
    start -= timedelta(days=(local.weekday()-2) % 7)
    if local < start:
        start -= timedelta(days=7)
    return start.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')


def database_path(data, now=None):
    return Path(data) / 'records.sqlite3'


def open_week(data, catalog=None, now=None):
    """One persistent history DB; recover all previous weekly databases without removing them."""
    from .storage import Store
    store = Store(database_path(data), catalog=catalog)
    try:
        store.recover_weekly_history(data, now)
        store.roll_week(now)
    except Exception:
        store.close()
        raise
    return store
