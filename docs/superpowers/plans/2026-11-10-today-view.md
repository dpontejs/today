# Slice 1 — Items, Today view, login, deploy · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An installable, passphrase-protected PWA at `today.diegoponte.dev` showing late / today / next items, with add, done and reopen.

**Architecture:** One FastAPI process (ADR 0001), plain `sqlite3` with SQL migrations (ADR 0002), server-rendered Jinja + HTMX, signed session cookie (ADR 0004). Packaged as one image on GHCR, run as a Compose stack behind Caddy on the VPS, same pattern as `flamengo-news`.

**Tech Stack:** Python 3.12, uv, FastAPI, uvicorn, Jinja2, python-multipart, argon2-cffi, itsdangerous; pytest + httpx; ruff. HTMX 2.0.x vendored as a static file.

**Spec:** `docs/features/01-today-view.md`, `docs/design.md`, `docs/adr/0001…0004`.

## Global Constraints

- Datetimes always timezone-aware; stored as UTC ISO-8601 (`2026-11-10T12:00:00+00:00`); shown in `America/Fortaleza`.
- Every time-dependent function takes `now: datetime` as a parameter; only route handlers call `datetime.now(UTC)`.
- No dependencies beyond the Tech Stack list. No ORM. No TODO / `pass` / `skip`.
- Code, UI copy and docs in English. Commits in pt-BR, conventional, no scope (`feat: …`).
- Colors, fonts and layout only from `docs/design.md` tokens (CSS custom properties). Dark only.
- Each task adds its part of `docs/guide/01-foundation.md` (concepts, why, commands, exercises, pitfalls, **Read next**).

## Review Focus

1. Item due 00:00–02:59 local time: UTC date differs from local date → must bucket by local day (Task 2 `test_bucket_boundary_uses_local_midnight` + `test_late_night_utc_next_day`).
2. Form posts naive local `datetime-local` value (`2026-11-11T09:00`) → server attaches Fortaleza tz, never UTC (Task 4 `test_due_at_stored_as_utc`).
3. Session cookie over plain HTTP in local dev → `COOKIE_SECURE=false` only via env; default true (Task 3 `test_session_cookie_flags`).
4. HTMX request with expired session → must get `HX-Redirect: /login`, not a login page swapped into a row (Task 3 `test_htmx_request_without_session_redirects`).
5. Title with HTML (`<script>`) → rendered escaped (Task 4 `test_title_is_escaped`).

---

### Task 1: Project skeleton, config, database and migrations

**Files:** Create `pyproject.toml`, `.gitignore`, `src/today/__init__.py`, `src/today/config.py`, `src/today/db.py`, `src/today/migrations/001_items.sql`, `tests/conftest.py`, `tests/test_db.py`, `.github/workflows/ci.yml`, `docs/guide/01-foundation.md`.

**Interfaces — Produces:**
- `Settings` (frozen dataclass): `db_path: Path`, `passphrase_hash: str`, `session_secret: str`, `tz: ZoneInfo` (`America/Fortaleza`), `cookie_secure: bool = True`; `load_settings() -> Settings` from env `DB_PATH`, `PASSPHRASE_HASH`, `SESSION_SECRET`, `COOKIE_SECURE`. Missing secret → `RuntimeError` naming the variable.
- `connect(path: Path) -> sqlite3.Connection` (WAL, `foreign_keys=ON`, `row_factory=sqlite3.Row`).
- `migrate(conn) -> list[str]` applies `migrations/NNN_*.sql` in order inside a transaction each, records them in `schema_version(name TEXT PRIMARY KEY, applied_at TEXT)`, returns names applied this call.
- Fixture `conn` (temp-file DB, migrated), fixture `settings`.

