import json
import sqlite3
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from py_vapid import Vapid01

from today import notify
from today.items.reminders import add_reminders
from today.items.repo import ItemIn, create_item, mark_done

TZ = ZoneInfo("America/Fortaleza")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)  # Tue 10 Nov 2026, 09:00 in Fortaleza


class FakeSender:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.results = results or {}
        self.sent: list[tuple[str, dict]] = []

    def __call__(self, sub: notify.Subscription, payload: str) -> str:
        self.sent.append((sub.endpoint, json.loads(payload)))
        return self.results.get(sub.endpoint, "ok")


def subscribe(conn, endpoint="https://push.example/a", lang="pt"):
    notify.save_subscription(conn, endpoint=endpoint, p256dh="k", auth="a", lang=lang, now=NOW)


def item_with_reminder(conn, title, due, remind, notes=None):
    item = create_item(conn, ItemIn(title=title, due_at=due, notes=notes), NOW - timedelta(days=1))
    add_reminders(conn, item.id, [remind])
    return item


def unsent(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM reminders WHERE sent_at IS NULL").fetchone()[0]


def test_single_due_reminder_sent_and_marked(conn: sqlite3.Connection):
    subscribe(conn)
    item_with_reminder(
        conn, "Prova de SD", datetime(2026, 11, 10, 10, 0, tzinfo=TZ), NOW - timedelta(minutes=1)
    )
    send = FakeSender()

    report = notify.deliver_due(conn, NOW, TZ, send)

    ((endpoint, payload),) = send.sent
    assert payload["title"] == "10:00 · Prova de SD"
    assert payload["url"] == "/"
    assert report.reminders == 1 and report.delivered == 1
    assert unsent(conn) == 0
    assert notify.status(conn).last_success_at == NOW


def test_several_due_grouped_in_one_notification(conn: sqlite3.Connection):
    subscribe(conn)
    item_with_reminder(conn, "A", NOW + timedelta(hours=1), NOW - timedelta(minutes=2))
    item_with_reminder(conn, "B", NOW + timedelta(hours=2), NOW)
    send = FakeSender()

    notify.deliver_due(conn, NOW, TZ, send)

    ((_, payload),) = send.sent
    assert payload["title"] == "2 lembretes agora"
    assert "A" in payload["body"] and "B" in payload["body"]


def test_future_reminder_not_sent(conn: sqlite3.Connection):
    subscribe(conn)
    item_with_reminder(conn, "later", NOW + timedelta(hours=2), NOW + timedelta(minutes=1))
    send = FakeSender()

    notify.deliver_due(conn, NOW, TZ, send)

    assert send.sent == [] and unsent(conn) == 1


def test_done_item_reminder_marked_without_sending(conn: sqlite3.Connection):
    subscribe(conn)
    item = item_with_reminder(conn, "done already", NOW + timedelta(hours=1), NOW - timedelta(minutes=1))
    mark_done(conn, item.id, NOW)
    send = FakeSender()

    notify.deliver_due(conn, NOW, TZ, send)

    assert send.sent == [] and unsent(conn) == 0


def test_gone_subscription_deleted(conn: sqlite3.Connection):
    subscribe(conn, "https://push.example/old")
    subscribe(conn, "https://push.example/new")
    item_with_reminder(conn, "x", NOW + timedelta(hours=1), NOW)
    send = FakeSender({"https://push.example/old": "gone"})

    report = notify.deliver_due(conn, NOW, TZ, send)

    assert [s.endpoint for s in notify.list_subscriptions(conn)] == ["https://push.example/new"]
    assert report.delivered == 1 and unsent(conn) == 0


def test_error_retries_then_gives_up_after_one_hour(conn: sqlite3.Connection):
    subscribe(conn)
    item_with_reminder(conn, "x", NOW + timedelta(hours=3), NOW)
    send = FakeSender({"https://push.example/a": "error"})

    notify.deliver_due(conn, NOW, TZ, send)
    assert unsent(conn) == 1  # will retry
    notify.deliver_due(conn, NOW + timedelta(minutes=30), TZ, send)
    assert unsent(conn) == 1
    notify.deliver_due(conn, NOW + timedelta(minutes=61), TZ, send)
    assert unsent(conn) == 0  # gave up
    assert notify.status(conn).last_error is not None


def test_no_subscription_marks_sent(conn: sqlite3.Connection):
    item_with_reminder(conn, "x", NOW + timedelta(hours=1), NOW)
    notify.deliver_due(conn, NOW, TZ, FakeSender())
    assert unsent(conn) == 0


def test_payload_language_follows_subscription(conn: sqlite3.Connection):
    subscribe(conn, "https://push.example/en", lang="en")
    subscribe(conn, "https://push.example/pt", lang="pt")
    item_with_reminder(conn, "A", NOW + timedelta(hours=1), NOW)
    item_with_reminder(conn, "B", NOW + timedelta(hours=1), NOW)
    send = FakeSender()

    notify.deliver_due(conn, NOW, TZ, send)

    titles = dict((endpoint, payload["title"]) for endpoint, payload in send.sent)
    assert titles == {
        "https://push.example/en": "2 reminders now",
        "https://push.example/pt": "2 lembretes agora",
    }


def test_badge_counts_late_and_today(conn: sqlite3.Connection):
    subscribe(conn)
    create_item(conn, ItemIn(title="late", due_at=NOW - timedelta(days=1)), NOW)
    item_with_reminder(conn, "soon", NOW + timedelta(hours=1), NOW)
    send = FakeSender()

    notify.deliver_due(conn, NOW, TZ, send)

    assert send.sent[0][1]["badge"] == 2


def test_daily_summary_once_after_8_and_only_with_items(conn: sqlite3.Connection):
    subscribe(conn)
    send = FakeSender()
    seven = datetime(2026, 11, 10, 7, 59, tzinfo=TZ)
    eight = datetime(2026, 11, 10, 8, 0, tzinfo=TZ)

    assert not notify.daily_summary(conn, eight, TZ, send)  # nothing today: no summary
    create_item(conn, ItemIn(title="Prova de SD", due_at=datetime(2026, 11, 10, 10, 0, tzinfo=TZ)), NOW)
    create_item(conn, ItemIn(title="Download dataset", due_at=datetime(2026, 11, 9, 9, 0, tzinfo=TZ)), NOW)

    assert not notify.daily_summary(conn, seven, TZ, send)
    assert notify.daily_summary(conn, eight, TZ, send)
    assert not notify.daily_summary(conn, eight + timedelta(hours=2), TZ, send)  # once per day

    ((_, payload),) = send.sent
    assert payload["title"] == "TERÇA · 1 hoje, 1 atrasado"
    assert "10:00 Prova de SD" in payload["body"] and "Download dataset" in payload["body"]
    assert notify.daily_summary(conn, eight + timedelta(days=1), TZ, send)  # next day: both are late now


def test_vapid_keys_roundtrip():
    private, public = notify.generate_vapid_keys()

    vapid = Vapid01.from_string(private_key=private)
    assert notify.application_server_key(vapid) == public
    assert len(public) == 87  # 65-byte uncompressed P-256 point, base64url without padding


# --- the real sender, against a local fake push service ---------------------------------------------


class _PushService:
    """A local HTTP endpoint standing in for Apple's/Google's push service."""

    def __init__(self, status: int) -> None:
        import http.server
        import threading

        self.requests: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                outer.requests.append(
                    {"headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
                )
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/push/abc"

    def close(self) -> None:
        self.server.shutdown()


def _browser_keys() -> tuple[str, str]:
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    point = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return notify._b64url(point), notify._b64url(os.urandom(16))


@pytest.mark.parametrize(("status", "expected"), [(201, "ok"), (410, "gone"), (404, "gone"), (500, "error")])
def test_make_sender_encrypts_signs_and_maps_status(status, expected):
    service = _PushService(status)
    try:
        private, public = notify.generate_vapid_keys()
        p256dh, auth = _browser_keys()
        send = notify.make_sender(private, "https://today.example")

        result = send(notify.Subscription(service.endpoint, p256dh, auth, "pt"), '{"title": "x"}')

        assert result == expected
        (request,) = service.requests
        assert request["headers"]["content-encoding"] == "aes128gcm"
        assert request["headers"]["authorization"].startswith("vapid t=")
        assert f"k={public}" in request["headers"]["authorization"]
        assert b"title" not in request["body"]  # the payload travels encrypted
    finally:
        service.close()
