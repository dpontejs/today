-- Job collection (feature 07). One row per (source, external_id). The user status is never overwritten.
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    workplace TEXT CHECK (workplace IN ('remote', 'hybrid', 'onsite')),
    description TEXT,
    url TEXT NOT NULL,
    published_at TEXT,
    first_seen_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'analyzed', 'dismissed', 'interested', 'applied')),
    status_at TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX jobs_by_status ON jobs (status, first_seen_at);

-- One row per collection slot ('2026-11-23T13'): the loop runs a slot once, even across restarts.
CREATE TABLE job_runs (
    slot TEXT PRIMARY KEY,
    ran_at TEXT NOT NULL,
    report_json TEXT NOT NULL
);
