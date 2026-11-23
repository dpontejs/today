"""One collection run: every source, filtered, stored. A failing source is reported; the others still run."""

import logging
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx

from today.jobs import repo
from today.jobs.filter import passes_filter
from today.jobs.models import Fetch
from today.jobs.sources.linkedin import fetch_linkedin_description

log = logging.getLogger(__name__)

Describe = Callable[[httpx.Client, str], str | None]
# Sources whose listing has no description: fetched per posting, only for new postings that pass the filter.
DESCRIBERS: dict[str, Describe] = {"linkedin": fetch_linkedin_description}


def collect(
    conn: sqlite3.Connection,
    client: httpx.Client,
    sources: Mapping[str, Fetch],
    now: datetime,
    describers: Mapping[str, Describe] = DESCRIBERS,
) -> repo.CollectReport:
    report: repo.CollectReport = {}
    for name, fetch in sources.items():
        try:
            fetched = fetch(client)
            kept = [job for job in fetched if passes_filter(job)]
            describe = describers.get(name)
            if describe:
                known = repo.known_ids(conn, name)
                kept = [
                    job
                    if job.external_id in known or job.description
                    else job.model_copy(update={"description": describe(client, job.external_id)})
                    for job in kept
                ]
            new = repo.upsert_jobs(conn, kept, now)
        except Exception as exc:  # any adapter failure is data for the report, not a crash
            log.warning("job source %s failed: %s", name, exc)
            report[name] = repo.SourceReport(fetched=0, kept=0, new=0, error=f"{type(exc).__name__}: {exc}")
            continue
        report[name] = repo.SourceReport(fetched=len(fetched), kept=len(kept), new=new, error=None)
    return report
