# 10 · Projects: is this idea worth it for me, and closing it well

- **Date:** 2026-11-24
- **Status:** proposed
- **ADRs:** [0007](../adr/0007-claude-code-for-analysis-and-writing.md) (same `Analyst`)
- **Depends on:** [08](08-job-pre-analysis.md) (profile and job analyses)

## Goal

Two moments of a portfolio project. **Start:** I describe an idea; today weighs it against my profile, the
gaps that repeat in the jobs I care about and the projects I already have, and answers with a verdict and
scope suggestions. **End:** a Claude Code skill, run inside the project's repo, writes the portfolio entry
and the LinkedIn post with me, then records the result back in today (post as a voice sample, profile updated,
project done). Why now: I want stronger projects before applying in volume, and credit-risk-mlops is underway.

## Out of scope

Tracking progress in the middle (reminders + each repo's ROADMAP already do it), publishing to LinkedIn
(never automated), private repos read from the server, résumé/cover letter (feature for applications).

## Contracts — P1 (today)

```python
class GapStat(BaseModel):          # today/projects/gaps.py
    skill: str                     # normalized: lowercase, trimmed
    jobs: int                      # distinct jobs listing it
    required: int                  # of those, as required
    weight: float                  # sum over jobs: 3 if interested/applied, 2 if score >= 70, else 1

def gap_stats(conn, now, days=60, limit=20) -> list[GapStat]   # analyzed in the last `days`, not dismissed

class IdeaEvaluation(BaseModel):   # today/projects/evaluate.py
    verdict: str                   # 1–2 sentences, pt-BR
    score: int = Field(ge=0, le=100)
    covers: list[str]              # gaps from gap_stats the project would show
    already_shown: list[str]       # what profile/projects already prove (low marginal value)
    missing: list[str]             # what the idea lacks to be convincing for the target roles
    scope_suggestions: list[str]   # concrete changes, each tied to a gap
    effort_note: str | None        # if the stated time looks short/long for the scope

def evaluate_idea(conn, analyst, model, project_id, now) -> IdeaEvaluation  # stores it on the project
```

- Migration `007_projects.sql`: `projects(id, name, idea_md, status CHECK IN ('idea','active','done',
  'dropped'), evaluation_json, evaluated_at, repo_url, created_at, updated_at)`;
  `voice_samples(id, kind CHECK IN ('linkedin_post'), body, created_at)`.
- Routes (session): `GET /projects` (list + new-idea form), `POST /projects` (name, idea_md → create +
  evaluate, 303 to detail), `GET /projects/{id}`, `POST /projects/{id}/evaluate` (after editing the idea),
  `POST /projects/{id}/status` (active | done | dropped). Evaluation runs in a thread, ≤ 300 s, htmx shows
  "avaliando…". Analyst unavailable → project saved, page says "avaliação pendente", button to retry.
- Model: `PROJECTS_MODEL` (default `opus`): few calls, the answer matters more than for job triage.
- Nav: `Section(key="projects", path="/projects", label_key="tab_projects", group="career")`.
- MCP: `get_gap_stats(days=60)`, `list_projects(status=None)`, `get_project(id)`,
  `update_project(id, status=None, repo_url=None)`, `list_voice_samples(kind="linkedin_post", limit=5)`,
  `add_voice_sample(kind, body)`.

## Contracts — P2 (skill)

`~/.claude/skills/fechar-projeto/SKILL.md` (personal, works in any repo). Steps: read repo (README, ROADMAP,
code, git log) → `get_project` / `list_projects` to link it → draft portfolio `Project` entry (EN+PT, shape of
`~/portfolio/src/data/projects.ts`) → write the post with me using `list_voice_samples` (none yet: write the
first together, no generic "LinkedIn style") → on approval: PR in `~/portfolio` with the entry,
`add_voice_sample` with the final post, `set_profile` with the project added, `update_project(status="done",
repo_url)`. Never publishes on LinkedIn.

## Acceptance criteria (as tests, P1)

- [ ] `test_gap_stats_counts_distinct_jobs_and_weights_interest`; `test_gap_stats_ignores_dismissed_and_old`.
- [ ] `test_gap_stats_normalizes_skill_names` ("Spark", " spark " → one).
- [ ] `test_create_project_evaluates_and_redirects` (fake analyst); `test_prompt_has_profile_gaps_and_projects`.
- [ ] `test_analyst_unavailable_keeps_project_with_pending_evaluation`; `test_reevaluate_replaces_evaluation`.
- [ ] `test_status_only_active_done_dropped`; `test_projects_require_session`; `test_projects_listed_under_more`.
- [ ] `test_mcp_gap_stats`; `test_mcp_update_project`; `test_mcp_voice_samples_newest_first_and_limit`.

## End-to-end check

Deployed: create "credit-risk-mlops" with its README summary as the idea → evaluation names real gaps from the
week's analyses. P2: run `/fechar-projeto` on a finished repo → portfolio PR opens, voice sample stored.

## Risks and open questions

- Gap names vary ("GCP" vs "Google Cloud"): normalization is lowercase/trim only; the evaluation prompt gets
  the raw list and may merge synonyms. Revisit if stats look fragmented.
