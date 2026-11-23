import sqlite3
from datetime import UTC, datetime, timedelta

from today.jobs import analysis_repo as ar
from today.jobs import repo
from today.jobs.analyze import MAX_DESCRIPTION, SYSTEM, analyze_pending, build_prompt
from today.jobs.models import Gap, JobAnalysis, JobPosting
from today.llm.analyst import AnalystError

NOW = datetime(2026, 11, 23, 16, 0, tzinfo=UTC)
PROFILE = "# Perfil de teste\nPython, PyTorch. Empresas-alvo: Acme."


def add_job(conn, external_id: str, seen: datetime = NOW, description: str | None = "Python") -> int:
    posting = JobPosting(
        source="fake",
        external_id=external_id,
        company="Acme",
        title=f"ML Engineer {external_id}",
        location="São Paulo",
        workplace="hybrid",
        description=description,
        url=f"https://example.com/{external_id}",
        published_at=None,
    )
    repo.upsert_jobs(conn, [posting], seen)
    return conn.execute("SELECT id FROM jobs WHERE external_id = ?", (external_id,)).fetchone()[0]


def result(score: int = 80) -> JobAnalysis:
    return JobAnalysis(
        meets=["Python"],
        gaps=[Gap(skill="Spark", kind="required", note="pede 2 anos")],
        workplace="hybrid",
        location="São Paulo",
        company_summary="Varejo grande.",
        seniority="junior",
        target_company=True,
        score=score,
        verdict="Vale aplicar.",
    )


class FakeAnalyst:
    def __init__(self, fail: set[str] = frozenset(), on_call=None) -> None:
        self.fail = fail
        self.on_call = on_call
        self.calls: list[dict] = []

    def complete(self, *, model, system, prompt, schema):
        self.calls.append({"model": model, "system": system, "prompt": prompt, "schema": schema})
        if self.on_call:
            self.on_call()
        if any(f"ML Engineer {key}\n" in prompt for key in self.fail):
            raise AnalystError("limit reached")
        return result()


def status(conn, job_id: int) -> str:
    return conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]


def test_analyze_pending_stores_analysis_and_marks_analyzed(conn: sqlite3.Connection):
    ar.set_profile(conn, PROFILE, NOW)
    job = add_job(conn, "a")
    analyst = FakeAnalyst()

    report = analyze_pending(conn, analyst, "sonnet", NOW, limit=20)

    assert report.analyzed == [job] and report.failed == 0 and report.skipped_reason is None
    assert status(conn, job) == "analyzed"
    (call,) = analyst.calls
    assert call["model"] == "sonnet" and call["system"] == SYSTEM and call["schema"] is JobAnalysis
    ((stored_job, stored),) = ar.analyses_since(conn, NOW)
    assert stored_job.id == job and stored == result()


def test_analyze_respects_limit_and_oldest_first(conn: sqlite3.Connection):
    ar.set_profile(conn, PROFILE, NOW)
    newest = add_job(conn, "c", NOW)
    oldest = add_job(conn, "a", NOW - timedelta(hours=2))
    middle = add_job(conn, "b", NOW - timedelta(hours=1))

    report = analyze_pending(conn, FakeAnalyst(), "sonnet", NOW, limit=2)

    assert report.analyzed == [oldest, middle]
    assert status(conn, newest) == "new"


def test_analyst_error_keeps_job_new(conn: sqlite3.Connection):
    ar.set_profile(conn, PROFILE, NOW)
    bad = add_job(conn, "bad")
    good = add_job(conn, "good")

    report = analyze_pending(conn, FakeAnalyst(fail={"bad"}), "sonnet", NOW, limit=20)

    assert report.analyzed == [good] and report.failed == 1
    assert status(conn, bad) == "new"
    assert [j.id for j in ar.pending_jobs(conn, 10)] == [bad]


def test_three_slot_failures_take_job_out_of_queue(conn: sqlite3.Connection):
    ar.set_profile(conn, PROFILE, NOW)
    bad = add_job(conn, "bad")
    for _ in range(3):
        analyze_pending(conn, FakeAnalyst(fail={"bad"}), "sonnet", NOW, limit=20)

    assert status(conn, bad) == "analyzed"
    assert analyze_pending(conn, FakeAnalyst(), "sonnet", NOW, limit=20).analyzed == []


