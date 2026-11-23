import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from today.config import load_settings
from today.jobs.loop import due_slot, record_run, select_sources
from today.jobs.repo import SourceReport

TZ = ZoneInfo("America/Fortaleza")


def local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 23, hour, minute, tzinfo=TZ)


def test_loop_runs_each_slot_once_and_catches_up_after_restart(conn: sqlite3.Connection):
    record_run(conn, "2026-11-23T07", local(7, 1), {})

    assert due_slot(conn, local(13, 5), TZ) == "2026-11-23T13"  # restarted at 13:05: runs once on boot
    record_run(conn, "2026-11-23T13", local(13, 5), {"gupy": SourceReport(3, 2, 2, None)})
    assert due_slot(conn, local(13, 6), TZ) is None  # never twice
    assert due_slot(conn, local(6, 59), TZ) is None  # nothing before the first slot of the day


def test_loop_after_a_long_outage_runs_only_the_latest_slot(conn: sqlite3.Connection):
    assert due_slot(conn, local(20), TZ) == "2026-11-23T19"
    record_run(conn, "2026-11-23T19", local(20), {})
    assert due_slot(conn, local(23, 59), TZ) is None


def test_slot_key_is_local_date_even_when_utc_is_tomorrow(conn: sqlite3.Connection):
    # 22:00 in Fortaleza is 01:00 UTC on the 24th.
    assert due_slot(conn, local(22).astimezone(ZoneInfo("UTC")), TZ) == "2026-11-23T19"


def test_record_run_stores_the_report_as_json(conn: sqlite3.Connection):
    record_run(conn, "2026-11-23T07", local(7, 1), {"gupy": SourceReport(3, 2, 1, None)})

    row = conn.execute("SELECT * FROM job_runs").fetchone()
    assert row["slot"] == "2026-11-23T07"
    assert '"new": 1' in row["report_json"]


def test_settings_jobs_off_by_default_and_sources_list(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "x")
    monkeypatch.setenv("SESSION_SECRET", "y")
    monkeypatch.delenv("JOBS_ENABLED", raising=False)
    monkeypatch.delenv("JOBS_SOURCES", raising=False)
    off = load_settings()
    assert off.jobs_enabled is False and off.jobs_sources is None

    monkeypatch.setenv("JOBS_ENABLED", "true")
    monkeypatch.setenv("JOBS_SOURCES", " gupy, linkedin ,")
    on = load_settings()
    assert on.jobs_enabled is True
    assert on.jobs_sources == frozenset({"gupy", "linkedin"})


def test_select_sources_keeps_the_named_ones_and_rejects_unknown():
    assert set(select_sources(None)) >= {"gupy", "linkedin", "greenhouse:inter"}
    assert set(select_sources(frozenset({"gupy", "remotar"}))) == {"gupy", "remotar"}
    with pytest.raises(ValueError, match="nope"):
        select_sources(frozenset({"nope"}))


def test_app_rejects_unknown_job_source_at_startup(settings):
    from dataclasses import replace

    from today.app import create_app

    with pytest.raises(ValueError, match="nope"):
        create_app(replace(settings, jobs_enabled=True, jobs_sources=frozenset({"nope"})))
    app = create_app(replace(settings, jobs_enabled=True, jobs_sources=frozenset({"gupy"})))
    assert set(app.state.job_sources) == {"gupy"}
