# 09 · Job pre-analysis: every new role scored against my profile

After each collection slot the app asks Claude to read up to 20 new roles against the profile stored in the
database and saves a structured verdict: requirements met, gaps (required vs. nice-to-have), workplace,
seniority, a 0–100 score and one sentence. A role scoring 75 or more pushes right away; the 08:00 summary
says how many roles came in and which one was best. Claude reads them with `list_jobs(min_score=70)`.

## Concepts

- **Ports and adapters for LLMs.** The app never talks to a vendor directly: `today/llm/analyst.py` defines
  one port, `Analyst.complete(model, system, prompt, schema) -> schema instance`, and two adapters.
  `ClaudeCliAnalyst` runs `claude -p` on the owner's subscription; `AnthropicApiAnalyst` calls the API.
  `ANALYST=claude_cli|anthropic_api` picks one at boot (ADR 0007); unset, analysis is off. Tests use a fake
  analyst, and the CLI adapter is tested against a fake `claude` script that records its argv and env.
- **A subprocess is a trust boundary.** `claude -p` runs in a fresh temp dir with an env of only `HOME`,
  `PATH`, `LANG` and `CLAUDE_CODE_OAUTH_TOKEN`, with `--tools ""` (no file or shell tools) and
  `--no-session-persistence`. `SESSION_SECRET`, `API_TOKEN` and `GEMINI_API_KEY` never reach it; a test
  checks that. Never `--bare`: it ignores the OAuth token.
- **Structured outputs.** The Pydantic model `JobAnalysis` *is* the contract: its JSON Schema goes to
  `--json-schema` (or becomes the only, forced tool on the API), and the answer is validated back into the
  model before anything is stored. Free text never reaches the database; a missing `structured_output`,
  `is_error: true` or a schema mismatch becomes `AnalystError`.
- **Prompt versioning.** Each stored analysis carries the model alias and `PROMPT_VERSION`. When the rubric
  changes, bump the version: old and new scores can then be told apart (and re-run) instead of silently
  mixed.
- **Retry budget.** An analyst error leaves the job `new`, so the next slot tries again; `analysis_attempts`
  counts failures and at 3 the job leaves the queue as `analyzed` with no row. One bad posting (or a
  description the model chokes on) can never block the 19 behind it.
- **Never overwrite the human.** `store_analysis` moves `new → analyzed` with `WHERE status = 'new'`: if you
  dismissed the role while Claude was reading it, your status wins and the analysis is still kept.
- **Cost and limits.** At most `ANALYZE_LIMIT` (20) calls per slot, three slots a day: ~60 Sonnet calls on the
  subscription, shared with interactive Claude Code use. Descriptions are cut at 12 000 characters. Watch
  `/usage` during the first week; if it hurts, lower the limit or switch to `anthropic_api` (no code change).

## Commands

```bash
uv run python -m today.jobs collect                                  # fill data/today.db with real roles
uv run python -m today.jobs analyze --one --profile data/profile.md  # oldest pending role, prints JSON
uv run python -m today.jobs analyze --one --job-id 42                # one role, stored profile
uv run pytest tests/llm tests/jobs -v
```

`analyze --one` writes nothing. The profile is set once through MCP (`set_profile`) and read back with
`get_profile`; it lives only in the database, never in the repository (the repo is public).

## Pitfalls

- The npm package `@anthropic-ai/claude-code` 2.x installs a native binary: the image copies that one file
  from a `node:22-slim` stage and ships without Node.
- `claude -p` writes its config under `~/.claude`, so the container user needs a real home directory.
- An empty profile skips the whole slot with a warning: jobs stay `new` until `set_profile` is called.
- `list_jobs(min_score=…)` lists every status by default: scored roles are already `analyzed`, not `new`.

## Exercises

1. Add `ANALYST=fake` that returns a fixed `JobAnalysis`, for running the app without any LLM. Which file
   changes, and which do not?
2. Bump `PROMPT_VERSION` to "2" and write `analyze --rerun-version 1` that re-scores old analyses. What stops
   it from hitting the limit in one go?

## Read next

- *Fundamentals of Software Architecture*: ch. 9 "Foundations" (architecture styles and the separation of a
  volatile dependency behind an interface) and ch. 4 "Architecture Characteristics Defined": cost, security
  and reliability traded off in one adapter.
- *Software Architecture: The Hard Parts*: ch. 13 "Contracts": `JobAnalysis` is a strict contract enforced by
  schema on both sides of a non-deterministic component.
