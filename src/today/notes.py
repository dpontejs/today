"""The Notes tab: a notepad of free notes, not tied to a date (no reminders, no due time)."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from today.auth import require_session
from today.items.repo import to_db

MAX_BODY = 5000


@dataclass(frozen=True)
class Note:
    id: int
    body: str
    pinned: bool
    created_at: datetime
    updated_at: datetime


def _row(row: sqlite3.Row) -> Note:
    return Note(
        id=row["id"],
        body=row["body"],
        pinned=bool(row["pinned"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def create_note(conn: sqlite3.Connection, body: str, now: datetime) -> Note:
    row = conn.execute(
        "INSERT INTO notes (body, created_at, updated_at) VALUES (?, ?, ?) RETURNING *",
        (body, to_db(now), to_db(now)),
    ).fetchone()
    return _row(row)


def get_note(conn: sqlite3.Connection, note_id: int) -> Note | None:
    row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
    return _row(row) if row else None


def list_notes(conn: sqlite3.Connection) -> list[Note]:
    rows = conn.execute("SELECT * FROM notes ORDER BY pinned DESC, updated_at DESC, id DESC").fetchall()
    return [_row(r) for r in rows]


def update_note(conn: sqlite3.Connection, note_id: int, body: str, now: datetime) -> Note | None:
    row = conn.execute(
        "UPDATE notes SET body = ?, updated_at = ? WHERE id = ? RETURNING *", (body, to_db(now), note_id)
    ).fetchone()
    return _row(row) if row else None


def set_pinned(conn: sqlite3.Connection, note_id: int, pinned: bool) -> Note | None:
    """Pinning does not count as an edit: `updated_at` stays."""
    row = conn.execute(
        "UPDATE notes SET pinned = ? WHERE id = ? RETURNING *", (int(pinned), note_id)
    ).fetchone()
    return _row(row) if row else None


def delete_note(conn: sqlite3.Connection, note_id: int) -> bool:
    return conn.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


def clean_body(raw: str) -> str | None:
    """Trim; None when empty or longer than MAX_BODY."""
    body = raw.strip()
    return body if 0 < len(body) <= MAX_BODY else None


# --- routes ----------------------------------------------------------------------------------------

router = APIRouter(dependencies=[Depends(require_session)])


def _render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(request, template, context, status_code=status_code)


def _found(request: Request, note_id: int) -> Note:
    note = get_note(request.app.state.conn, note_id)
    if note is None:
        raise HTTPException(status_code=404)
    return note


@router.get("/notes", response_class=HTMLResponse)
def notes_page(request: Request) -> HTMLResponse:
    return _render(
        request, "notes.html", active_tab="notes", notes=list_notes(request.app.state.conn), error=None
    )


@router.post("/notes", response_class=HTMLResponse)
def add_note(request: Request, body: Annotated[str, Form()] = "") -> Response:
    conn = request.app.state.conn
    cleaned = clean_body(body)
    if cleaned is None:
        return _render(
            request,
            "notes.html",
            422,
            active_tab="notes",
            notes=list_notes(conn),
            error="note_invalid",
            draft=body,
        )
    create_note(conn, cleaned, request.app.state.clock())
    return RedirectResponse("/notes", status_code=303)


@router.get("/notes/{note_id}", response_class=HTMLResponse)
def show_note(request: Request, note_id: int) -> HTMLResponse:
    return _render(request, "_note.html", note=_found(request, note_id))


@router.get("/notes/{note_id}/edit", response_class=HTMLResponse)
def edit_note(request: Request, note_id: int) -> HTMLResponse:
    note = _found(request, note_id)
    return _render(request, "_note_edit.html", note=note, draft=note.body, error=None)


@router.post("/notes/{note_id}", response_class=HTMLResponse)
def save_note(request: Request, note_id: int, body: Annotated[str, Form()] = "") -> HTMLResponse:
    note = _found(request, note_id)
    cleaned = clean_body(body)
    if cleaned is None:
        return _render(request, "_note_edit.html", 422, note=note, draft=body, error="note_invalid")
    return _render(
        request,
        "_note.html",
        note=update_note(request.app.state.conn, note_id, cleaned, request.app.state.clock()),
    )


@router.post("/notes/{note_id}/pin", response_class=HTMLResponse)
def toggle_pin(request: Request, note_id: int) -> HTMLResponse:
    note = _found(request, note_id)
    return _render(request, "_note.html", note=set_pinned(request.app.state.conn, note_id, not note.pinned))


@router.post("/notes/{note_id}/delete")
def remove_note(request: Request, note_id: int) -> Response:
    _found(request, note_id)
    delete_note(request.app.state.conn, note_id)
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=200)  # htmx swaps the card for nothing
    return RedirectResponse("/notes", status_code=303)
