import json
import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from today import notify
from today.config import load_settings
from today.jobs import analysis_repo
from today.jobs.loop import due_slot, record_run, run_slot, select_sources
from today.jobs.models import JobAnalysis, JobPosting
from today.jobs.repo import SourceReport

TZ = ZoneInfo("America/Fortaleza")


def local(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 23, hour, minute, tzinfo=TZ)


def day(d: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, d, hour, minute, tzinfo=TZ)


def test_collects_every_other_day_at_seven(conn: sqlite3.Connection):
    """Not applying in volume yet (2026-11-26): one collection at 07:00 every 2 days is enough."""
    assert due_slot(conn, day(23, 6, 59), TZ) is None
    assert due_slot(conn, day(23, 7, 5), TZ) == "2026-11-23T07"
    record_run(conn, "2026-11-23T07", day(23, 7, 5), {"gupy": SourceReport(3, 2, 2, None)})

    assert due_slot(conn, day(23, 20), TZ) is None  # never twice in a day
    assert due_slot(conn, day(24, 9), TZ) is None  # the day in between is skipped
    assert due_slot(conn, day(25, 6, 59), TZ) is None
    assert due_slot(conn, day(25, 7), TZ) == "2026-11-25T07"


def test_after_an_outage_collects_once_on_the_first_due_day(conn: sqlite3.Connection):
    record_run(conn, "2026-11-23T07", day(23, 7), {})

    assert due_slot(conn, day(27, 15), TZ) == "2026-11-27T07"
    record_run(conn, "2026-11-27T07", day(27, 15), {})
    assert due_slot(conn, day(28, 7), TZ) is None


def test_old_three_a_day_slots_count_as_the_last_run(conn: sqlite3.Connection):
    record_run(conn, "2026-11-24T19", day(24, 19), {})
    assert due_slot(conn, day(25, 7), TZ) is None
    assert due_slot(conn, day(26, 7), TZ) == "2026-11-26T07"


def test_every_days_is_configurable(conn: sqlite3.Connection):
    record_run(conn, "2026-11-23T07", day(23, 7), {})
    assert due_slot(conn, day(24, 7), TZ, every_days=1) == "2026-11-24T07"


def test_slot_key_is_local_date_even_when_utc_is_tomorrow(conn: sqlite3.Connection):
    # 22:00 in Fortaleza is 01:00 UTC on the 24th.
    assert due_slot(conn, day(23, 22).astimezone(ZoneInfo("UTC")), TZ) == "2026-11-23T07"


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


# --- analysis and push after the slot (feature 08) --------------------------------------------------


NOW = datetime(2026, 11, 23, 16, 0, tzinfo=UTC)


class ScoreAnalyst:
    """Scores each job by the number in its title: 'ML Engineer 90' → 90."""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, model, system, prompt, schema):
        self.calls += 1
        score = int(prompt.split("Título: ML Engineer ")[1].split("\n")[0])
        return JobAnalysis(
            meets=[], gaps=[], workplace="remote", location=None, company_summary="x",
            seniority="junior", target_company=False, score=score, verdict="ok",
        )  # fmt: skip


class Sender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def __call__(self, sub, payload: str) -> str:
        self.sent.append(json.loads(payload))
        return "ok"


def static_source(*scores: int, company: str = "Nubank"):
    postings = [
        JobPosting(
            source="fake",
            external_id=str(s),
            company=company,
            title=f"ML Engineer {s}",
            location=None,
            workplace="remote",
            description=None,
            url=f"https://example.com/{s}",
            published_at=None,
        )  # fmt: skip
        for s in scores
    ]
    return {"fake": lambda _client: postings}


def ready(conn, lang: str = "pt") -> Sender:
    analysis_repo.set_profile(conn, "# Perfil\nPython", NOW)
    notify.save_subscription(conn, "https://push.example/a", "k", "a", lang, NOW)
    return Sender()


