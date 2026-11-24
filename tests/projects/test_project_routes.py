import sqlite3
from datetime import UTC, datetime

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings
from today.llm.analyst import AnalystUnavailable
from today.projects import repo as pr
from today.projects.evaluate import IdeaEvaluation

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
PT = {"Accept-Language": "pt-BR"}


class FakeAnalyst:
    def __init__(self, fail: bool = False, score: int = 82) -> None:
        self.fail, self.score, self.calls = fail, score, 0

    def complete(self, *, model, system, prompt, schema):
        self.calls += 1
        if self.fail:
            raise AnalystUnavailable("limit reached")
        return IdeaEvaluation(
            verdict=f"Vale a pena ({self.calls}).", score=self.score, covers=["spark"],
            already_shown=["PyTorch"], missing=["deploy em nuvem"], scope_suggestions=["Adicionar GCP"],
            effort_note="Prazo curto para o escopo.",
        )  # fmt: skip


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.clock = lambda: NOW
    app.state.analyst = FakeAnalyst()
    c = TestClient(app, base_url="https://testserver", follow_redirects=False, headers=PT)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.conn


def create(client: TestClient, name: str = "credit-risk", idea: str = "Risco de crédito no GCP"):
    return client.post("/projects", data={"name": name, "idea_md": idea})


def test_projects_require_session(settings: Settings):
    anonymous = TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)
    assert anonymous.get("/projects").status_code in (302, 303)
    assert anonymous.post("/projects", data={"name": "x", "idea_md": "y"}).status_code in (302, 303)


def test_projects_listed_under_more(client: TestClient):
    html = client.get("/").text
    assert 'href="/projects"' in html[html.index('class="nav-more') :]


def test_create_project_evaluates_and_redirects(client: TestClient):
    response = create(client)

    assert response.status_code == 303
    (project,) = pr.list_projects(db(client))
    assert response.headers["location"] == f"/projects/{project.id}"
    html = client.get(response.headers["location"]).text
    for text in (
        "Vale a pena (1).",
        "82",
        "spark",
        "PyTorch",
        "deploy em nuvem",
        "Adicionar GCP",
        "Prazo curto",
    ):
        assert text in html
    assert "Risco de crédito no GCP" in html


def test_create_requires_name_and_idea(client: TestClient):
    response = client.post("/projects", data={"name": " ", "idea_md": "algo"})
    assert response.status_code == 422
    assert pr.list_projects(db(client)) == []


def test_idea_is_escaped(client: TestClient):
    create(client, idea="<script>alert(1)</script>")
    (project,) = pr.list_projects(db(client))
    assert "<script>alert(1)</script>" not in client.get(f"/projects/{project.id}").text


def test_analyst_unavailable_keeps_project_with_pending_evaluation(client: TestClient):
    client.app.state.analyst = FakeAnalyst(fail=True)

    response = create(client)

    assert response.status_code == 303
    (project,) = pr.list_projects(db(client))
    assert project.evaluation is None
    html = client.get(response.headers["location"]).text
    assert "Avaliação pendente" in html and f'action="/projects/{project.id}/evaluate"' in html


def test_analyst_off_page_says_unavailable(client: TestClient):
    client.app.state.analyst = None
    response = create(client)
    assert "Avaliação indisponível" in client.get(response.headers["location"]).text


def test_reevaluate_replaces_evaluation_and_idea(client: TestClient):
    create(client)
    (project,) = pr.list_projects(db(client))

    response = client.post(f"/projects/{project.id}/evaluate", data={"idea_md": "Nova versão da ideia"})

    assert response.status_code == 303
    html = client.get(f"/projects/{project.id}").text
    assert "Vale a pena (2)." in html and "Nova versão da ideia" in html


def test_status_only_active_done_dropped(client: TestClient):
    create(client)
    (project,) = pr.list_projects(db(client))

    assert client.post(f"/projects/{project.id}/status", data={"status": "active"}).status_code == 303
    assert pr.get_project(db(client), project.id).status == "active"
    for bad in ("idea", "nope"):
        assert client.post(f"/projects/{project.id}/status", data={"status": bad}).status_code == 422


def test_unknown_project_is_404(client: TestClient):
    assert client.get("/projects/999").status_code == 404
    assert client.post("/projects/999/evaluate", data={}).status_code == 404
    assert client.post("/projects/999/status", data={"status": "done"}).status_code == 404
