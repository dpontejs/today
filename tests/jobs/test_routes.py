"""Jobs tab: triage the analyzed roles on a list + detail screen."""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today.app import create_app
from today.config import Settings
from today.jobs import analysis_repo as ar
from today.jobs import repo
from today.jobs.models import Gap, JobAnalysis, JobPosting

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
PT = {"Accept-Language": "pt-BR"}


@pytest.fixture
def client(settings: Settings) -> TestClient:
    app = create_app(settings)
    app.state.clock = lambda: NOW
    c = TestClient(app, base_url="https://testserver", follow_redirects=False, headers=PT)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.conn


def add(
    conn: sqlite3.Connection,
    company: str,
    score: int | None,
    timing: str = "now",
    seniority: str = "junior",
    target: bool = False,
) -> int:
    """A job seen now; analyzed with `score` unless it is None (still in the analysis queue)."""
    posting = JobPosting(
        source="fake",
        external_id=company,
        company=company,
        title=f"ML Engineer {company}",
        location="São Paulo" if timing == "after_move" else "Brasil",
        workplace="hybrid" if timing == "after_move" else "remote",
        description="Python, PyTorch",
        url=f"https://example.com/{company}",
        published_at=None,
    )
    repo.upsert_jobs(conn, [posting], NOW - timedelta(hours=1))
    job_id = conn.execute("SELECT id FROM jobs WHERE external_id = ?", (company,)).fetchone()[0]
    if score is not None:
        analysis = JobAnalysis(
            meets=["PyTorch", "visão computacional"],
            gaps=[
                Gap(skill="Spark", kind="required", note=None),
                Gap(skill="Kubernetes", kind="nice_to_have", note=None),
            ],
            workplace="hybrid" if timing == "after_move" else "remote",
            location="São Paulo" if timing == "after_move" else None,
            company_summary=f"{company} é uma fintech grande.",
            seniority=seniority,
            target_company=target,
            score=score,
            verdict=f"Veredito da {company}.",
            timing=timing,
        )
        ar.store_analysis(conn, job_id, analysis, "sonnet", NOW)
    return job_id


def status(conn: sqlite3.Connection, job_id: int) -> str:
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def test_jobs_require_session(settings: Settings):
    anonymous = TestClient(create_app(settings), base_url="https://testserver", follow_redirects=False)
    assert anonymous.get("/jobs").status_code in (302, 303)
    assert anonymous.post("/jobs/1/status", data={"status": "dismissed"}).status_code in (302, 303)


def test_jobs_listed_under_more_on_the_nav(client: TestClient):
    html = client.get("/").text
    more = html[html.index('class="nav-more') :]
    assert 'href="/jobs"' in more and "VAGAS" in more


def test_review_lists_analyzed_now_jobs_scoring_70_or_more_best_first(client: TestClient):
    conn = db(client)
    add(conn, "Good", 72)
    add(conn, "Strong", 90)
    add(conn, "Weak", 69)
    add(conn, "Later", 95, timing="after_move")
    add(conn, "Queued", None)

    html = client.get("/jobs").text

    assert html.index("Strong") < html.index("Good")
    assert "Weak" not in html and "Later" not in html and "Queued" not in html
    assert 'data-view="review" aria-current="true"' in html
    assert 'data-count="review">2<' in html and 'data-count="later">1<' in html
    assert 'data-count="low">1<' in html
    assert "1 na fila de análise" in html
    assert "split-has-detail" not in html  # the phone sees the list first


def test_later_view_holds_after_move_jobs(client: TestClient):
    conn = db(client)
    add(conn, "Strong", 90)
    add(conn, "Later", 95, timing="after_move")

    html = client.get("/jobs?view=later").text

    assert "Later" in html and "Strong" not in html


def test_triaged_jobs_leave_review_for_their_view(client: TestClient):
    conn = db(client)
    liked = add(conn, "Liked", 80)
    repo.set_status(conn, liked, "interested", NOW)

    assert "Liked" not in client.get("/jobs").text
    assert "Liked" in client.get("/jobs?view=interested").text


def test_unknown_view_is_404(client: TestClient):
    assert client.get("/jobs?view=nope").status_code == 404


def test_row_pills_show_workplace_target_and_internship(client: TestClient):
    add(db(client), "Nubank", 88, seniority="intern", target=True)

    html = client.get("/jobs").text

    for pill in ("REMOTO", "★ ALVO", "ESTÁGIO"):
        assert pill in html


