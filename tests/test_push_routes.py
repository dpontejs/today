import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
from conftest import PASSPHRASE
from fastapi.testclient import TestClient

from today import notify
from today.app import create_app
from today.config import Settings, load_settings
from today.items.reminders import list_reminders

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
PT = {"Accept-Language": "pt-BR"}
SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BPk", "auth": "au"}}


@pytest.fixture
def vapid_settings(settings: Settings) -> Settings:
    private, public = notify.generate_vapid_keys()
    return Settings(
        **{
            **settings.__dict__,
            "vapid_private_key": private,
            "vapid_public_key": public,
            "vapid_subject": "https://today.example",
        }
    )


class Recorder:
    def __init__(self) -> None:
        self.sent = []

    def __call__(self, sub, payload):
        self.sent.append(sub.endpoint)
        return "ok"


@pytest.fixture
def client(vapid_settings: Settings) -> TestClient:
    app = create_app(vapid_settings)
    app.state.clock = lambda: NOW
    app.state.push_sender = Recorder()
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    return c


def db(client: TestClient) -> sqlite3.Connection:
    return client.app.state.conn


def test_public_key_served(client: TestClient, vapid_settings: Settings):
    assert client.get("/push/key").json() == {"public_key": vapid_settings.vapid_public_key}


def test_subscribe_upserts_and_unsubscribe_removes(client: TestClient):
    assert client.post("/push/subscribe", json=SUB, headers=PT).status_code == 204
    renewed = {**SUB, "keys": {"p256dh": "NEW", "auth": "au2"}}
    assert client.post("/push/subscribe", json=renewed, headers=PT).status_code == 204

    (sub,) = notify.list_subscriptions(db(client))
    assert (sub.p256dh, sub.lang) == ("NEW", "pt")

    assert client.post("/push/unsubscribe", json={"endpoint": SUB["endpoint"]}).status_code == 204
    assert notify.list_subscriptions(db(client)) == []


def test_subscribe_rejects_bad_payload(client: TestClient):
    assert client.post("/push/subscribe", json={"endpoint": "x"}).status_code == 422
    assert client.post("/push/subscribe", json={**SUB, "endpoint": "http://insecure"}).status_code == 422


def test_test_push_reports_device_count(client: TestClient):
    assert "Nenhum aparelho" in client.post("/push/test", headers=PT).text
    client.post("/push/subscribe", json=SUB, headers=PT)

    html = client.post("/push/test", headers=PT).text

    assert "Enviado para 1 aparelho" in html
    assert client.app.state.push_sender.sent == [SUB["endpoint"]]


def test_status_shows_last_delivery(client: TestClient):
    html = client.get("/", headers=PT).text
    assert 'id="push-status"' in html and "Ativar notificações" in html

    client.post("/push/subscribe", json=SUB, headers=PT)
    client.post("/push/test", headers=PT)
    html = client.get("/", headers=PT).text
    assert "1 aparelho" in html and "último envio 09:00" in html


def test_push_routes_require_session(vapid_settings: Settings):
    anonymous = TestClient(create_app(vapid_settings), base_url="https://testserver", follow_redirects=False)
    for path in ["/push/subscribe", "/push/unsubscribe", "/push/test"]:
        assert anonymous.post(path, json=SUB).status_code == 303
    assert anonymous.get("/push/key").status_code == 303


def test_push_disabled_without_vapid(settings: Settings):
    app = create_app(settings)
    c = TestClient(app, base_url="https://testserver", follow_redirects=False)
    c.post("/login", data={"passphrase": PASSPHRASE})
    assert c.get("/push/key").status_code == 404
    assert c.post("/push/subscribe", json=SUB).status_code == 404
    assert 'id="push-status"' not in c.get("/").text


def test_load_settings_requires_subject_with_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "h")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("VAPID_PRIVATE_KEY", "k")
    monkeypatch.setenv("VAPID_PUBLIC_KEY", "p")
    monkeypatch.delenv("VAPID_SUBJECT", raising=False)
    with pytest.raises(RuntimeError, match="VAPID_SUBJECT"):
        load_settings()


def test_default_reminder_at_due_for_manual_form(client: TestClient):
    client.post("/items", data={"title": "Review ch. 3", "due_at": "2026-11-11T09:00"})

    item_id = db(client).execute("SELECT id FROM items").fetchone()["id"]
    assert list_reminders(db(client), item_id) == [datetime(2026, 11, 11, 12, 0, tzinfo=UTC)]


def test_default_reminder_for_mcp_only_when_reminders_omitted(conn: sqlite3.Connection):
    from zoneinfo import ZoneInfo

    from today import mcp_server

    tz = ZoneInfo("America/Fortaleza")
    omitted = mcp_server.DraftIn(title="a", due_at="2026-11-11T09:00")
    explicit_none = mcp_server.DraftIn(title="b", due_at="2026-11-11T09:00", reminders=[])

    a, b = mcp_server.create_items(conn, [omitted, explicit_none], NOW, tz)["created"]

    assert a["reminders"] == ["2026-11-11T09:00:00-03:00"]
    assert b["reminders"] == []


def test_past_due_manual_item_gets_no_reminder(client: TestClient):
    client.post(
        "/items", data={"title": "yesterday", "due_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")}
    )
    assert db(client).execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0
