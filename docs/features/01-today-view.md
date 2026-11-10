# 01 · Items, Today view, login, deploy

- **Date:** 2026-11-10
- **Status:** proposed
- **ADRs:** 0001, 0002, 0004

## Goal

An installable PWA at `today.diegoponte.dev`, behind a passphrase, that shows what is late, today and next,
and lets me add, finish and reopen items by hand. Running on the VPS, so slice 2 can add push on top.

## Out of scope

Push and reminders (slice 2), ROADMAP import (3), text/audio capture (4, 5), editing and deleting items,
recurrence, offline mode (the service worker only makes the app installable).

## Contracts

```python
# Pages (HTML, Jinja + HTMX)
# GET  /            → Today view (late, today, next 7 days, add form)
# GET  /login       → form;  POST /login → 303 / (sets cookie) | 401 form with error | 429 after 5 fails/10 min
# POST /logout      → 303 /login
# POST /items                 → 303 / | 422 form with field errors
# POST /items/{id}/done       → HTMX fragment of the row; 404 if missing
# POST /items/{id}/reopen     → HTMX fragment of the row; 404 if missing
# GET  /healthz → 200 {"status":"ok"} · GET /manifest.webmanifest · GET /sw.js (no auth)

class ItemIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime          # form sends local time; converted to UTC
    remind_at: AwareDatetime | None = None
    notes: str | None = Field(default=None, max_length=2000)
```

- Database: migration `001_items.sql`:
  `items(id INTEGER PK, title TEXT NOT NULL, notes TEXT, due_at TEXT NOT NULL, remind_at TEXT,
  status TEXT NOT NULL CHECK (status IN ('open','done')) DEFAULT 'open', done_at TEXT,
  source TEXT NOT NULL DEFAULT 'manual', source_key TEXT UNIQUE, created_at TEXT NOT NULL)`; all times UTC ISO.
- Buckets (in `America/Fortaleza`): **late** = open and `due_at < now`; **today** = open and
  `now ≤ due_at < end of local day`; **next** = open and due within the following 7 local days. Done items of
  today show struck through at the bottom.
- Visual identity: the direction chosen on the identity canvas, written down as tokens in `docs/design.md`.

## Acceptance criteria (as tests)

- [ ] `test_buckets_split_late_today_next`: given items due yesterday, in 1 h and in 3 days, when Today is built at a fixed `now`, then each lands in its bucket.
- [ ] `test_bucket_boundary_uses_local_midnight`: given `now` 23:30 Fortaleza and an item due 00:30 local tomorrow, then it is in next, not today.
- [ ] `test_due_at_stored_as_utc`: given a form with 09:00 local, when posted, then the row holds `12:00:00+00:00`.
- [ ] `test_create_rejects_empty_title`: given an empty title, when posted, then 422 and no row.
- [ ] `test_done_then_reopen_round_trip`: given an open item, when done then reopen, then status is open and `done_at` is null.
- [ ] `test_done_is_idempotent`: given a done item, when done again, then 200 and `done_at` unchanged.
- [ ] `test_unknown_item_returns_404`: when done on a missing id, then 404.
- [ ] `test_routes_require_session`: given no cookie, when GET / or POST /items, then 303 to /login; `/healthz`, manifest and `sw.js` stay public.
- [ ] `test_login_wrong_passphrase_401`, `test_login_rate_limited_after_5_failures`.
- [ ] `test_session_cookie_flags`: cookie is HttpOnly, Secure, SameSite=Lax, 90 days.
- [ ] `test_migrations_apply_once`: starting twice leaves one `schema_version` row per migration.

## End-to-end check

```bash
uv run pytest && docker compose up -d --build && curl -fsS localhost:8000/healthz
# after the infra PR (stack + Caddy route + DNS) and deploy:
curl -fsS https://today.diegoponte.dev/healthz
```

On the iPhone: open the URL in Safari → log in → Share → Add to Home Screen → opens full screen with the icon,
stays logged in after closing, an item added there shows up in the desktop browser.

## Risks and open questions

- The infra side is a separate PR in `infra` (stack, Caddy route, DNS record, secrets); deploy follows the
  flamengo-news pattern (GHCR image, pull on the VPS).
