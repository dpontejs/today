# 01 · Foundation: one process, one file, one screen

This guide walks through slice 1: the project skeleton, the database, login, the Today screen, the PWA shell
and the deploy. Each section has the concept, why it was done this way, the commands, exercises and pitfalls,
and a **Read next** pointer into the two architecture books.

## 1. Settings and the database

### Concepts

- **Twelve-factor config.** Everything that changes between environments (database path, secrets) comes from
  environment variables, read once at startup into a frozen `Settings` object (`src/today/config.py`). Code
  never calls `os.environ` anywhere else, so tests build a `Settings` by hand.
- **SQLite in WAL mode.** Write-Ahead Logging lets readers keep reading while one writer writes. With one
  process and one user that is all the concurrency we need ([ADR 0002](../adr/0002-sqlite-on-a-volume.md)).
- **Versioned migrations.** Schema changes are numbered SQL files in `src/today/migrations/`. `migrate()`
  applies the ones not yet recorded in `schema_version`, each inside a transaction, so a broken file leaves
  the database as it was.
- **Time as data.** Every timestamp is stored as a UTC ISO-8601 string. ISO strings in the same offset sort
  the same way as the instants they represent, so `WHERE due_at < ?` works on plain text.

### Why

- No ORM: about ten queries, all visible in one module. The cost of an ORM (configuration, a second query
  language, lazy-loading surprises) buys nothing here.
- Migrations as plain SQL instead of a tool such as Alembic: one file per change is easy to read in review and
  to run by hand with the `sqlite3` CLI.

### Commands

```bash
uv sync                      # create .venv from uv.lock
uv run pytest tests/test_db.py
sqlite3 data/today.db '.schema items'
sqlite3 data/today.db 'SELECT * FROM schema_version'
```

### Exercises

1. Add `002_example.sql` with a broken statement and run `migrate()`. Check that `schema_version` did not
   change and that `001` is still applied. Delete the file afterwards.
2. Insert two items with `due_at` in different offsets (`-03:00` and `+00:00`) and sort them with
   `ORDER BY due_at`. Why does the order come out wrong, and why does storing everything in UTC prevent it?

### Pitfalls

- `sqlite3` in Python opens implicit transactions by default; `isolation_level=None` turns that off so
  `BEGIN`/`COMMIT` in `migrate()` mean exactly what they say.
- Splitting a migration on `;` breaks on triggers or string literals that contain `;`. Fine for now; switch
  to `executescript` inside a savepoint if a migration ever needs them.

### Read next

- *Fundamentals of Software Architecture*: architecture characteristics. Which characteristics this choice
  favours (simplicity, cost, deployability) and which it gives up (scalability, elasticity).
- *Software Architecture: The Hard Parts*: ch. 6 "Pulling Apart Operational Data", the section on choosing
  a database type.

## 2. Items and the Today buckets

### Concepts

- **Pure time.** `build_today(conn, now, tz)` receives `now` instead of reading the clock. Tests pin any
  instant (23:30 local, 22:00 local that is already tomorrow in UTC) without mocking.
- **Local day, UTC storage.** The user's day starts at local midnight in `America/Fortaleza`.
  `local_day_bounds` builds that midnight in the local zone, converts it to UTC, and the SQL compares UTC
  strings. The conversion happens once, at the edge, never inside SQL.
- **Idempotent status changes.** `mark_done` only updates rows still `open`, so pressing "done" twice (a double
  tap, an HTMX retry) keeps the first `done_at`.

### Why

The bucket rules are the product: "what is late" must match what the user sees on the wall clock. Keeping
them in one pure function with exhaustive boundary tests is cheaper than discovering a midnight bug on the
phone at 00:30.

### Commands

```bash
uv run pytest tests/test_items.py -v
uv run python -c "from datetime import datetime, UTC; from zoneinfo import ZoneInfo; \
print(datetime(2026,11,11,1,0,tzinfo=UTC).astimezone(ZoneInfo('America/Fortaleza')))"
```

### Exercises

1. Change `local_day_bounds` to use `now.date()` instead of `now.astimezone(tz).date()`. Which tests fail
   and why?
2. Add a "someday" bucket for items without a date. What would change in the schema (`due_at NOT NULL`) and
   in the migration?

### Pitfalls

- `datetime.combine(date, time.min, tzinfo=tz)` is fine for Fortaleza (no DST). In a zone with DST, local
  midnight can be ambiguous or missing; `zoneinfo` resolves it with `fold`, and tests would need a DST case.
- Comparing ISO strings only works when every value has the same offset. That is why `to_db` always converts
  to UTC.

