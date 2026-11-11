# 0005. Expose items to AI clients through an MCP server with a bearer token

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** —

## Context

The only way to create items is the HTML form behind the login cookie. The user wants to fill and query the
app from Claude Code sessions (e.g. "put the M0 tasks from my ROADMAP into today"), which also means the
language understanding runs on the user's Claude subscription instead of paid Gemini calls. Claude Code
connects to remote tools over MCP (streamable HTTP) and can send a static `Authorization` header.

## Decision

Serve an MCP endpoint at `/mcp` inside the same FastAPI process, using the official `mcp` SDK (v2,
`MCPServer`) in stateless mode with JSON responses. Tools: `list_items`, `create_items` (batch, idempotent
by `source_key`), `complete_item`, `reopen_item`. Access requires `Authorization: Bearer <API_TOKEN>`,
compared in constant time. Without `API_TOKEN` set, the endpoint does not exist (404).

## Alternatives considered

- Plain JSON REST API + `curl` from Claude: works, but every session re-learns the URL shapes; MCP gives the
  model typed tools with descriptions.
- OAuth (MCP authorization spec): the right answer for many users; for one user a long random token is enough.
- Separate MCP process: a second deployable for four functions that already live in `items` (ADR 0001).

## Consequences

- Any MCP client (Claude Code, Claude Desktop, others) can manage items; the tool schema is a public contract.
- One more secret to rotate; whoever holds the token can read and change every item.
- New dependency tree (`mcp`, `httpx2`, `sse-starlette`, `pyjwt`…), pinned by `uv.lock`.

## How to revert

Delete the `/mcp` route, the `today.mcp` module and the dependency. No data changes: items created through
MCP are ordinary rows (`source = 'mcp'`). Half a day.

## Read next

- *Software Architecture: The Hard Parts*: ch. 13 "Contracts" (strict vs. loose contracts: the tool schemas).
- *Fundamentals of Software Architecture*: architecture characteristics: interoperability and security as
  characteristics in tension; architecture decision records.
