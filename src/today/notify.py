"""Web push: device subscriptions, the reminder loop and the 08:00 summary (ADR 0001, ADR 0006).

`deliver_due` and `daily_summary` are one tick each and take `send(subscription, payload) -> "ok" | "gone" |
"error"`, so tests use a fake and production uses `make_sender` (pywebpush + VAPID). `run_loop` calls them
every minute from the FastAPI lifespan.
"""

import asyncio
import base64
import json
import logging
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.concurrency import run_in_threadpool

from today.i18n import LANGS, day_label, weekday_long
from today.items.repo import Item, row_to_item, to_db
from today.items.today import build_today

log = logging.getLogger("today.notify")

Send = Callable[["Subscription", str], str]
GIVE_UP_AFTER = timedelta(hours=1)
SUMMARY_FROM_HOUR, SUMMARY_UNTIL_HOUR = 8, 12
LOOP_SECONDS = 60

TEXT = {
    "en": {"many": "{n} reminders now", "summary": "{weekday} · {today} today, {late} late", "late": "Late"},
    "pt": {
        "many": "{n} lembretes agora",
        "summary": "{weekday} · {today} hoje, {late} {late_word}",
        "late": "Atrasado",
    },
}


@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str
    lang: str


@dataclass(frozen=True)
class DeliveryReport:
    reminders: int = 0
    delivered: int = 0
    failed: int = 0


@dataclass(frozen=True)
class PushStatus:
    devices: int
    last_success_at: datetime | None
    last_error: str | None


# --- subscriptions ---------------------------------------------------------------------------------


