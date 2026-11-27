"""One collection run: every source, filtered, stored. A failing source is reported; the others still run."""

import logging
import sqlite3
from collections.abc import Callable, Mapping
from datetime import datetime

import httpx

from today.jobs import repo
from today.jobs.filter import passes_filter
from today.jobs.models import Fetch, PartialFetch
from today.jobs.sources import linkedin

log = logging.getLogger(__name__)

Describe = Callable[[httpx.Client, str], str | None]


def default_describers() -> dict[str, Describe]:
    """Sources whose listing has no description: fetched per posting, only for new postings that pass the
    filter. Fresh per run, since a describer remembers its pacing and whether it was blocked."""
    return {"linkedin": linkedin.Describer()}


def collect(
    conn: sqlite3.Connection,
    client: httpx.Client,
    sources: Mapping[str, Fetch],
    now: datetime,
    describers: Mapping[str, Describe] | None = None,
) -> repo.CollectReport:
    describers = default_describers() if describers is None else describers
    report: repo.CollectReport = {}
    for name, fetch in sources.items():
        error = None
        try:
            try:
                fetched = fetch(client)
            except PartialFetch as partial:
                fetched, error = partial.jobs, str(partial)
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
            if error is None and repo.is_board(name):  # only a complete listing proves a job is gone
                repo.track_board(conn, name, {job.external_id for job in fetched}, now)
        except Exception as exc:  # any adapter failure is data for the report, not a crash
            log.warning("job source %s failed: %s", name, exc)
            report[name] = repo.SourceReport(fetched=0, kept=0, new=0, error=f"{type(exc).__name__}: {exc}")
            continue
        report[name] = repo.SourceReport(fetched=len(fetched), kept=len(kept), new=new, error=error)
    return report


# A filled LinkedIn job still answers 200, with this banner instead of the apply button.
CLOSED_MARKERS = ("No longer accepting applications", "Não aceita mais candidaturas", "Vaga encerrada")


def check_interested_open(conn: sqlite3.Connection, client: httpx.Client, now: datetime) -> int:
    """Interested jobs from search sources (no full listing to compare with): fetch each page and close the
    ones that answer 404/410 or say they no longer accept applications. Returns how many pages it fetched."""
    rows = conn.execute(
        "SELECT id, source, url FROM jobs WHERE status = 'interested' AND closed_at IS NULL"
    ).fetchall()
    checked, gone = 0, []
    for row in rows:
        if repo.is_board(row["source"]):
            continue
        checked += 1
        try:
            response = client.get(row["url"], follow_redirects=True)
        except httpx.HTTPError as exc:  # unknown, not closed
            log.info("job %s page check failed: %s", row["id"], exc)
            continue
        if response.status_code in (404, 410) or any(m in response.text for m in CLOSED_MARKERS):
            gone.append(row["id"])
    repo.close_jobs(conn, gone, now)
    return checked
