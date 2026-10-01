# Spec: Date Filter for Profile Page

## Overview

Let the signed-in user narrow the profile page to a time period. The landing page promises "view your spending for any date range — last week, last month, or a custom period", and step 04 shipped a profile page that always shows all-time figures. This step adds a filter bar to `/profile`: a row of preset chips (Last 7 days, Last 30 days, This month, Last month, All time) and a custom From/To date form. The chosen period is carried in the URL query string (so it can be bookmarked and survives a reload), is validated on the server, and re-computes the total, count, top category, category breakdown and recent-expenses list for that period. No JavaScript is used; the filter is a plain GET form plus links.

## Depends on

- Step 01 — Database setup (`expenses.date` stored as `YYYY-MM-DD`)
- Step 03 — Login and logout (`login_required`, session)
- Step 04 — Profile page design (`/profile` view, `profile.html`, `inr` / `display_date` filters, `.profile-*` styles)

## Routes

No new routes. `GET /profile` (logged-in) now accepts two optional query parameters:

- `from` — start date, inclusive, format `YYYY-MM-DD`
- `to` — end date, inclusive, format `YYYY-MM-DD`

Either, both or neither may be given. With neither, the page behaves exactly as it does today (all time). Because `from` is a Python keyword, the view reads it with `request.args.get("from")`, and links to it are built with a dict unpack, for example `url_for("profile", **{"from": value})`.

## Database changes

No database changes. Filtering uses the existing `expenses.date` column with parameterised `>=` and `<=` comparisons on the `YYYY-MM-DD` text, which orders correctly as text (verified against `database/db.py`; no index change is required for this step).

## Behaviour

**What the filter affects** (all scoped to the signed-in user, as before):

- Total spent, Expenses count, Top category, the Spending by category panel (percentages are of the *filtered* total), and the Recent expenses table (the 10 newest expenses *within* the period).

**What it does not affect:**

- The "This month" stat card. It always shows the current calendar month regardless of the filter, because its label says so.
- The account card.

