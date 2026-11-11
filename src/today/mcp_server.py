"""MCP server: list, create, edit, complete, reopen and delete items from AI clients (ADR 0005).

The tool logic lives in plain functions over a connection (easy to test); `build_mcp` wraps them as MCP tools
and `mount_mcp` serves them at `/mcp` behind a bearer token. Stateless HTTP with JSON responses: every call
stands alone, which fits one process (ADR 0001) and short tools.
"""

import hmac
import sqlite3
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from today.items.reminders import add_reminders, clean_reminders, list_reminders, replace_unsent_reminders
from today.items.repo import Item, ItemIn, insert_item, mark_done, reopen
from today.items.repo import delete_item as delete_row
from today.items.repo import update_item as update_row
from today.items.today import build_today

MAX_BATCH = 100
SOURCE = "mcp"


class DraftIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime = Field(description="ISO 8601. Without an offset it is America/Fortaleza local time.")
    notes: str | None = Field(default=None, max_length=2000)
    source_key: str | None = Field(
        default=None,
        max_length=200,
        description="Stable id for imports, e.g. 'roadmap:M0:book-ch-1-2'. An existing key is skipped.",
    )
    reminders: list[datetime] = Field(
        default=[],
        description="When to notify (ISO 8601, local if no offset). Past and after-due_at ones are dropped.",
    )


class ItemOut(BaseModel):
    id: int
    title: str
    notes: str | None
    due_at: str = Field(description="ISO 8601 in America/Fortaleza")
    status: Literal["open", "done"]
    source: str
    source_key: str | None
    reminders: list[str] = Field(description="Notification times, ISO 8601 in America/Fortaleza")


class Deleted(BaseModel):
    deleted: int


class ItemsByBucket(BaseModel):
    late: list[ItemOut]
    today: list[ItemOut]
    next: list[ItemOut]
    done_today: list[ItemOut]


class CreateResult(BaseModel):
    created: list[ItemOut]
    skipped_source_keys: list[str]


def _local(value: datetime, tz: ZoneInfo) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=tz)


def _parse(value: str, tz: ZoneInfo, field: str) -> datetime:
    try:
        return _local(datetime.fromisoformat(value), tz)
    except ValueError:
        raise ValueError(f"{field} must be ISO 8601, e.g. 2026-11-20T09:00") from None


def _out(conn: sqlite3.Connection, item: Item, tz: ZoneInfo) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "notes": item.notes,
        "due_at": item.due_at.astimezone(tz).isoformat(),
        "status": item.status,
        "source": item.source,
        "source_key": item.source_key,
        "reminders": [r.astimezone(tz).isoformat() for r in list_reminders(conn, item.id)],
    }


# --- tool logic ------------------------------------------------------------------------------------


def list_items(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo, days: int = 7) -> dict:
    if not 1 <= days <= 60:
        raise ValueError("days must be between 1 and 60")
    view = build_today(conn, now, tz, next_days=days)
    return {
        "late": [_out(conn, i, tz) for i in view.late],
        "today": [_out(conn, i, tz) for i in view.today],
        "next": [_out(conn, i, tz) for i in view.next],
        "done_today": [_out(conn, i, tz) for i in view.done_today],
    }


def create_items(conn: sqlite3.Connection, drafts: list[DraftIn], now: datetime, tz: ZoneInfo) -> dict:
    if len(drafts) > MAX_BATCH:
        raise ValueError(f"send at most {MAX_BATCH} items per call")
    created, skipped = [], []
    for d in drafts:
        due = _local(d.due_at, tz)
        data = ItemIn(title=d.title.strip(), due_at=due, notes=d.notes)
        item = insert_item(conn, data, now, source=SOURCE, source_key=d.source_key)
        if item is None:
            skipped.append(d.source_key)
            continue
        times = clean_reminders([_local(r, tz) for r in d.reminders], due_at=due, now=now)
        add_reminders(conn, item.id, times)
        created.append(_out(conn, item, tz))
    return {"created": created, "skipped_source_keys": skipped}


def complete_item(conn: sqlite3.Connection, item_id: int, now: datetime, tz: ZoneInfo) -> dict:
    item = mark_done(conn, item_id, now)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    return _out(conn, item, tz)


def reopen_item(conn: sqlite3.Connection, item_id: int, tz: ZoneInfo) -> dict:
    item = reopen(conn, item_id)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    return _out(conn, item, tz)


