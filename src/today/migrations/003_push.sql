-- Web push: one row per subscribed device/browser, plus the once-a-day summary log.
CREATE TABLE push_subscriptions (
    id INTEGER PRIMARY KEY,
    endpoint TEXT NOT NULL UNIQUE,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    created_at TEXT NOT NULL,
    last_success_at TEXT,
    last_error TEXT
);

CREATE TABLE daily_summaries (
    day TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);

CREATE TABLE push_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
