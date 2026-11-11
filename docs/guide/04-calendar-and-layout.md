# 04 · Calendar tab, range choice and a capture bar that stays put

## Concepts

- **Month grid as a table.** A month is tabular data (weeks × weekdays), so it is a `<table>` with `<th>`
  weekday headers: screen readers announce row and column for free. Each in-month day is a link
  (`/calendar?month=2026-11&day=2026-11-20`), so the selected day survives reloads and can be bookmarked.
- **Grouping by local day.** `month_grid` loads the items of the visible weeks in one query (UTC bounds of
  local midnights) and groups them by `due_at.astimezone(tz).date()`. An item at 22:00 in Fortaleza is 01:00
  UTC the next day; grouping by the UTC date would put it on the wrong square.
- **State in the URL or a cookie, not the server.** The 7/14/30 choice is a `?days=` link that also sets a
  `today_days` cookie; the calendar month and day are query parameters. Bad values fall back to defaults
  instead of erroring: the user only ever clicks links the app made.
- **`position: sticky` for the capture bar.** It stays in normal flow (no overlap at the end of the page) but
  sticks to the bottom of the viewport while the list scrolls under it. The safe-area inset keeps it above the
  iPhone home indicator.
- **`<details>` for "show more".** The first five rows render normally; the rest sit in a `<details>`, which
  opens without JavaScript and is keyboard accessible.

## Exercises

1. Make the week start on Sunday. Which two lines change, and which test should change with them?
2. Replace the full-page calendar navigation with `hx-boost="true"` on the grid. What gets faster, and what
   does the browser history do?

## Read next

- *Fundamentals of Software Architecture*: architecture characteristics: usability and accessibility as
  explicit, testable characteristics rather than afterthoughts.
