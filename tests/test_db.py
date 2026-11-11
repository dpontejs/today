import sqlite3
from pathlib import Path

import pytest

from today.config import load_settings
from today.db import MIGRATIONS_DIR, connect, migrate


def test_migrations_apply_once(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    first = migrate(conn)
    second = migrate(conn)

    files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert first == files
    assert second == []
    rows = conn.execute("SELECT name FROM schema_version ORDER BY name").fetchall()
    assert [r["name"] for r in rows] == files


def test_items_status_check(conn: sqlite3.Connection):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO items (title, due_at, status, created_at) VALUES (?, ?, ?, ?)",
            ("x", "2026-11-10T12:00:00+00:00", "x", "2026-11-10T12:00:00+00:00"),
        )


def test_connect_uses_wal(tmp_path: Path):
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_load_settings_requires_secret(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "h")
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        load_settings()


def test_load_settings_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "h")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    monkeypatch.delenv("DB_PATH", raising=False)
    s = load_settings()
    assert s.cookie_secure is True
    assert s.tz.key == "America/Fortaleza"
    assert s.db_path == Path("data/today.db")


def test_load_settings_rejects_short_api_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "h")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.setenv("API_TOKEN", "short")
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        load_settings()


def test_load_settings_api_token_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PASSPHRASE_HASH", "h")
    monkeypatch.setenv("SESSION_SECRET", "s")
    monkeypatch.delenv("API_TOKEN", raising=False)
    assert load_settings().api_token is None
