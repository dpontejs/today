import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today import mcp_server
from today.app import create_app
from today.config import Settings
from today.items.repo import ItemIn, create_item, get_item

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
    assert names == {"list_items", "create_items", "complete_item", "reopen_item"}


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
