import sqlite3
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.calendar_view import month_grid
from today.config import Settings
from today.items.repo import ItemIn, create_item, mark_done

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # Tue 10 Nov 2026, 09:00 in Fortaleza
PT = {"Accept-Language": "pt-BR"}


def add(conn: sqlite3.Connection, title: str, due_at: datetime):
    return create_item(conn, ItemIn(title=title, due_at=due_at), NOW)


# --- month grid ------------------------------------------------------------------------------------


def test_month_grid_starts_monday_and_pads(conn: sqlite3.Connection):
    weeks = month_grid(conn, 2026, 11, NOW, TZ)

    cells = [c for week in weeks for c in week]
    assert all(len(week) == 7 for week in weeks)
    assert cells[0].day == date(2026, 10, 26)  # Monday before Sun 1 Nov
    assert cells[6].day == date(2026, 11, 1) and cells[6].in_month
    assert not cells[0].in_month
    assert cells[-1].day.weekday() == 6 and cells[-1].day >= date(2026, 11, 30)


def test_month_grid_counts_open_and_late_by_local_day(conn: sqlite3.Connection):
    add(conn, "exam", datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    add(conn, "late night", datetime(2026, 11, 20, 22, 0, tzinfo=TZ))  # 01:00 UTC on the 21st
    add(conn, "overdue", datetime(2026, 11, 9, 9, 0, tzinfo=TZ))
    done = add(conn, "finished", datetime(2026, 11, 12, 9, 0, tzinfo=TZ))
    mark_done(conn, done.id, NOW)

    cells = {c.day: c for week in month_grid(conn, 2026, 11, NOW, TZ) for c in week}

    assert cells[date(2026, 11, 20)].count == 2
    assert cells[date(2026, 11, 21)].count == 0
    assert cells[date(2026, 11, 9)].late
    assert not cells[date(2026, 11, 20)].late
    assert cells[date(2026, 11, 12)].count == 0 and cells[date(2026, 11, 12)].done == 1
    assert cells[date(2026, 11, 10)].is_today


# --- pages -----------------------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.clock = lambda: NOW
    app.state.extractor = None
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.conn


def test_calendar_defaults_to_this_month_and_today(client: TestClient):
    add(db(client), "Prova de Sistemas Distribuídos", datetime(2026, 11, 10, 15, 0, tzinfo=TZ))

    html = client.get("/calendar", headers=PT).text

    assert "NOVEMBRO" in html and "2026" in html
    assert "TER 10 NOV" in html
    assert "Prova de Sistemas Distribuídos" in html
    assert 'href="/calendar?month=2026-10"' in html and 'href="/calendar?month=2026-12"' in html
    assert 'aria-current="page"' in html


def test_calendar_selected_day_lists_its_items(client: TestClient):
    add(db(client), "exam", datetime(2026, 11, 20, 9, 0, tzinfo=TZ))
    add(db(client), "other day", datetime(2026, 11, 21, 9, 0, tzinfo=TZ))

    html = client.get("/calendar?month=2026-11&day=2026-11-20", headers=PT).text

    assert "SEX 20 NOV" in html
    assert "exam" in html and "other day" not in html
    assert 'href="/calendar?month=2026-11&amp;day=2026-11-21"' in html


def test_calendar_other_month_without_day_asks_to_pick(client: TestClient):
    html = client.get("/calendar?month=2027-01", headers=PT).text
    assert "JANEIRO" in html and "Toque num dia" in html


def test_calendar_bad_params_fall_back_to_today(client: TestClient):
    html = client.get("/calendar?month=banana&day=2026-13-40", headers=PT).text
    assert "NOVEMBRO" in html and "TER 10 NOV" in html


def test_calendar_day_outside_month_is_ignored(client: TestClient):
    html = client.get("/calendar?month=2026-12&day=2026-11-20", headers=PT).text
    assert "DEZEMBRO" in html and "Toque num dia" in html


def test_calendar_requires_session(settings: Settings):
    anonymous = TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)
    assert anonymous.get("/calendar").status_code == 303


def test_tabs_on_both_pages(client: TestClient):
    home, cal = client.get("/", headers=PT).text, client.get("/calendar", headers=PT).text
    for html in (home, cal):
        assert 'href="/calendar"' in html and 'href="/"' in html and "CALENDÁRIO" in html


# --- home: range, times, collapsing, pinned capture ------------------------------------------------


def test_home_range_param_widens_and_is_remembered(client: TestClient):
    add(db(client), "in twelve days", NOW + timedelta(days=12))

    assert "in twelve days" not in client.get("/").text
    response = client.get("/?days=14")
    assert "in twelve days" in response.text and "NEXT 14 DAYS" in response.text
    assert response.cookies["today_days"] == "14"
    assert "in twelve days" in client.get("/").text  # cookie remembered


def test_home_range_rejects_other_values(client: TestClient):
    assert "NEXT 7 DAYS" in client.get("/?days=365").text


def test_rows_show_day_and_time(client: TestClient):
    add(db(client), "docker", datetime(2026, 11, 12, 14, 0, tzinfo=TZ))
    add(db(client), "overdue", datetime(2026, 11, 9, 8, 30, tzinfo=TZ))

    html = client.get("/", headers=PT).text

    assert "QUI 12" in html and "14:00" in html
    assert "SEG 09" in html and "08:30" in html


def test_long_section_collapses_after_five(client: TestClient):
    for i in range(7):
        add(db(client), f"task {i}", NOW + timedelta(days=1, hours=i))

    html = client.get("/", headers=PT).text

    assert "VER MAIS (2)" in html
    assert html.index("task 4") < html.index("VER MAIS (2)") < html.index("task 5")


def test_capture_is_pinned_to_the_bottom():
    css = (Path(__file__).parents[1] / "src/today/static/app.css").read_text()
    rule = css[css.index(".capture {") :].split("}", 1)[0]
    assert "position: sticky" in rule and "bottom: 0" in rule
