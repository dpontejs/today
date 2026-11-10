# 01 · Foundation: one process, one file, one screen

This guide walks through slice 1: the project skeleton, the database, login, the Today screen, the PWA shell
and the deploy. Each section has the concept, why it was done this way, the commands, exercises and pitfalls,
and a **Read next** pointer into the two architecture books.

## 1. Settings and the database

### Concepts

- **Twelve-factor config.** Everything that changes between environments (database path, secrets) comes from
  environment variables, read once at startup into a frozen `Settings` object (`src/today/config.py`). Code
  never calls `os.environ` anywhere else, so tests build a `Settings` by hand.
- **SQLite in WAL mode.** Write-Ahead Logging lets readers keep reading while one writer writes. With one
  process and one user that is all the concurrency we need ([ADR 0002](../adr/0002-sqlite-on-a-volume.md)).
- **Versioned migrations.** Schema changes are numbered SQL files in `src/today/migrations/`. `migrate()`
  applies the ones not yet recorded in `schema_version`, each inside a transaction, so a broken file leaves
  the database as it was.
- **Time as data.** Every timestamp is stored as a UTC ISO-8601 string. ISO strings in the same offset sort
  the same way as the instants they represent, so `WHERE due_at < ?` works on plain text.

### Why

- No ORM: about ten queries, all visible in one module. The cost of an ORM (configuration, a second query
  language, lazy-loading surprises) buys nothing here.
- Migrations as plain SQL instead of a tool such as Alembic: one file per change is easy to read in review and
  to run by hand with the `sqlite3` CLI.

### Commands

```bash
uv sync                      # create .venv from uv.lock
uv run pytest tests/test_db.py
sqlite3 data/today.db '.schema items'
sqlite3 data/today.db 'SELECT * FROM schema_version'
```

### Exercises

1. Add `002_example.sql` with a broken statement and run `migrate()`. Check that `schema_version` did not
   change and that `001` is still applied. Delete the file afterwards.
2. Insert two items with `due_at` in different offsets (`-03:00` and `+00:00`) and sort them with
   `ORDER BY due_at`. Why does the order come out wrong, and why does storing everything in UTC prevent it?

### Pitfalls

- `sqlite3` in Python opens implicit transactions by default; `isolation_level=None` turns that off so
  `BEGIN`/`COMMIT` in `migrate()` mean exactly what they say.
- Splitting a migration on `;` breaks on triggers or string literals that contain `;`. Fine for now; switch
  to `executescript` inside a savepoint if a migration ever needs them.

### Read next

- *Fundamentals of Software Architecture*: architecture characteristics. Which characteristics this choice
  favours (simplicity, cost, deployability) and which it gives up (scalability, elasticity).
- *Software Architecture: The Hard Parts*: ch. 6 "Pulling Apart Operational Data", the section on choosing
  a database type.

## 2. Items and the Today buckets

### Concepts

- **Pure time.** `build_today(conn, now, tz)` receives `now` instead of reading the clock. Tests pin any
  instant (23:30 local, 22:00 local that is already tomorrow in UTC) without mocking.
- **Local day, UTC storage.** The user's day starts at local midnight in `America/Fortaleza`.
  `local_day_bounds` builds that midnight in the local zone, converts it to UTC, and the SQL compares UTC
  strings. The conversion happens once, at the edge, never inside SQL.
- **Idempotent status changes.** `mark_done` only updates rows still `open`, so pressing "done" twice (a double
  tap, an HTMX retry) keeps the first `done_at`.

### Why

The bucket rules are the product: "what is late" must match what the user sees on the wall clock. Keeping
them in one pure function with exhaustive boundary tests is cheaper than discovering a midnight bug on the
phone at 00:30.

### Commands

```bash
uv run pytest tests/test_items.py -v
uv run python -c "from datetime import datetime, UTC; from zoneinfo import ZoneInfo; \
print(datetime(2026,11,11,1,0,tzinfo=UTC).astimezone(ZoneInfo('America/Fortaleza')))"
```

### Exercises

1. Change `local_day_bounds` to use `now.date()` instead of `now.astimezone(tz).date()`. Which tests fail
   and why?
2. Add a "someday" bucket for items without a date. What would change in the schema (`due_at NOT NULL`) and
   in the migration?

### Pitfalls

- `datetime.combine(date, time.min, tzinfo=tz)` is fine for Fortaleza (no DST). In a zone with DST, local
  midnight can be ambiguous or missing; `zoneinfo` resolves it with `fold`, and tests would need a DST case.
- Comparing ISO strings only works when every value has the same offset. That is why `to_db` always converts
  to UTC.

### Read next

- *Fundamentals of Software Architecture*: modularity. `items` owns its table and exposes functions, not
  SQL; other modules (`notify`, `importers`) will call `create_item`, never `INSERT INTO items`.
- *Software Architecture: The Hard Parts*: ch. 6, data ownership (one owner per table, even inside a
  monolith).
