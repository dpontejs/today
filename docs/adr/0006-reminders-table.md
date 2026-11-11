# 0006. Store reminders in their own table, many per item

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** —

## Context

An exam needs several nudges (a week before, the day before, an hour before); a quick task needs one. Slice 1
put a single nullable `items.remind_at` column in place. The push slice will send reminders and must record,
per reminder, whether it was sent.

## Decision

A `reminders` table: `(id, item_id → items ON DELETE CASCADE, remind_at, sent_at)`, `UNIQUE(item_id, remind_at)`,
indexed by `(sent_at, remind_at)` for the "what is due and unsent" query. Migration 002 copies existing
`items.remind_at` values; the column stays unused until a later cleanup.

## Alternatives considered

- JSON array in `items.reminders`: no per-reminder `sent_at` without rewriting the array; no index for the
  due-reminders query.
- Fixed columns (`remind_1`, `remind_2`, …): arbitrary limit, awkward queries.

## Consequences

- The reminder loop becomes one indexed query plus an `UPDATE … SET sent_at` per reminder (idempotent).
- Deleting an item removes its reminders (`foreign_keys=ON` is already set in `connect`).

## How to revert

Collapse to the earliest unsent reminder per item into `items.remind_at` with one `UPDATE … SELECT MIN(...)`,
then drop the table. An hour; loses the extra reminders.

## Read next

- *Software Architecture: The Hard Parts*: ch. 6 "Pulling Apart Operational Data" (data relationships and
  ownership) and ch. 9 "Data Ownership and Distributed Transactions" (why this stays one table owned by `items`).