### Read next

- *Fundamentals of Software Architecture*: modularity. `items` owns its table and exposes functions, not
  SQL; other modules (`notify`, `importers`) will call `create_item`, never `INSERT INTO items`.
- *Software Architecture: The Hard Parts*: ch. 6, data ownership (one owner per table, even inside a
  monolith).

## 3. Login and session

### Concepts

- **Password hashing with Argon2.** The passphrase never lives in the repo or the environment; only its
  Argon2 hash does (`PASSPHRASE_HASH`). Argon2 is deliberately slow and memory-hungry, so a leaked hash is
  expensive to brute-force.
- **Signed cookie session.** After login the server sets `today_session = sign("owner")` with
  `itsdangerous.TimestampSigner`. No session table: the signature proves the server issued it, the timestamp
  enforces 90 days. Changing `SESSION_SECRET` logs every device out.
- **Cookie flags.** `HttpOnly` (JavaScript cannot read it), `Secure` (HTTPS only), `SameSite=Lax` (not sent
  on cross-site POSTs, which blocks basic CSRF on our forms).
- **HTMX and redirects.** HTMX follows a 303 silently and would swap the login page into a list row. For
  HTMX requests the server answers `200` + `HX-Redirect: /login`, and HTMX reloads the whole page.

### Why

One user does not justify OAuth or a users table ([ADR 0004](../adr/0004-single-user-passphrase-auth.md)).
Basic auth in Caddy would have been zero code, but installed iOS PWAs handle its prompt badly.

### Commands

```bash
# create the hash for the VPS secret (prompts, never echoes)
uv run python -c "import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass.getpass()))"
# a random session secret
openssl rand -hex 32
# local dev over http
COOKIE_SECURE=false PASSPHRASE_HASH='...' SESSION_SECRET=dev uv run uvicorn --factory today.app:from_env --reload
```

### Exercises

1. Log in, copy the cookie value from the browser devtools, change one character and reload. What happens and
   which line of `auth.py` decides it?
2. The rate limiter lives in memory. What happens to it on a restart, and with two app instances? Which ADR
   makes that acceptable?

### Pitfalls

- Behind Caddy every request comes from Caddy's IP, so the rate limiter would block everyone at once. Uvicorn
  must run with `--proxy-headers --forwarded-allow-ips` set to the proxy network (done in the Dockerfile).
- `TestClient` talks plain HTTP by default and httpx refuses to send `Secure` cookies over it: the tests use
  `base_url="https://testserver"`.

### Read next

- *Fundamentals of Software Architecture*: architecture characteristics: security as an explicit
  characteristic and the trade-off against simplicity; architecture decision records.

## 4. The Today page: server-rendered HTML with HTMX

### Concepts

- **Server-side rendering.** The server builds the whole page with Jinja templates; the browser gets HTML,
  not JSON. One language (Python) owns the bucket rules and the markup.
- **HTMX for the small dynamic bits.** Finishing an item is `hx-post="/items/7/done"` on a button; the
  server answers with the new `<li>` and HTMX swaps it in place (`hx-swap="outerHTML"`). No client-side
  state, no build step, about 50 KB of JavaScript vendored as a file.
- **Forms and local time.** `<input type="datetime-local">` sends `2026-11-11T09:00` with no zone. The server
  attaches `America/Fortaleza` before converting to UTC (`parse_local_datetime`). Attaching UTC instead would
  shift every item by three hours.
- **Autoescaping.** Jinja escapes `{{ item.title }}`, so a title like `<script>` is shown, not executed.

### Why

The UI is one screen with a list and a form. A SPA (React, a JSON API, a bundler) would double the code
and the moving parts for no visible gain. HTMX keeps the architecture a single deployable unit
([ADR 0001](../adr/0001-modular-monolith-with-in-process-scheduler.md)).

### Commands

```bash
uv run pytest tests/test_pages.py -v
COOKIE_SECURE=false PASSPHRASE_HASH="$(uv run python -c "from argon2 import PasswordHasher; print(PasswordHasher().hash('dev'))")" \
  SESSION_SECRET=dev uv run uvicorn --factory today.app:from_env --reload
# open http://127.0.0.1:8000 with the browser's device toolbar at 390 px wide
```

### Exercises

1. Open the network tab, finish an item, and look at the response body. What is the smallest change to make
   the item move to the "done" group at the bottom instead of being styled in place? (Hint: `hx-target`
   and `hx-select`.)
2. Submit the form with an empty title. Why is the status 422 and not 400, and why does the page re-render
   instead of redirecting?

