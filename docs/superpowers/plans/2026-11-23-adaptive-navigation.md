# Adaptive navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One navigation that becomes a bottom bar on the phone and a left sidebar on wide screens, ready to
receive career sections (Jobs, Study, Projects, Profile) with one line each, without changing the visual identity.

**Architecture:** Sections are declared once in `today/nav.py` and injected into every template by a Jinja
context processor. `_nav.html` replaces `_tabs.html`. CSS switches layout at `min-width: 900px`. A
`_split.html` list+detail layout is added for later features.

**Tech Stack:** FastAPI, Jinja2, HTMX, plain CSS (tokens in `docs/design.md`).

**Spec:** design approved in chat on 2026-11-23 (recorded in the PR description):
phone = bottom bar `HOJE · CALENDÁRIO · ANOTAÇÕES · MAIS`, capture bar above it, `MAIS` hidden while there is
no career section; desktop ≥ 900px = fixed left sidebar, routine group, rule, career group; content gets a
max reading width; list+detail layout ready but unused; no new colors, fonts or light theme.

## Global Constraints

- Only tokens from `docs/design.md`; no radius, no shadow, no emoji. Touch targets ≥ 44px.
- Breakpoint exactly `@media (min-width: 900px)`.
- Order of routine sections: Today `/`, Calendar `/calendar`, Notes `/notes` (bottom bar order is the
  approved one; replaces the current Today · Notes · Calendar).
- Bottom bar respects `env(safe-area-inset-bottom)` (installed iPhone PWA).
- i18n: every label through `t()`, pt and en.

## Review Focus

- iPhone with home indicator: bar must not sit under it → assert `safe-area-inset-bottom` in `.nav` rule (Task 2).
- Capture bar must not be covered by the bottom bar → assert `.capture` bottom offset uses `--nav-h` (Task 2).
- Login page must not show navigation → test in Task 1.
- Keyboard users: active link keeps `aria-current="page"` in both layouts → Task 1.
- Desktop content must not stretch edge to edge → assert `max-width` on `.board` inside the media query (Task 2).

---

### Task 1: Section registry and `_nav.html`

**Files:**
- Create: `src/today/nav.py`, `src/today/templates/_nav.html`, `tests/test_nav.py`
- Modify: `src/today/app.py:50` (add context processor), `src/today/i18n.py` (`more`, `nav_label`),
  `today.html`, `notes.html`, `calendar.html` (include `_nav.html`), `tests/test_notes.py:51` (new order)
- Delete: `src/today/templates/_tabs.html`

**Interfaces:**
- Produces: `Section(key: str, path: str, label_key: str, group: Literal["routine", "career"])`,
  `SECTIONS: list[Section]`, `nav_context(request) -> {"nav_routine": [...], "nav_career": [...]}`.
  Later features add one `Section(..., group="career")` to `SECTIONS`.

- [ ] **Step 1: Write failing tests** in `tests/test_nav.py`:
  - `test_nav_order_today_calendar_notes`: for `/`, `/calendar`, `/notes`, `href="/"` < `href="/calendar"` < `href="/notes"`.
  - `test_active_section_marked`: `/notes` contains `href="/notes" aria-current="page"`, and only one `aria-current="page"`.
  - `test_more_hidden_without_career_sections`: `'class="nav-more"' not in html`.
  - `test_more_lists_career_sections` (monkeypatch `SECTIONS` with a `career` entry `/jobs`): `nav-more` present and contains `href="/jobs"`.
  - `test_login_has_no_nav`: `/login` has no `class="nav"`.
- [ ] **Step 2:** `uv run pytest tests/test_nav.py -v` → FAIL.
- [ ] **Step 3:** Implement. `_nav.html` = one `<nav class="nav" aria-label="{{ t('nav_label') }}">` with routine links,
  then, if `nav_career`, a `<details class="nav-more"><summary>{{ t('more') }}</summary>` with career links
  (on desktop the same links render open, see Task 2). Update `test_notes.py::test_tabs_order...` to the new order.
- [ ] **Step 4:** `uv run pytest -q` → all pass; `uv run ruff check . && uv run ruff format --check .`.
- [ ] **Step 5:** Commit `feat: navegação declarada em uma lista de seções`.

### Task 2: Bottom bar on the phone, sidebar on desktop, split layout

**Files:**
- Modify: `src/today/static/app.css` (replace `.tabs` rules at ~325), `tests/test_css.py`,
  `src/today/i18n.py` (`back`: "VOLTAR" / "BACK")
- Create: `src/today/templates/_split.html`, test in `tests/test_nav.py`

**Interfaces:**
- Produces: `_split.html` with blocks `list` and `detail`, class `split`, and `split-has-detail` on the root
  when `detail` is not empty (phone shows only the detail then, with `← {{ t('back') }}` linking to the list).
  CSS custom property `--nav-h: 56px`.

- [ ] **Step 1: Write failing tests** in `tests/test_css.py`:
  - `test_nav_is_bottom_bar_on_phone`: `.nav` rule has `position: fixed`, `bottom: 0`, `env(safe-area-inset-bottom)`.
  - `test_capture_sits_above_nav`: `.capture` rule uses `var(--nav-h)` in its bottom offset.
  - `test_desktop_sidebar_and_reading_width`: CSS contains `@media (min-width: 900px)`; inside it `.nav` has
    `position: sticky` (or fixed) with `left: 0`, and `.board` has a `max-width`.
  - `test_split_template_renders_detail_flag` (in `test_nav.py`, render via `app.state.templates`): with detail
    → `split-has-detail`; without → absent.
- [ ] **Step 2:** `uv run pytest tests/test_css.py tests/test_nav.py -v` → FAIL.
- [ ] **Step 3:** Implement CSS with existing tokens only; pills/labels reuse current typography; `.nav-more`
  opens upward as a panel on the phone and is `open`-styled (list always visible) inside the media query.
- [ ] **Step 4:** `uv run pytest -q` → pass. Then run the app (`run` skill) and check at 390×844 and 1440×900:
  bar not under the home indicator, capture bar visible above it, sidebar on desktop, active state visible.
  Attach both screenshots to the PR.
- [ ] **Step 5:** Commit `feat: barra inferior no celular e menu lateral no computador`.

### Task 3: Docs

- [ ] Update `docs/design.md` Layout section (bottom bar, sidebar, breakpoint, split layout) and README slice
  list (slice 6: adaptive navigation). Add `docs/guide/07-adaptive-navigation.md` in the style of the other
  guides (concepts: mobile-first CSS, media queries, safe areas; Read next). Commit `docs: guia da navegação adaptável`.
