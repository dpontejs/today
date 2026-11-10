# 0002. Store data in SQLite on a Docker volume

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** —

## Context

One user, one process (ADR 0001), a few hundred rows a month. The VPS plans a shared Postgres, but it is not
running yet and its backups are not done. The prototype already used SQLite with plain SQL.

## Decision

SQLite file on a named Docker volume, WAL mode, plain `sqlite3` with versioned SQL migration files applied at
startup. Datetimes are stored as UTC ISO-8601 strings and shown in `America/Fortaleza`.

## Alternatives considered

- Shared Postgres on the VPS: not ready; adds a network dependency and credentials for no gain at this size.
- An ORM (SQLAlchemy): more to learn and configure than the ~10 queries need.

## Consequences

- Zero extra services; tests use a temporary file, so they are fast and isolated.
- Backups are a file copy (`sqlite3 .backup`) until the infra backup job exists.
- Only one writer process: matches ADR 0001, blocks horizontal scaling.

## How to revert

Port the migrations to Postgres SQL, swap the connection helper, and copy the rows with a one-off script. About
one day; the queries are plain SQL in one module.

## Read next

- *The Hard Parts*: ch. 6 "Pulling Apart Operational Data" (choosing a database type, data ownership).
- *Fundamentals of Software Architecture*: architecture characteristics (simplicity and cost over scalability).