def save_subscription(
    conn: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, lang: str, now: datetime
) -> None:
    conn.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, lang, created_at) VALUES (?, ?, ?, ?, ?)
           ON CONFLICT (endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,
                                                lang = excluded.lang, last_error = NULL""",
        (endpoint, p256dh, auth, lang if lang in LANGS else "en", to_db(now)),
    )


def delete_subscription(conn: sqlite3.Connection, endpoint: str) -> None:
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def list_subscriptions(conn: sqlite3.Connection) -> list[Subscription]:
    rows = conn.execute("SELECT endpoint, p256dh, auth, lang FROM push_subscriptions ORDER BY id").fetchall()
    return [Subscription(r["endpoint"], r["p256dh"], r["auth"], r["lang"]) for r in rows]


def status(conn: sqlite3.Connection) -> PushStatus:
    row = conn.execute(
        """SELECT COUNT(*) AS n, MAX(last_success_at) AS ok,
                  (SELECT last_error FROM push_subscriptions WHERE last_error IS NOT NULL
                   ORDER BY id DESC LIMIT 1) AS err
           FROM push_subscriptions"""
    ).fetchone()
    last_error = row["err"] or _kv(conn, "last_push_error")
    return PushStatus(row["n"], datetime.fromisoformat(row["ok"]) if row["ok"] else None, last_error)


def _kv(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM push_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _set_kv(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO push_state (key, value) VALUES (?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def send_to_all(
    conn: sqlite3.Connection, now: datetime, send: Send, payload_for: Callable[[str], dict]
) -> tuple:
    delivered = failed = 0
    for sub in list_subscriptions(conn):
        result = send(sub, json.dumps(payload_for(sub.lang), ensure_ascii=False))
        if result == "ok":
            delivered += 1
            conn.execute(
                "UPDATE push_subscriptions SET last_success_at = ?, last_error = NULL WHERE endpoint = ?",
                (to_db(now), sub.endpoint),
            )
        elif result == "gone":
            delete_subscription(conn, sub.endpoint)
            _set_kv(conn, "last_push_error", f"{now.isoformat()} subscription expired and was removed")
        else:
            failed += 1
            conn.execute(
                "UPDATE push_subscriptions SET last_error = ? WHERE endpoint = ?",
                (f"{now.isoformat()} delivery failed", sub.endpoint),
            )
    return delivered, failed


# --- reminders -------------------------------------------------------------------------------------


def _badge(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo) -> int:
    view = build_today(conn, now, tz)
    return len(view.late) + len(view.today)


def _reminder_payload(items: list[Item], lang: str, now: datetime, tz: ZoneInfo, badge: int) -> dict:
    if len(items) == 1:
        (item,) = items
        due = item.due_at.astimezone(tz)
        title = f"{due:%H:%M} · {item.title}"
        body = item.notes or day_label(due, lang)
    else:
        title = TEXT[lang]["many"].format(n=len(items))
        body = "\n".join(f"{i.due_at.astimezone(tz):%H:%M} {i.title}" for i in items)
    return {"title": title, "body": body, "url": "/", "tag": f"reminders-{now:%Y%m%d%H%M}", "badge": badge}


def deliver_due(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo, send: Send) -> DeliveryReport:
    rows = conn.execute(
        """SELECT r.id AS reminder_id, r.remind_at, i.* FROM reminders r JOIN items i ON i.id = r.item_id
           WHERE r.sent_at IS NULL AND r.remind_at <= ? ORDER BY r.remind_at, r.id""",
        (to_db(now),),
    ).fetchall()
    if not rows:
        return DeliveryReport()

    def mark(ids: list[int]) -> None:
        conn.executemany("UPDATE reminders SET sent_at = ? WHERE id = ?", [(to_db(now), i) for i in ids])

    mark([r["reminder_id"] for r in rows if r["status"] == "done"])  # finished: nothing to remind
    pending = [r for r in rows if r["status"] == "open"]
    if not pending:
        return DeliveryReport()

    items = list({r["id"]: row_to_item(r) for r in pending}.values())
    badge = _badge(conn, now, tz)
    delivered, failed = send_to_all(
        conn, now, send, lambda lang: _reminder_payload(items, lang, now, tz, badge)
    )

    if delivered or not list_subscriptions(conn) and not failed:
        mark([r["reminder_id"] for r in pending])
    else:  # every device failed: retry next tick, but not forever
        cutoff = now - GIVE_UP_AFTER
        mark([r["reminder_id"] for r in pending if datetime.fromisoformat(r["remind_at"]) <= cutoff])
    return DeliveryReport(reminders=len(pending), delivered=delivered, failed=failed)


# --- 08:00 summary ---------------------------------------------------------------------------------


def _summary_payload(
    conn, now: datetime, tz: ZoneInfo, lang: str, late: list[Item], today: list[Item]
) -> dict:
    text = TEXT[lang]
    title = text["summary"].format(
        weekday=weekday_long(now.astimezone(tz), lang),
        today=len(today),
        late=len(late),
        late_word="atrasado" if len(late) == 1 else "atrasados",
    )
    lines = [f"{i.due_at.astimezone(tz):%H:%M} {i.title}" for i in today]
    lines += [f"{text['late']}: {i.title}" for i in late]
    return {
        "title": title,
        "body": "\n".join(lines),
        "url": "/",
        "tag": "daily-summary",
        "badge": len(late) + len(today),
    }


def daily_summary(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo, send: Send) -> bool:
    """Once per local day between 08:00 and 12:00, and only when something is late or due today."""
    local = now.astimezone(tz)
    if not SUMMARY_FROM_HOUR <= local.hour < SUMMARY_UNTIL_HOUR:
        return False
    day = local.date().isoformat()
    if conn.execute("SELECT 1 FROM daily_summaries WHERE day = ?", (day,)).fetchone():
        return False
    view = build_today(conn, now, tz)
    if not view.late and not view.today:
        return False
    conn.execute("INSERT INTO daily_summaries (day, sent_at) VALUES (?, ?)", (day, to_db(now)))
    delivered, _ = send_to_all(
        conn, now, send, lambda lang: _summary_payload(conn, now, tz, lang, view.late, view.today)
    )
    return delivered > 0


# --- VAPID and the real sender ---------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def generate_vapid_keys() -> tuple[str, str]:
    """(private key as base64url DER, applicationServerKey as base64url uncompressed point)."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(private), _b64url(public)


def application_server_key(vapid) -> str:
    return _b64url(
        vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
    )


def make_sender(private_key: str, subject: str) -> Send:
    from py_vapid import Vapid02  # RFC 8292 "vapid t=…, k=…", what aes128gcm push services (Apple) expect
    from pywebpush import WebPushException, webpush

    vapid = Vapid02.from_string(private_key=private_key)

    def send(sub: Subscription, payload: str) -> str:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": subject},  # pywebpush adds aud/exp to this dict: a fresh one per call
                ttl=3600,
                timeout=10,
            )
        except WebPushException as exc:
            code = exc.response.status_code if exc.response is not None else None
            log.warning("push to %s failed: %s", sub.endpoint[:40], code or exc)
            return "gone" if code in (404, 410) else "error"
        except Exception:  # network trouble: retried by the loop
            log.exception("push to %s failed", sub.endpoint[:40])
            return "error"
        return "ok"

    return send


async def run_loop(app) -> None:
    """Every minute: deliver due reminders, then maybe the daily summary. Never dies on an error."""
    while True:
        try:
            state = app.state
            now, tz = state.clock(), state.settings.tz
            await run_in_threadpool(deliver_due, state.conn, now, tz, state.push_sender)
            await run_in_threadpool(daily_summary, state.conn, now, tz, state.push_sender)
        except Exception:
            log.exception("reminder loop tick failed")
        await asyncio.sleep(LOOP_SECONDS)


if __name__ == "__main__":  # python -m today.notify keys
    if sys.argv[1:] == ["keys"]:
        private, public = generate_vapid_keys()
        print(f"VAPID_PRIVATE_KEY={private}\nVAPID_PUBLIC_KEY={public}")
    else:
        print("usage: python -m today.notify keys")