**Presets** (computed on the server from today's date; each is a link to `/profile` with explicit `from` / `to`, except All time, which has no parameters):

| Chip | from | to |
| --- | --- | --- |
| Last 7 days | today − 6 days | today |
| Last 30 days | today − 29 days | today |
| This month | first day of the current month | today |
| Last month | first day of the previous month | last day of the previous month |
| All time | (none) | (none) |

A chip is shown as active when the current `from` / `to` equal that preset's values exactly (All time is active when both are absent).

**Custom range:** two `<input type="date" name="from">` / `name="to"` fields in a `<form method="get" action="/profile">` with an "Apply" button, pre-filled with the current valid values. A "Clear" link next to it goes to plain `/profile`.

**Period caption:** under the filter bar, one line states the period in effect, using the existing `05 Oct 2026` date format:

- no filter: `Showing all time`
- both: `Showing 01 Sep 2026 – 30 Sep 2026`
- only `from`: `Showing from 01 Sep 2026`
- only `to`: `Showing up to 30 Sep 2026`

**Validation** (server side; the browser's date input is a convenience, not a guard):

- A value that is not a real `YYYY-MM-DD` date (wrong format, `2026-02-30`, text) is invalid. Show the message `Enter dates in YYYY-MM-DD format.` in the existing `.auth-error` style box in the filter bar and fall back to **no filter** (all time) for the whole request.
- If both are valid and `from` is after `to`, show `Start date must be on or before end date.` and fall back to no filter.
- Blank values (an empty `from=` from the form) count as absent, not invalid.
- Future dates are allowed. A range with no matching expenses is not an error.
- Responses stay HTTP 200, never 400 or 500, for any query-string input.

**Empty states:**

- The user has no expenses at all: unchanged from step 04 ("No expenses yet" card). The filter bar is not shown.
- The user has expenses, but none fall in the period: the summary row shows zeros and "—" for Top category, and instead of the category and table panels one card says `No expenses in this period` with a "Clear filter" link to `/profile`.

## Templates

- **Create:** none
- **Modify:** `templates/profile.html`
  - add the filter bar (chips, date form, Apply, Clear, error box, period caption) between the summary row and the category panel, shown only when the user has at least one expense
  - add the "No expenses in this period" card for the has-expenses-but-none-in-range case
  - everything else stays as in step 04

## Files to change

- `app.py` — extend `profile()`: parse and validate `from` / `to`, build the preset list, add the date conditions to the totals, category and recent queries, add a `has_any` check, pass the new values to the template
- `templates/profile.html` — as above
- `static/css/style.css` — filter bar styles, using `.profile-*` naming

## Files to create

None.

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only. The date conditions are built from a fixed set of SQL fragments (for example appending `AND date >= ?` and `AND date <= ?`) with the values bound as parameters; the query-string values themselves must never be concatenated or formatted into SQL.
- Passwords hashed with werkzeug (not touched in this step)
- Use CSS variables — never hardcode hex values; new colours may only use the existing variables (`--accent`, `--accent-light`, `--paper-card`, `--border`, `--danger`, etc.)
- All templates extend `base.html`
- Parse dates with `datetime.strptime(value, "%Y-%m-%d")` (or `date.fromisoformat`) inside a `try/except ValueError`; reject anything that does not round-trip to the same `YYYY-MM-DD` string, so values like `2026-1-5` are invalid rather than silently accepted
- Every expense query stays scoped with `WHERE user_id = ?` bound to `session["user_id"]`; the filter only adds conditions and never replaces that one
- Keep totals, counts and the category grouping in SQL, as in step 04
- Echo submitted dates back into the form only after validation, and let Jinja auto-escape everything; never use `|safe`
- The "This month" card keeps its current query unchanged
- Do not add JavaScript; preset chips are plain links and the custom range is a plain GET form
- Layout must stay usable at 400px: chips wrap onto multiple lines, and the date inputs and buttons stack instead of overflowing; reuse the existing 900px and 600px breakpoints
- Do not change any other route or the login flow

## Definition of done

- [ ] `GET /profile` with no parameters looks and behaves exactly as in step 04, with the period caption `Showing all time` and the "All time" chip active
- [ ] `GET /profile?from=2026-09-01&to=2026-09-30` shows only the signed-in user's expenses dated in September 2026 (both ends inclusive) in the table, and Total spent, Expenses count, Top category and category percentages match a direct SQL query for that range
- [ ] An expense dated exactly on `from` and one dated exactly on `to` are both included; one dated the day before `from` and one the day after `to` are excluded
- [ ] Only `from` given shows everything on or after it; only `to` given shows everything on or before it; the caption reads `Showing from …` / `Showing up to …` accordingly
- [ ] The category percentages are computed from the filtered total and the bar widths match them
- [ ] The Recent expenses table shows at most 10 rows from within the range, newest first
- [ ] The "This month" card shows the same value with and without a filter applied
- [ ] Each preset chip links to the right range for today's date, the matching chip is marked active, and clicking "Last month" shows only the previous calendar month's expenses
- [ ] Submitting the custom form (Apply) loads `/profile?from=…&to=…` with the same results as typing that URL, and the date inputs are pre-filled with the values in use
- [ ] "Clear" and the "All time" chip both go to `/profile` with no parameters
- [ ] `?from=abc`, `?to=2026-02-30` and `?from=2026-1-5` each return 200, show `Enter dates in YYYY-MM-DD format.` and display unfiltered (all-time) data
- [ ] `?from=2026-09-30&to=2026-09-01` returns 200, shows `Start date must be on or before end date.` and displays unfiltered data
- [ ] `?from=&to=` (blank values) returns 200 with no error and behaves as no filter
- [ ] A valid range with no matching expenses shows zeros, "—" for Top category and the `No expenses in this period` card with a working "Clear filter" link, and no error
- [ ] A user with no expenses at all still sees the step 04 "No expenses yet" card and no filter bar
- [ ] Signed in as a second user with the same `from` / `to`, only that user's expenses appear; another user's data never leaks through the filter
- [ ] A signed-out request to `/profile?from=2026-09-01` still redirects to `/login`
- [ ] A query string such as `?from=<script>alert(1)</script>` does not run script or appear unescaped in the page, and returns 200
- [ ] At 400px width the chips wrap, the date form stacks, and nothing overflows the page
- [ ] A grep of `app.py` finds no string-formatted SQL, and a grep of the new CSS finds no hex colour codes
- [ ] `/`, `/login`, `/register`, `/terms`, `/privacy` and the step 03 and 04 behaviours still work
