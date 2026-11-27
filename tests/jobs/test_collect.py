import sqlite3
from datetime import UTC, datetime, timedelta
from functools import partial

import httpx
import pytest

from today.jobs import repo
from today.jobs.collect import collect
from today.jobs.models import JobPosting
from today.jobs.sources import greenhouse

NOW = datetime(2026, 11, 23, 16, 0, tzinfo=UTC)
OFFLINE = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))


def posting(external_id: str, title: str = "Machine Learning Engineer", source: str = "fake") -> JobPosting:
    return JobPosting(
        source=source,
        external_id=external_id,
        company="Acme",
        title=title,
        location="Brazil",
        workplace="remote",
        description=None,
        url=f"https://example.com/{external_id}",
        published_at=None,
    )


def static(*jobs: JobPosting):
    return lambda _client: list(jobs)


def count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


def test_collect_inserts_new_and_dedupes_by_source_and_id(conn: sqlite3.Connection):
    sources = {"fake": static(posting("1"), posting("2"), posting("3", "Account Executive"))}

    first = collect(conn, OFFLINE, sources, NOW, describers={})
    second = collect(conn, OFFLINE, sources, NOW + timedelta(hours=6), describers={})

    assert first["fake"] == repo.SourceReport(fetched=3, kept=2, new=2, error=None)
    assert second["fake"] == repo.SourceReport(fetched=3, kept=2, new=0, error=None)
    assert count(conn) == 2
    row = repo.list_jobs(conn, status="new", limit=10)[0]
    assert row.first_seen_at == NOW and row.status_at == NOW


def test_collect_keeps_user_status_on_resight(conn: sqlite3.Connection):
    sources = {"fake": static(posting("1"))}
    collect(conn, OFFLINE, sources, NOW, describers={})
    (row,) = repo.list_jobs(conn, status=None, limit=10)
    repo.set_status(conn, row.id, "interested", NOW + timedelta(hours=1))

    collect(conn, OFFLINE, sources, NOW + timedelta(hours=6), describers={})

    (again,) = repo.list_jobs(conn, status=None, limit=10)
    assert again.status == "interested"
    assert again.status_at == NOW + timedelta(hours=1)


def test_failing_source_reported_others_saved(conn: sqlite3.Connection):
    # Greenhouse answering 200 with a shape it never had: the adapter raises, the run goes on.
    changed = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"postings": []}))
    )
    sources = {"greenhouse:inter": partial(greenhouse.fetch, token="inter"), "fake": static(posting("1"))}

    report = collect(conn, changed, sources, NOW, describers={})

    assert report["greenhouse:inter"].error is not None
    assert report["greenhouse:inter"].new == 0
    assert report["fake"] == repo.SourceReport(fetched=1, kept=1, new=1, error=None)
    assert count(conn) == 1


def test_same_role_two_sources_kept_twice(conn: sqlite3.Connection):
    # By design: the same opening at Greenhouse and LinkedIn is two rows (different `source`).
    sources = {
        "greenhouse:inter": static(posting("42", source="greenhouse:inter")),
        "linkedin": static(posting("42", source="linkedin")),
    }

    collect(conn, OFFLINE, sources, NOW, describers={})

    assert count(conn) == 2


def test_collect_describes_only_new_kept_postings(conn: sqlite3.Connection):
    asked: list[str] = []

    def describe(_client: httpx.Client, external_id: str) -> str:
        asked.append(external_id)
        return f"about {external_id}"

    sources = {"linkedin": static(posting("1", source="linkedin"), posting("2", "Vendas", source="linkedin"))}
    collect(conn, OFFLINE, sources, NOW, describers={"linkedin": describe})
    collect(conn, OFFLINE, sources, NOW, describers={"linkedin": describe})

    assert asked == ["1"]
    (row,) = repo.list_jobs(conn, status=None, limit=10)
    assert row.description == "about 1"


def test_list_jobs_filters_by_status_newest_first(conn: sqlite3.Connection):
    collect(conn, OFFLINE, {"fake": static(posting("1"))}, NOW, describers={})
    collect(conn, OFFLINE, {"fake": static(posting("2"))}, NOW + timedelta(hours=6), describers={})
    first, second = repo.list_jobs(conn, status="new", limit=10)
    repo.set_status(conn, second.id, "dismissed", NOW)

    assert [j.external_id for j in repo.list_jobs(conn, status="new", limit=10)] == ["2"]
    assert [j.external_id for j in repo.list_jobs(conn, status="dismissed", limit=10)] == ["1"]
    assert first.external_id == "2"


def test_set_status_rejects_unknown_status_and_id(conn: sqlite3.Connection):
    collect(conn, OFFLINE, {"fake": static(posting("1"))}, NOW, describers={})
    (row,) = repo.list_jobs(conn, status=None, limit=10)

    with pytest.raises(ValueError, match="status"):
        repo.set_status(conn, row.id, "hired", NOW)
    with pytest.raises(ValueError, match="not found"):
        repo.set_status(conn, 999, "applied", NOW)


def test_partial_source_saves_jobs_and_reports_the_error(conn: sqlite3.Connection):
    from today.jobs.models import PartialFetch

    def blocked(_client: httpx.Client) -> list[JobPosting]:
        raise PartialFetch([posting("1", source="linkedin")], "blocked (HTTP 429) after 1 postings")

    report = collect(conn, OFFLINE, {"linkedin": blocked}, NOW, describers={})

    assert report["linkedin"] == repo.SourceReport(
        fetched=1, kept=1, new=1, error="blocked (HTTP 429) after 1 postings"
    )
    assert count(conn) == 1


