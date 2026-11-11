import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from today.db import MIGRATIONS_DIR, connect, migrate
from today.items.reminders import add_reminders, clean_reminders, list_reminders
from today.items.repo import ItemIn, create_item

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def test_migration_copies_remind_at(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    conn.execute("CREATE TABLE schema_version (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    conn.executescript((MIGRATIONS_DIR / "001_items.sql").read_text())
    conn.execute("INSERT INTO schema_version VALUES ('001_items.sql', 'x')")
    conn.execute(
        "INSERT INTO items (title, due_at, remind_at, created_at) VALUES ('a', ?, ?, ?)",
        ("2026-11-20T12:00:00+00:00", "2026-11-19T22:00:00+00:00", NOW.isoformat()),
    )

    assert migrate(conn) == ["002_reminders.sql"]

    rows = conn.execute("SELECT item_id, remind_at, sent_at FROM reminders").fetchall()
    assert [tuple(r) for r in rows] == [(1, "2026-11-19T22:00:00+00:00", None)]


def test_add_and_list_reminders_in_utc(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(days=10)), NOW)
    local = datetime.fromisoformat("2026-11-19T19:00:00-03:00")

    add_reminders(conn, item.id, [local, local])

    assert list_reminders(conn, item.id) == [datetime(2026, 11, 19, 22, 0, tzinfo=UTC)]
    row = conn.execute("SELECT remind_at FROM reminders").fetchone()
    assert row["remind_at"] == "2026-11-19T22:00:00+00:00"


def test_deleting_item_deletes_reminders(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(days=10)), NOW)
    add_reminders(conn, item.id, [NOW + timedelta(days=1)])

    conn.execute("DELETE FROM items WHERE id = ?", (item.id,))

    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0


def test_clean_reminders_drops_past_after_due_dupes_and_caps():
    due = NOW + timedelta(days=10)
    times = [
        NOW - timedelta(hours=1),  # past
        due + timedelta(hours=1),  # after the event
        NOW + timedelta(days=3),
        NOW + timedelta(days=1),
        NOW + timedelta(days=1),  # duplicate
        due,  # at the event time is fine
        NOW + timedelta(days=2),
        NOW + timedelta(days=4),
        NOW + timedelta(days=5),
    ]

    cleaned = clean_reminders(times, due_at=due, now=NOW)

    assert cleaned == [NOW + timedelta(days=d) for d in (1, 2, 3, 4, 5)]