def test_detail_shows_verdict_meets_gaps_link_and_actions(client: TestClient):
    job = add(db(client), "Nubank", 88)

    html = client.get(f"/jobs/{job}?view=review").text

    assert "split-has-detail" in html
    assert "Veredito da Nubank." in html and "Nubank é uma fintech grande." in html
    assert "PyTorch" in html
    assert 'class="gap gap-required"' in html and "Spark" in html
    assert 'class="gap gap-nice"' in html and "Kubernetes" in html
    assert 'href="https://example.com/Nubank"' in html
    for action in ("interested", "dismissed", "applied"):
        assert f'value="{action}"' in html
    assert 'href="/jobs?view=review"' in html  # the phone's back link keeps the view


def test_detail_of_job_still_in_queue(client: TestClient):
    job = add(db(client), "Queued", None)

    html = client.get(f"/jobs/{job}").text

    assert "Ainda na fila de análise." in html


def test_detail_unknown_job_is_404(client: TestClient):
    assert client.get("/jobs/999").status_code == 404


def test_mark_opens_next_job_of_the_view(client: TestClient):
    conn = db(client)
    first = add(conn, "Strong", 90)
    second = add(conn, "Good", 75)

    response = client.post(f"/jobs/{first}/status", data={"status": "interested", "view": "review"})

    assert response.status_code == 303
    assert response.headers["location"] == f"/jobs/{second}?view=review"
    assert status(conn, first) == "interested"


def test_mark_last_job_returns_to_the_view(client: TestClient):
    only = add(db(client), "Strong", 90)

    response = client.post(f"/jobs/{only}/status", data={"status": "dismissed", "view": "review"})

    assert response.headers["location"] == "/jobs?view=review"


def test_mark_twice_is_harmless(client: TestClient):
    conn = db(client)
    job = add(conn, "Strong", 90)

    for _ in range(2):
        response = client.post(f"/jobs/{job}/status", data={"status": "applied", "view": "review"})
        assert response.status_code == 303
    assert status(conn, job) == "applied"


def test_mark_rejects_statuses_the_user_does_not_set(client: TestClient):
    job = add(db(client), "Strong", 90)

    for bad in ("new", "analyzed", "nope"):
        assert client.post(f"/jobs/{job}/status", data={"status": bad, "view": "review"}).status_code == 422
    assert status(db(client), job) == "analyzed"


def test_mark_unknown_job_is_404(client: TestClient):
    assert client.post("/jobs/999/status", data={"status": "dismissed", "view": "review"}).status_code == 404


def test_job_link_only_for_http_urls(client: TestClient):
    """URLs come from scraped feeds (Remotar's externalLink is typed by the poster): no javascript: link."""
    conn = db(client)
    job = add(conn, "Evil", 80)
    conn.execute("UPDATE jobs SET url = 'javascript:alert(1)' WHERE id = ?", (job,))

    html = client.get(f"/jobs/{job}").text

    assert "javascript:" not in html


def test_job_whose_analysis_failed_stays_in_review(client: TestClient):
    """Three failed analyses leave the job `analyzed` without an analysis: it must not vanish from the tab."""
    conn = db(client)
    job = add(conn, "Broken", None)
    for _ in range(ar.MAX_ATTEMPTS):
        ar.record_failure(conn, job)
    add(conn, "Strong", 90)

    html = client.get("/jobs").text
    assert html.index("Strong") < html.index("Broken")  # unscored jobs go last
    assert 'data-count="review">2<' in html
    assert "A análise desta vaga falhou." in client.get(f"/jobs/{job}").text


def test_low_view_holds_jobs_under_70(client: TestClient):
    conn = db(client)
    add(conn, "Weak", 40)
    add(conn, "Strong", 90)

    html = client.get("/jobs?view=low").text

    assert "Weak" in html and "Strong" not in html


def test_closed_jobs_leave_every_view_but_applied_and_closed(client: TestClient):
    conn = db(client)
    gone = add(conn, "Gone", 90)
    liked = add(conn, "Liked", 85)
    sent = add(conn, "Sent", 80)
    repo.set_status(conn, liked, "interested", NOW)
    repo.set_status(conn, sent, "applied", NOW)
    repo.close_jobs(conn, [gone, liked, sent], NOW)

    for view in ("review", "interested"):
        html = client.get(f"/jobs?view={view}").text
        assert "Gone" not in html and "Liked" not in html, view
    closed = client.get("/jobs?view=closed").text
    assert "Gone" in closed and "Liked" in closed and "Sent" not in closed
    applied = client.get("/jobs?view=applied").text
    assert "Sent" in applied and "ENCERRADA" in applied  # your history stays, marked closed


def test_closed_jobs_leave_the_analysis_queue(client: TestClient):
    conn = db(client)
    queued = add(conn, "Queued", None)
    repo.close_jobs(conn, [queued], NOW)

    assert ar.pending_jobs(conn, 10) == []
