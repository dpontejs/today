-- Projects (feature 10): ideas evaluated against the profile and job gaps, then closed by a skill.
CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    idea_md TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'idea' CHECK (status IN ('idea', 'active', 'done', 'dropped')),
    evaluation_json TEXT,
    evaluated_at TEXT,
    repo_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Texts the owner approved, used as style references when writing in their voice (first kind: LinkedIn posts).
CREATE TABLE voice_samples (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('linkedin_post')),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX voice_samples_by_kind ON voice_samples (kind, created_at)
