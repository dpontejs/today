# Job collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collect ML/AI roles from 9 sources three times a day into SQLite, filtered and deduplicated,
readable and triaged through MCP.

**Architecture:** New package `today/jobs/` (adapters in `sources/`, pure `filter.py`, `repo.py`, `collect.py`,
`loop.py`). Adapters are plain functions `Fetch = Callable[[httpx.Client], list[JobPosting]]` tested against
recorded responses. A second asyncio task in the FastAPI lifespan runs the slots, as ADR 0001 does for reminders.

**Tech Stack:** Python 3.12, FastAPI, SQLite, httpx (new), pytest, MCP SDK.

**Spec:** `docs/features/07-job-collection.md` (contracts, terms, migration, acceptance tests). Endpoints:
`docs/research/fontes-de-vagas.md`.

## Global Constraints

- Tests never hit the network: adapters get an `httpx.Client(transport=httpx.MockTransport(...))` serving
  files from `tests/fixtures/jobs/`. Record each fixture once with curl and trim to 2–3 postings, one of them
  non-ML (to exercise the filter later).
- Greenhouse tokens: `ifoodcarreiras, inter, c6bank, xpinc, btgpactual, quintoandar, stone, vtex,
  wildlifestudios, hotmartcareersbr`. Gupy terms: `machine learning, cientista de dados, visão computacional,
  MLOps, inteligência artificial, deep learning`, `workplaceType` not sent (filter decides).
- LinkedIn: guest endpoint only, `f_TPR=r86400`, ≤ 3 pages/term, `sleep(uniform(3, 7))` injectable, stop the
  source on 429/999. Never cookies, never login.
- All datetimes stored as UTC ISO strings; slots computed in `settings.tz`.
- `User-Agent: today-personal/1.0` on every request except LinkedIn (browser UA, as JobSpy does).

## Review Focus

- A source returns 200 with an HTML error page or a changed shape → adapter raises, report shows the error,
  others still save → `test_failing_source_reported_others_saved` uses a shape-changed fixture (Task 3).
- Same role at two sources (e.g. Greenhouse and LinkedIn) → kept twice by design (different `source`); assert
  it in Task 3 so nobody "fixes" it silently.
- HTML descriptions with entities/scripts → `description` is plain text: assert no `<` in Greenhouse output (Task 1).
- Server restart at 13:05 → the 13:00 slot runs once on boot, never twice → Task 4.
- Title "Sales Engineer – AI products" → dropped (role term must be the role, see filter list) → Task 2.

---

### Task 1: `JobPosting` and the 9 adapters

**Files:** Create `src/today/jobs/{__init__,models}.py`, `src/today/jobs/sources/{__init__,greenhouse,gupy,ashby,
lever,eightfold,oracle,himalayas,remotar,linkedin}.py`, `tests/fixtures/jobs/*`, `tests/jobs/test_sources.py`.
Modify `pyproject.toml` (`httpx`).

**Interfaces:**
- Produces: `JobPosting` (fields exactly as in the spec), `Fetch`, `SOURCES: dict[str, Fetch]` in
  `sources/__init__.py` keyed by the spec's `source` strings (one entry per Greenhouse token), and
  `html_to_text(html: str) -> str` in `models.py`.

- [ ] **Step 1:** One test per adapter, `test_<source>_parses_recorded_response`: asserts count, the first
  posting's `external_id`, `company`, `title`, `url`, `workplace` (`None` for Greenhouse/LinkedIn/Himalayas
  unless the field exists), and `"<" not in description`.
- [ ] **Step 2:** `uv run pytest tests/jobs/test_sources.py -v` → FAIL.
- [ ] **Step 3:** Implement adapters one by one with the endpoints from the research file. Gupy portal paging
  via `offset`; Eightfold detail via `position_details`; LinkedIn detail page fetched by `collect` only for
  filtered jobs, so the adapter exposes `fetch_linkedin_description(client, external_id) -> str | None`.
- [ ] **Step 4:** tests pass; `ruff check`, `ruff format --check`.
- [ ] **Step 5:** Commit `feat: adaptadores das fontes de vagas`.

### Task 2: Filter

**Files:** Create `src/today/jobs/filter.py`, `tests/jobs/test_filter.py`.

**Interfaces:** Produces `passes_filter(job: JobPosting) -> bool`.

