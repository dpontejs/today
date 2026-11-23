# 07 · Adaptive navigation: one list of sections, two layouts

## Concepts

- **Sections as data.** `today/nav.py` declares `SECTIONS`, a list of `Section(key, path, label_key, group)`.
  A Jinja context processor (`nav_context`) hands every template the routine and career groups, each entry
  paired with "is this the current page?", worked out from the request path. A new feature adds one line to
  the list; no template or route changes. Before, each route passed its own `active_tab` and the links were
  hard-coded in `_tabs.html`.
- **Mobile-first CSS.** The base rules describe the phone: `.nav` is `position: fixed; bottom: 0`. One
  `@media (min-width: 900px)` block turns the same markup into a left sidebar. Writing the small screen first
  means the phone never downloads rules it has to undo, and the desktop block reads as a list of differences.
- **A custom property as a switch.** `--nav-h` is 56px on the phone and `0px` inside the media query. The
  board's bottom padding and the capture bar's `bottom` are written once as `calc(var(--nav-h) + …)`, so they
  are right in both layouts without duplicated rules.
- **Safe areas.** With `viewport-fit=cover`, an installed iPhone PWA draws under the home indicator.
  `env(safe-area-inset-bottom)` is that strip's height (0 elsewhere); the bar adds it to its height and
  padding, so links stay tappable and the background still reaches the edge.
- **`<details>` for MORE.** Career sections fold into a `<details class="nav-more">`: no JavaScript, keyboard
  accessible. On desktop the summary is hidden and `::details-content` is made visible, so the same links
  read as an always-open group. While there is no career section, MORE is not rendered at all.
- **List + detail.** `_split.html` exposes `list` and `detail` blocks. It renders the detail into a variable
  first (`self.detail()`) to know whether there is one: if so, the root gets `split-has-detail` and the phone
  shows only the detail with a back link; desktop shows both columns.

## Exercises

1. Add a `Section(key="jobs", path="/jobs", label_key=…, group="career")` and a stub route. Check MAIS on a
   390px window and the second sidebar group at 1440px. Which test in `tests/test_nav.py` already covers it?
2. `is_active` uses a path prefix. Write a test for `/calendarx` (should not highlight Calendar) and decide
   whether the current code passes it.

## Read next

- *Responsive Web Design* (Ethan Marcotte), ch. 1 "Our Responsive Web" and ch. 4 "Media Queries": why one
  document with fluid rules beats separate mobile and desktop sites.
