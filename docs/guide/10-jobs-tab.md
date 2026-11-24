# 10 · Jobs tab: triage the analyzed roles on a list + detail screen

## Concepts

- **Views as SQL fragments.** `analysis_repo.VIEWS` maps each tab filter (`review`, `interested`, `applied`,
  `later`, `dismissed`) to a `WHERE` clause over `jobs LEFT JOIN job_analyses`. Listing, counting and the
  route's validation all read the same dict, so a new view is one entry. `review` and `later` split the
  analyzed jobs by `json_extract(analysis_json, '$.timing')`: the analysis stays one JSON column, and SQLite
  still filters on a field inside it.
- **The first career section.** Adding `Section(key="jobs", group="career")` to `nav.SECTIONS` is all it took
  for MORE to appear on the phone and for the sidebar to grow a second group (guide 07).
- **Post/Redirect/Get as a workflow.** `POST /jobs/{id}/status` answers `303 See Other` pointing at the *next*
  job of the same view, computed before the status changes. Reloading never re-submits, the back button works,
  and triage becomes "read, press a button, read the next one".
- **Progressive enhancement with `hx-boost`.** The forms and links are plain HTML and work without
  JavaScript. `hx-boost="true"` on the page makes htmx fetch them in the background and swap the body, so
  triage does not flash a full reload; it follows the 303 like a browser would.
- **Template inheritance inside an include.** `jobs.html` extends `base.html` and includes `_jobs_split.html`,
  which extends `_split.html` and fills its `list` and `detail` blocks. The split layout decides, from whether
  `detail` rendered anything, if the phone shows the list or the detail.

## Pitfalls

- Marking twice: the second POST finds the job outside the view's list and redirects to the view's first
  job instead of failing; `test_mark_twice_is_harmless` pins it.
- Only the statuses the owner sets are accepted (`interested`, `dismissed`, `applied`); `new` and `analyzed`
  belong to the pipeline and answer 422.

## Exercises

1. Add a keyboard shortcut layer (j/k to move, i/d/a to mark) with a dozen lines of JavaScript, keeping the
   forms as the source of truth.
2. Add a `min_score` slider to `review` without a new route: one more query parameter and one more clause.

## Read next

*Designing Data-Intensive Applications* (Kleppmann), chapter 2, on JSON documents inside a relational store;
and the htmx essay "Hypermedia-Driven Applications" (htmx.org/essays) on why the server renders the workflow.
