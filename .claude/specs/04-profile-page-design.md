# Spec: Profile Page Design

## Overview

Replace the `/profile` placeholder ("Profile page — coming in Step 4") with a real page for the signed-in user. It is where people land after login, so it needs to answer "who am I signed in as, and where is my money going?" at a glance: an account header (name, email, member-since date), a row of summary figures, a spending breakdown by category, and the most recent expenses. It is read-only; adding, editing and deleting expenses arrive in later steps. This step also introduces a reusable `login_required` guard, which the expense steps will reuse, and makes `/profile` the first route that requires a signed-in user.

## Depends on

- Step 01 — Database setup (`users` and `expenses` tables, seeded demo data)
- Step 02 — Registration
- Step 03 — Login and logout (session with `user_id` / `user_name`, flash messages, signed-in navbar)

## Routes

- `GET /profile` — render the signed-in user's profile page — logged-in (exists as a placeholder, becomes real). A signed-out visitor is redirected to `/login` with a flash message.

No other new routes. The expense placeholder routes are unchanged.

## Database changes

No database changes. The page only reads from the existing tables (verified against `database/db.py`):

- `users`: `id`, `name`, `email`, `created_at`
- `expenses`: `user_id`, `amount`, `category`, `date` (`YYYY-MM-DD`), `description`

Every query on `expenses` must be filtered by the signed-in user's id.

## Page design

All of this lives in `templates/profile.html`, in this order from top to bottom:

1. **Account card** — a circular avatar showing the user's first initial (uppercase), then the name as the heading and the email beneath it in muted text, then "Member since <Month YYYY>" derived from `created_at`. An "Add expense" button (`btn-primary`) on the right links to `url_for('add_expense')`.
2. **Summary row** — four cards in one row (2×2 on narrow screens):
   - **Total spent** — sum of all the user's expenses, in ₹
   - **Expenses** — count of the user's expenses
   - **This month** — sum for the current calendar month, in ₹
   - **Top category** — the category with the highest total, with its amount; "—" if there are no expenses
3. **Spending by category** — one row per category that has expenses, ordered by total descending. Each row shows the category name, a horizontal bar whose width is that category's share of the total, the amount in ₹ and the percentage. The bar style should echo the landing page's `mock-bar` look (same track height, rounded ends, accent colours).
4. **Recent expenses** — a table of the 10 most recent expenses, newest first (by `date`, then `id`), with columns Date, Category, Description, Amount (right-aligned). A missing description shows "—".
5. **Empty state** — if the user has no expenses, replace sections 3 and 4 with one centred card: "No expenses yet" with a short line and a link to add one. The account card and summary row still render, with zero values.

Amounts are shown as `₹` plus a thousands separator and two decimals (e.g. `₹12,450.00`). Dates in the table are shown as `05 Oct 2026`. Both are done by Jinja filters registered in `app.py`, not by string-building inside the template.

## Templates

- **Create:** `templates/profile.html` — extends `base.html`, implements the layout above
- **Modify:** `templates/base.html` — when signed in, make the user's name in the navbar a link to `url_for('profile')` (it is currently plain text). Nothing else in `base.html` changes.

## Files to change

- `app.py` — add a `login_required` decorator; apply it to `profile()`; implement `profile()` (queries and render); register the `inr` and date display filters
- `templates/base.html` — navbar name becomes a link to the profile
- `static/css/style.css` — profile page styles (account card, avatar, stat cards, category bars, expense table, empty state), including responsive rules

## Files to create

- `templates/profile.html`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only — no f-strings or `%` formatting in SQL. Date-range filters for "this month" must pass the boundary dates as parameters (e.g. first day of this month and first day of next month as `YYYY-MM-DD` strings).
- Passwords hashed with werkzeug (not touched in this step; never select or expose `password_hash` on this page)
- Use CSS variables — never hardcode hex values. The only colours allowed in new CSS are the existing variables in `static/css/style.css` (`--accent`, `--accent-light`, `--accent-2`, `--paper-card`, `--border`, etc.).
- All templates extend `base.html`
- Use `get_db()` from `database/db.py` and close the connection (`contextlib.closing` or `try/finally`)
- `login_required` is a small decorator (using `functools.wraps`) that checks `"user_id" in session`; if absent it flashes "Please sign in to view that page." and redirects to `url_for("login")`. Apply it only to `/profile` in this step; do not change the other routes.
- Load the user row by `session["user_id"]`. If no row exists (for example the user was deleted while their cookie lived on), call `session.clear()` and redirect to `/login` rather than raising an error.
- Only ever read the signed-in user's data: every `expenses` query has `WHERE user_id = ?` bound to `session["user_id"]`. The page takes no user id from the URL or form.
- Do all totals, counts and the category grouping in SQL (`SUM`, `COUNT`, `GROUP BY`), not by looping over every row in Python.
- Let Jinja auto-escape user-supplied text (name, email, description). Never use `|safe` on it.
- Compute bar widths and percentages in the view (or a filter), guard against dividing by zero when the total is 0, and round percentages to whole numbers.
- Layout must work on narrow screens: reuse the existing breakpoints (900px and 600px) so cards stack and the table scrolls horizontally inside its own container instead of breaking the page.
- Do not add JavaScript for this page.

## Definition of done

- [ ] Signed out, `GET /profile` redirects to `/login` and the login page shows the "Please sign in to view that page." message
- [ ] After signing in as `demo@spendly.com` / `demo123` you land on a profile page showing name "Demo User", email `demo@spendly.com` and "Member since" with the month and year the user was created
- [ ] The avatar shows the letter "D"
- [ ] Total spent, Expenses count, This month and Top category match the demo user's data (check the numbers against a direct query on `expense_tracker.db`)
- [ ] "This month" counts only expenses dated in the current calendar month, and an expense dated in another month is excluded (verify with an extra row or a user with older expenses, e.g. from `/seed-expense`)
- [ ] The category section lists only categories that have expenses, ordered by total descending, with bar widths proportional to each share and percentages that are whole numbers
- [ ] Recent expenses shows at most 10 rows, newest first, with dates like `05 Oct 2026` and amounts like `₹1,800.00` right-aligned; a null description shows "—"
- [ ] A user with no expenses (for example one newly created via `/register`) sees zeros in the summary, "—" for Top category, and the "No expenses yet" card instead of the category and table sections, with no error
- [ ] Signing in as a second user shows only that user's expenses, never the demo user's
- [ ] If the user's row is deleted while signed in, reloading `/profile` redirects to `/login` with no 500 error
- [ ] The "Add expense" button and the empty-state link go to `/expenses/add` (the placeholder text still appears, which is expected for now)
- [ ] The navbar name is a link to `/profile` when signed in; the signed-out navbar is unchanged
- [ ] A name or description containing `<script>` is displayed as text and does not execute
- [ ] At 400px width the summary cards, category rows and table do not overflow the page, and the table scrolls inside its container
- [ ] `/`, `/login`, `/register`, `/terms`, `/privacy` and the login and logout flows from step 03 still work
- [ ] A grep of `app.py` finds no string-formatted SQL, and a grep of the new CSS finds no hex colour codes
