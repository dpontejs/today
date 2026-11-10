# 0003. Use Gemini Flash-Lite for capture, behind `extract_items`

- **Date:** 2026-11-10
- **Status:** accepted
- **Supersedes:** —

## Context

Capture turns a sentence or a short voice note ("amanhã às 9 revisar o capítulo 3") into item drafts. It is a
single structured-output call, not an agent loop. It must accept audio, run unattended on the VPS, and cost
close to nothing. Rough estimate: 20 notes/day × 15 s ≈ 300k audio tokens/month, under US$ 0.50 at
Flash-Lite audio rates (to confirm on the official pricing page before slice 4).

## Decision

Gemini Flash-Lite via the `google-genai` SDK with an API key, model from env `MODEL`. All provider code sits
behind one function: `extract_items(text: str | None, audio: bytes | None, now: datetime) -> list[ItemDraft]`,
returning Pydantic-validated drafts that the user confirms before anything is saved.

## Alternatives considered

- `claude -p` with the personal subscription, as in EdutorIA's demo: puts a personal login on an exposed
  server, needs a separate speech-to-text step, and subscription use in an unattended service has usage rules to
  check. EdutorIA itself keeps that login on the dev's host only.
- Claude API + a transcription model: two vendors and two calls for one feature.
- Browser speech recognition (Web Speech API): uneven support in installed iOS PWAs; pt-BR quality varies.

## Consequences

- Native audio input, one call, one vendor.
- Provider lock-in is limited to one module; evals in tests pin the expected drafts.
- The API key is a secret on the VPS.

## How to revert

Write another implementation of `extract_items` (e.g. Claude API + transcription) and switch by env. Half a
day plus re-running the capture evals. No stored data depends on the provider.

## Read next

- *Fundamentals of Software Architecture*: architecture decisions and ADRs; component-based thinking (isolating
  a volatile dependency).
- *The Hard Parts*: ch. 13 "Contracts" (strict vs. loose contracts: the `ItemDraft` schema).
