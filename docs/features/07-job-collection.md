# 07 · Job collection: open roles land in the database three times a day

- **Date:** 2026-11-23
- **Status:** implemented (branch feat/coleta-vagas)
- **ADRs:** [0001](../adr/0001-modular-monolith-with-in-process-scheduler.md) (in-process loop)
- **Research:** [docs/research/fontes-de-vagas.md](../research/fontes-de-vagas.md) (endpoints verified 2026-11-23)

## Goal

ML / AI / data / computer vision roles from the companies and boards in the research are collected at 07:00,
13:00 and 19:00, filtered without an LLM, deduplicated and stored with a status. Usable through MCP before any
screen exists; the LLM pre-analysis comes in feature 08.

## Out of scope

LLM analysis, profile, push about jobs, the Jobs screen, Uber and Magalu (no API), logged-in LinkedIn (never).

## Contracts

```python
# today/jobs/sources/*.py — one adapter per source, no shared state
class JobPosting(BaseModel):
    source: str            # "greenhouse:ifoodcarreiras", "gupy", "ashby:nubank", "lever:ciandt",
                           # "eightfold:mercadolibre", "oracle:picpay", "himalayas", "remotar", "linkedin"
    external_id: str
    company: str
    title: str
    location: str | None
    workplace: Literal["remote", "hybrid", "onsite"] | None   # None when the source has no field
    description: str | None   # plain text; HTML stripped
    url: str
    published_at: datetime | None

Fetch = Callable[[httpx.Client], list[JobPosting]]

def passes_filter(job: JobPosting) -> bool          # title matches role terms AND (remote | workplace unknown
                                                    # in Brazil/LatAm | hybrid/onsite in São Paulo or Natal)
def collect(conn, client, sources, now) -> CollectReport   # {source: {"fetched","kept","new","error"}}
async def run_jobs_loop(app) -> None                # runs `collect` once per slot (07/13/19 local), catches up once after a restart
```

- Role terms (case-insensitive, pt+en): machine learning, ML, MLE, MLOps, data scien*, cientista de dados,
  deep learning, computer vision, visão computacional, AI/IA engineer, LLM, GenAI, applied scientist,
  research engineer, estágio/intern **only together with** one of those.
- Migration `005_jobs.sql`: `jobs(id, source, external_id, company, title, location, workplace, description,
  url, published_at, first_seen_at, status, status_at, UNIQUE(source, external_id))`, `status` in
  `new | analyzed | dismissed | interested | applied`; `job_runs(slot TEXT PRIMARY KEY, ran_at, report_json)`.
- Re-seeing a stored job updates nothing but keeps it alive; status set by the user is never overwritten.
- One failing source (HTTP error, changed shape) is logged in the report; the others still run.
- LinkedIn: guest endpoint only, `f_TPR=r86400`, at most 3 pages per term, 3–7 s between requests,
  stops on 429/999. Detail page fetched only for jobs that pass the filter.
- Env: `JOBS_ENABLED=true` starts the loop; `JOBS_SOURCES` optional comma list to switch sources off.
- MCP: `list_jobs(status="new", limit=30) -> list[JobOut]`, `update_job_status(id, status) -> JobOut`.
- New dependency: `httpx`. Adapters are tested against recorded responses in `tests/fixtures/jobs/`, never
  the network.

## Acceptance criteria (as tests)

- [x] `test_<source>_parses_recorded_response` for each of the 9 sources: given the fixture, then fields map.
- [x] `test_filter_keeps_ml_roles_and_drops_sales`; `test_filter_drops_onsite_outside_sp`;
      `test_intern_kept_only_with_role_term`.
- [x] `test_collect_inserts_new_and_dedupes_by_source_and_id`: run twice, then one row each.
- [x] `test_collect_keeps_user_status_on_resight`: given `interested`, when seen again, then still `interested`.
- [x] `test_failing_source_reported_others_saved`.
- [x] `test_loop_runs_each_slot_once_and_catches_up_after_restart`.
- [x] `test_mcp_list_jobs_filters_by_status`; `test_mcp_update_job_status_rejects_unknown_status`;
      `test_mcp_jobs_require_bearer_token`.

## End-to-end check

```bash
uv run pytest && uv run python -m today.jobs collect --dry-run   # real network, prints the report, writes nothing
```

Then, deployed: after the next slot, `list_jobs` through Claude returns real roles from at least 6 sources.

## Risks and open questions

- Gupy may cap a search at 100 results: use one request per term, which stays under the cap.
- Shapes of unofficial endpoints (Gupy portal, Eightfold, Oracle) can change; the report makes that visible.
