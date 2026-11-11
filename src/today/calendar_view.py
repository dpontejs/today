"""The Calendar tab: a month grid (Monday first) with per-day counts, and the items of the chosen day."""

import sqlite3
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from today.auth import require_session
from today.items.repo import Item, row_to_item, to_db
from today.items.today import row_kind


@dataclass(frozen=True)
class Cell:
    day: date
    in_month: bool
    count: int  # open items due that local day
    done: int
    late: bool  # an open item of that day is already overdue
    is_today: bool


def _local_midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time.min, tzinfo=tz)


def _items_between(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[Item]:
    rows = conn.execute(
        "SELECT * FROM items WHERE due_at >= ? AND due_at < ? ORDER BY due_at, id", (to_db(start), to_db(end))
    ).fetchall()
    return [row_to_item(r) for r in rows]


def month_grid(
    conn: sqlite3.Connection, year: int, month: int, now: datetime, tz: ZoneInfo
) -> list[list[Cell]]:
    first = date(year, month, 1)
    last = date(year, month, monthrange(year, month)[1])
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=6 - last.weekday())
    items = _items_between(
        conn, _local_midnight(grid_start, tz), _local_midnight(grid_end + timedelta(days=1), tz)
    )

    by_day: dict[date, list[Item]] = {}
    for item in items:
        by_day.setdefault(item.due_at.astimezone(tz).date(), []).append(item)
    today = now.astimezone(tz).date()

    cells = []
    day = grid_start
    while day <= grid_end:
        its = by_day.get(day, [])
        open_items = [i for i in its if i.status == "open"]
        cells.append(
            Cell(
                day=day,
                in_month=day.month == month,
                count=len(open_items),
                done=len(its) - len(open_items),
                late=any(i.due_at < now for i in open_items),
                is_today=day == today,
            )
        )
        day += timedelta(days=1)
    return [cells[i : i + 7] for i in range(0, len(cells), 7)]


def items_on(conn: sqlite3.Connection, day: date, tz: ZoneInfo) -> list[Item]:
    start = _local_midnight(day, tz)
    return _items_between(conn, start, start + timedelta(days=1))


def calendar_url(month: date, day: date | None = None) -> str:
    params = {"month": month.strftime("%Y-%m")}
    if day:
        params["day"] = day.isoformat()
    return "/calendar?" + urlencode(params)


def _parse_month(value: str | None) -> date | None:
    try:
        return datetime.strptime(value or "", "%Y-%m").date()
    except ValueError:
        return None


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


router = APIRouter(dependencies=[Depends(require_session)])


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    month: Annotated[str | None, Query()] = None,
    day: Annotated[str | None, Query()] = None,
) -> HTMLResponse:
    conn, tz = request.app.state.conn, request.app.state.settings.tz
    now = request.app.state.clock()
    today = now.astimezone(tz).date()

    shown = _parse_month(month)
    selected = _parse_day(day)
    if shown is None:  # no month or a bad one: this month, today selected
        shown, selected = today.replace(day=1), today
    elif selected is None and shown == today.replace(day=1):
        selected = today
    if selected is not None and (selected.year, selected.month) != (shown.year, shown.month):
        selected = None

    weeks = month_grid(conn, shown.year, shown.month, now, tz)
    prev_month = (shown - timedelta(days=1)).replace(day=1)
    next_month = (shown + timedelta(days=32)).replace(day=1)
    day_items = items_on(conn, selected, tz) if selected else []
    return request.app.state.templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "active_tab": "calendar",
            "month": shown,
            "weeks": weeks,
            "month_total": sum(c.count + c.done for w in weeks for c in w if c.in_month),
            "selected": selected,
            "rows": [(item, row_kind(item, now, tz)) for item in day_items],
            "prev_url": calendar_url(prev_month),
            "next_url": calendar_url(next_month),
            "cell_url": lambda d: calendar_url(shown, d),
        },
    )
