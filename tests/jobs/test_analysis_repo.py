import sqlite3
from datetime import UTC, datetime, timedelta

from today.jobs import analysis_repo as ar
from today.jobs import repo
from today.jobs.models import Gap, JobAnalysis, JobPosting

NOW = datetime(2026, 11, 23, 16, 0, tzinfo=UTC)


def add_job(
    conn: sqlite3.Connection,
    external_id: str,
    seen: datetime,
    company: str = "Acme",
    published: datetime | None = None,
) -> int:
    posting = JobPosting(
        source="fake",
        external_id=external_id,
        company=company,
        title="ML Engineer",
        location="Brasil",
        workplace="remote",
        description="Python, PyTorch",
        url=f"https://example.com/{external_id}",
        published_at=published,
    )
    repo.upsert_jobs(conn, [posting], seen)
    return conn.execute("SELECT id FROM jobs WHERE external_id = ?", (external_id,)).fetchone()[0]


def analysis(score: int = 80) -> JobAnalysis:
    return JobAnalysis(
        meets=["Python"],
        gaps=[Gap(skill="Kubernetes", kind="nice_to_have", note=None)],
        workplace="remote",
        location="Brasil",
        company_summary="Fintech grande.",
        seniority="junior",
        target_company=False,
        score=score,
        verdict="Boa vaga.",
    )


def test_pending_newest_first_and_limit(conn: sqlite3.Connection):
    """A role published today must not wait behind days of backlog (first collection brings ~300)."""
    newest = add_job(conn, "c", NOW)
    oldest = add_job(conn, "a", NOW - timedelta(hours=2))
    middle = add_job(conn, "b", NOW - timedelta(hours=1))
    done = add_job(conn, "d", NOW + timedelta(hours=1))
    repo.set_status(conn, done, "dismissed", NOW)

    assert [j.id for j in ar.pending_jobs(conn, 2)] == [newest, middle]
    assert [j.id for j in ar.pending_jobs(conn, 10)] == [newest, middle, oldest]


def test_pending_same_slot_ordered_by_publication(conn: sqlite3.Connection):
    """Jobs seen in the same slot: most recently published first, unknown dates last."""
    undated = add_job(conn, "u", NOW)
    old = add_job(conn, "o", NOW, published=NOW - timedelta(days=30))
    fresh = add_job(conn, "f", NOW, published=NOW - timedelta(days=1))

    assert [j.id for j in ar.pending_jobs(conn, 10)] == [fresh, old, undated]


def test_store_marks_analyzed_only_if_new(conn: sqlite3.Connection):
    fresh = add_job(conn, "a", NOW)
    triaged = add_job(conn, "b", NOW)
    repo.set_status(conn, triaged, "interested", NOW)

    ar.store_analysis(conn, fresh, analysis(80), "sonnet", NOW)
    ar.store_analysis(conn, triaged, analysis(60), "sonnet", NOW)

    statuses = {r["id"]: r["status"] for r in conn.execute("SELECT id, status FROM jobs")}
    assert statuses == {fresh: "analyzed", triaged: "interested"}
    row = conn.execute("SELECT * FROM job_analyses WHERE job_id = ?", (fresh,)).fetchone()
    assert row["score"] == 80 and row["model"] == "sonnet" and row["prompt_version"] == ar.PROMPT_VERSION
    assert JobAnalysis.model_validate_json(row["analysis_json"]) == analysis(80)


def test_store_twice_keeps_the_latest(conn: sqlite3.Connection):
    job = add_job(conn, "a", NOW)
    ar.store_analysis(conn, job, analysis(50), "sonnet", NOW)
    ar.store_analysis(conn, job, analysis(90), "opus", NOW)
    assert [tuple(r) for r in conn.execute("SELECT score, model FROM job_analyses")] == [(90, "opus")]


def test_three_failures_stop_retrying(conn: sqlite3.Connection):
    job = add_job(conn, "a", NOW)

    assert ar.record_failure(conn, job) == 1
    assert ar.record_failure(conn, job) == 2
    assert [j.id for j in ar.pending_jobs(conn, 10)] == [job]
    assert ar.record_failure(conn, job) == 3

    assert ar.pending_jobs(conn, 10) == []
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "analyzed"
    assert conn.execute("SELECT COUNT(*) FROM job_analyses").fetchone()[0] == 0


def test_profile_roundtrip_and_empty_default(conn: sqlite3.Connection):
    assert ar.get_profile(conn) == ""
    ar.set_profile(conn, "# Perfil\nPython", NOW)
    ar.set_profile(conn, "# Perfil\nPython, PyTorch", NOW)
    assert ar.get_profile(conn) == "# Perfil\nPython, PyTorch"


def test_analyses_since(conn: sqlite3.Connection):
    old = add_job(conn, "a", NOW)
    new = add_job(conn, "b", NOW, company="Nubank")
    ar.store_analysis(conn, old, analysis(70), "sonnet", NOW - timedelta(days=2))
    ar.store_analysis(conn, new, analysis(85), "sonnet", NOW)

    ((job, result),) = ar.analyses_since(conn, NOW - timedelta(hours=24))
    assert job.id == new and job.company == "Nubank" and result.score == 85


def test_list_jobs_still_works_with_new_column(conn: sqlite3.Connection):
    job = add_job(conn, "a", NOW)
    ar.record_failure(conn, job)
    (row,) = repo.list_jobs(conn, None, 10)
    assert row.id == job
