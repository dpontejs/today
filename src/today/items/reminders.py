"""Reminders of an item (ADR 0006): many per item, stored in UTC, sent by the push loop."""

import sqlite3
from collections.abc import Iterable
from datetime import datetime

from today.items.repo import to_db

MAX_REMINDERS = 5


def clean_reminders(times: Iterable[datetime], due_at: datetime, now: datetime) -> list[datetime]:
    """Keep reminders between now and the due time, without duplicates, earliest first, at most five."""
    kept = sorted({t for t in times if now <= t <= due_at})
    return kept[:MAX_REMINDERS]


def add_reminders(conn: sqlite3.Connection, item_id: int, times: Iterable[datetime]) -> None:
    conn.executemany(
        "INSERT INTO reminders (item_id, remind_at) VALUES (?, ?) ON CONFLICT DO NOTHING",
        [(item_id, to_db(t)) for t in times],
    )


def list_reminders(conn: sqlite3.Connection, item_id: int) -> list[datetime]:
    rows = conn.execute(
        "SELECT remind_at FROM reminders WHERE item_id = ? ORDER BY remind_at", (item_id,)
    ).fetchall()
    return [datetime.fromisoformat(r["remind_at"]) for r in rows]