- [ ] **Step 1:** Tests: `test_filter_keeps_ml_roles_and_drops_sales` (parametrized: "Senior ML Engineer",
  "Cientista de Dados Pleno", "Engenheiro de Visão Computacional", "MLOps Engineer" kept; "Account Executive",
  "Sales Engineer – AI products", "Product Designer" dropped); `test_filter_drops_onsite_outside_sp`
  (onsite Rio dropped; onsite "São Paulo, SP" and "Natal" kept; remote anywhere kept; workplace None +
  "Brazil" kept); `test_intern_kept_only_with_role_term` ("Estágio em Ciência de Dados" kept, "Estágio
  Comercial" dropped).
- [ ] **Step 2–4:** red → implement with word-boundary regexes over the spec's terms; a leading
  `sales|account|commercial|comercial|vendas` in the title drops → green.
- [ ] **Step 5:** Commit `feat: filtro de vagas por cargo e local`.

### Task 3: Migration, repo and `collect`

**Files:** Create `src/today/migrations/005_jobs.sql`, `src/today/jobs/{repo,collect}.py`,
`tests/jobs/test_collect.py`.

**Interfaces:**
- Produces: `JOB_STATUSES = ("new","analyzed","dismissed","interested","applied")`;
  `upsert_jobs(conn, jobs: list[JobPosting], now) -> int` (new count); `list_jobs(conn, status: str | None,
  limit: int) -> list[JobRow]`; `set_status(conn, job_id: int, status: str, now) -> JobRow` (ValueError on
  unknown status or id); `collect(conn, client, sources: dict[str, Fetch], now) -> CollectReport`
  (`dict[str, SourceReport(fetched, kept, new, error: str | None)]`).

- [ ] **Step 1:** Tests from the spec: `test_collect_inserts_new_and_dedupes_by_source_and_id`,
  `test_collect_keeps_user_status_on_resight`, `test_failing_source_reported_others_saved`,
  `test_same_role_two_sources_kept_twice`.
- [ ] **Step 2–4:** red → implement (`INSERT ... ON CONFLICT(source, external_id) DO NOTHING`) → green.
- [ ] **Step 5:** Commit `feat: tabela de vagas e coleta com deduplicação`.

### Task 4: Slots loop, CLI and settings

**Files:** Create `src/today/jobs/loop.py`, `src/today/jobs/__main__.py`, `tests/jobs/test_loop.py`. Modify
`src/today/config.py` (`jobs_enabled: bool`, `jobs_sources: frozenset[str] | None` from `JOBS_ENABLED`,
`JOBS_SOURCES`), `src/today/app.py` lifespan (start `run_jobs_loop` when enabled, cancel like the reminder loop).

**Interfaces:** Produces `due_slot(conn, now, tz) -> str | None` (`"2026-11-23T13"` style key, the latest slot
≤ now not yet in `job_runs`, only today's), `run_jobs_loop(app)` (every 60 s: `due_slot` → `collect` in a
thread → insert `job_runs`).

- [ ] **Step 1:** `test_loop_runs_each_slot_once_and_catches_up_after_restart`: at 13:05 with 07 done →
  `"…T13"`; after recording it → `None`; at 06:59 → `None`; at 20:00 with nothing recorded → only `"…T19"`.
- [ ] **Step 2–4:** red → implement → green. CLI: `python -m today.jobs collect [--dry-run]` runs all sources
  with a real client and prints the report as a table; `--dry-run` uses an in-memory DB.
- [ ] **Step 5:** Commit `feat: coleta de vagas às 7h, 13h e 19h`.

### Task 5: MCP tools and docs

**Files:** Modify `src/today/mcp_server.py`, `tests/test_mcp.py`, `README.md`, `docs/features/07-job-collection.md`
(status), create `docs/guide/08-job-collection.md`.

- [ ] **Step 1:** Tests: `test_mcp_list_jobs_filters_by_status`, `test_mcp_update_job_status_rejects_unknown_status`,
  `test_mcp_jobs_require_bearer_token`.
- [ ] **Step 2–4:** red → add `list_jobs(status="new", limit=30)` and `update_job_status(id, status)` through
  `guarded`; extend server `instructions` with one sentence about jobs → green.
- [ ] **Step 5:** End-to-end: `uv run python -m today.jobs collect --dry-run` → at least 6 sources with
  `kept > 0` and no error except possibly LinkedIn; paste the table in the PR.
- [ ] **Step 6:** Guide (concepts: adapters/ports, recorded fixtures, idempotent upsert, scheduling slots;
  Read next) and README slice line. Commit `feat: ferramentas MCP de vagas e guia`.