- [ ] Write `test_migrations_apply_once` (call `migrate` twice → second returns `[]`, `schema_version` has one row per file) and `test_items_status_check` (insert `status='x'` → `sqlite3.IntegrityError`); `test_load_settings_requires_secret`.
- [ ] Run `uv run pytest tests/test_db.py -v` → FAIL (module missing).
- [ ] Implement config, db and `001_items.sql` exactly as in the spec's Database line, plus index on `(status, due_at)`.
- [ ] Run → PASS. Add CI job: `uv sync --frozen`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`.
- [ ] Commit `feat: esqueleto do projeto, config e migrações SQLite`.

### Task 2: Items repository and Today buckets

**Files:** Create `src/today/items/__init__.py`, `src/today/items/repo.py`, `src/today/items/today.py`, `tests/test_items.py`.

**Interfaces — Consumes:** `connect`, `migrate`. **Produces:**
- `ItemIn` (spec's Pydantic model), `Item` (frozen dataclass: `id, title, notes, due_at, remind_at, status, done_at, source, source_key, created_at`, datetimes aware UTC).
- `create_item(conn, data: ItemIn, now: datetime) -> Item` · `get_item(conn, id: int) -> Item | None`
- `mark_done(conn, id: int, now: datetime) -> Item | None` (already done → unchanged) · `reopen(conn, id: int) -> Item | None`
- `TodayView` (frozen dataclass: `late, today, next, done_today: list[Item]`, `next_item_id: int | None` = first of `today`).
- `build_today(conn, now: datetime, tz: ZoneInfo) -> TodayView`; buckets per the spec; each list ordered by `due_at`.

- [ ] Write the spec tests `test_buckets_split_late_today_next`, `test_bucket_boundary_uses_local_midnight`, `test_done_then_reopen_round_trip`, `test_done_is_idempotent`, plus `test_late_night_utc_next_day` (`now` 22:00 Fortaleza = 01:00 UTC next day; item due 23:30 local → today) and `test_done_today_listed_separately`. Use a fixed `now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)`.
- [ ] Run → FAIL. Implement: local-day bounds computed in `tz`, converted to UTC, then one SQL query per bucket on ISO strings.
- [ ] Run → PASS. Commit `feat: repositório de itens e buckets do dia`.

### Task 3: Passphrase login and session

**Files:** Create `src/today/auth.py`, `src/today/app.py`, `src/today/templates/base.html`, `src/today/templates/login.html`, `tests/test_auth.py`.

**Interfaces — Consumes:** `Settings`. **Produces:**
- `create_app(settings: Settings) -> FastAPI` (lifespan: `connect` + `migrate`; stores conn and settings on `app.state`).
- `require_session` dependency: no/invalid cookie → 303 to `/login`; if header `HX-Request` → 200 with `HX-Redirect: /login`.
- Cookie `today_session`, `itsdangerous.TimestampSigner(session_secret)`, max age 90 days, `HttpOnly`, `SameSite=Lax`, `Secure=settings.cookie_secure`.
- `LoginLimiter`: in-memory, 5 failures per IP per 10 min → 429; takes `now` for tests.
- Public: `/login`, `/healthz` → `{"status":"ok"}`.

- [ ] Write `test_login_success_sets_cookie`, `test_login_wrong_passphrase_401`, `test_login_rate_limited_after_5_failures`, `test_session_cookie_flags`, `test_routes_require_session` (GET `/`, POST `/items` → 303 `/login`), `test_htmx_request_without_session_redirects`, `test_logout_clears_cookie`, `test_tampered_cookie_rejected`. Test passphrase hashed with `argon2.PasswordHasher` in the fixture.
- [ ] Run → FAIL. Implement. Login page uses design tokens (centered, mono input, accent button).
- [ ] Run → PASS. Commit `feat: login por senha com cookie de sessão`.

### Task 4: Today page and item routes

**Files:** Create `src/today/items/routes.py`, `src/today/templates/today.html`, `src/today/templates/_row.html`, `src/today/static/app.css`, `src/today/static/htmx.min.js`; modify `src/today/app.py`; test `tests/test_pages.py`.

**Interfaces — Consumes:** `build_today`, `create_item`, `mark_done`, `reopen`, `require_session`.
- `GET /` renders `today.html` (sections LATE / TODAY / NEXT 7 DAYS / done, counts right-aligned, row grid `62px | 1fr | auto`, pills `NEXT` / `ON TIME` / `LATE` / struck-through done, per `docs/design.md`). Add form: title, `datetime-local` due, optional notes.
- `POST /items` → 303 `/`; invalid → 422 re-rendering the page with field errors. Naive form datetime gets `settings.tz`.
- `POST /items/{id}/done|reopen` → `_row.html` fragment (`hx-swap="outerHTML"`); missing → 404.

- [ ] Write `test_today_page_shows_sections`, `test_due_at_stored_as_utc`, `test_create_rejects_empty_title`, `test_unknown_item_returns_404`, `test_done_returns_row_fragment`, `test_title_is_escaped`, `test_next_pill_on_first_today_item`.
- [ ] Run → FAIL. Implement routes, templates, CSS (tokens as custom properties on `:root`; no colors outside them).
- [ ] Run → PASS. Check by hand at 390px wide in a browser with `uv run uvicorn today.app:app --reload` (`COOKIE_SECURE=false`). Commit `feat: tela Hoje e rotas de itens`.

### Task 5: PWA shell — manifest, service worker, icons, fonts

**Files:** Create `src/today/static/manifest.webmanifest`, `src/today/static/sw.js`, `src/today/static/icons/icon.svg`, `icon-180.png`, `icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `src/today/static/fonts/*.woff2` + `OFL.txt`; modify `base.html`, `app.py`; test `tests/test_pwa.py`.

