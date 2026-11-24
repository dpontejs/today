import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today import mcp_server
from today.app import create_app
from today.config import Settings
from today.items.reminders import add_reminders
from today.items.repo import ItemIn, create_item, get_item
from today.jobs.models import JobPosting
from today.jobs.repo import upsert_jobs

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # 09:00 in Fortaleza
TOKEN = "t" * 40
MCP_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def draft(title: str, due_at: str, **extra) -> mcp_server.DraftIn:
    return mcp_server.DraftIn(title=title, due_at=due_at, **extra)


# --- tool functions, called directly ---------------------------------------------------------------


def test_create_items_naive_due_is_local(conn: sqlite3.Connection):
    result = mcp_server.create_items(conn, [draft("Review ch. 3", "2026-11-11T09:00")], NOW, TZ)

    assert result["skipped_source_keys"] == []
    (created,) = result["created"]
    assert created["due_at"] == "2026-11-11T09:00:00-03:00"
    assert created["source"] == "mcp"
    row = conn.execute("SELECT due_at FROM items WHERE id = ?", (created["id"],)).fetchone()
    assert row["due_at"] == "2026-11-11T12:00:00+00:00"


def test_create_items_keeps_explicit_offset(conn: sqlite3.Connection):
    result = mcp_server.create_items(conn, [draft("x", "2026-11-11T12:00:00+00:00")], NOW, TZ)
    assert result["created"][0]["due_at"] == "2026-11-11T09:00:00-03:00"


def test_create_items_is_idempotent_by_source_key(conn: sqlite3.Connection):
    batch = [
        draft("Book ch. 1-2", "2026-11-30T18:00", source_key="roadmap:M0:book-ch-1-2"),
        draft("PySpark track", "2026-11-30T18:00", source_key="roadmap:M0:pyspark"),
    ]
    first = mcp_server.create_items(conn, batch, NOW, TZ)
    second = mcp_server.create_items(conn, batch, NOW, TZ)

    assert len(first["created"]) == 2
    assert second["created"] == []
    assert second["skipped_source_keys"] == ["roadmap:M0:book-ch-1-2", "roadmap:M0:pyspark"]
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


def test_create_items_rejects_more_than_100(conn: sqlite3.Connection):
    batch = [draft(f"t{i}", "2026-11-11T09:00") for i in range(101)]
    with pytest.raises(ValueError, match="at most 100"):
        mcp_server.create_items(conn, batch, NOW, TZ)
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0


def test_list_items_buckets_in_local_time(conn: sqlite3.Connection):
    create_item(conn, ItemIn(title="late", due_at=NOW - timedelta(days=1)), NOW)
    create_item(conn, ItemIn(title="soon", due_at=NOW + timedelta(hours=1)), NOW)
    create_item(conn, ItemIn(title="thursday", due_at=NOW + timedelta(days=2)), NOW)
    create_item(conn, ItemIn(title="in ten days", due_at=NOW + timedelta(days=10)), NOW)

    result = mcp_server.list_items(conn, NOW, TZ, days=7)

    assert [i["title"] for i in result["late"]] == ["late"]
    assert [i["title"] for i in result["today"]] == ["soon"]
    assert [i["title"] for i in result["next"]] == ["thursday"]
    assert result["today"][0]["due_at"] == "2026-11-10T10:00:00-03:00"
    assert [i["title"] for i in mcp_server.list_items(conn, NOW, TZ, days=14)["next"]] == [
        "thursday",
        "in ten days",
    ]


def test_list_items_rejects_silly_window(conn: sqlite3.Connection):
    with pytest.raises(ValueError, match="between 1 and 60"):
        mcp_server.list_items(conn, NOW, TZ, days=0)


def test_complete_and_reopen_item(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(hours=1)), NOW)

    assert mcp_server.complete_item(conn, item.id, NOW, TZ)["status"] == "done"
    assert mcp_server.reopen_item(conn, item.id, TZ)["status"] == "open"
    with pytest.raises(ValueError, match="item 999 not found"):
        mcp_server.complete_item(conn, 999, NOW, TZ)
    with pytest.raises(ValueError, match="item 999 not found"):
        mcp_server.reopen_item(conn, 999, TZ)


# --- over HTTP ------------------------------------------------------------------------------------


@pytest.fixture
def mcp_settings(settings: Settings) -> Settings:
    return Settings(**{**settings.__dict__, "api_token": TOKEN})


@pytest.fixture
def client(mcp_settings: Settings):
    app = create_app(mcp_settings)
    app.state.clock = lambda: NOW
    with TestClient(app, base_url="https://testserver", follow_redirects=False) as c:
        yield c


def rpc(client: TestClient, method: str, params: dict | None = None, headers: dict | None = None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers=headers or MCP_HEADERS)


def test_mcp_requires_token(client: TestClient):
    no_auth = {k: v for k, v in MCP_HEADERS.items() if k != "Authorization"}
    assert rpc(client, "tools/list", headers=no_auth).status_code == 401
    wrong = {**MCP_HEADERS, "Authorization": "Bearer nope"}
    assert rpc(client, "tools/list", headers=wrong).status_code == 401