def test_user_status_not_overwritten_by_analysis(conn: sqlite3.Connection):
    ar.set_profile(conn, PROFILE, NOW)
    job = add_job(conn, "a")
    analyst = FakeAnalyst(on_call=lambda: repo.set_status(conn, job, "dismissed", NOW))

    analyze_pending(conn, analyst, "sonnet", NOW, limit=20)

    assert status(conn, job) == "dismissed"
    assert len(ar.analyses_since(conn, NOW)) == 1  # the analysis is still kept


def test_empty_profile_skips_slot(conn: sqlite3.Connection, caplog):
    job = add_job(conn, "a")
    analyst = FakeAnalyst()

    with caplog.at_level("WARNING"):
        report = analyze_pending(conn, analyst, "sonnet", NOW, limit=20)

    assert report.analyzed == [] and report.skipped_reason == "empty profile"
    assert analyst.calls == [] and status(conn, job) == "new"
    assert sum("profile" in r.getMessage() for r in caplog.records) == 1


def test_long_description_truncated_in_prompt(conn: sqlite3.Connection):
    long_id = add_job(conn, "long", description="x" * 40_000)
    none_id = add_job(conn, "none", description=None)
    jobs = {j.id: j for j in repo.list_jobs(conn, None, 10)}

    prompt = build_prompt(jobs[long_id], PROFILE)
    assert "x" * MAX_DESCRIPTION in prompt and "x" * (MAX_DESCRIPTION + 1) not in prompt
    assert "(truncated)" in prompt
    assert MAX_DESCRIPTION == 12_000
    assert "(truncated)" not in build_prompt(jobs[none_id], PROFILE)


def test_prompt_contains_profile_title_company_location(conn: sqlite3.Connection):
    job_id = add_job(conn, "a", description="Experiência com PyTorch")
    (job,) = [j for j in repo.list_jobs(conn, None, 10) if j.id == job_id]

    prompt = build_prompt(job, PROFILE)

    for text in (PROFILE, "ML Engineer a", "Acme", "São Paulo", "hybrid", "Experiência com PyTorch"):
        assert text in prompt


def test_system_prompt_has_the_rubric():
    for text in ("Você avalia vagas para uma pessoa", "+5", "−20", "Natal"):
        assert text in SYSTEM


def test_analyze_one_prints_without_writing(conn: sqlite3.Connection):
    from today.jobs.analyze import analyze_one

    ar.set_profile(conn, PROFILE, NOW)
    older = add_job(conn, "a", NOW - timedelta(hours=1))
    newer = add_job(conn, "b", NOW)
    analyst = FakeAnalyst()

    job, out = analyze_one(conn, analyst, "sonnet")
    assert job.id == older and out == result()
    job, _ = analyze_one(conn, analyst, "sonnet", job_id=newer, profile="# Outro perfil")
    assert job.id == newer and "# Outro perfil" in analyst.calls[-1]["prompt"]

    assert conn.execute("SELECT COUNT(*) FROM job_analyses").fetchone()[0] == 0
    assert {status(conn, older), status(conn, newer)} == {"new"}


def test_analyze_one_needs_a_profile_and_a_job(conn: sqlite3.Connection):
    import pytest

    from today.jobs.analyze import analyze_one

    with pytest.raises(ValueError, match="profile"):
        analyze_one(conn, FakeAnalyst(), "sonnet")
    ar.set_profile(conn, PROFILE, NOW)
    with pytest.raises(ValueError, match="no job"):
        analyze_one(conn, FakeAnalyst(), "sonnet")
    with pytest.raises(ValueError, match="no job"):
        analyze_one(conn, FakeAnalyst(), "sonnet", job_id=999)


def test_unavailable_analyst_stops_slot_without_spending_retries(conn: sqlite3.Connection):
    from today.llm.analyst import AnalystUnavailable

    class Down(FakeAnalyst):
        def complete(self, **kwargs):
            self.calls.append(kwargs)
            raise AnalystUnavailable("usage limit reached")

    ar.set_profile(conn, PROFILE, NOW)
    jobs = [add_job(conn, k, NOW - timedelta(minutes=i)) for i, k in enumerate("abc")]
    for _ in range(4):
        analyst = Down()
        report = analyze_pending(conn, analyst, "sonnet", NOW, limit=20)
        assert len(analyst.calls) == 1  # first failure stops the slot
        assert report.analyzed == [] and "unavailable" in report.skipped_reason

    assert {status(conn, j) for j in jobs} == {"new"}
    assert len(ar.pending_jobs(conn, 10)) == 3
