"""Collection slots at 07:00, 13:00 and 19:00 local (ADR 0001: an asyncio task in the app process).

Each slot runs once, recorded in `job_runs`. After a restart or an outage only the latest slot of the day
that is still missing runs, so a restart at 13:05 collects once and never twice."""

import asyncio
import dataclasses
import json
import logging
import sqlite3
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from zoneinfo import ZoneInfo

from starlette.concurrency import run_in_threadpool

from today import notify
from today.jobs.analyze import analyze_pending
from today.jobs.collect import collect
from today.jobs.models import Fetch
from today.jobs.repo import SourceReport
from today.jobs.sources import SOURCES, make_client
from today.llm.analyst import Analyst

log = logging.getLogger(__name__)

SLOT_HOURS = (7, 13, 19)
LOOP_SECONDS = 60


def due_slot(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo) -> str | None:
    """The key ('2026-11-23T13') of today's latest slot at or before `now`, unless it already ran."""
    local = now.astimezone(tz)
    passed = [h for h in SLOT_HOURS if h <= local.hour]
    if not passed:
        return None
    slot = f"{local.date().isoformat()}T{passed[-1]:02d}"
    done = conn.execute("SELECT 1 FROM job_runs WHERE slot = ?", (slot,)).fetchone()
    return None if done else slot


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
            slot = due_slot(state.conn, now, state.settings.tz)
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
