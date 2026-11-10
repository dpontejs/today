# 0001. Build a modular monolith with an in-process reminder loop

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** — (replaces the Gmail + Dkron design of the planning-ai prototype)

## Context

One user, one phone, a handful of reminders a day. The app runs on a shared 2 vCPU / 4 GB VPS next to other
stacks. The prototype used Gmail as the channel and Dkron as the scheduler: two external systems to operate,
OAuth to maintain, and reminders lost if a Dkron job and the database disagreed. Web Push to an installed PWA
now works on iOS (16.4+) and Android, so e-mail is no longer needed as the channel.

## Decision

One FastAPI process with four modules (`items`, `notify`, `capture`, `importers`) that talk through plain
function calls. Reminders are rows in the database; a loop inside the process wakes every 60 s, sends due
reminders via Web Push, and marks them sent. Modules do not import each other's internals.

## Alternatives considered

- Keep Dkron (`@at` jobs + HTTP callback): a second service and two sources of truth for one table.
- Keep Gmail as the channel: OAuth on a server, slower, worse on the phone than a native notification.
- Separate worker container: same code, more to deploy; worth it only if the API needs to scale out.

## Consequences

- State lives in one place; a restart re-sends whatever came due while the app was down.
- Only one instance may run, or reminders are sent twice. Fine for one user; the `sent_at` update is the guard.
- Delivery precision is ±60 s.

## How to revert

Move the loop body into its own entrypoint (`python -m today.notify`) and run it as a second container: one
day, no data migration. Swapping in an external scheduler later means calling the same function from it.

## Read next

- *Fundamentals of Software Architecture*: modularity (cohesion, coupling), architecture characteristics, and the
  modular monolith vs. service-based styles.
- *The Hard Parts*: ch. 2 "Discerning Coupling" (architecture quantum: this app is one quantum) and ch. 11
  "Managing Distributed Workflows" (orchestration vs. choreography: what Dkron would have been).
