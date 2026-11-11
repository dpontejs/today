"""Item storage: plain SQL over the `items` table. All datetimes in and out are aware; stored as UTC."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import AwareDatetime, BaseModel, Field


class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime
    remind_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


@dataclass(frozen=True)
class Item:
    id: int
    title: str
    notes: str | None
    due_at: datetime
    remind_at: datetime | None
    status: str
    done_at: datetime | None
    source: str
    source_key: str | None
    created_at: datetime


def to_db(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def row_to_item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        title=row["title"],
        notes=row["notes"],
        due_at=datetime.fromisoformat(row["due_at"]),
        remind_at=_from_db(row["remind_at"]),
        status=row["status"],
        done_at=_from_db(row["done_at"]),
        source=row["source"],
        source_key=row["source_key"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def insert_item(
    conn: sqlite3.Connection,
    data: ItemIn,
    now: datetime,
    source: str = "manual",
    source_key: str | None = None,
) -> Item | None:
    """Insert one item. With a `source_key` that already exists, nothing is inserted and None is returned."""
    row = conn.execute(
        """INSERT INTO items (title, notes, due_at, remind_at, source, source_key, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (source_key) DO NOTHING
           RETURNING *""",
        (
            data.title,
            data.notes,
            to_db(data.due_at),
            to_db(data.remind_at) if data.remind_at else None,
            source,
            source_key,
            to_db(now),
        ),
    ).fetchone()
    return row_to_item(row) if row else None


def create_item(conn: sqlite3.Connection, data: ItemIn, now: datetime) -> Item:
    item = insert_item(conn, data, now)
    assert item is not None  # no source_key, so no conflict is possible
    return item


def get_item(conn: sqlite3.Connection, item_id: int) -> Item | None:
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return row_to_item(row) if row else None


def mark_done(conn: sqlite3.Connection, item_id: int, now: datetime) -> Item | None:
    """Idempotent: an item already done keeps its original `done_at`."""
    conn.execute(
        "UPDATE items SET status = 'done', done_at = ? WHERE id = ? AND status = 'open'",
        (to_db(now), item_id),
    )
    return get_item(conn, item_id)


def reopen(conn: sqlite3.Connection, item_id: int) -> Item | None:
    conn.execute("UPDATE items SET status = 'open', done_at = NULL WHERE id = ?", (item_id,))
    return get_item(conn, item_id)


UPDATABLE = ("title", "due_at", "notes")


def update_item(conn: sqlite3.Connection, item_id: int, changes: dict) -> Item | None:
    """Set only the given columns (`title`, `due_at` aware datetime, `notes` str or None)."""
    unknown = set(changes) - set(UPDATABLE)
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}")
    if changes:
        values = {k: to_db(v) if k == "due_at" else v for k, v in changes.items()}
        assignments = ", ".join(f"{column} = ?" for column in values)  # names come from UPDATABLE only
        conn.execute(f"UPDATE items SET {assignments} WHERE id = ?", (*values.values(), item_id))
    return get_item(conn, item_id)


def delete_item(conn: sqlite3.Connection, item_id: int) -> bool:
    """Delete an item; its reminders go with it (ON DELETE CASCADE)."""
    return conn.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0
