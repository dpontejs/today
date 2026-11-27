# today

A personal PWA for the day's reminders and to-dos. Type or **say** "tomorrow at 9 review chapter 3" and it becomes an item; the phone gets a **push notification** when it is due; one screen shows what is **late, today and next**.

First real use: tracking the 90-day study roadmap of [credit-risk-mlops](https://github.com/dpontejs/credit-risk-mlops) (milestones M0–M4).

Also a study project: every architectural decision is recorded as an ADR and mapped to a concept in
*Fundamentals of Software Architecture* (Richards & Ford) and *Software Architecture: The Hard Parts* (Ford, Richards, Sadalage, Dehghani), so the docs double as a reading guide.

## Architecture at a glance

```
iPhone / browser (installed PWA)
   │  HTTPS (Caddy on the VPS)
   ▼
FastAPI app — one process, one container          (ADR 0001)
   ├─ items      CRUD + Today view (Jinja + HTMX)
   ├─ notify     push subscriptions + 60 s reminder loop → Web Push (VAPID)
   ├─ mcp        /mcp tools for Claude & other MCP clients (ADR 0005)
   ├─ capture    text or voice → item drafts + reminders (Gemini)  (ADR 0003, 0006)
   └─ jobs       collect every 2 days at 07h → score vs. profile (claude -p)  (ADR 0007)
SQLite on a Docker volume                          (ADR 0002)
```

## Delivery slices (one PR each, deployed after each)

1. Skeleton, items, Today view, login, deploy — [docs/features/01-today-view.md](docs/features/01-today-view.md) ✓
2. MCP server: manage items from Claude sessions — [docs/features/02-mcp-server.md](docs/features/02-mcp-server.md) ✓
3. Natural-language capture by text or voice, with suggested reminders — [docs/features/03-natural-language-capture.md](docs/features/03-natural-language-capture.md) ✓
4. Calendar tab, 7/14/30 days, pinned capture bar ✓
5. Web push + reminder loop + daily summary — [docs/features/05-web-push.md](docs/features/05-web-push.md)
6. Adaptive navigation: bottom bar on the phone, sidebar on desktop, ready for career sections — [docs/guide/07-adaptive-navigation.md](docs/guide/07-adaptive-navigation.md) ✓
7. Job collection: ML/AI roles below senior, every 2 days at 07h; closed jobs detected; read and triaged through MCP — [docs/features/07-job-collection.md](docs/features/07-job-collection.md)
8. Job pre-analysis: each new role scored 0–100 against my profile by Claude, strong matches pushed — [docs/features/08-job-pre-analysis.md](docs/features/08-job-pre-analysis.md), [guide](docs/guide/09-job-pre-analysis.md)
9. Jobs tab: list + detail triage on desktop (to review, interested, applied, after the move, dismissed) — [guide](docs/guide/10-jobs-tab.md)
10. Projects: idea evaluated against my profile and the gaps that repeat in the jobs I want; closed by the `/fechar-projeto` skill — [docs/features/10-projects.md](docs/features/10-projects.md), [guide](docs/guide/11-projects.md)

ROADMAP import from the desktop is done through Claude + MCP (slice 2).

Out of the MVP: recurrence, writing back to ROADMAP.md, chat agent, e-mail, multi-user, Postgres, native app, Google Calendar.

## Decisions

| ADR | Decision |
|-----|----------|
| [0001](docs/adr/0001-modular-monolith-with-in-process-scheduler.md) | Modular monolith with an in-process reminder loop (no Dkron, no e-mail) |
| [0002](docs/adr/0002-sqlite-on-a-volume.md) | SQLite on a Docker volume |
| [0003](docs/adr/0003-gemini-for-capture.md) | Gemini Flash-Lite for capture, behind `extract_items` |
| [0004](docs/adr/0004-single-user-passphrase-auth.md) | Single-user passphrase auth with a session cookie |
| [0005](docs/adr/0005-mcp-api-with-bearer-token.md) | MCP server at `/mcp` behind a bearer token |
| [0006](docs/adr/0006-reminders-table.md) | Reminders in their own table, many per item |
| [0007](docs/adr/0007-claude-code-for-analysis-and-writing.md) | Claude Code (`claude -p`) on the subscription for job analysis, behind `Analyst` |

## Docs

- `docs/guide/` — didactic guide per slice: concepts, why, commands, exercises, pitfalls, and **Read next** (book chapter).
- `docs/adr/` — architecture decision records.
- `docs/features/` — one page per slice: contracts and acceptance tests.
