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


def test_more_hidden_without_career_sections(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    routine = [s for s in nav.SECTIONS if s.group == "routine"]
    monkeypatch.setattr(nav, "SECTIONS", routine)
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


def render_split(client: TestClient, detail: str) -> str:
    source = (
        '{% extends "_split.html" %}{% block list %}LIST{% endblock %}{% block detail %}'
        + detail
        + "{% endblock %}"
    )
    template = client.app.state.templates.env.from_string(source)
    return template.render(t=lambda key: key.upper(), list_url="/things")


def test_split_template_renders_detail_flag(client: TestClient):
    with_detail = render_split(client, "DETAIL")
    assert "split-has-detail" in with_detail and 'href="/things"' in with_detail

    without = render_split(client, "  ")
    assert 'class="split"' in without and "split-has-detail" not in without and "LIST" in without


def test_today_stays_active_after_add_form_error(client: TestClient):
    """A failed add re-renders the Today page at /items; Today must still be the current section."""
    response = client.post("/items", data={"title": "", "due_at": ""})
    assert response.status_code == 422
    assert 'href="/" aria-current="page"' in response.text


def test_active_career_section_does_not_open_more_panel(client: TestClient):
    """On the phone MORE is a popup over the content; it must not load already open."""
    jobs = nav.Section(key="jobs", path="/jobs", label_key="tab_today", group="career")
    html = client.app.state.templates.env.get_template("_nav.html").render(
        t=lambda key: key.upper(), nav_routine=[], nav_career=[(jobs, True)]
    )
    details = html[html.index("<details") : html.index(">", html.index("<details")) + 1]
    assert " open" not in details
    assert 'class="nav-more is-active"' in html and 'href="/jobs" aria-current="page"' in html


def test_language_switch_reachable_from_every_section(client: TestClient):
    """The PT/EN switch used to live only in the Today header; it must be in the navigation (MORE/sidebar)."""
    for path in ("/calendar", "/notes", "/jobs", "/projects"):
        html = nav_html(client.get(path, headers={"Accept-Language": "pt-BR"}).text)
        assert 'href="/lang/en"' in html, path
