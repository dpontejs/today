# 05 · Web push: reminders that actually ring on the phone

- **Date:** 2026-11-10
- **Status:** proposed
- **ADRs:** [0001](../adr/0001-modular-monolith-with-in-process-scheduler.md) (in-process loop), [0006](../adr/0006-reminders-table.md)

## Goal

Reminders arrive as notifications on the installed iPhone app (and any browser that subscribes), grouped when
several are due together, plus a daily summary at 08:00. The Today screen says whether notifications work.

## Out of scope

Snooze, notification action buttons (iOS ignores them), per-item notification settings, e-mail fallback.

## Contracts

```python
# GET  /push/key              → {"public_key": "<base64url applicationServerKey>"}         (session)
# POST /push/subscribe        JSON PushSubscription.toJSON() → 204; upsert by endpoint; stores request language
# POST /push/unsubscribe      {"endpoint": ...} → 204
# POST /push/test             → 200 fragment "Sent to N devices" / "No device subscribed"
# Disabled (404) when VAPID_PRIVATE_KEY is unset.

def deliver_due(conn, now, tz, send) -> DeliveryReport   # one loop tick; `send(sub, payload) -> "ok" | "gone" | "error"`
def daily_summary(conn, now, tz, send) -> bool            # at or after 08:00 local, once per day, only if something is late/today
```

- Migration `003_push.sql`: `push_subscriptions(id, endpoint UNIQUE, p256dh, auth, lang, created_at,
  last_success_at, last_error)` and `daily_summaries(day TEXT PRIMARY KEY, sent_at)`.
- Due reminders: `sent_at IS NULL AND remind_at <= now`, joined to items. Done items: marked sent, never shown.
  Delivered to at least one device → marked sent. All devices failed → retried next tick until the reminder is
  1 h old, then marked sent. `gone` (404/410) → subscription deleted.
- Grouping: one due reminder → title `HH:MM · <title>`, body = notes or the day; several → `N reminders now` /
  `N lembretes agora`, body = titles. Payload `{"title","body","url":"/","tag","badge":<late+today count>}`.
- Default reminder: items created by hand or by MCP **without** a `reminders` field get one at `due_at`
  (`reminders: []` means none). Capture keeps its explicit choice.
- Loop: started in the FastAPI lifespan when VAPID is configured; every 60 s runs `deliver_due` then
  `daily_summary` in a worker thread; exceptions are logged, never kill the loop.
- Env: `VAPID_PRIVATE_KEY` (base64url DER), `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` (`mailto:` or https URL).
  `python -m today.notify keys` prints a fresh pair.

## Acceptance criteria (as tests)

- [ ] `test_single_due_reminder_sent_and_marked`; `test_several_due_grouped_in_one_notification`.
- [ ] `test_future_reminder_not_sent`; `test_done_item_reminder_marked_without_sending`.
- [ ] `test_gone_subscription_deleted`; `test_error_retries_then_gives_up_after_one_hour`.
- [ ] `test_no_subscription_marks_sent`; `test_payload_language_follows_subscription`.
- [ ] `test_daily_summary_once_after_8_and_only_with_items`.
- [ ] `test_subscribe_upserts_and_unsubscribe_removes`; `test_push_routes_require_session`; `test_push_disabled_without_vapid`.
- [ ] `test_test_push_reports_device_count`; `test_status_shows_last_delivery`.
- [ ] `test_default_reminder_at_due_for_manual_and_mcp`; `test_vapid_keys_roundtrip`.

## End-to-end check

Production: enable on the installed iPhone app → "ENVIAR TESTE" arrives with the icon → create "teste em 3
minutos" by voice with a reminder → it arrives within ~1 minute of the time, app closed.

## Risks and open questions

- iOS only delivers to the home-screen app and may silently drop a subscription; the status line and the test
  button exist to make that visible.
