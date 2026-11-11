-- Many reminders per item (ADR 0006). items.remind_at is copied here and left unused.
CREATE TABLE reminders (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    remind_at TEXT NOT NULL,
    sent_at TEXT,
    UNIQUE (item_id, remind_at)
);

CREATE INDEX reminders_due ON reminders (sent_at, remind_at);

INSERT INTO reminders (item_id, remind_at)
SELECT id, remind_at FROM items WHERE remind_at IS NOT NULL;
