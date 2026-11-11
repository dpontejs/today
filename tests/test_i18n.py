import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings
from today.i18n import LANG_COOKIE, STRINGS, day_label, month_short, pick_lang, weekday_long
from today.items.repo import ItemIn, create_item

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # Tue 10 Nov, 09:00 in Fortaleza
PT = {"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}


@pytest.fixture
def app(settings: Settings):
    app = create_app(settings)
    app.state.clock = lambda: NOW
    return app


@pytest.fixture
def client(app) -> TestClient:
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("pt-BR,pt;q=0.9,en;q=0.8", "pt"),
        ("en-US,en;q=0.9", "en"),
        ("en;q=0.5, pt;q=0.8", "pt"),
        ("fr-FR", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_pick_lang_from_accept_language(header, expected):
    assert pick_lang(cookie=None, accept_language=header) == expected


def test_cookie_overrides_accept_language():
    assert pick_lang(cookie="en", accept_language="pt-BR") == "en"
    assert pick_lang(cookie="pt", accept_language="en-US") == "pt"


def test_invalid_cookie_is_ignored():
    assert pick_lang(cookie="xx", accept_language="pt-BR") == "pt"


def test_every_key_has_both_languages():
    assert STRINGS["en"].keys() == STRINGS["pt"].keys()


def test_date_names_in_portuguese():
    tuesday = datetime(2026, 11, 10, 9, 0, tzinfo=TZ)
    monday = datetime(2026, 11, 9, 9, 0, tzinfo=TZ)
    assert weekday_long(tuesday, "pt") == "TERÇA"
    assert month_short(tuesday, "pt") == "NOV"
    assert day_label(monday, "pt") == "SEG 09"
    assert day_label(monday, "en") == "MON 09"


def test_today_page_in_portuguese(client: TestClient, app):
    db: sqlite3.Connection = app.state.conn
    create_item(db, ItemIn(title="atrasado", due_at=NOW - timedelta(days=1)), NOW)
    create_item(db, ItemIn(title="proximo", due_at=NOW + timedelta(hours=1)), NOW)

    html = client.get("/", headers=PT).text

    assert '<html lang="pt-BR">' in html
    for text in [
        "TERÇA · NOV",
        "ATRASADOS",
        "PRÓXIMOS 7 DIAS",
        ">ATRASADO<",
        ">PRÓXIMO<",
        "SEG 09",
        "SAIR",
        "CRIAR",
    ]:
        assert text in html, text
    assert "TODAY" not in html


def test_validation_error_in_portuguese(client: TestClient):
    response = client.post("/items", data={"title": "", "due_at": "x"}, headers=PT)

    assert response.status_code == 422
    assert "O título é obrigatório." in response.text
    assert "Escolha data e hora." in response.text


def test_login_page_in_portuguese(app):
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)

    assert "Entrar" in anonymous.get("/login", headers=PT).text
    assert "Senha incorreta." in anonymous.post("/login", data={"passphrase": "x"}, headers=PT).text


def test_lang_switch_sets_cookie_and_is_public(app):
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)

    response = anonymous.get("/lang/pt", headers={"Referer": "https://testserver/login"})

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert response.cookies[LANG_COOKIE] == "pt"
    assert "Entrar" in anonymous.get("/login", headers={"Accept-Language": "en-US"}).text


def test_lang_switch_ignores_foreign_referer(app):
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)

    response = anonymous.get("/lang/en", headers={"Referer": "https://evil.example/phish"})

    assert response.headers["location"] == "/"


def test_unknown_lang_is_404(app):
    anonymous = TestClient(app, base_url="https://testserver", follow_redirects=False)
    assert anonymous.get("/lang/xx").status_code == 404


def test_page_offers_switch_to_other_language(client: TestClient):
    assert 'href="/lang/en"' in client.get("/", headers=PT).text
    assert 'href="/lang/pt"' in client.get("/").text
