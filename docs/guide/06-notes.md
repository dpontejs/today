# 06 · Notes: a notepad next to the dated items

## Concepts

- **A separate table, not an item without a date.** Items have a due time, reminders and a done state; notes
  have none of that. Making `items.due_at` nullable would push "if it has no date…" checks into every query
  (Today buckets, calendar, push loop). A `notes` table keeps both models simple.
- **Edit in place with HTMX.** Each note is an `<article id="note-7">`. EDITAR fetches `/notes/7/edit` (a
  form) and swaps it in; SALVAR posts and swaps the card back; CANCELAR fetches the card again. The server is
  the only place that renders a note.
- **Pinning is not editing.** `set_pinned` leaves `updated_at` alone, so pinning an old note does not make it
  look recently edited.
- **Line breaks without HTML.** The body is stored as typed and shown with `white-space: pre-wrap`; Jinja
  escapes it, so `<b>` shows up as text.

## Exercises

1. Add a search box that filters notes with `WHERE body LIKE ?`. What breaks with `%` or `_` in the query,
   and how do you escape it?
2. Add "turn into reminder": send the note's text to `/capture` and show the review card. Which module should
   own that link between notes and items?

## Read next

- *Software Architecture: The Hard Parts*: ch. 6 "Pulling Apart Operational Data": when two concepts deserve
  separate tables (and, at a larger scale, separate services).
