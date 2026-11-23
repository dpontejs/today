# Job pre-analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each collection slot, score up to 20 new roles against the owner's profile with Claude, store
the structured analysis, push strong matches and mention new roles in the 08:00 summary.

**Architecture:** `today/llm/analyst.py` holds the `Analyst` protocol and its two implementations (ADR 0007).
`today/jobs/analyze.py` turns a `JobRow` + profile into a prompt, calls the analyst, stores `JobAnalysis`.
`run_slot` (feature 07) gains an analysis step after `collect`. Profile is one markdown row, set through MCP.

**Tech Stack:** Python 3.12, SQLite, Pydantic, Claude Code CLI 2.1.x (`claude -p`), `anthropic` SDK (new), Node 22 in the image.

**Spec:** `docs/features/08-job-pre-analysis.md`; decision `docs/adr/0007-claude-code-for-analysis-and-writing.md`.

## Global Constraints

- The repo is **public**: the owner's profile is never committed (no fixture with real CV text; tests use a
  fake profile). It lives only in the DB and is loaded with `set_profile`.
- `claude -p` runs in a fresh `tempfile.TemporaryDirectory(prefix="today-claude-")`, env limited to
  `HOME, PATH, LANG` + `CLAUDE_CODE_OAUTH_TOKEN`; flags exactly: `-p --output-format json --model <m>
  --json-schema <schema> --system-prompt <s> --tools "" --no-session-persistence`. Never `--bare` (it ignores
  the OAuth token). Timeout 300 s. Prompt goes through stdin.
- Env: `ANALYST=claude_cli|anthropic_api` (unset → analysis off), `ANALYST_MODEL` default `sonnet`,
  `JOBS_PUSH_SCORE` default 75, `ANALYZE_LIMIT` default 20.
- Stored analysis: `JobAnalysis.model_dump_json()`, plus `model` and `PROMPT_VERSION = "1"`.
- Push copy (pt): one → `★ {score} · {company} · {title}`; several → `{n} vagas fortes`, body = lines; `url` `/`.
  Summary appends `{n} vagas novas, melhor: {company} · {score}` (en: `{n} new jobs, best: …`).

## Review Focus

- Description `None` or 40k chars → prompt truncates description to 12 000 chars and says "(truncated)"; no crash → Task 3.
- Job status changed by the user while analysis runs → analysis stored, status untouched → Task 3.
- Profile empty → analysis skipped for the slot and logged once; jobs stay `new` → Task 3.
- `structured_output` missing or `is_error: true` (limit reached) → `AnalystError`, job stays `new` → Task 1.
- No push subscription / push disabled → analysis still runs and stores → Task 4.

---

### Task 1: `Analyst` protocol, Claude CLI and Anthropic API implementations, ADR wiring

**Files:** Create `src/today/llm/{__init__,analyst}.py`, `tests/llm/test_analyst.py`. Modify `pyproject.toml`
(`anthropic`), `src/today/config.py` (`analyst`, `analyst_model`, `jobs_push_score`, `analyze_limit`),
`Dockerfile` (runtime stage: Node 22 from `node:22-slim` copy or NodeSource, `npm i -g @anthropic-ai/claude-code@2.1.331`).

**Interfaces:**
- Produces: `class AnalystError(Exception)`; `class Analyst(Protocol): def complete(self, *, model: str,
  system: str, prompt: str, schema: type[T]) -> T`; `ClaudeCliAnalyst(command=("claude",), timeout_s=300)`;
  `AnthropicApiAnalyst(client)` (tool-use with the schema as the only tool, forced `tool_choice`);
  `make_analyst(settings) -> Analyst | None`.

- [ ] **Step 1:** Tests with a fake command (a tiny Python script in `tests/llm/fake_claude.py` that echoes a
  canned JSON and dumps its argv/env to a file): `test_claude_cli_builds_args_and_env_without_app_secrets`
  (args contain the flags above; env has no `SESSION_SECRET`, `GEMINI_API_KEY`, `DB_PATH`);
  `test_claude_cli_returns_validated_model`; `test_claude_cli_missing_structured_output_is_error`;
  `test_claude_cli_is_error_result_is_error`; `test_claude_cli_timeout_is_error`;
  `test_anthropic_api_parses_tool_input` (fake client object); `test_make_analyst_off_when_unset`.
- [ ] **Step 2–4:** red → implement → green; `ruff check`, `ruff format --check`.
- [ ] **Step 5:** `docker build .` succeeds and `docker run --rm --entrypoint claude <img> --version` prints 2.1.331.
- [ ] **Step 6:** Commit `feat: interface Analyst com Claude Code e API da Anthropic`.

### Task 2: Migration, profile and analysis storage

**Files:** Create `src/today/migrations/006_job_analysis.sql`, `src/today/jobs/analysis_repo.py`,
`tests/jobs/test_analysis_repo.py`.

