# 11 · Projects: is this idea worth it for me?

## Concepts

- **Marginal value, not absolute value.** The evaluation prompt (`projects/evaluate.py`) carries three things:
  the profile, the gaps that repeat in the jobs the owner cares about, and the projects already registered.
  The question is not "is this a good project?" but "what would it prove that nothing in my portfolio proves
  yet, for the roles I want?". `already_shown` makes repetition visible; `scope_suggestions` tie each change
  to a gap.
- **Aggregating LLM outputs.** Feature 08 stores each job analysis as validated JSON. `gap_stats` reads those
  documents back and counts gaps per *distinct job* (a job listing "Spark" twice counts once), weighting the
  jobs the owner showed interest in. Structured outputs pay off twice: once when stored, again when queried.
- **Write first, call the model second.** `POST /projects` inserts the row before calling the analyst. A limit
  or an outage leaves "evaluation pending" and a retry button instead of a lost idea. The same reason makes
  `evaluate_idea` store only after a valid answer.
- **Different models for different stakes.** Job triage runs ~60 times a day on Sonnet; idea evaluation runs a
  few times a month on Opus (`PROJECTS_MODEL`). Same `Analyst` port (ADR 0007), one more setting.
- **The screen starts, the conversation finishes.** Closing a project (portfolio entry, LinkedIn post) is
  iterative writing that needs the repo's code, so it lives in the `/fechar-projeto` Claude Code skill. The
  MCP tools added here (`get_gap_stats`, projects, voice samples) are the contract between the two.

## Pitfalls

- Two test files with the same basename in folders without `__init__.py` collide under pytest's default
  import mode (`tests/jobs/test_routes.py` vs `tests/projects/…`): name them uniquely.
- Gap names are only lowercased and trimmed; "GCP" and "Google Cloud" stay apart in the stats, and the prompt
  asks the model to merge synonyms when it reads the list.

## Exercises

1. Show the top 10 of `gap_stats` on the Projects page, above the form, so the owner sees the market signal
   before writing an idea.
2. Add an `effort` field (weeks) to the form and pass it to the prompt instead of relying on free text.

## Read next

*Designing Machine Learning Systems* (Chip Huyen), chapter 1, on framing a project by the business objective
before the model; the same reasoning frames a portfolio project by the jobs it should help land.
