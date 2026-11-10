import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings
from today.items.repo import ItemIn, create_item, get_item

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # Tue 10 Nov, 09:00 in Fortaleza


@pytest.fixture
def app(settings: Settings):
    app = create_app(settings)
    app.state.clock = lambda: NOW
    return app


@pytest.fixture
def db(app) -> sqlite3.Connection:
    return app.state.conn


@pytest.fixture
def client(app) -> TestClient:
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def add(db: sqlite3.Connection, title: str, due_at: datetime):
    return create_item(db, ItemIn(title=title, due_at=due_at), now=NOW)


def count(db: sqlite3.Connection) -> int:
    return db.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def test_routes_require_session(app):
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)
    for method, path in [
        ("GET", "/"),
        ("POST", "/items"),
        ("POST", "/items/1/done"),
        ("POST", "/items/1/reopen"),
    ]:
        response = anonymous.request(method, path)
        assert response.status_code == 303, path
        assert response.headers["location"] == "/login"


def test_today_page_shows_sections(client: TestClient, db: sqlite3.Connection):
    add(db, "Download Home Credit dataset", NOW - timedelta(days=1))
    add(db, "Book ch. 1", NOW + timedelta(hours=2))
    add(db, "Introduction to Docker", NOW + timedelta(days=2))

    html = client.get("/").text

    for label in ["LATE", "TODAY", "NEXT 7 DAYS"]:
        assert label in html
    late, today, upcoming = html.index("Download Home Credit"), html.index("Book ch. 1"), html.index("Docker")
    assert late < today < upcoming
    assert "11:00" in html  # 14:00 UTC shown in Fortaleza time
    assert "TUESDAY" in html


def test_due_at_stored_as_utc(client: TestClient, db: sqlite3.Connection):
    response = client.post("/items", data={"title": "Review ch. 3", "due_at": "2026-11-11T09:00"})

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    row = db.execute("SELECT title, due_at FROM items").fetchone()
    assert (row["title"], row["due_at"]) == ("Review ch. 3", "2026-11-11T12:00:00+00:00")


def test_create_rejects_empty_title(client: TestClient, db: sqlite3.Connection):
    response = client.post("/items", data={"title": "  ", "due_at": "2026-11-11T09:00"})

    assert response.status_code == 422
    assert "Title is required" in response.text
    assert count(db) == 0


def test_create_rejects_invalid_due(client: TestClient, db: sqlite3.Connection):
    response = client.post("/items", data={"title": "x", "due_at": "tomorrow"})

    assert response.status_code == 422
    assert "Pick a date and time" in response.text
    assert count(db) == 0


def test_unknown_item_returns_404(client: TestClient):
    assert client.post("/items/999/done").status_code == 404
    assert client.post("/items/999/reopen").status_code == 404


def test_done_returns_row_fragment(client: TestClient, db: sqlite3.Connection):
    item = add(db, "Book ch. 1", NOW + timedelta(hours=2))

    response = client.post(f"/items/{item.id}/done", headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert "<html" not in response.text
    assert f'id="item-{item.id}"' in response.text
    assert "DONE" in response.text
    assert get_item(db, item.id).status == "done"


def test_reopen_returns_open_row(client: TestClient, db: sqlite3.Connection):
    item = add(db, "Book ch. 1", NOW + timedelta(hours=2))
    client.post(f"/items/{item.id}/done")

    response = client.post(f"/items/{item.id}/reopen")

    assert response.status_code == 200
    assert "DONE" not in response.text
    assert get_item(db, item.id).status == "open"


def test_title_is_escaped(client: TestClient, db: sqlite3.Connection):
    add(db, "<script>alert(1)</script>", NOW + timedelta(hours=1))

    html = client.get("/").text

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_next_pill_on_first_today_item(client: TestClient, db: sqlite3.Connection):
    add(db, "first", NOW + timedelta(hours=1))
    add(db, "second", NOW + timedelta(hours=3))
    add(db, "overdue", NOW - timedelta(hours=1))

    html = client.get("/").text

    first, second = html.index("first"), html.index("second")
    assert html.count('class="pill pill-next"') == 1
    assert first < html.index('class="pill pill-next"') < second
    assert html.count('class="pill pill-late"') == 1