**Interfaces:** Produces `get_profile(conn) -> str` (`""` when unset), `set_profile(conn, body_md, now)`;
`pending_jobs(conn, limit) -> list[JobRow]` (status `new`, `analysis_attempts < 3`, oldest `first_seen_at`
first); `store_analysis(conn, job_id, analysis: JobAnalysis, model, now)` (insert + status `new → analyzed`
only if still `new`); `record_failure(conn, job_id) -> int` (attempts; at 3 sets status `analyzed`);
`analyses_since(conn, since) -> list[tuple[JobRow, JobAnalysis]]`.

- [ ] **Step 1:** Migration: `job_analyses(job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
  analysis_json TEXT NOT NULL, score INTEGER NOT NULL, model TEXT NOT NULL, prompt_version TEXT NOT NULL,
  analyzed_at TEXT NOT NULL)`, `ALTER TABLE jobs ADD COLUMN analysis_attempts INTEGER NOT NULL DEFAULT 0`,
  `profile(id INTEGER PRIMARY KEY CHECK (id = 1), body_md TEXT NOT NULL, updated_at TEXT NOT NULL)`.
- [ ] **Step 2:** Tests: `test_pending_oldest_first_and_limit`, `test_store_marks_analyzed_only_if_new`,
  `test_three_failures_stop_retrying`, `test_profile_roundtrip_and_empty_default`.
- [ ] **Step 3–4:** red → implement → green. **Step 5:** Commit `feat: perfil e tabela de análises de vagas`.

### Task 3: `JobAnalysis` schema, prompt and `analyze_pending`

**Files:** Create `src/today/jobs/analyze.py`, `tests/jobs/test_analyze.py`.

**Interfaces:** Produces `JobAnalysis`, `Gap` (exactly as in the spec), `PROMPT_VERSION`, `build_prompt(job:
JobRow, profile: str) -> str`, `SYSTEM` (pt-BR: "Você avalia vagas para uma pessoa..."; scoring rubric:
required gaps weigh most, nice-to-have little, seniority one level above is fine, target company +5, onsite
outside SP/Natal −20), `analyze_pending(conn, analyst, model, now, limit) -> AnalyzeReport(analyzed, failed,
skipped_reason: str | None)`.

- [ ] **Step 1:** Tests with a fake analyst: `test_analyze_pending_stores_analysis_and_marks_analyzed`,
  `test_analyze_respects_limit_and_oldest_first`, `test_analyst_error_keeps_job_new`,
  `test_user_status_not_overwritten_by_analysis`, `test_empty_profile_skips_slot`,
  `test_long_description_truncated_in_prompt`, `test_prompt_contains_profile_title_company_location`.
- [ ] **Step 2–4:** red → implement → green. **Step 5:** Commit `feat: pré-análise de vagas contra o perfil`.

### Task 4: Slot wiring, push and summary

**Files:** Modify `src/today/jobs/loop.py` (`run_slot` → after `collect`, `analyze_pending` when an analyst
exists, then `push_strong`), `src/today/notify.py` (`_summary_payload`, `daily_summary` also sends when only
new jobs exist), `src/today/app.py` (`app.state.analyst = make_analyst(settings)`), tests in
`tests/jobs/test_loop.py`, `tests/test_notify.py`.

**Interfaces:** Produces `push_strong(conn, analyzed_ids, threshold, now, send) -> int`.

- [ ] **Step 1:** Tests: `test_strong_match_pushes_once_per_slot`, `test_several_strong_matches_grouped`,
  `test_no_push_sender_still_analyzes`, `test_daily_summary_mentions_new_jobs` (jobs analyzed in the last 24 h,
  best score), `test_summary_sent_when_only_jobs`.
- [ ] **Step 2–4:** red → implement → green. **Step 5:** Commit `feat: push de vagas fortes e vagas no resumo das 8h`.

### Task 5: MCP, CLI, docs

**Files:** Modify `src/today/mcp_server.py`, `src/today/jobs/__main__.py`, `tests/test_mcp.py`, README,
`docs/features/08-job-pre-analysis.md` (status); create `docs/guide/09-job-pre-analysis.md`.

- [ ] **Step 1:** Tests: `test_mcp_set_and_get_profile`, `test_mcp_list_jobs_min_score` (returns `analysis`
  and `score`, sorted by score desc when `min_score` is given).
- [ ] **Step 2–4:** red → implement → green. CLI: `python -m today.jobs analyze --one [--job-id N]` runs the
  configured analyst on one stored job and prints the JSON, writing nothing.
- [ ] **Step 5:** End-to-end, local: copy the prod DB or run a `collect`; `set_profile` with a draft built
  from `~/Diego_Ponte_Resume.pdf`, `~/portfolio/src/data/profile.ts` and the READMEs of credit-risk-mlops and
  assistente-credito (no phone/e-mail; preferences from `docs/features/08`), saved to `data/profile.md`
  (gitignored) for the owner to review; `analyze --one` on 3 real jobs (one strong, one weak, one internship);
  paste the three verdicts and scores in the PR.
- [ ] **Step 6:** Guide (concepts: ports & adapters for LLMs, structured outputs, prompt versioning, retry
  budget, cost/limits; Read next) and README. Commit `feat: perfil e análise pelo MCP e guia`.
