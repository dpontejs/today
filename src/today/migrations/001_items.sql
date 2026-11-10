-- Items: every time is a UTC ISO-8601 string (2026-11-10T12:00:00+00:00).
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    notes TEXT,
    due_at TEXT NOT NULL,
    remind_at TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done')),
    done_at TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    source_key TEXT UNIQUE,
    created_at TEXT NOT NULL
);

CREATE INDEX items_status_due ON items (status, due_at);
