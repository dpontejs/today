# 03 · Natural-language capture: from a sentence (or your voice) to items and reminders

Slice 3 turns the bottom of the Today screen into one box: type "tenho prova dia 20 de Sistemas Distribuídos"
or hold the mic and say it. The app shows what it understood, with suggested reminders, and one tap creates it.

## Concepts

- **Structured output.** Gemini is called with `response_mime_type="application/json"` and
  `response_schema=list[CaptureDraft]`, so it must answer with a JSON array matching that pydantic model.
  `parse_drafts` still validates it: a schema is a strong hint to the model, not a guarantee.
- **The prompt carries the clock.** "amanhã", "sexta", "dia 20" only mean something relative to *now* in
  *your* zone, so `build_prompt` states both. The model resolves dates; the server double-checks them.
- **Propose, then confirm.** The model never writes to the database. Its drafts become a review card (a plain
  HTML form); only `POST /capture/confirm` creates items. Nothing is kept on the server between the steps.
- **Rules in two places.** The prompt asks for reminder rules (a week before, the day before at 19:00, an hour
  before); `clean_reminders` enforces the hard ones (not in the past, not after the event, no duplicates, at
  most five). Never trust the model for invariants.
- **Recording in the browser.** `MediaRecorder` records while the button is held. iOS Safari produces
  `audio/mp4` (AAC); Gemini documents that container as `audio/m4a`, hence `gemini_mime`.
- **A dependency seam.** Routes call `app.state.extractor`; tests replace it with a fake, so no test needs the
  network or a key.

## Why

- One model call handles text and audio, so voice comes almost for free ([ADR 0003](../adr/0003-gemini-for-capture.md)).
- Reminders got their own table because an exam needs several and the push loop must mark each one sent
  ([ADR 0006](../adr/0006-reminders-table.md)).

## Commands

```bash
GEMINI_API_KEY=... COOKIE_SECURE=false PASSPHRASE_HASH='...' SESSION_SECRET=dev \
  uv run uvicorn --factory today.app:from_env
curl -s -b jar -H 'Accept-Language: pt-BR' --data-urlencode 'text=ligar pro banco amanhã às 9' localhost:8000/capture
```

## Exercises

1. Say "reunião toda segunda às 10". What does the model do with a recurring event, and where would you add
   recurrence (prompt, schema, table)?
2. Change `temperature` to 1 and run the same sentence five times. What changes, and why is 0 the right
   choice for extraction?
3. Remove `clean_reminders` from `_card`. Which test fails, and what would the user see?

## Pitfalls

- iOS asks for microphone permission on the first press; releasing during the prompt must not leave the
  recorder running (the `held` flag in `capture.js`).
- htmx does not swap 4xx responses by default; the `htmx-config` meta swaps 413/415/422 so validation messages
  show up.
- The key is shared with other projects: same quota, and rotating it touches all of them.

## Read next

- *Fundamentals of Software Architecture*: component-based thinking: isolating a volatile dependency (the
  LLM vendor) behind one function.
- *Software Architecture: The Hard Parts*: ch. 13 "Contracts": the JSON schema between the app and the model.
