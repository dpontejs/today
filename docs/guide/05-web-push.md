# 05 · Web push: reminders that ring on the phone

## Concepts

- **The three parties.** The *browser* (or the installed iPhone app) creates a **subscription**: an
  `endpoint` URL on its vendor's push service (Apple: `web.push.apple.com`) plus two keys. The *app server*
  stores it. To notify, the server POSTs an encrypted message to the endpoint; the vendor wakes the phone, and
  the **service worker** shows the notification, even with the app closed.
- **VAPID (RFC 8292).** The server signs each request with its own key pair, so the push service knows who
  is sending. The browser was told the public half (`applicationServerKey`) when it subscribed, and only
  messages signed with the matching private key are accepted. Header shape: `Authorization: vapid t=<JWT>, k=<public key>`.
- **Payload encryption (RFC 8291, `aes128gcm`).** The message is encrypted with the subscription's `p256dh`
  and `auth` keys; Apple and Google only carry ciphertext.
- **The loop.** Every 60 s `deliver_due` picks unsent reminders whose time has come, groups them into one
  notification, sends it to every device and marks them sent. A device that answers 404/410 is gone and is
  deleted; if every device fails, the reminder is retried for up to an hour.
- **iOS rules.** Push works only for the app added to the Home Screen; permission must be requested from a
  tap; every push must show a notification (no silent pushes); action buttons are ignored.

## Why

- In-process loop instead of an external scheduler: one source of truth, re-sends after a restart
  ([ADR 0001](../adr/0001-modular-monolith-with-in-process-scheduler.md)).
- One row per reminder with `sent_at` makes "already sent?" an indexed query ([ADR 0006](../adr/0006-reminders-table.md)).
- A status line and a test button exist because push fails silently by nature.

## Commands

```bash
uv run python -m today.notify keys        # VAPID_PRIVATE_KEY / VAPID_PUBLIC_KEY
VAPID_SUBJECT=https://today.example ... uv run uvicorn --factory today.app:from_env
```

## Exercises

1. Change `Vapid02` back to `Vapid01` in `make_sender` and run `tests/test_notify.py`. What does the
   `Authorization` header look like now, and why would Apple reject it?
2. Turn the phone's Focus mode on and send a test. Who decides whether it shows: the server, Apple, or iOS?
3. Stop the container for ten minutes with a reminder due in five. What happens when it starts again?

## Pitfalls

- `pywebpush` adds `aud` and `exp` to the claims dict you pass: build a new dict per call.
- Headless Chromium's shell build crashes on notifications; the service worker logic is checked by running
  `sw.js` against a fake `self` in Node, and the encryption/signing against a local fake push service.

## Read next

- *Software Architecture: The Hard Parts*: ch. 11 "Managing Distributed Workflows" (this is choreography
  with an external party you do not control: retries, idempotence, giving up).
- *Fundamentals of Software Architecture*: event-driven architecture: the push service as a broker you
  only talk to through a contract.