def test_mcp_absent_without_api_token(settings: Settings):
    with TestClient(create_app(settings), base_url="https://testserver") as c:
        assert rpc(c, "tools/list").status_code == 404


def test_mcp_lists_tools(client: TestClient):
    response = rpc(client, "tools/list")

    assert response.status_code == 200
    names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert names == {
        "list_items",
        "create_items",
        "complete_item",
        "reopen_item",
        "update_item",
        "delete_item",
        "list_jobs",
        "update_job_status",
        "get_profile",
        "set_profile",
    }


def test_mcp_over_http_end_to_end(client: TestClient):
    args = {"items": [{"title": "Introduction to Docker", "due_at": "2026-11-10T15:00"}]}
    response = rpc(client, "tools/call", {"name": "create_items", "arguments": args})

    assert response.status_code == 200
    result = response.json()["result"]
    assert not result.get("isError")
    created = result["structuredContent"]["created"][0]
    assert get_item(client.app.state.conn, created["id"]).title == "Introduction to Docker"

    client.post("/login", data={"passphrase": PASSPHRASE})
    assert "Introduction to Docker" in client.get("/").text


def test_mcp_tool_error_is_reported(client: TestClient):
    response = rpc(client, "tools/call", {"name": "complete_item", "arguments": {"id": 999}})

    result = response.json()["result"]
    assert result["isError"] is True
    assert "item 999 not found" in result["content"][0]["text"]


# --- edit, delete and reminders -------------------------------------------------------------------


def test_update_item_changes_only_given_fields(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="old", due_at=NOW + timedelta(days=2), notes="keep"), NOW)

    out = mcp_server.update_item(conn, item.id, NOW, TZ, title="new", due_at="2026-11-20T09:00")

    assert (out["title"], out["due_at"], out["notes"]) == ("new", "2026-11-20T09:00:00-03:00", "keep")
    row = conn.execute("SELECT title, due_at, notes FROM items WHERE id = ?", (item.id,)).fetchone()
    assert tuple(row) == ("new", "2026-11-20T12:00:00+00:00", "keep")


def test_update_item_can_clear_notes(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(days=2), notes="x"), NOW)
    assert mcp_server.update_item(conn, item.id, NOW, TZ, notes="")["notes"] is None


def test_update_item_validates(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(days=2)), NOW)
    with pytest.raises(ValueError, match="nothing to update"):
        mcp_server.update_item(conn, item.id, NOW, TZ)
    with pytest.raises(ValueError, match="title"):
        mcp_server.update_item(conn, item.id, NOW, TZ, title="  ")
    with pytest.raises(ValueError, match="due_at"):
        mcp_server.update_item(conn, item.id, NOW, TZ, due_at="friday")
    with pytest.raises(ValueError, match="item 999 not found"):
        mcp_server.update_item(conn, 999, NOW, TZ, title="x")


def test_update_item_replaces_unsent_reminders_only(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="exam", due_at=datetime(2026, 11, 20, 12, 0, tzinfo=UTC)), NOW)
    add_reminders(
        conn, item.id, [datetime(2026, 11, 13, 12, 0, tzinfo=UTC), datetime(2026, 11, 19, 22, 0, tzinfo=UTC)]
    )
    conn.execute("UPDATE reminders SET sent_at = ? WHERE remind_at LIKE '2026-11-13%'", (NOW.isoformat(),))

    out = mcp_server.update_item(conn, item.id, NOW, TZ, reminders=["2026-11-20T08:00", "2026-11-01T09:00"])

    # the sent one stays (history), the unsent one is replaced, the past one is dropped
    assert out["reminders"] == ["2026-11-13T09:00:00-03:00", "2026-11-20T08:00:00-03:00"]


def test_delete_item_removes_item_and_reminders(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(days=2)), NOW)
    add_reminders(conn, item.id, [NOW + timedelta(days=1)])

    assert mcp_server.delete_item(conn, item.id) == {"deleted": item.id}
    assert get_item(conn, item.id) is None
    assert conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
    with pytest.raises(ValueError, match="item 999 not found"):
        mcp_server.delete_item(conn, 999)


def test_create_items_with_reminders(conn: sqlite3.Connection):
    batch = [draft("exam", "2026-11-20T09:00", reminders=["2026-11-19T19:00", "2026-11-25T09:00"])]

    (created,) = mcp_server.create_items(conn, batch, NOW, TZ)["created"]

    assert created["reminders"] == ["2026-11-19T19:00:00-03:00"]  # after the event: dropped


def test_list_items_shows_reminders(conn: sqlite3.Connection):
    item = create_item(conn, ItemIn(title="a", due_at=NOW + timedelta(hours=5)), NOW)
    add_reminders(conn, item.id, [NOW + timedelta(hours=4)])

    (listed,) = mcp_server.list_items(conn, NOW, TZ)["today"]

    assert listed["reminders"] == ["2026-11-10T13:00:00-03:00"]


