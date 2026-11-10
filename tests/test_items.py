import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from today.items.repo import ItemIn, create_item, get_item, mark_done, reopen
from today.items.today import build_today

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # 09:00 in Fortaleza


def add(conn: sqlite3.Connection, title: str, due_at: datetime):
    return create_item(conn, ItemIn(title=title, due_at=due_at), now=NOW)


def titles(items) -> list[str]:
    return [i.title for i in items]


def test_create_item_stores_utc(conn: sqlite3.Connection):
    item = add(conn, "a", datetime(2026, 11, 11, 9, 0, tzinfo=TZ))
    row = conn.execute("SELECT due_at, created_at FROM items WHERE id = ?", (item.id,)).fetchone()
    assert row["due_at"] == "2026-11-11T12:00:00+00:00"
    assert row["created_at"] == "2026-11-10T12:00:00+00:00"
    assert item.due_at == datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    assert item.status == "open"
    assert item.source == "manual"


def test_buckets_split_late_today_next(conn: sqlite3.Connection):
    add(conn, "yesterday", NOW - timedelta(days=1))
    add(conn, "in one hour", NOW + timedelta(hours=1))
    add(conn, "in three days", NOW + timedelta(days=3))
    add(conn, "in ten days", NOW + timedelta(days=10))

    view = build_today(conn, NOW, TZ)

    assert titles(view.late) == ["yesterday"]
    assert titles(view.today) == ["in one hour"]
    assert titles(view.next) == ["in three days"]
    assert view.next_item_id == view.today[0].id


def test_bucket_boundary_uses_local_midnight(conn: sqlite3.Connection):
    now = datetime(2026, 11, 10, 23, 30, tzinfo=TZ)
    add(conn, "after midnight", datetime(2026, 11, 11, 0, 30, tzinfo=TZ))

    view = build_today(conn, now, TZ)

    assert view.today == []
    assert titles(view.next) == ["after midnight"]


def test_late_night_utc_next_day(conn: sqlite3.Connection):
    now = datetime(2026, 11, 10, 22, 0, tzinfo=TZ)  # already 2026-11-11 01:00 in UTC
    add(conn, "tonight", datetime(2026, 11, 10, 23, 30, tzinfo=TZ))

    view = build_today(conn, now, TZ)

    assert titles(view.today) == ["tonight"]
    assert view.next == []


def test_next_window_is_seven_local_days(conn: sqlite3.Connection):
    add(conn, "day 7", datetime(2026, 11, 17, 23, 0, tzinfo=TZ))
    add(conn, "day 8", datetime(2026, 11, 18, 0, 30, tzinfo=TZ))

    view = build_today(conn, NOW, TZ)

    assert titles(view.next) == ["day 7"]


def test_buckets_ordered_by_due(conn: sqlite3.Connection):
    add(conn, "later", NOW + timedelta(hours=5))
    add(conn, "sooner", NOW + timedelta(hours=1))

    view = build_today(conn, NOW, TZ)

    assert titles(view.today) == ["sooner", "later"]


def test_done_then_reopen_round_trip(conn: sqlite3.Connection):
    item = add(conn, "a", NOW + timedelta(hours=1))

    done = mark_done(conn, item.id, NOW)
    assert done is not None and done.status == "done" and done.done_at == NOW

    reopened = reopen(conn, item.id)
    assert reopened is not None and reopened.status == "open" and reopened.done_at is None


def test_done_is_idempotent(conn: sqlite3.Connection):
    item = add(conn, "a", NOW + timedelta(hours=1))
    mark_done(conn, item.id, NOW)

    again = mark_done(conn, item.id, NOW + timedelta(hours=2))

    assert again is not None and again.done_at == NOW


def test_missing_item_returns_none(conn: sqlite3.Connection):
    assert get_item(conn, 999) is None
    assert mark_done(conn, 999, NOW) is None
    assert reopen(conn, 999) is None


def test_done_today_listed_separately(conn: sqlite3.Connection):
    item = add(conn, "finished", NOW + timedelta(hours=1))
    old = add(conn, "finished last week", NOW - timedelta(days=7))
    mark_done(conn, item.id, NOW)
    mark_done(conn, old.id, NOW - timedelta(days=7))

    view = build_today(conn, NOW, TZ)

    assert view.today == []
    assert titles(view.done_today) == ["finished"]
    assert view.next_item_id is None