# --- closed jobs ---------------------------------------------------------------------------------------


def closed_at(conn: sqlite3.Connection, external_id: str):
    return conn.execute("SELECT closed_at FROM jobs WHERE external_id = ?", (external_id,)).fetchone()[0]


def run(conn: sqlite3.Connection, name: str, ids: list[str], days: int) -> None:
    jobs = [posting(i, source=name) for i in ids]
    collect(conn, OFFLINE, {name: static(*jobs)}, NOW + timedelta(days=days), describers={})


def test_board_job_missing_twice_is_closed(conn: sqlite3.Connection):
    """Greenhouse/Lever/Ashby list every open job of the company: absent twice in a row means closed."""
    run(conn, "greenhouse:acme", ["1", "2"], 0)

    run(conn, "greenhouse:acme", ["1"], 2)
    assert closed_at(conn, "2") is None  # one miss can be a glitch

    run(conn, "greenhouse:acme", ["1"], 4)
    assert closed_at(conn, "2") is not None and closed_at(conn, "1") is None


def test_board_job_seen_again_resets_misses(conn: sqlite3.Connection):
    for ids, days in ((["1", "2"], 0), (["1"], 2), (["1", "2"], 4), (["1"], 6)):
        run(conn, "lever:acme", ids, days)

    assert closed_at(conn, "2") is None


def test_search_sources_never_close_by_absence(conn: sqlite3.Connection):
    """A search (Gupy portal, LinkedIn, Remotar...) not returning a job says nothing about it being closed."""
    run(conn, "gupy", ["1"], 0)
    for days in (2, 4, 6):
        run(conn, "gupy", [], days)

    assert closed_at(conn, "1") is None


def test_failed_board_fetch_closes_nothing(conn: sqlite3.Connection):
    name = "ashby:acme"
    run(conn, name, ["1"], 0)

    def broken(_client):
        raise httpx.ConnectError("down")

    for days in (2, 4):
        collect(conn, OFFLINE, {name: broken}, NOW + timedelta(days=days), describers={})

    assert closed_at(conn, "1") is None


def test_interested_search_job_closed_when_its_page_is_gone(conn: sqlite3.Connection):
    from today.jobs.collect import check_interested_open

    for key, source in (("gone", "gupy"), ("filled", "linkedin"), ("open", "remotar"), ("liked", "gupy")):
        repo.upsert_jobs(conn, [posting(key, source=source)], NOW)
    for row in repo.list_jobs(conn, None, 10):
        if row.external_id in ("gone", "filled", "open"):
            repo.set_status(conn, row.id, "interested", NOW)

    def page(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        if key == "gone":
            return httpx.Response(404)
        if key == "filled":
            return httpx.Response(200, text="<p>No longer accepting applications</p>")
        return httpx.Response(200, text="<p>Apply now</p>")

    client = httpx.Client(transport=httpx.MockTransport(page))
    checked = check_interested_open(conn, client, NOW, sleep=lambda _s: None)

    assert checked == 3  # only interested jobs from search sources are fetched
    assert closed_at(conn, "gone") and closed_at(conn, "filled")
    assert closed_at(conn, "open") is None and closed_at(conn, "liked") is None


def test_board_job_listed_again_reopens(conn: sqlite3.Connection):
    """Two glitchy runs must not bury a job for good: back on the board means open again."""
    for ids, days in ((["1", "2"], 0), (["1"], 2), (["1"], 4)):
        run(conn, "greenhouse:acme", ids, days)
    assert closed_at(conn, "2") is not None

    run(conn, "greenhouse:acme", ["1", "2"], 6)
    assert closed_at(conn, "2") is None


def test_empty_board_listing_closes_nothing(conn: sqlite3.Connection):
    """200 with jobs: [] (bad token, ATS migration, incident) is not proof that every job closed."""
    run(conn, "greenhouse:acme", ["1"], 0)
    for days in (2, 4):
        run(conn, "greenhouse:acme", [], days)

    assert closed_at(conn, "1") is None


def interested(conn: sqlite3.Connection, *jobs: JobPosting) -> None:
    repo.upsert_jobs(conn, list(jobs), NOW)
    for row in repo.list_jobs(conn, None, 10):
        repo.set_status(conn, row.id, "interested", NOW)


def test_linkedin_page_check_uses_browser_headers_and_pacing(conn: sqlite3.Connection):
    from today.jobs.collect import check_interested_open

    interested(conn, posting("a", source="linkedin"), posting("b", source="linkedin"))
    agents: list[str] = []
    slept: list[float] = []

    def page(request: httpx.Request) -> httpx.Response:
        agents.append(request.headers["user-agent"])
        return httpx.Response(999)  # LinkedIn's "go away": unknown, not closed

    client = httpx.Client(transport=httpx.MockTransport(page))
    check_interested_open(conn, client, NOW, sleep=slept.append)

    assert agents and all("Mozilla" in a for a in agents)
    assert slept and all(3 <= s <= 7 for s in slept)
    assert closed_at(conn, "a") is None and closed_at(conn, "b") is None


def test_bad_stored_url_does_not_break_the_check(conn: sqlite3.Connection):
    from today.jobs.collect import check_interested_open

    interested(conn, posting("x", source="gupy").model_copy(update={"url": "http://"}))
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    check_interested_open(conn, client, NOW, sleep=lambda _s: None)

    assert closed_at(conn, "x") is None
