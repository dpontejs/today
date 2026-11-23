"""Storage for the owner's profile and the job analyses (feature 08). Plain SQL, like `repo`."""

import sqlite3
from datetime import datetime

from today.jobs.models import PROMPT_VERSION, JobAnalysis
from today.jobs.repo import JOB_STATUSES, JobRow, row_to_job, to_db

MAX_ATTEMPTS = 3

__all__ = [
    "PROMPT_VERSION",
    "analyses_since",
    "get_profile",
    "pending_jobs",
    "record_failure",
    "strong_analyses",
]


def get_profile(conn: sqlite3.Connection) -> str:
    """The profile markdown, or "" when it was never set."""
    row = conn.execute("SELECT body_md FROM profile WHERE id = 1").fetchone()
    return row["body_md"] if row else ""


def set_profile(conn: sqlite3.Connection, body_md: str, now: datetime) -> None:
    conn.execute(
        """INSERT INTO profile (id, body_md, updated_at) VALUES (1, ?, ?)
           ON CONFLICT (id) DO UPDATE SET body_md = excluded.body_md, updated_at = excluded.updated_at""",
        (body_md, to_db(now)),
    )


def pending_jobs(conn: sqlite3.Connection, limit: int) -> list[JobRow]:
    """Jobs still `new` with retries left, oldest first."""
    rows = conn.execute(
        """SELECT * FROM jobs WHERE status = 'new' AND analysis_attempts < ?
           ORDER BY first_seen_at, id LIMIT ?""",
        (MAX_ATTEMPTS, limit),
    ).fetchall()
    return [row_to_job(r) for r in rows]


def store_analysis(
    conn: sqlite3.Connection, job_id: int, analysis: JobAnalysis, model: str, now: datetime
) -> None:
    """Save the analysis; move the job `new → analyzed` only if the user has not triaged it meanwhile."""
    conn.execute("BEGIN")
    try:
        conn.execute(
            """INSERT INTO job_analyses (job_id, analysis_json, score, model, prompt_version, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (job_id) DO UPDATE SET analysis_json = excluded.analysis_json,
                   score = excluded.score, model = excluded.model,
                   prompt_version = excluded.prompt_version, analyzed_at = excluded.analyzed_at""",
            (job_id, analysis.model_dump_json(), analysis.score, model, PROMPT_VERSION, to_db(now)),
        )
        conn.execute(
            "UPDATE jobs SET status = 'analyzed', status_at = ? WHERE id = ? AND status = 'new'",
            (to_db(now), job_id),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def record_failure(conn: sqlite3.Connection, job_id: int) -> int:
    """Count a failed analysis. At MAX_ATTEMPTS the job leaves the queue as `analyzed` with no analysis."""
    (attempts,) = conn.execute(
        "UPDATE jobs SET analysis_attempts = analysis_attempts + 1 WHERE id = ? RETURNING analysis_attempts",
        (job_id,),
    ).fetchone()
    if attempts >= MAX_ATTEMPTS:
        conn.execute("UPDATE jobs SET status = 'analyzed' WHERE id = ? AND status = 'new'", (job_id,))
    return attempts


def strong_analyses(
    conn: sqlite3.Connection, job_ids: list[int], threshold: int
) -> list[tuple[JobRow, JobAnalysis]]:
    """Of `job_ids`, those scoring >= threshold and not dismissed meanwhile, best score first."""
    marks = ",".join("?" * len(job_ids))
    return _with_analysis(
        conn.execute(
            f"""SELECT j.*, a.analysis_json FROM job_analyses a JOIN jobs j ON j.id = a.job_id
                WHERE a.job_id IN ({marks}) AND a.score >= ? AND j.status != 'dismissed'
                ORDER BY a.score DESC, j.id""",
            (*job_ids, threshold),
        ).fetchall()
    )


def jobs_with_analysis(
    conn: sqlite3.Connection, status: str | None, limit: int, min_score: int | None
) -> list[tuple[JobRow, JobAnalysis | None]]:
    """Jobs with their analysis (None when not analyzed). Newest first, or best score first with min_score."""
    if status is not None and status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    where, args = [], []
    if status is not None:
        where.append("j.status = ?")
        args.append(status)
    if min_score is not None:
        where.append("a.score >= ?")
        args.append(min_score)
    order = (
        "a.score DESC, j.first_seen_at DESC, j.id DESC"
        if min_score is not None
        else "j.first_seen_at DESC, j.id DESC"
    )
    rows = conn.execute(
        f"""SELECT j.*, a.analysis_json FROM jobs j LEFT JOIN job_analyses a ON a.job_id = j.id
            {"WHERE " + " AND ".join(where) if where else ""} ORDER BY {order} LIMIT ?""",
        (*args, limit),
    ).fetchall()
    return _with_analysis(rows)


def analyses_since(conn: sqlite3.Connection, since: datetime) -> list[tuple[JobRow, JobAnalysis]]:
    """Jobs analyzed at or after `since`, best score first."""
    rows = conn.execute(
        """SELECT j.*, a.analysis_json FROM job_analyses a JOIN jobs j ON j.id = a.job_id
           WHERE a.analyzed_at >= ? ORDER BY a.score DESC, j.id""",
        (to_db(since),),
    ).fetchall()
    return _with_analysis(rows)


def _with_analysis(rows: list[sqlite3.Row]) -> list:
    out = []
    for r in rows:
        data = dict(r)
        raw = data.pop("analysis_json")
        analysis = JobAnalysis.model_validate_json(raw) if raw is not None else None
        out.append((row_to_job(data), analysis))
    return out
