"""Builders shared by the projects tests: jobs with a stored analysis."""

import sqlite3
from datetime import datetime

from today.jobs import analysis_repo as ar
from today.jobs import repo
from today.jobs.models import Gap, JobAnalysis, JobPosting


def job_with_gaps(
    conn: sqlite3.Connection,
    key: str,
    gaps: list[tuple[str, str]],
    analyzed_at: datetime,
    score: int = 60,
    status: str | None = None,
) -> int:
    """A job analyzed at `analyzed_at` with `gaps` as (skill, kind); optionally triaged to `status`."""
    posting = JobPosting(
        source="fake", external_id=key, company=f"Co {key}", title=f"ML Engineer {key}", location="Brasil",
        workplace="remote", description="x", url=f"https://example.com/{key}", published_at=None,
    )  # fmt: skip
    repo.upsert_jobs(conn, [posting], analyzed_at)
    job_id = conn.execute("SELECT id FROM jobs WHERE external_id = ?", (key,)).fetchone()[0]
    analysis = JobAnalysis(
        meets=[], gaps=[Gap(skill=s, kind=k, note=None) for s, k in gaps], workplace="remote", location=None,
        company_summary="x", seniority="junior", target_company=False, score=score, verdict="x",
    )  # fmt: skip
    ar.store_analysis(conn, job_id, analysis, "sonnet", analyzed_at)
    if status:
        repo.set_status(conn, job_id, status, analyzed_at)
    return job_id
