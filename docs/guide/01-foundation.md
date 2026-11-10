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
