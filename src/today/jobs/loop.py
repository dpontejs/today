"""One collection at 07:00 local every `JOBS_EVERY_DAYS` days, 2 by default (ADR 0001: an asyncio task in
the app process). Each run is recorded in `job_runs`; after a restart or an outage the collection runs once,
on the first due day, never twice."""

import asyncio
import dataclasses
import json
import logging
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime
from functools import partial
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from today import notify
from today.jobs.analyze import analyze_pending
from today.jobs.collect import check_interested_open, collect
from today.jobs.models import Fetch
from today.jobs.repo import SourceReport
from today.jobs.sources import SOURCES, make_client
from today.llm.analyst import Analyst

log = logging.getLogger(__name__)

SLOT_HOUR = 7
EVERY_DAYS = 2
LOOP_SECONDS = 60


def due_slot(
    conn: sqlite3.Connection, now: datetime, tz: ZoneInfo, every_days: int = EVERY_DAYS
) -> str | None:
    """Today's key ('2026-11-25T07') from 07:00 on, when the last run is `every_days` old or more."""
    local = now.astimezone(tz)
    if local.hour < SLOT_HOUR:
        return None
    last = conn.execute("SELECT MAX(slot) FROM job_runs").fetchone()[0]
    if last and (local.date() - date.fromisoformat(last[:10])).days < every_days:
        return None
    return f"{local.date().isoformat()}T{SLOT_HOUR:02d}"


def record_run(
    conn: sqlite3.Connection, slot: str, now: datetime, report: Mapping[str, SourceReport]
) -> None:
    report_json = json.dumps({name: dataclasses.asdict(r) for name, r in report.items()})
    conn.execute(
        "INSERT INTO job_runs (slot, ran_at, report_json) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
        (slot, now.isoformat(), report_json),
    )


def select_sources(names: frozenset[str] | None) -> dict[str, Fetch]:
    """All sources, or only the named ones (`JOBS_SOURCES`). An unknown name is a configuration error."""
    if names is None:
        return dict(SOURCES)
    unknown = names - SOURCES.keys()
    if unknown:
        raise ValueError(f"unknown job sources in JOBS_SOURCES: {', '.join(sorted(unknown))}")
    return {name: fetch for name, fetch in SOURCES.items() if name in names}


def run_slot(
    conn: sqlite3.Connection,
    slot: str,
    sources: Mapping[str, Fetch],
    now: datetime,
    *,
    analyst: Analyst | None = None,
    model: str = "sonnet",
    limit: int = 20,
    push_score: int = 75,
    send: notify.Send | None = None,
) -> None:
    """Collect, record the slot, then (with an analyst) analyze pending jobs and push the strong ones."""
    with make_client() as client:
        report = collect(conn, client, sources, now)
        record_run(conn, slot, now, report)
        try:  # after record_run: a failure here must not leave the slot due (it would recollect each minute)
            check_interested_open(conn, client, now)
        except Exception:
            log.exception("job slot %s: interested-jobs page check failed", slot)
    log.info("job slot %s: %s", slot, {name: (r.new, r.error) for name, r in report.items()})
    if analyst is None:
        return
    analysis = analyze_pending(conn, analyst, model, now, limit)
    pushed = notify.push_strong(conn, analysis.analyzed, push_score, now, send)
    log.info(
        "job slot %s analysis: %s analyzed, %s failed, %s pushed%s",
        slot,
        len(analysis.analyzed),
        analysis.failed,
        pushed,
        f" (skipped: {analysis.skipped_reason})" if analysis.skipped_reason else "",
    )


async def run_jobs_loop(app) -> None:
    """Every minute: if a slot is due, collect in a thread and record it. Never dies on an error."""
    while True:
        try:
            state = app.state
            now = state.clock()
            slot = due_slot(state.conn, now, state.settings.tz, state.settings.jobs_every_days)
            if slot:
                settings = state.settings
                run = partial(
                    run_slot,
                    state.conn,
                    slot,
                    state.job_sources,
                    now,
                    analyst=state.analyst,
                    model=settings.analyst_model,
                    limit=settings.analyze_limit,
                    push_score=settings.jobs_push_score,
                    send=state.push_sender,
                )
                await run_in_threadpool(run)
        except Exception:
            log.exception("jobs loop tick failed")
        await asyncio.sleep(LOOP_SECONDS)
