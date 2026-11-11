# 02 · An MCP server: letting Claude manage the items

Slice 2 adds `/mcp`, so any MCP client (Claude Code, Claude Desktop) can list, create, complete and reopen
items. Claude does the language work ("put the M0 tasks from my roadmap in today"); the app only stores.

## Concepts

- **MCP (Model Context Protocol).** JSON-RPC 2.0 between an AI client and a server that offers *tools* (typed
  functions with descriptions). The client reads `tools/list`, the model decides to call one, the client sends
  `tools/call` and the result goes back into the conversation.
- **Streamable HTTP, stateless.** Each request is a plain `POST /mcp` with one JSON-RPC message; the server
  answers with JSON (`json_response=True`) and keeps no session. One process, short tools: nothing to stream.
- **Structured output.** Tools return pydantic models, so results come back both as text and as
  `structuredContent` that matches a published JSON schema: the tool contract ([ADR 0005](../adr/0005-mcp-api-with-bearer-token.md)).
- **Tool errors vs. crashes.** `ToolError("item 999 not found")` reaches the model as `isError: true` with the
  message, so it can recover. Any other exception becomes a generic "Error executing tool".
- **Idempotent imports.** `source_key` is `UNIQUE`; `INSERT … ON CONFLICT (source_key) DO NOTHING RETURNING *`
  makes "import the roadmap" safe to run twice.

## Why

- MCP instead of a REST API: the model gets names, schemas and descriptions instead of re-deriving URL shapes
  in every session.
- Inside the same process instead of a separate service: four thin functions over the `items` module
  (ADR 0001).
- A static bearer token instead of OAuth: one user, one client.

## Commands

```bash
# local server with MCP enabled
API_TOKEN=$(openssl rand -hex 32) COOKIE_SECURE=false PASSPHRASE_HASH='...' SESSION_SECRET=dev \
  uv run uvicorn --factory today.app:from_env --port 8000

# raw protocol, the way a client starts
curl -s localhost:8000/mcp -H "Authorization: Bearer $API_TOKEN" \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# connect Claude Code (user scope: available in every project)
claude mcp add --scope user --transport http today https://today.diegoponte.dev/mcp \
  --header "Authorization: Bearer $API_TOKEN"
```

## Exercises

1. Call `create_items` with a `due_at` of `"tomorrow 9am"`. Who rejects it, and what does the model see?
2. Remove `host="0.0.0.0"` from `mount_mcp` and run the tests with `Host: today.diegoponte.dev`. Which
   protection kicks in, and why is it pointless behind a bearer token?
3. Ask Claude to import M0 twice. Which part of the code guarantees there are no duplicates?

## Pitfalls

- A mounted Starlette sub-app's lifespan never runs: the MCP session manager is started in the FastAPI
  lifespan, and tests must use `with TestClient(app)` to trigger it.
- The token gives full read/write access. Keep it in `~/.config/infra/secrets.env` and in Claude Code's
  config, never in the repo.

## Read next

- *Software Architecture: The Hard Parts*: ch. 13 "Contracts": strict (JSON schema) vs. loose contracts and
  what changing a tool's parameters costs its clients.
- *Fundamentals of Software Architecture*: integration styles; why this is an *operation* exposed for
  another system rather than a shared database.
