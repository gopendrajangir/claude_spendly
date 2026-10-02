# Spec: Edit Expense

## Overview

Let a signed-in user correct an expense they already recorded. Today `/expenses/<id>/edit` is a stub that returns the text "Edit expense — coming in Step 8", and nothing links to it. This step makes it a real page: the profile page's Recent expenses table gets an "Edit" link on every row, which opens a form pre-filled with that expense's amount, category, date and description. A valid submit updates that one row and returns to the profile with a confirmation; an invalid one re-renders the form with the error. Users can only ever edit their own expenses. Following `CLAUDE.md`, the new SQL lives in `database/db.py` helpers rather than in the route, and missing or foreign expenses end in `abort(404)`.

(`CLAUDE.md`'s route table calls edit "Step 8"; this spec follows the project's spec numbering, where it is step 07.)

## Depends on

- Step 01 — Database setup (`expenses` table, `CATEGORIES`, `get_db()` with foreign keys on)
- Step 03 — Login and logout (`login_required`, session, flash messages)
- Step 04 — Profile page design (the Recent expenses table that gets the Edit links)
- Step 06 — Add expense (the form fields, `_validate_expense_form`, the CSRF helpers and the messages are reused)

## Routes

- `GET /expenses/<int:id>/edit` — render the edit form pre-filled from the expense — logged-in, owner only (exists as a stub, becomes real)
- `POST /expenses/<int:id>/edit` — validate, update the expense, flash "Expense updated." and redirect to `/profile`; on a validation error re-render the form with the error and the entered values — logged-in, owner only

Rules shared by both methods:

- Signed-out visitors are redirected to `/login` with the existing "Please sign in to view that page." message.
- If the expense does not exist, or belongs to another user, respond with `abort(404)`. Do not use 403, so the response does not reveal that another user's expense exists. A non-integer id never reaches the view (Flask's `<int:id>` converter returns 404).
- The `/expenses/<int:id>/delete` stub is unchanged.

## Database changes

No schema changes: no new columns, no `updated_at`, no constraints. `created_at`, `id` and `user_id` are never modified.

Two new helpers in `database/db.py` (per `CLAUDE.md`: DB logic lives there, not in routes), both using `closing(get_db())` and parameterised SQL:

- `get_expense(expense_id, user_id)` — returns the row (`sqlite3.Row` with `id, user_id, amount, category, date, description`) only if it exists **and** belongs to `user_id`, otherwise `None`. The query filters on both `id = ?` and `user_id = ?`.
- `update_expense(expense_id, user_id, amount, category, date, description)` — runs `UPDATE expenses SET amount = ?, category = ?, date = ?, description = ? WHERE id = ? AND user_id = ?`, commits, and returns the number of rows changed (`0` if the expense is missing or not the user's).

## Form fields

The same four fields, controls and rules as the add form (see `06-add-expense.md`): `amount`, `category` (from `CATEGORIES`), `date`, `description`, plus the hidden `csrf_token`. The differences:

- The form is pre-filled from the stored expense on GET: amount as a two-decimal string (`450.5` is shown as `450.50`), the category selected, the date as stored, and an empty string for a `NULL` description.
- After a failed POST the entered values are kept (not the stored ones).
- The submit button reads "Save changes", the page title and heading read "Edit expense", and the form posts to this expense's edit URL. "Cancel" links to `/profile`.

## Validation and messages

Reuse `_validate_expense_form` unchanged for the amount, category, date-format and description rules, in the same order, with the same messages, shown one at a time in the `.auth-error` box, with HTTP 200 and the entered values kept.

**One change: the future-date rule.** A date after today is rejected with `Date cannot be in the future.` **unless it equals the expense's currently stored date.** This keeps legacy rows editable: `seed_db()` creates demo expenses dated later in the current month, so a user must be able to fix the description or amount of such a row without being forced to change its date. Changing the date to a different future date is still rejected. Implement this by giving the validator an optional `existing_date` argument that defaults to `None` (the add view passes nothing, so add behaviour is unchanged).

**CSRF:** exactly as in the add form. A missing or mismatched token returns HTTP 400 with `Your session expired. Please try again.`, the expense is not changed, and the form is re-rendered with the entered values. The token check runs after the 404 check and before field validation.

**Ownership:** the update always uses `session["user_id"]` in the `WHERE` clause. A `user_id` or `id` field posted in the form is ignored.

## Templates

- **Create:**
  - `templates/edit_expense.html` — extends `base.html`; title "Edit expense — Spendly"; the same auth-page layout as the add page (`.auth-section`, `.auth-container`, `.auth-header`, `.auth-card`, `.auth-error`, `.auth-switch`); includes the shared form partial
  - `templates/_expense_form.html` — the form fields (hidden csrf input, amount, category select built from `categories`, date, description, submit button), parameterised by `form_action`, `submit_label` and the field values
- **Modify:**
  - `templates/add_expense.html` — use the shared partial instead of its own copy of the fields. Its rendered behaviour must not change.
  - `templates/profile.html` — add an "Actions" column header and, in every Recent expenses row, an "Edit" link to `url_for('edit_expense', id=e.id)`. Do not give the new cell the `num` class.

## Files to change

- `app.py` — import `abort`, `get_expense` and `update_expense`; make `edit_expense()` a real GET/POST view with `@login_required`; give `_validate_expense_form` the optional `existing_date` argument
- `database/db.py` — add `get_expense` and `update_expense`
- `templates/add_expense.html`, `templates/profile.html` — as above
- `static/css/style.css` — a small style for the per-row action link, using CSS variables only
- `tests/test_06-add-expense.py` — the step 06 regression test that expects the edit stub text ("coming in Step") no longer holds and must be updated to expect only the delete stub placeholder; no other behaviour in that file changes

## Files to create

- `templates/edit_expense.html`
- `templates/_expense_form.html`

## New dependencies

No new dependencies.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only; no f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (not touched in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html` (partials are included, not extended)
- `CLAUDE.md`: the new SQL goes in `database/db.py` only, never inline in `app.py`; the edit view must contain no `execute(` calls
- `CLAUDE.md`: use `abort(404)` for a missing or foreign expense, not a returned string; the stub text must be gone
- `CLAUDE.md`: every link uses `url_for()`; no hardcoded URLs in templates
- Keep the view to one responsibility: load the expense, check CSRF, validate, call `update_expense`, flash, redirect
- Reuse `csrf_token()` and `_csrf_valid()`; do not duplicate them
- Do not strip the CSRF token; strip amount, date and description as in the add form
- Let Jinja auto-escape everything (including the pre-filled description); no `|safe`; no JavaScript
- Do not implement or change the delete stub, and do not refactor the existing inline SQL in `register()`, `login()`, `profile()` or `add_expense()` in this step
- `CLAUDE.md` itself is out of date (its route table and "db.py is empty" note); updating it is not part of this step

## Definition of done

- [ ] Signed out, `GET` and `POST /expenses/<id>/edit` redirect to `/login`, the login page shows "Please sign in to view that page.", and no expense changes
- [ ] Signed in, `GET /expenses/<id>/edit` for one of your own expenses returns 200 with the form pre-filled: the amount with two decimals (`450.50`), the stored category selected, the stored date, the description (empty for `NULL`), a hidden CSRF token, the heading "Edit expense", a "Save changes" button, and a "Cancel" link to `/profile`
- [ ] `GET` for an expense that belongs to another user, for an id that does not exist, and for `/expenses/abc/edit` each return 404
- [ ] A valid `POST` redirects to `/profile`, shows "Expense updated.", and updates the amount, category, date and description of exactly that row; `id`, `user_id` and `created_at` are unchanged and no other expense changes
- [ ] A `POST` to another user's or a nonexistent expense with an otherwise valid form and token returns 404 and changes nothing
- [ ] Every amount, category, date and description case rejected by the add form is rejected here with the same message, HTTP 200, the entered values kept in the form, and the stored expense unchanged; only the first error is shown when several fields are invalid
- [ ] A new future date (tomorrow) is rejected with `Date cannot be in the future.`; a future date equal to the expense's stored date is accepted; today and past dates are accepted
- [ ] A blank or whitespace-only description is stored as `NULL` and shows as "—" in the profile table
- [ ] A `POST` without a `csrf_token`, or with a wrong, non-ASCII or other-session token, returns 400 with `Your session expired. Please try again.` and changes nothing; the token from a normal `GET` of the form is accepted
- [ ] A `user_id` or `id` value posted in the form is ignored: the row keeps its owner and id
- [ ] A description such as `<script>alert(1)</script>` appears escaped in the pre-filled form and on the profile page
- [ ] The profile page's Recent expenses table has an "Actions" column with an "Edit" link on every row pointing at `/expenses/<that row's id>/edit`; the empty state has no Edit links
- [ ] After editing an expense's amount or category, the profile's Total spent, Expenses count, category breakdown and Recent expenses list reflect the change
- [ ] `get_expense(id, user_id)` returns `None` for another user's expense, and `update_expense(...)` returns 0 and changes nothing when the expense is not the user's
- [ ] The add form behaves exactly as before: all step 06 tests pass, except that the stub-regression test is updated as described above
- [ ] `/expenses/<id>/delete` still returns its placeholder text, and `/`, `/login`, `/register`, `/terms`, `/privacy`, `/profile` and `/analytics` still work
- [ ] A grep of `app.py` finds no string-formatted SQL and no `execute(` in the edit view, and no new hex colour codes are added to the CSS