### Pitfalls

- Inputs below 16px make iOS Safari zoom into the field on focus. All inputs use 16px.
- `datetime-local` renders with the device locale (24 h in pt-BR, AM/PM in en-US); the value sent is always
  ISO, so the server does not care.

### Read next

- *Fundamentals of Software Architecture*: the layered architecture style (presentation → domain →
  persistence) and why a small modular monolith can still keep those layers inside each module.

## 5. The PWA shell: manifest, service worker, icons, fonts

### Concepts

- **Web app manifest** (`/manifest.webmanifest`): name, icons, colors and `display: standalone`. It is what
  turns "a website" into "an app" when added to the home screen: own icon, no browser bars.
- **Service worker** (`/sw.js`): a script the browser keeps running in the background for this origin. In
  slice 1 it does nothing but exist (installability). In slice 2 it receives push messages even when the app
  is closed. It is served from `/`, not `/static/`, because a worker only controls URLs under its own path.
- **iOS specifics.** Safari ignores most of the manifest for the home-screen icon and reads
  `<link rel="apple-touch-icon">` (180 px) and the `apple-mobile-web-app-*` meta tags instead.
- **Maskable icons.** Android crops icons into circles or squircles. A maskable icon is full-bleed with the
  important part inside the central 80 %, so nothing gets cut.

### Why

- Self-hosted fonts: no request to Google at runtime (privacy, and the app works on a flaky connection once
  cached), and the exact files are versioned with the code.
- One SVG as the source of every icon size: change the drawing, re-run the command below, commit the PNGs.

### Commands

```bash
cd src/today/static/icons
for s in 180 192 512; do rsvg-convert -w $s -h $s icon.svg -o icon-$s.png; done
cp icon-512.png icon-maskable-512.png
# Chrome DevTools → Application → Manifest shows parse errors and installability
```

### Exercises

1. Move `sw.js` to `/static/sw.js` and register it from there. What does DevTools say about its scope, and
   why would push still work but page control not?
2. Open <https://maskable.app> and load `icon-maskable-512.png`. Does the tile survive the circle mask?

### Pitfalls

- A service worker is cached aggressively. `Cache-Control: no-cache` on `/sw.js` makes the browser
  revalidate it, so a new version reaches the phone on the next launch.
- iOS only allows push for apps added to the home screen, and the "Add to Home Screen" prompt is never shown
  automatically: the user does it from the Share sheet.

### Read next

- *Fundamentals of Software Architecture*: architecture characteristics: deployability and the "-ilities"
  of the client (installability, availability on the phone) that shaped the choice of a PWA over a native
  app.

## 6. The container image

### Concepts

- **Multi-stage build.** The `build` stage has `uv` and resolves dependencies from `uv.lock`; the runtime
  stage only copies the finished `.venv`. The final image has no compiler, no uv, no test code.
- **Layer caching.** `pyproject.toml` and `uv.lock` are copied before the code, so changing a template does
  not reinstall FastAPI.
- **Least privilege.** Non-root user (uid 10001), `read_only` root filesystem, `/tmp` as tmpfs, no Linux
  capabilities, `no-new-privileges`. The only writable place is the `/data` volume with the SQLite file.
- **Healthcheck.** Docker marks the container `healthy` only when `/healthz` answers; the VPS deploy agent
  waits for that and rolls back otherwise.
- **Immutable and moving tags.** CI pushes `:sha-<commit>` (never changes, rollback target) and `:main` (moves,
  what the VPS follows).

### Commands

```bash
cp .env.example .env            # fill PASSPHRASE_HASH (single-quoted) and SESSION_SECRET
docker compose up -d --build
curl -fsS 127.0.0.1:8000/healthz
docker compose exec today id    # uid=10001(app)
docker compose down             # the today_data volume (and the items) survive
```

### Exercises

1. Remove `read_only: true`, run `docker compose exec today touch /app/x`, then put it back and try again.
   What class of attack does a read-only root filesystem make harder?
2. Change one line in `today.html` and rebuild. Which build steps are `CACHED`, and why?

### Pitfalls

- Argon2 hashes contain `$`. Compose interpolates `$` in `.env` unless the value is single-quoted.
- `--forwarded-allow-ips "*"` trusts `X-Forwarded-For` from anyone who can reach port 8000. That is safe
  only because the port is not published on the VPS: Caddy is the only client.

### Read next

- *Fundamentals of Software Architecture*: deployability and the operational characteristics; the
  "architecture quantum" idea: this image is the whole quantum, deployed as one unit.
