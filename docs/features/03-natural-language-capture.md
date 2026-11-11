# 03 · Natural-language capture: type or say it, confirm, done

- **Date:** 2026-11-10
- **Status:** proposed
- **ADRs:** [0003](../adr/0003-gemini-for-capture.md) (Gemini behind `extract_items`), [0006](../adr/0006-reminders-table.md)

## Goal

On the phone, one box: type or hold the mic and say "tenho prova dia 20 de Sistemas Distribuídos". The app shows
what it understood (title, date, suggested reminders) and one tap creates it. The manual form stays, collapsed.

## Out of scope

Sending the reminders (push, next slice), recurrence, editing an item after creation, MCP-created reminders.

## Contracts

```python
# POST /capture  (form: text=... | multipart: audio=<file>)  →  200 HTMX fragment "_capture_review.html"
#   empty text and no audio → 422 · audio > 2 MB or not audio/* → 413 / 415 · model failure → 200 with error card
# POST /capture/confirm  (form: title[], due_at[], reminders[] per draft index)  →  303 /
class CaptureDraft(BaseModel):            # what the model returns (JSON schema for Gemini)
    title: str                             # in the user's language, short
    due_at: str                            # "YYYY-MM-DDTHH:MM", America/Fortaleza; 09:00 when no time was said
    notes: str | None
    reminders: list[str]                   # same format; suggested by kind of event

def extract_items(text: str | None, audio: bytes | None, mime: str | None,
                  now: datetime, tz: ZoneInfo, lang: str) -> list[CaptureDraft]
# app.state.extractor holds it; tests swap in a fake. Raises CaptureError on API/parse failure.
```

- Database: migration `002_reminders.sql`: `reminders(id INTEGER PK, item_id INTEGER NOT NULL REFERENCES items(id)
  ON DELETE CASCADE, remind_at TEXT NOT NULL, sent_at TEXT, UNIQUE(item_id, remind_at))` plus an index on
  `(sent_at, remind_at)`; existing `items.remind_at` values are copied over. `items.remind_at` stays (unused).
- Reminder rules (prompt + server): events with a date (exam, delivery, appointment, meeting) get up to three
  reminders (7 days before at 09:00 when the event is 8+ days away, the day before at 19:00, and 1 hour before);
  plain tasks get one at the due time. The server drops reminders in the past or after `due_at`, dedupes, caps 5.
- Env: `GEMINI_API_KEY` (capture is hidden when unset), `GEMINI_MODEL` (default `gemini-3.5-flash-lite`).
- iOS records `audio/mp4`; it is sent to Gemini as-is.

## Acceptance criteria (as tests)

- [ ] `test_capture_text_shows_review_card`: fake extractor → card with title, local date and reminder checkboxes.
- [ ] `test_capture_passes_now_tz_and_lang`: the extractor gets `now`, `America/Fortaleza` and the request language.
- [ ] `test_capture_audio_passes_bytes_and_mime`; `test_capture_rejects_large_audio_413`; `test_capture_rejects_non_audio_415`.
- [ ] `test_capture_empty_is_422`; `test_capture_model_error_shows_message`.
- [ ] `test_confirm_creates_item_and_reminders_in_utc`; `test_confirm_only_checked_reminders`.
- [ ] `test_clean_reminders_drops_past_after_due_dupes_and_caps`.
- [ ] `test_migration_copies_remind_at`; `test_deleting_item_deletes_reminders`.
- [ ] `test_build_prompt_states_now_zone_language_and_rules`; `test_parse_model_json_to_drafts` (bad JSON → CaptureError).
- [ ] `test_capture_hidden_without_gemini_key`.

## End-to-end check

Local server with the real key: "tenho prova dia 20 de Sistemas Distribuídos" (text) → card → confirm → Today/next
shows it. On the iPhone (installed app): hold the mic, say the same, release → card → confirm.

## Risks and open questions

- Gemini's acceptance of iOS `audio/mp4` is checked on the device; fallback is server-side conversion.
- The key is shared with edutor-ia and flamengo-news (same quota; rotating it touches all three).
