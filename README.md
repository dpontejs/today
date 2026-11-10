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
   ├─ capture    text/audio → item drafts (Gemini)  (ADR 0003)
   └─ importers  ROADMAP.md → items (deterministic)
SQLite on a Docker volume                          (ADR 0002)
```

## Delivery slices (one PR each, deployed after each)

1. Skeleton, items, Today view, login, deploy — [docs/features/01-today-view.md](docs/features/01-today-view.md)
2. Web push + reminder loop + notification status
3. ROADMAP import
4. Text capture
5. Audio capture

Out of the MVP: recurrence, writing back to ROADMAP.md, chat agent, e-mail, multi-user, Postgres, native app, Google Calendar.

## Decisions

| ADR | Decision |
|-----|----------|
| [0001](docs/adr/0001-modular-monolith-with-in-process-scheduler.md) | Modular monolith with an in-process reminder loop (no Dkron, no e-mail) |
| [0002](docs/adr/0002-sqlite-on-a-volume.md) | SQLite on a Docker volume |
| [0003](docs/adr/0003-gemini-for-capture.md) | Gemini Flash-Lite for capture, behind `extract_items` |
| [0004](docs/adr/0004-single-user-passphrase-auth.md) | Single-user passphrase auth with a session cookie |

## Docs

- `docs/guide/` — didactic guide per slice: concepts, why, commands, exercises, pitfalls, and **Read next** (book chapter).
- `docs/adr/` — architecture decision records.
- `docs/features/` — one page per slice: contracts and acceptance tests.
