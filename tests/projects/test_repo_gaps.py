import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from helpers import job_with_gaps

from today.projects import repo as pr
from today.projects.gaps import gap_stats

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_gap_stats_counts_distinct_jobs_and_weights_interest(conn: sqlite3.Connection):
    job_with_gaps(conn, "a", [("Spark", "required"), ("Kubernetes", "nice_to_have")], NOW, score=50)
    job_with_gaps(conn, "b", [("Spark", "nice_to_have")], NOW, score=80)  # strong: x2
    job_with_gaps(conn, "c", [("Kubernetes", "required")], NOW, score=40, status="interested")  # x3

    stats = {s.skill: s for s in gap_stats(conn, NOW)}

    assert (stats["spark"].jobs, stats["spark"].required, stats["spark"].weight) == (2, 1, 3.0)
    assert (stats["kubernetes"].jobs, stats["kubernetes"].required, stats["kubernetes"].weight) == (2, 1, 4.0)
    assert [s.skill for s in gap_stats(conn, NOW)] == ["kubernetes", "spark"]  # heaviest first


def test_gap_stats_ignores_dismissed_and_old(conn: sqlite3.Connection):
    job_with_gaps(conn, "old", [("Spark", "required")], NOW - timedelta(days=61))
    job_with_gaps(conn, "nope", [("Spark", "required")], NOW, status="dismissed")
    job_with_gaps(conn, "ok", [("Airflow", "required")], NOW - timedelta(days=59))

    assert [s.skill for s in gap_stats(conn, NOW)] == ["airflow"]


def test_gap_stats_normalizes_skill_names(conn: sqlite3.Connection):
    job_with_gaps(conn, "a", [("Spark", "required"), (" spark ", "nice_to_have")], NOW)
    job_with_gaps(conn, "b", [("SPARK", "required")], NOW)

    (only,) = gap_stats(conn, NOW)
    assert (only.skill, only.jobs, only.required) == ("spark", 2, 2)


def test_gap_stats_limit(conn: sqlite3.Connection):
    job_with_gaps(conn, "a", [(f"skill{i}", "required") for i in range(30)], NOW)
    assert len(gap_stats(conn, NOW, limit=20)) == 20


def test_project_lifecycle_and_unknown_status(conn: sqlite3.Connection):
    pid = pr.create_project(conn, "credit-risk-mlops", "Risco de crédito no GCP", NOW)
    project = pr.get_project(conn, pid)
    assert (project.name, project.status, project.evaluation) == ("credit-risk-mlops", "idea", None)

    pr.update_project(conn, pid, NOW, status="active", repo_url="https://github.com/x/y")
    assert pr.get_project(conn, pid).status == "active"
    assert [p.id for p in pr.list_projects(conn, status="active")] == [pid]
    with pytest.raises(ValueError):
        pr.update_project(conn, pid, NOW, status="nope")
    assert pr.get_project(conn, 999) is None


def test_voice_samples_newest_first_and_limit(conn: sqlite3.Connection):
    for i in range(4):
        pr.add_voice_sample(conn, "linkedin_post", f"post {i}", NOW + timedelta(minutes=i))

    assert [s.body for s in pr.list_voice_samples(conn, "linkedin_post", limit=2)] == ["post 3", "post 2"]
    with pytest.raises(ValueError):
        pr.add_voice_sample(conn, "tweet", "x", NOW)
