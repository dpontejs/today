-- Job pre-analysis (feature 08). One analysis per job, a re-analysis replaces it.
CREATE TABLE job_analyses (
    job_id INTEGER PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    analysis_json TEXT NOT NULL,
    score INTEGER NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    analyzed_at TEXT NOT NULL
);

CREATE INDEX job_analyses_by_time ON job_analyses (analyzed_at);

-- Failed analyses per job: at 3 the job leaves the queue (status analyzed, no row).
ALTER TABLE jobs ADD COLUMN analysis_attempts INTEGER NOT NULL DEFAULT 0;

-- The owner's profile in markdown, a single row. Never committed: set through MCP (set_profile).
CREATE TABLE profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    body_md TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
