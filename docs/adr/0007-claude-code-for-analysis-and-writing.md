# 0007. Claude Code (`claude -p`) on the subscription for job analysis and writing, behind `Analyst`

- **Date:** 2026-11-23
- **Status:** accepted
- **Supersedes:** — (capture stays on Gemini, ADR 0003)

## Context

Job pre-analysis (feature 08) and, later, résumé tailoring, cover letters and interview prep need a stronger
model than Flash-Lite. Volume: ~20–60 structured calls/day, single user. The owner already pays a Claude
subscription. Checked 2026-11-23 in the Claude Code docs: `claude setup-token` issues a one-year OAuth token read
from `CLAUDE_CODE_OAUTH_TOKEN`; subscription credentials must not serve other users ("on behalf of their
users"); plan limits "assume ordinary, individual usage" (not defined) and are shared with the owner's
interactive use. ADR 0003 left this rule open; this resolves it for a one-user app.

## Decision

All calls go through one protocol, `Analyst.complete(model, prompt, schema) -> dict`, with two implementations
picked by env `ANALYST=claude_cli|anthropic_api`:

- `claude_cli` (default): `claude -p --output-format json --json-schema ... --tools "" --no-session-persistence
  --system-prompt ...` in an empty temp dir, env limited to `HOME/PATH/LANG` + `CLAUDE_CODE_OAUTH_TOKEN`, as in
  EdutorIA's `claude_cli.py`. The runtime image gains Node and the pinned Claude Code CLI.
- `anthropic_api`: Anthropic SDK with `ANTHROPIC_API_KEY`, same schemas.

Outputs are stored as validated JSON (Pydantic) with the model id and prompt version, never as free text.

## Alternatives considered

- API only: no grey area, but a second bill for something the subscription already covers.
- Worker on the owner's PC: token never leaves the machine, but analysis stops when the PC is off.
- Gemini for everything: weaker on long reasoning and writing in the owner's voice.

## Consequences

- A personal long-lived token sits on the VPS (env, never in the image or logs); it expires yearly.
- Usage competes with the owner's Claude Code quota: measure for the first week (`/usage`).
- Image size grows by the Node runtime.

## How to revert

Set `ANALYST=anthropic_api` and `ANTHROPIC_API_KEY`: no code change, stored analyses stay valid. Dropping the
CLI from the image is a one-line Dockerfile change.
