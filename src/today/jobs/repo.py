"""Job storage: plain SQL over `jobs`. Datetimes in and out are aware; stored as UTC ISO strings."""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from today.jobs.models import JobPosting

JOB_STATUSES = ("new", "analyzed", "dismissed", "interested", "applied")


@dataclass(frozen=True)
class SourceReport:
    fetched: int
    kept: int
    new: int
    error: str | None


CollectReport = dict[str, SourceReport]


@dataclass(frozen=True)
class JobRow:
    id: int
    source: str
    external_id: str
    company: str
    title: str
    location: str | None
    workplace: str | None
    description: str | None
    url: str
    published_at: datetime | None
    first_seen_at: datetime
    status: str
    status_at: datetime
    analysis_attempts: int = 0
    missed_runs: int = 0
    closed_at: datetime | None = None


def to_db(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def row_to_job(row: sqlite3.Row) -> JobRow:
    data = dict(row)
    for key in ("published_at", "first_seen_at", "status_at", "closed_at"):
        if key in data:
            data[key] = _from_db(data[key])
    return JobRow(**data)


def known_ids(conn: sqlite3.Connection, source: str) -> set[str]:
    rows = conn.execute("SELECT external_id FROM jobs WHERE source = ?", (source,))
    return {r["external_id"] for r in rows}


def upsert_jobs(conn: sqlite3.Connection, jobs: list[JobPosting], now: datetime) -> int:
    """Insert unseen postings, leave stored ones exactly as they are. Returns how many were new."""
    new = 0
    for job in jobs:
        cursor = conn.execute(
            """
            INSERT INTO jobs (source, external_id, company, title, location, workplace, description, url,
                              published_at, first_seen_at, status, status_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)
            ON CONFLICT (source, external_id) DO NOTHING
            """,
            (
                job.source,
                job.external_id,
                job.company,
                job.title,
                job.location,
                job.workplace,
                job.description,
                job.url,
                to_db(job.published_at),
                to_db(now),
                to_db(now),
            ),
        )
        new += cursor.rowcount
    return new


def list_jobs(conn: sqlite3.Connection, status: str | None, limit: int) -> list[JobRow]:
    """Newest first. `status=None` lists every status."""
    if status is not None and status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    where, args = ("WHERE status = ?", [status]) if status else ("", [])
    rows = conn.execute(
        f"SELECT * FROM jobs {where} ORDER BY first_seen_at DESC, id DESC LIMIT ?", (*args, limit)
    ).fetchall()
    return [row_to_job(r) for r in rows]


# Sources that list every open job of one company: absence there means the job closed (feature 07).
BOARD_PREFIXES = ("greenhouse:", "lever:", "ashby:")
MISSES_TO_CLOSE = 2


def is_board(source: str) -> bool:
    return source.startswith(BOARD_PREFIXES)


def track_board(conn: sqlite3.Connection, source: str, seen_ids: set[str], now: datetime) -> int:
    """After a complete fetch of a board: reset misses of the jobs seen, count one more miss for the open
    jobs not seen, and close those missed MISSES_TO_CLOSE times in a row. Returns how many it closed."""
    rows = conn.execute(
        "SELECT id, external_id FROM jobs WHERE source = ? AND closed_at IS NULL", (source,)
    ).fetchall()
    seen = [r["id"] for r in rows if r["external_id"] in seen_ids]
    missed = [r["id"] for r in rows if r["external_id"] not in seen_ids]
    conn.executemany("UPDATE jobs SET missed_runs = 0 WHERE id = ?", [(i,) for i in seen])
    conn.executemany("UPDATE jobs SET missed_runs = missed_runs + 1 WHERE id = ?", [(i,) for i in missed])
    gone = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM jobs WHERE source = ? AND closed_at IS NULL AND missed_runs >= ?",
            (source, MISSES_TO_CLOSE),
        )
    ]
    return close_jobs(conn, gone, now)


def close_jobs(conn: sqlite3.Connection, job_ids: list[int], now: datetime) -> int:
    conn.executemany(
        "UPDATE jobs SET closed_at = ? WHERE id = ? AND closed_at IS NULL", [(to_db(now), i) for i in job_ids]
    )
    return len(job_ids)


def set_status(conn: sqlite3.Connection, job_id: int, status: str, now: datetime) -> JobRow:
    if status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    conn.execute("UPDATE jobs SET status = ?, status_at = ? WHERE id = ?", (status, to_db(now), job_id))
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"job {job_id} not found")
    return row_to_job(row)
