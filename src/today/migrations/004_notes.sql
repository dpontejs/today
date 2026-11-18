-- Free notes: a notepad without dates. Pinned first, then most recently edited.
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    body TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX notes_order ON notes (pinned, updated_at);