def test_strong_match_pushes_once_per_slot(conn: sqlite3.Connection):
    send = ready(conn)

    run_slot(
        conn, "2026-11-23T13", static_source(90, 40), NOW, analyst=ScoreAnalyst(), push_score=75, send=send
    )

    (payload,) = send.sent
    assert payload["title"] == "★ 90 · Nubank · ML Engineer 90"
    assert payload["url"] == "/"
    # Next slot, nothing new: no second push.
    run_slot(
        conn, "2026-11-23T19", static_source(90, 40), NOW, analyst=ScoreAnalyst(), push_score=75, send=send
    )
    assert len(send.sent) == 1


def test_several_strong_matches_grouped(conn: sqlite3.Connection):
    send = ready(conn)

    run_slot(conn, "2026-11-23T13", static_source(80, 95, 30), NOW, analyst=ScoreAnalyst(), send=send)

    (payload,) = send.sent
    assert payload["title"] == "2 vagas fortes"
    assert payload["body"].splitlines() == [
        "★ 95 · Nubank · ML Engineer 95",
        "★ 80 · Nubank · ML Engineer 80",
    ]


def test_strong_push_in_english(conn: sqlite3.Connection):
    send = ready(conn, lang="en")
    run_slot(conn, "2026-11-23T13", static_source(80, 95), NOW, analyst=ScoreAnalyst(), send=send)
    assert send.sent[0]["title"] == "2 strong jobs"


def test_no_strong_match_no_push(conn: sqlite3.Connection):
    send = ready(conn)
    run_slot(conn, "2026-11-23T13", static_source(74), NOW, analyst=ScoreAnalyst(), send=send)
    assert send.sent == []


def test_no_push_sender_still_analyzes(conn: sqlite3.Connection):
    analysis_repo.set_profile(conn, "# Perfil\nPython", NOW)

    run_slot(conn, "2026-11-23T13", static_source(90), NOW, analyst=ScoreAnalyst(), send=None)

    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "analyzed"
    assert len(analysis_repo.analyses_since(conn, NOW)) == 1


def test_slot_without_analyst_only_collects(conn: sqlite3.Connection):
    run_slot(conn, "2026-11-23T13", static_source(90), NOW)
    assert conn.execute("SELECT status FROM jobs").fetchone()[0] == "new"
    assert conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0] == 1


def test_analysis_respects_limit(conn: sqlite3.Connection):
    analysis_repo.set_profile(conn, "# Perfil\nPython", NOW)
    analyst = ScoreAnalyst()
    run_slot(conn, "2026-11-23T13", static_source(10, 20, 30), NOW, analyst=analyst, limit=2)
    assert analyst.calls == 2


def test_app_builds_analyst_from_settings(settings):
    from dataclasses import replace

    from today.app import create_app
    from today.llm.analyst import ClaudeCliAnalyst

    assert create_app(settings).state.analyst is None
    assert isinstance(create_app(replace(settings, analyst="claude_cli")).state.analyst, ClaudeCliAnalyst)


class TimingAnalyst(ScoreAnalyst):
    """Like ScoreAnalyst, but scores of 90 or more only fit after the move (e.g. hybrid in São Paulo)."""

    def complete(self, *, model, system, prompt, schema):
        result = super().complete(model=model, system=system, prompt=prompt, schema=schema)
        return result.model_copy(update={"timing": "after_move" if result.score >= 90 else "now"})


def test_after_move_match_not_pushed(conn: sqlite3.Connection):
    """A strong role that only fits after the move to São Paulo is listed, but does not ring the phone now."""
    send = ready(conn)

    run_slot(conn, "2026-11-23T13", static_source(95, 80), NOW, analyst=TimingAnalyst(), send=send)

    (payload,) = send.sent
    assert payload["title"] == "★ 80 · Nubank · ML Engineer 80"


def test_only_after_move_matches_sends_nothing(conn: sqlite3.Connection):
    send = ready(conn)

    run_slot(conn, "2026-11-23T13", static_source(95), NOW, analyst=TimingAnalyst(), send=send)

    assert send.sent == []
