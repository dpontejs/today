-- Closed jobs (2026-11-26). Board sources (Greenhouse, Lever, Ashby) list every open job of a company:
-- a stored job missing from two successful fetches in a row is closed. Interested jobs from search sources
-- are checked on their own page instead.
ALTER TABLE jobs ADD COLUMN missed_runs INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN closed_at TEXT