def update_item(
    conn: sqlite3.Connection,
    item_id: int,
    now: datetime,
    tz: ZoneInfo,
    title: str | None = None,
    due_at: str | None = None,
    notes: str | None = None,
    reminders: list[str] | None = None,
) -> dict:
    """Change only what is given. `notes=""` clears the notes; `reminders` replaces the unsent ones."""
    if title is None and due_at is None and notes is None and reminders is None:
        raise ValueError("nothing to update: pass title, due_at, notes or reminders")
    changes: dict = {}
    if title is not None:
        if not title.strip() or len(title.strip()) > 200:
            raise ValueError("title must have 1 to 200 characters")
        changes["title"] = title.strip()
    if due_at is not None:
        changes["due_at"] = _parse(due_at, tz, "due_at")
    if notes is not None:
        changes["notes"] = notes.strip()[:2000] or None
    times = [_parse(r, tz, "reminders") for r in reminders] if reminders is not None else None

    item = update_row(conn, item_id, changes)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    if times is not None:
        replace_unsent_reminders(conn, item_id, clean_reminders(times, due_at=item.due_at, now=now))
    return _out(conn, item, tz)


def delete_item(conn: sqlite3.Connection, item_id: int) -> dict:
    if not delete_row(conn, item_id):
        raise ValueError(f"item {item_id} not found")
    return {"deleted": item_id}


# --- MCP wiring ------------------------------------------------------------------------------------


def build_mcp(app: FastAPI) -> MCPServer:
    """Tools read the connection, clock and zone from `app.state` at call time (tests swap the clock)."""
    server = MCPServer(
        "today",
        instructions=(
            "Personal reminders and to-dos of one user in America/Fortaleza. "
            "Times without an offset are local. Use source_key when importing from a document, "
            "so running the import again does not duplicate items."
        ),
    )
    state = app.state

    def tz() -> ZoneInfo:
        return state.settings.tz

    def guarded(fn, *args):
        try:
            return fn(*args)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="list_items",
        description="Open items split into late, today and the next `days` days, plus items done today.",
    )
    def list_items_tool(days: int = 7) -> ItemsByBucket:
        return ItemsByBucket(**guarded(list_items, state.conn, state.clock(), tz(), days))

    @server.tool(
        name="create_items",
        description=f"Create up to {MAX_BATCH} items. Items whose source_key already exists are skipped.",
    )
    def create_items_tool(items: list[DraftIn]) -> CreateResult:
        return CreateResult(**guarded(create_items, state.conn, items, state.clock(), tz()))

    @server.tool(
        name="complete_item",
        description="Mark an item as done. Doing it twice keeps the first completion time.",
    )
    def complete_item_tool(id: int) -> ItemOut:
        return ItemOut(**guarded(complete_item, state.conn, id, state.clock(), tz()))

    @server.tool(name="reopen_item", description="Reopen an item that was marked as done.")
    def reopen_item_tool(id: int) -> ItemOut:
        return ItemOut(**guarded(reopen_item, state.conn, id, tz()))

    @server.tool(
        name="update_item",
        description=(
            "Edit an item: pass only what changes. Times are ISO 8601 (local if no offset). notes='' clears "
            "the notes. reminders replaces the reminders not sent yet."
        ),
    )
    def update_item_tool(
        id: int,
        title: str | None = None,
        due_at: str | None = None,
        notes: str | None = None,
        reminders: list[str] | None = None,
    ) -> ItemOut:
        return ItemOut(
            **guarded(update_item, state.conn, id, state.clock(), tz(), title, due_at, notes, reminders)
        )

    @server.tool(name="delete_item", description="Delete an item and its reminders. Cannot be undone.")
    def delete_item_tool(id: int) -> Deleted:
        return Deleted(**guarded(delete_item, state.conn, id))

    return server


class BearerGuard:
    """ASGI wrapper: 401 unless `Authorization: Bearer <token>` matches (constant-time comparison)."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", []))
        if not hmac.compare_digest(headers.get(b"authorization", b""), self.expected):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def mount_mcp(app: FastAPI, token: str) -> MCPServer:
    server = build_mcp(app)
    # host="0.0.0.0" turns off the SDK's localhost-only Host check: the app is served as today.diegoponte.dev
    # and the bearer token is the protection.
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, host="0.0.0.0"
    )
    (route,) = [r for r in mcp_app.routes if getattr(r, "path", None) == "/mcp"]
    app.router.add_route("/mcp", BearerGuard(route.endpoint, token), methods=["GET", "POST", "DELETE"])
    return server
