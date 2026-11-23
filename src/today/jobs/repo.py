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


def _to_db(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _from_db(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(row: sqlite3.Row) -> JobRow:
    data = dict(row)
    for key in ("published_at", "first_seen_at", "status_at"):
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
                _to_db(job.published_at),
                _to_db(now),
                _to_db(now),
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
    return [_row(r) for r in rows]


def set_status(conn: sqlite3.Connection, job_id: int, status: str, now: datetime) -> JobRow:
    if status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    conn.execute("UPDATE jobs SET status = ?, status_at = ? WHERE id = ?", (status, _to_db(now), job_id))
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"job {job_id} not found")
    return _row(row)
