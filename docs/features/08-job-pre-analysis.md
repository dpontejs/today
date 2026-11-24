# 08 · Job pre-analysis: every new role is scored against my profile

- **Date:** 2026-11-23
- **Status:** implemented
- **ADRs:** [0007](../adr/0007-claude-code-for-analysis-and-writing.md) (Claude Code behind `Analyst`)
- **Depends on:** [07](07-job-collection.md)

## Goal

Each collected role that passed the filter gets a structured analysis — requirements I meet, gaps (required vs
nice-to-have), workplace, company, seniority, a 0–100 fit score and a one-line verdict — so I only read the
ones worth applying to. The 08:00 summary mentions new roles; a strong match pushes right away.

## Out of scope

Jobs screen, résumé tailoring, cover letters, interview prep, study topics from gaps (all later features).

## Contracts

```python
class Analyst(Protocol):                        # today/llm/analyst.py — ClaudeCliAnalyst, AnthropicApiAnalyst
    def complete[T: BaseModel](self, *, model: str, system: str, prompt: str, schema: type[T]) -> T: ...

class Gap(BaseModel):
    skill: str
    kind: Literal["required", "nice_to_have"]
    note: str | None

class JobAnalysis(BaseModel):
    meets: list[str]
    gaps: list[Gap]
    workplace: Literal["remote", "hybrid", "onsite", "unknown"]
    location: str | None
    company_summary: str            # area, size, maturity in one or two sentences
    seniority: Literal["intern", "junior", "mid", "senior", "staff_plus", "unknown"]
    target_company: bool            # company is in the profile's target list
    score: int = Field(ge=0, le=100)
    verdict: str                    # one sentence, pt-BR

def analyze_pending(conn, analyst, model, now, limit=20) -> AnalyzeReport     # profile read from the DB
```

- Migration `006_job_analysis.sql`: `job_analyses(job_id PK FK jobs, analysis_json, score, model,
  prompt_version, analyzed_at)`; `profile(id=1, body_md, updated_at)`.
- Runs right after each collection slot, at most `limit` jobs per slot, newest first (a role seen today never waits behind the backlog); the rest wait.
- An analyst error (login, limit, timeout, invalid JSON) leaves the job `new` for the next slot; three
  failures on the same job → `analyzed` with no row and logged, so one bad posting never blocks the queue.
- Push: score ≥ `JOBS_PUSH_SCORE` (default 75) → `★ <score> · <company> · <title>`, at most one push per slot
  (several → `N vagas fortes`). Daily summary appends `N vagas novas, melhor: <company> · <score>`.
- Profile: markdown seeded once from the CV, `~/portfolio/src/data/profile.ts` and project READMEs; holds
  preferences (seniority incl. internships, target companies, remote now / SP later).
- MCP: `get_profile`, `set_profile(body_md)`, `list_jobs` gains `min_score` and returns the analysis.
- Env: `ANALYST`, `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY`, `ANALYST_MODEL` (default Sonnet alias).

## Acceptance criteria (as tests)

- [x] `test_analyze_pending_stores_analysis_and_marks_analyzed` (fake analyst).
- [x] `test_analyze_respects_limit_and_newest_first`.
- [x] `test_analyst_error_keeps_job_new`; `test_three_failures_stop_retrying`.
- [x] `test_user_status_not_overwritten_by_analysis`.
- [x] `test_strong_match_pushes_once_per_slot`; `test_several_strong_matches_grouped`.
- [x] `test_daily_summary_mentions_new_jobs`.
- [x] `test_claude_cli_builds_args_and_env_without_app_secrets` (fake command).
- [x] `test_claude_cli_missing_structured_output_is_error`.
- [x] `test_mcp_set_and_get_profile`; `test_mcp_list_jobs_min_score`.

## End-to-end check

```bash
uv run pytest && uv run python -m today.jobs analyze --one   # real claude -p on one stored job, prints JSON
```

Deployed: after a slot, `list_jobs(min_score=70)` through Claude returns scored roles; one push arrives when a
role scores ≥ 75. Watch `/usage` during the first week.

## Risks and open questions

- Score calibration: review 20 real analyses in the first week and adjust the prompt (prompt_version bumps).
