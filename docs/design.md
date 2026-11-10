# Visual identity: "Departure board"

Reminders are departures: each item has a time, a status (`NEXT`, `ON TIME`, `LATE`) and a gate it leaves
from. The screen reads like an airport board: dark ground, big condensed times, monospace text, one signal
color. No gradients, no cards with shadows, no emoji, no rounded "AI app" pastel.

## Tokens

| Token | Value | Use |
|-------|-------|-----|
| `--bg` | `#0E0F11` | page ground, text on accent/late pills |
| `--panel` | `#1A1C1F` | inputs, raised surfaces |
| `--rule` | `#2A2C30` | section rules, borders, empty progress cells |
| `--rule-soft` | `#24262A` | dashed row separators |
| `--ink` | `#EDE6D6` | main text |
| `--ink-2` | `#B9B4A8` | secondary text (upcoming rows) |
| `--muted` | `#8C8A84` | labels, captions (5.4:1 on `--bg`) |
| `--accent` | `#FFB000` | the next item, today's date, primary button, progress |
| `--late` | `#FF6A3D` | late label and pill (6.5:1 on `--bg`) |

Dark only in the MVP: it suits the lock-screen glance, and a light theme doubles the visual QA.

## Type

- **Display / times:** Barlow Condensed 700. Date numeral 84px, row times 26px, tabular.
- **Everything else:** JetBrains Mono 400/600/700. Body 14px, row titles 14px, labels 10–11px uppercase
  with `letter-spacing: 0.14–0.18em`.
- Self-hosted woff2 files in `static/fonts/` (no Google Fonts request at runtime, works offline).

## Layout

- Single column, 18px side gutter, sections separated by a 1px `--rule` line with label left, count right.
- Row = grid `62px | 1fr | auto` (time, title, status pill). Pills are square (no radius), 10px bold uppercase.
- Status vocabulary: `NEXT` (accent pill, first item due today), `ON TIME` (muted text), `LATE` (late pill),
  `DONE` (title struck through, muted).
- Milestone strip at the bottom: 21-cell bar (one per day), filled cells in accent.
- Capture bar pinned to the bottom: input + 52px square accent button (mic). Touch targets ≥ 44px.

## Icon and notifications

- Icon: a split-flap tile on `--bg` with an accent "t" cut by the flap line. Exported to 180/192/512px PNG
  and a maskable 512px variant.
- Notification title `HH:MM · <title>`, body with the milestone or note. The daily summary at 08:00 reads
  `<Weekday> · N today, M late`.

Reference mockups: the identity canvas (private link, kept by the author).
