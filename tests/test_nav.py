import re

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today import nav
from today.app import create_app
from today.config import Settings

PT = {"Accept-Language": "pt-BR"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    c = TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def nav_html(html: str) -> str:
    match = re.search(r'<nav class="nav".*?</nav>', html, re.S)
    assert match, "no navigation on the page"
    return match.group(0)


def test_nav_order_today_calendar_notes(client: TestClient):
    for path in ("/", "/calendar", "/notes"):
        html = nav_html(client.get(path, headers=PT).text)
        assert html.index('href="/"') < html.index('href="/calendar"') < html.index('href="/notes"'), path


def test_pt_labels_match_approved_bar(client: TestClient):
    html = nav_html(client.get("/", headers=PT).text)
    assert html.index("HOJE") < html.index("CALENDÁRIO") < html.index("ANOTAÇÕES")


def test_active_section_marked(client: TestClient):
    html = client.get("/notes").text
    assert 'href="/notes" aria-current="page"' in html
    assert html.count('aria-current="page"') == 1


def test_more_hidden_without_career_sections(client: TestClient):
    assert 'class="nav-more"' not in client.get("/").text


def test_more_lists_career_sections(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    jobs = nav.Section(key="jobs", path="/jobs", label_key="tab_today", group="career")
    monkeypatch.setattr(nav, "SECTIONS", [*nav.SECTIONS, jobs])

    html = nav_html(client.get("/").text)
    more = html[html.index('class="nav-more"') :]
    assert 'href="/jobs"' in more


def test_login_has_no_nav(settings: Settings):
    anonymous = TestClient(create_app(settings), base_url="https://testserver")
    assert 'class="nav"' not in anonymous.get("/login").text
