"""The Today view: open items split into late / today / next, by the user's local calendar day."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from today.items.repo import Item, row_to_item, to_db

NEXT_DAYS = 7


@dataclass(frozen=True)
class TodayView:
    late: list[Item]
    today: list[Item]
    next: list[Item]
    done_today: list[Item]
    next_item_id: int | None


def local_day_bounds(now: datetime, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Start of the local day `now` falls in, and start of the next one (aware, in `tz`)."""
    start = datetime.combine(now.astimezone(tz).date(), time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def _select(conn: sqlite3.Connection, where: str, params: tuple, order: str = "due_at") -> list[Item]:
    rows = conn.execute(f"SELECT * FROM items WHERE {where} ORDER BY {order}, id", params).fetchall()
    return [row_to_item(r) for r in rows]


def build_today(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo) -> TodayView:
    day_start, day_end = local_day_bounds(now, tz)
    next_end = day_end + timedelta(days=NEXT_DAYS)
    now_s, end_s = to_db(now), to_db(day_end)

    late = _select(conn, "status = 'open' AND due_at < ?", (now_s,))
    today = _select(conn, "status = 'open' AND due_at >= ? AND due_at < ?", (now_s, end_s))
    upcoming = _select(conn, "status = 'open' AND due_at >= ? AND due_at < ?", (end_s, to_db(next_end)))
    done_today = _select(
        conn, "status = 'done' AND done_at >= ? AND done_at < ?", (to_db(day_start), end_s), order="done_at"
    )
    return TodayView(
        late=late,
        today=today,
        next=upcoming,
        done_today=done_today,
        next_item_id=today[0].id if today else None,
    )


def row_kind(item: Item, now: datetime, tz: ZoneInfo) -> str:
    """Which bucket a single item belongs to now: 'done', 'late', 'today' or 'next'."""
    if item.status == "done":
        return "done"
    if item.due_at < now:
        return "late"
    return "today" if item.due_at < local_day_bounds(now, tz)[1] else "next"