def test_mcp_lists_edit_and_delete_tools(client: TestClient):
    names = {tool["name"] for tool in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"update_item", "delete_item"} <= names


# --- jobs (feature 07) ----------------------------------------------------------------------------


def seed_jobs(conn: sqlite3.Connection) -> list[int]:
    jobs = [
        JobPosting(
            source="gupy",
            external_id=str(n),
            company="Acme",
            title=f"ML Engineer {n}",
            location=None,
            workplace="remote",
            description="x" * 5000 if n == 1 else "short",
            url=f"https://acme.gupy.io/job/{n}",
            published_at=NOW,
        )
        for n in (1, 2)
    ]
    upsert_jobs(conn, jobs, NOW)
    return [r["id"] for r in conn.execute("SELECT id FROM jobs ORDER BY external_id")]


def test_mcp_list_jobs_filters_by_status(conn: sqlite3.Connection):
    first, second = seed_jobs(conn)
    mcp_server.update_job_status(conn, second, "interested", NOW, TZ)

    new = mcp_server.list_jobs(conn, TZ, status="new", limit=30)
    interested = mcp_server.list_jobs(conn, TZ, status="interested", limit=30)
    every = mcp_server.list_jobs(conn, TZ, status="all", limit=30)

    assert [j["id"] for j in new] == [first]
    assert [j["id"] for j in interested] == [second]
    assert len(every) == 2
    assert new[0]["first_seen_at"] == "2026-11-10T09:00:00-03:00"
    assert len(new[0]["description"]) <= mcp_server.MAX_DESCRIPTION + 1


def test_mcp_update_job_status_rejects_unknown_status(conn: sqlite3.Connection):
    (job_id, _) = seed_jobs(conn)

    with pytest.raises(ValueError, match="status must be one of"):
        mcp_server.update_job_status(conn, job_id, "hired", NOW, TZ)
    with pytest.raises(ValueError, match="limit"):
        mcp_server.list_jobs(conn, TZ, status="new", limit=0)
    assert mcp_server.update_job_status(conn, job_id, "applied", NOW, TZ)["status"] == "applied"


def test_mcp_jobs_require_bearer_token(client: TestClient):
    seed_jobs(client.app.state.conn)
    call = {"name": "list_jobs", "arguments": {}}
    no_auth = {k: v for k, v in MCP_HEADERS.items() if k != "Authorization"}

    assert rpc(client, "tools/call", call, headers=no_auth).status_code == 401
    response = rpc(client, "tools/call", call)
    result = response.json()["result"]
    assert not result.get("isError")
    assert [j["title"] for j in result["structuredContent"]["result"]] == ["ML Engineer 2", "ML Engineer 1"]

    bad = rpc(client, "tools/call", {"name": "update_job_status", "arguments": {"id": 1, "status": "hired"}})
    assert bad.json()["result"]["isError"] is True


# --- profile and analyses (feature 08) ------------------------------------------------------------


def scored(score: int):
    from today.jobs.models import JobAnalysis

    return JobAnalysis(
        meets=["Python"], gaps=[], workplace="remote", location=None, company_summary="x",
        seniority="junior", target_company=False, score=score, verdict="ok",
    )  # fmt: skip


def test_mcp_set_and_get_profile(client: TestClient):
    def call(name: str, arguments: dict) -> dict:
        result = rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
        assert not result.get("isError"), result
        return result["structuredContent"]

    assert call("get_profile", {}) == {"body_md": "", "updated": False}
    assert call("set_profile", {"body_md": "# Perfil\nPython"})["updated"] is True
    assert call("get_profile", {})["body_md"] == "# Perfil\nPython"
    bad = rpc(client, "tools/call", {"name": "set_profile", "arguments": {"body_md": "  "}})
    assert bad.json()["result"]["isError"] is True


def test_mcp_list_jobs_min_score(conn: sqlite3.Connection):
    from today.jobs.analysis_repo import store_analysis

    first, second = seed_jobs(conn)
    store_analysis(conn, first, scored(65), "sonnet", NOW)
    store_analysis(conn, second, scored(90), "sonnet", NOW)
    unscored = JobPosting(
        source="gupy", external_id="3", company="Acme", title="ML 3", location=None,
        workplace=None, description=None, url="https://x", published_at=None,
    )  # fmt: skip
    upsert_jobs(conn, [unscored], NOW)

    strong = mcp_server.list_jobs(conn, TZ, min_score=70)
    assert [(j["id"], j["score"]) for j in strong] == [(second, 90)]
    assert strong[0]["analysis"]["verdict"] == "ok" and strong[0]["status"] == "analyzed"

    both = mcp_server.list_jobs(conn, TZ, min_score=60)
    assert [j["score"] for j in both] == [90, 65]

    every = mcp_server.list_jobs(conn, TZ, status="all")
    assert {j["title"]: j["score"] for j in every}["ML 3"] is None
    assert mcp_server.list_jobs(conn, TZ, min_score=60, status="interested") == []
