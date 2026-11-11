"""HTTP routes for items: the Today page, the add form, and done/reopen fragments for HTMX."""

from datetime import datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from today import notify
from today.auth import require_session
from today.items.reminders import add_reminders, clean_reminders
from today.items.repo import Item, ItemIn, create_item, mark_done, reopen
from today.items.today import build_today, row_kind

router = APIRouter(dependencies=[Depends(require_session)])

FORM_DATETIME = "%Y-%m-%dT%H:%M"


def parse_local_datetime(value: str, tz: ZoneInfo) -> datetime | None:
    """`<input type="datetime-local">` sends a naive local time: attach the user's zone, never UTC."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _default_due(now: datetime, tz: ZoneInfo) -> str:
    next_hour = now.astimezone(tz).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_hour.strftime(FORM_DATETIME)


DAY_CHOICES = (7, 14, 30)
DAYS_COOKIE = "today_days"


def _days(request: Request) -> int:
    for raw in (request.query_params.get("days"), request.cookies.get(DAYS_COOKIE)):
        if raw and raw.isdigit() and int(raw) in DAY_CHOICES:
            return int(raw)
    return DAY_CHOICES[0]


def _render_page(
    request: Request, status_code: int = 200, errors: dict | None = None, form: dict | None = None
) -> HTMLResponse:
    settings, conn = request.app.state.settings, request.app.state.conn
    now = request.app.state.clock()
    days = _days(request)
    view = build_today(conn, now, settings.tz, next_days=days)
    response = request.app.state.templates.TemplateResponse(
        request,
        "today.html",
        {
            "active_tab": "today",
            "view": view,
            "now": now.astimezone(settings.tz),
            "days": days,
            "day_choices": DAY_CHOICES,
            "late_rows": [(i, "late", False) for i in view.late],
            "today_rows": [(i, "today", i.id == view.next_item_id) for i in view.today]
            + [(i, "done", False) for i in view.done_today],
            "next_rows": [(i, "next", False) for i in view.next],
            "errors": errors or {},
            "form": form or {"title": "", "due_at": _default_due(now, settings.tz)},
            "capture_enabled": request.app.state.extractor is not None,
            "push": notify.status(conn) if request.app.state.push_sender else None,
        },
        status_code=status_code,
    )
    if request.query_params.get("days") == str(days):
        response.set_cookie(
            DAYS_COOKIE,
            str(days),
            max_age=365 * 24 * 3600,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
        )
    return response


def _render_row(request: Request, item: Item) -> HTMLResponse:
    settings = request.app.state.settings
    kind = row_kind(item, request.app.state.clock(), settings.tz)
    return request.app.state.templates.TemplateResponse(
        request, "_row.html", {"item": item, "kind": kind, "is_next": False}
    )


@router.get("/", response_class=HTMLResponse)
def today_page(request: Request) -> HTMLResponse:
    return _render_page(request)


@router.post("/items", response_class=HTMLResponse)
def create(
    request: Request,
    title: Annotated[str, Form()] = "",
    due_at: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
) -> Response:
    settings = request.app.state.settings
    form = {"title": title, "due_at": due_at}
    errors = {}
    if not title.strip():
        errors["title"] = "error_title_required"
    due = parse_local_datetime(due_at, settings.tz)
    if due is None:
        errors["due_at"] = "error_pick_date"
    if errors:
        return _render_page(request, 422, errors, form)

    try:
        data = ItemIn(title=title.strip(), due_at=due, notes=notes.strip() or None)
    except ValidationError:
        return _render_page(request, 422, {"title": "error_title_too_long"}, form)
    now = request.app.state.clock()
    item = create_item(request.app.state.conn, data, now)
    add_reminders(
        request.app.state.conn, item.id, clean_reminders([item.due_at], due_at=item.due_at, now=now)
    )
    return RedirectResponse("/", status_code=303)


@router.post("/items/{item_id}/done", response_class=HTMLResponse)
def done(request: Request, item_id: int) -> HTMLResponse:
    item = mark_done(request.app.state.conn, item_id, request.app.state.clock())
    if item is None:
        raise HTTPException(status_code=404)
    return _render_row(request, item)


@router.post("/items/{item_id}/reopen", response_class=HTMLResponse)
def reopen_item(request: Request, item_id: int) -> HTMLResponse:
    item = reopen(request.app.state.conn, item_id)
    if item is None:
        raise HTTPException(status_code=404)
    return _render_row(request, item)
