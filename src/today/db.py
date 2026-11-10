"""SQLite connection and versioned SQL migrations (ADR 0002)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations in name order, each in its own transaction. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_version")}
    applied = []
    for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if file.name in done:
            continue
        conn.execute("BEGIN")
        try:
            for statement in file.read_text().split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (name, applied_at) VALUES (?, ?)",
                (file.name, datetime.now(UTC).isoformat()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        applied.append(file.name)
    return applied
