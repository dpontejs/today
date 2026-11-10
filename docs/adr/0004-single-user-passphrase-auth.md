# 0004. Single-user passphrase auth with a session cookie

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** —

## Context

The app is public on the internet (push needs HTTPS and a reachable origin) but has exactly one user. Caddy
basic auth breaks installed PWAs on iOS (credential prompts inside the standalone app, service worker fetches).

## Decision

A login page checks a passphrase against an Argon2 hash in env `PASSPHRASE_HASH`; on success the app sets a
signed, `HttpOnly`, `Secure`, `SameSite=Lax` session cookie valid for 90 days. Every route except `/login`,
`/healthz`, the manifest, icons and the service worker requires it. Login attempts are rate-limited per IP.

## Alternatives considered

- Caddy basic auth: breaks in installed iOS PWAs.
- OAuth (Google sign-in): a provider, redirects and consent screen for one user.
- Passkeys (WebAuthn): best UX, more code; a good later upgrade.

## Consequences

- No user table; adding users later is a schema change.
- Losing the cookie means typing the passphrase once on that device.

## How to revert

Add a `users` table and an `owner_id` column on items, then put a real auth flow in front. Two to three days,
including migrating existing rows to the first user.

## Read next

- *Fundamentals of Software Architecture*: architecture characteristics: security as an explicit
  characteristic, traded against simplicity.