- Manifest: `name` "today", `display` "standalone", `start_url` "/", `background_color` and `theme_color` `#0E0F11`, the icons above. `sw.js` served at `/sw.js` (scope `/`), install + activate + network-only fetch (offline is out of scope). `base.html`: `apple-touch-icon` (180), `apple-mobile-web-app-capable`, `theme-color`, SW registration.
- Icon: split-flap tile per `docs/design.md`, drawn in `icon.svg`; PNGs rendered once with `rsvg-convert` (or Inkscape) and committed. Fonts: Barlow Condensed 700, JetBrains Mono 400/600/700 woff2, `@font-face` in `app.css`.

- [ ] Write `test_manifest_public_and_valid` (200 without cookie, JSON with the fields above), `test_sw_served_at_root_scope` (200, `application/javascript`, `Service-Worker-Allowed: /`), `test_icons_exist`.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat: shell PWA com manifest, service worker, ícones e fontes`.

### Task 6: Container image and CI publish

**Files:** Create `Dockerfile`, `compose.yml` (local), `.dockerignore`; modify `.github/workflows/ci.yml`.

- Multi-stage on `python:3.12-slim` with uv; non-root user; `CMD uvicorn today.app:app --host 0.0.0.0 --port 8000`; `HEALTHCHECK` on `/healthz`; data in `/data` (`DB_PATH=/data/today.db`). Must run with `read_only: true` + tmpfs `/tmp`, `cap_drop: ALL`, like `infra/stacks/flamengo-news`.
- CI `image` job on `main`: build and push `ghcr.io/dpontejs/today:main` and `:sha-<short>` (copy flamengo-news' job: `permissions: packages: write`).

- [ ] Run `docker compose up -d --build && curl -fsS localhost:8000/healthz` → `{"status":"ok"}`; log in through the browser; `docker compose down`.
- [ ] Commit `chore: imagem Docker e publicação no GHCR`.

### Task 7: Infra stack (separate PR in `~/infra`)

**Files (in `~/infra`):** create `stacks/today/compose.yml` (copy flamengo-news: image `ghcr.io/dpontejs/today:main`, volume `today_data:/data`, hardening, network `web`); add `today.{$DOMAIN}` block to `stacks/caddy/conf/Caddyfile` (`import security_headers`, `reverse_proxy today:8000`); add `today` to `var.subdomains` in Terraform; Ansible `today.env.j2` (`PASSPHRASE_HASH`, `SESSION_SECRET`), task + handler, `today` in `stacks_enabled`; secrets in `~/.config/infra/secrets.env`.

- [ ] `make plan` shows only the two DNS records; `make stacks-test` passes; open PR; after merge `make apply` + Ansible run.
- [ ] Verify `curl -fsS https://today.diegoponte.dev/healthz`; on the iPhone: log in → Add to Home Screen → standalone, stays logged in after closing, item added on the phone appears on the desktop.
- [ ] Mark `docs/features/01-today-view.md` Status: delivered (PR #). Finish `docs/guide/01-foundation.md` with the deploy section.
