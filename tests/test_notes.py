import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings
from today.notes import create_note, get_note, list_notes, set_pinned, update_note

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)  # Wed 18 Nov 2026, 09:00 in Fortaleza
PT = {"Accept-Language": "pt-BR"}


# --- repository ------------------------------------------------------------------------------------


def test_list_pinned_first_then_most_recently_edited(conn: sqlite3.Connection):
    old = create_note(conn, "old", NOW - timedelta(days=2))
    new = create_note(conn, "new", NOW - timedelta(days=1))
    pinned = create_note(conn, "pinned", NOW - timedelta(days=3))
    set_pinned(conn, pinned.id, True)
    update_note(conn, old.id, "old, edited today", NOW)

    assert [n.body for n in list_notes(conn)] == ["pinned", "old, edited today", "new"]
    assert get_note(conn, new.id).updated_at == NOW - timedelta(days=1)


def test_update_and_pin_unknown_note_return_none(conn: sqlite3.Connection):
    assert update_note(conn, 999, "x", NOW) is None
    assert set_pinned(conn, 999, True) is None


# --- pages -----------------------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.clock = lambda: NOW
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.conn


def test_tabs_order_today_notes_calendar(client: TestClient):
    for path in ("/", "/notes", "/calendar"):
        html = client.get(path, headers=PT).text
        assert html.index('href="/"') < html.index('href="/notes"') < html.index('href="/calendar"'), path
    assert 'href="/notes" aria-current="page"' in client.get("/notes").text


def test_notes_page_empty_state(client: TestClient):
    html = client.get("/notes", headers=PT).text
    assert "ANOTAÇÕES" in html and "Nenhuma anotação ainda." in html


def test_create_note_keeps_line_breaks_and_escapes(client: TestClient):
    response = client.post("/notes", data={"body": "  ideias:\n- <b>MLflow</b>\n- DVC  "})

    assert response.status_code == 303 and response.headers["location"] == "/notes"
    html = client.get("/notes").text
    assert "ideias:\n- &lt;b&gt;MLflow&lt;/b&gt;\n- DVC" in html
    assert "<b>MLflow</b>" not in html


@pytest.mark.parametrize("body", ["", "   ", "x" * 5001])
def test_create_note_rejects_empty_or_too_long(client: TestClient, body: str):
    assert client.post("/notes", data={"body": body}, headers=PT).status_code == 422
    assert list_notes(db(client)) == []


def test_edit_form_and_update(client: TestClient):
    note = create_note(db(client), "first draft", NOW - timedelta(hours=1))

    form = client.get(f"/notes/{note.id}/edit", headers=PT).text
    assert "<textarea" in form and "first draft" in form

    fragment = client.post(
        f"/notes/{note.id}", data={"body": "final text"}, headers={"HX-Request": "true"}
    ).text
    assert "final text" in fragment and "<html" not in fragment
    assert get_note(db(client), note.id).updated_at == NOW


def test_update_rejects_empty(client: TestClient):
    note = create_note(db(client), "keep me", NOW)
    assert client.post(f"/notes/{note.id}", data={"body": " "}).status_code == 422
    assert get_note(db(client), note.id).body == "keep me"


def test_pin_toggles(client: TestClient):
    note = create_note(db(client), "a", NOW)

    html = client.post(f"/notes/{note.id}/pin", headers=PT).text
    assert get_note(db(client), note.id).pinned and "DESAFIXAR" in html
    client.post(f"/notes/{note.id}/pin")
    assert not get_note(db(client), note.id).pinned


def test_delete_htmx_and_plain(client: TestClient):
    a = create_note(db(client), "a", NOW)
    b = create_note(db(client), "b", NOW)

    htmx = client.post(f"/notes/{a.id}/delete", headers={"HX-Request": "true"})
    assert htmx.status_code == 200 and htmx.text == ""
    plain = client.post(f"/notes/{b.id}/delete")
    assert plain.status_code == 303 and plain.headers["location"] == "/notes"
    assert list_notes(db(client)) == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/notes/999/edit"),
        ("GET", "/notes/999"),
        ("POST", "/notes/999"),
        ("POST", "/notes/999/pin"),
        ("POST", "/notes/999/delete"),
    ],
)
def test_unknown_note_is_404(client: TestClient, method: str, path: str):
    assert client.request(method, path, data={"body": "x"}).status_code == 404


def test_notes_require_session(settings: Settings):
    anonymous = TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)
    assert anonymous.get("/notes").status_code == 303
    assert anonymous.post("/notes", data={"body": "x"}).status_code == 303
