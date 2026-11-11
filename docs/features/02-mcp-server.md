# 02 · MCP server: manage items from Claude sessions

- **Date:** 2026-11-10
- **Status:** proposed
- **ADRs:** [0005](../adr/0005-mcp-api-with-bearer-token.md)

## Goal

From any Claude Code session: "what is late?", "put the M0 tasks from ~/credit-risk-mlops/docs/ROADMAP.md
into today", "mark the Docker course as done". Claude parses the natural language; the app stores items.

## Out of scope

Editing or deleting items, OAuth, per-client tokens, MCP resources/prompts, push (slice 3 now).

## Contracts

```python
# POST/GET/DELETE /mcp — MCP streamable HTTP, stateless, JSON responses.
# Header: Authorization: Bearer <API_TOKEN>. Missing/wrong → 401. API_TOKEN unset → 404.

class DraftIn(BaseModel):            # one item to create
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime                 # ISO 8601; without offset it is America/Fortaleza local time
    notes: str | None = Field(default=None, max_length=2000)
    source_key: str | None = Field(default=None, max_length=200)  # e.g. "roadmap:M0:book-ch-1-2"

class ItemOut(BaseModel):
    id: int; title: str; notes: str | None; due_at: str  # ISO in America/Fortaleza (-03:00)
    status: Literal["open", "done"]; source: str; source_key: str | None

list_items(days: int = 7) -> {"late": [ItemOut], "today": [ItemOut], "next": [ItemOut], "done_today": [ItemOut]}
create_items(items: list[DraftIn]) -> {"created": [ItemOut], "skipped_source_keys": [str]}   # max 100 per call
complete_item(id: int) -> ItemOut       # unknown id → tool error "item <id> not found"
reopen_item(id: int) -> ItemOut
```

- Database: no migration. MCP rows get `source = 'mcp'`; `source_key` (already `UNIQUE`) makes imports idempotent.
- Settings: optional env `API_TOKEN` (32+ chars when set).
- SDK: `MCPServer(...).streamable_http_app(stateless_http=True, json_response=True, host="0.0.0.0")`;
  `host="0.0.0.0"` turns off the SDK's localhost-only Host check (the bearer token is the protection);
  FastAPI's lifespan runs `session_manager.run()` because a mounted sub-app's lifespan never runs.

## Acceptance criteria (as tests)

- [ ] `test_mcp_requires_token`: no header / wrong token → 401; `API_TOKEN` unset → 404.
- [ ] `test_mcp_lists_tools`: `tools/list` returns the four tool names.
- [ ] `test_create_items_naive_due_is_local`: `due_at` "2026-11-11T09:00" → stored `12:00:00+00:00`.
- [ ] `test_create_items_is_idempotent_by_source_key`: same batch twice → second call creates 0, skips all keys.
- [ ] `test_create_items_rejects_more_than_100`: 101 drafts → tool error, nothing stored.
- [ ] `test_list_items_buckets_in_local_time`: late/today/next match `build_today`; `due_at` has `-03:00`.
- [ ] `test_complete_and_reopen_item`: status changes; unknown id → tool error.
- [ ] `test_mcp_over_http_end_to_end`: JSON-RPC `tools/call create_items` through `/mcp` with the token, then
      the item appears on the Today page.

## End-to-end check

```bash
claude mcp add --transport http today https://today.diegoponte.dev/mcp --header "Authorization: Bearer $TOKEN"
claude   # "what do I have late in today?" → list_items
```

## Risks and open questions

- MCP SDK v2 is young; its HTTP app is pinned by `uv.lock`, and the end-to-end test catches API drift.
