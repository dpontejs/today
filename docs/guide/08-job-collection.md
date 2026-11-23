# 08 · Job collection: nine sources, one table, three times a day

`python -m today.jobs collect --dry-run` runs every source once against the real network and prints a
report. With `JOBS_ENABLED=true` the app does the same at 07:00, 13:00 and 19:00 and stores what passes the
filter; Claude reads it with `list_jobs` and triages with `update_job_status`.

## Concepts

- **Adapters (ports and adapters, in miniature).** Each source is a plain function
  `fetch(client) -> list[JobPosting]` in `today/jobs/sources/`. Greenhouse, Gupy, Ashby, Lever, Eightfold,
  Oracle, Himalayas, Remotar and LinkedIn all speak different JSON (or HTML); the rest of the code only sees
  `JobPosting`. Adding a company on Greenhouse is one token in `greenhouse.TOKENS`; adding a new ATS is one
  file and one line in `SOURCES`.
- **The client is injected.** Adapters receive an `httpx.Client`, never build one. Production passes a real
  client (`make_client()`, with `User-Agent: today-personal/1.0`); tests pass one whose transport is
  `httpx.MockTransport` serving files from `tests/fixtures/jobs/`. No test touches the network.
- **Recorded fixtures.** Each fixture is a real response, recorded once with curl and trimmed to two or three
  postings, one of them not ML (so the filter has something to drop). LinkedIn's is the exception: written by
  hand from the known card markup because the guest endpoint answered 429 while recording. Re-record it
  before relying on LinkedIn. When a source changes shape, re-record
  the fixture, watch the test fail, then fix the adapter.
- **Fail one, not all.** `collect` wraps each source in `try/except` and writes the error into the report.
  An HTML maintenance page answering 200 makes `get_json` raise; the other eight sources still save.
- **Idempotent upsert.** `UNIQUE(source, external_id)` plus `INSERT … ON CONFLICT DO NOTHING`: collecting
  twice stores one row, and a status set by you (`interested`, `applied`) is never overwritten. The same
  opening on Greenhouse and on LinkedIn is two rows on purpose: different sources, different links.
- **Scheduling slots, not cron.** The loop wakes every minute and asks `due_slot`: "what is today's latest
  slot at or before now that is not in `job_runs`?" A restart at 13:05 runs the 13:00 slot once; an outage
  from 06:00 to 20:00 runs only 19:00, not three stale collections. The slot key uses the local date, so
  22:00 in Fortaleza (01:00 UTC tomorrow) still belongs to today.
- **Being a polite client.** LinkedIn is read only through the guest endpoint, last 24 h, three pages per
  term, 3–7 s between requests (search pages and description pages alike), and stops at the first 429/999,
  keeping what it had and showing the block in the report (`PartialFetch`). Never logged in, and the cookie
  jar is cleared before every request. A 200 page with no readable job card raises, so a challenge page or a
  markup change shows up as an error instead of "0 jobs".

## Commands

```bash
uv run python -m today.jobs collect --dry-run                  # every source, in-memory DB
uv run python -m today.jobs collect --dry-run --sources gupy   # one source
JOBS_ENABLED=true JOBS_SOURCES=gupy,remotar uv run uvicorn --factory today.app:from_env
uv run pytest tests/jobs -v
```

## Pitfalls

- The migration runner splits files on `;`. A semicolon inside an SQL comment breaks the migration.
- Greenhouse escapes its HTML once more (`&lt;p&gt;`): unescape first, then strip the tags.
- An unknown name in `JOBS_SOURCES` stops the app at boot, on purpose: a typo would otherwise switch a
  source off without a sound.

## Exercises

1. Add `last_seen_at` and mark postings not seen for a week as closed. Which part of `upsert_jobs` changes,
   and why does it stop being "do nothing" on conflict?
2. Add a Workday company (endpoint in `docs/research/fontes-de-vagas.md`): record a fixture, write the test,
   then the adapter.

## Read next

- *Fundamentals of Software Architecture*: ch. 12 "Microkernel Architecture Style": a core plus
  plug-ins, which is what `SOURCES` is.
- *Software Architecture: The Hard Parts*: ch. 13 "Contracts": strict vs. loose contracts. `JobPosting` is the
  strict contract inside; each adapter absorbs a loose one outside.
