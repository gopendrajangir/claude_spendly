# Spec: Add Expense

## Overview

Let a signed-in user record an expense. Today `/expenses/add` is a placeholder that returns the text "Add expense — coming in Step 7", although the profile page already links to it from the "Add expense" button and the empty-state card. This step turns it into a real form: amount, category, date and an optional description. On a valid submit it inserts one row into `expenses` for the signed-in user and sends them back to their profile, where the new expense shows up in the totals, the category breakdown and the recent list. It is the first feature that lets users create their own data, so it is also the first logged-in POST in the app, and it adds basic CSRF protection for it.

## Depends on

- Step 01 — Database setup (`expenses` table, fixed `CATEGORIES` list in `database/db.py`)
- Step 03 — Login and logout (`login_required`, session, flash messages)
- Step 04 — Profile page design (where the user lands, and where the "Add expense" links come from)
- Step 05 — Date filter for profile page (a new expense must appear correctly under any filter whose range contains its date)

## Routes

- `GET /expenses/add` — render the add-expense form with the date defaulting to today — logged-in (exists as a placeholder, becomes real)
- `POST /expenses/add` — validate the form, insert the expense, flash "Expense added." and redirect to `/profile`; on a validation error re-render the form with the error and the entered values — logged-in

Signed-out visitors to either method are redirected to `/login` with the existing "Please sign in to view that page." message. The placeholder routes for edit and delete are unchanged.

## Database changes

No database changes. The existing `expenses` columns are used as they are (verified against `database/db.py`): `user_id`, `amount` (REAL), `category`, `date` (`YYYY-MM-DD`), `description` (nullable), `created_at` (defaults to now). The fixed category list stays a Python constant (`CATEGORIES` in `database/db.py`); there is no database-level constraint on it, so the route must validate it.

## Form fields

| Field | Control | Rules |
| --- | --- | --- |
| `amount` | text input with `inputmode="decimal"` | required; see "Amount" below |
| `category` | `<select>` with a blank "Select a category" first option and the 7 values of `CATEGORIES` in their defined order | required; must be exactly one of `CATEGORIES` |
| `date` | `<input type="date">`, pre-filled with today | required; real `YYYY-MM-DD` date; not in the future |
| `description` | text input, `maxlength="200"` | optional; trimmed; blank becomes `NULL`; at most 200 characters |
| `csrf_token` | hidden input | must match the session's token |

**Amount:** after stripping surrounding whitespace the value must be digits with an optional decimal part (for example `450`, `450.5`, `450.50`). Signs, commas, spaces inside the number, exponent notation (`1e3`) and words such as `nan` or `inf` are all invalid. Valid values must then be greater than 0, have at most 2 decimal places, and be at most `9999999.99`. Use `decimal.Decimal` to check the decimal places and range, and store the value as a float rounded to 2 places.

## Validation and messages

Checked in this order; the first failure is shown, using exactly these messages in the existing `.auth-error` box. A failed submit re-renders the form with HTTP 200, keeps the entered values (amount, category, date, description), and inserts nothing.

1. amount missing or not in the valid format → `Enter a valid amount.`
2. amount is 0 → `Amount must be greater than 0.`
3. amount has more than 2 decimal places → `Amount can have at most 2 decimal places.`
4. amount above 9999999.99 → `Amount is too large.`
5. category missing or not in `CATEGORIES` → `Choose a valid category.`
6. date missing or not a real canonical `YYYY-MM-DD` date → `Enter a valid date (YYYY-MM-DD).`
7. date after today → `Date cannot be in the future.`
8. description longer than 200 characters after trimming → `Description must be 200 characters or fewer.`

**CSRF:** if the submitted `csrf_token` is missing or does not match the session's token (compared in constant time), nothing is inserted and the form is re-rendered with the message `Your session expired. Please try again.` and HTTP 400. This check runs before the field validation.

**Ownership:** the expense is always stored for `session["user_id"]`. A `user_id` field sent in the form is ignored.

## Templates

- **Create:** `templates/add_expense.html` — extends `base.html`; reuses the auth page pattern (`.auth-section`, `.auth-container`, `.auth-card`, `.form-group`, `.form-input`, `.btn-submit`, `.auth-error`) with the title "Add expense", the form above, a submit button "Add expense", and a "Cancel" link back to `/profile`
- **Modify:** none (the profile page's existing links already point at this route)

## Files to change

- `app.py` — import `CATEGORIES`, `secrets`, `hmac` and `Decimal`; add a `csrf_token()` helper (stored in the session, exposed to templates); make `add_expense()` a real GET/POST view with `login_required`; reuse the existing `_parse_filter_date` helper to parse the date
- `static/css/style.css` — only if the `<select>` needs a small style to match `.form-input`; use existing variables

## Files to create

- `templates/add_expense.html`

## New dependencies

No new dependencies (`decimal`, `secrets` and `hmac` are standard library).

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only; no f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (not touched in this step)
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `get_db()` from `database/db.py` and close the connection (`contextlib.closing`)
- Insert exactly one row with `INSERT INTO expenses (user_id, amount, category, date, description) VALUES (?, ?, ?, ?, ?)`, bind every value, and commit
- Take the category list from `CATEGORIES`, not a second hardcoded copy in the route or template
- Strip the amount, date and description; do not strip anything from the CSRF token
- Generate the CSRF token with `secrets.token_urlsafe` once per session and keep it in the session; compare with `hmac.compare_digest`; include it as a hidden field in the form
- The token check applies to this form only in this step; the login and register forms are not changed
- Let Jinja auto-escape everything, including the description echoed back after an error; no `|safe`
- Do not touch the edit and delete placeholder routes or any other route
- Do not add JavaScript; the page works as a plain form

## Definition of done

- [ ] Signed out, `GET /expenses/add` and `POST /expenses/add` redirect to `/login`, the login page shows "Please sign in to view that page.", and no expense row is created
- [ ] Signed in, `GET /expenses/add` returns 200 and shows the form with the date field set to today, a blank category choice, and exactly the 7 categories from `CATEGORIES` in order
- [ ] Submitting amount `450.50`, a valid category, today's date and a description redirects to `/profile`, shows "Expense added." there, and adds exactly one row for the signed-in user with `amount = 450.5`, the chosen category, the date and the description
- [ ] The new expense appears in the profile's Recent expenses list, and Total spent, Expenses count and the category breakdown include it
- [ ] A new expense dated inside an active profile date filter shows up under that filter, and one dated outside it does not
- [ ] An amount with surrounding spaces (`  12.5  `) is accepted and stored as `12.5`; an amount of `12.345` is rejected
- [ ] Each of these amounts is rejected with the matching message and creates no row: empty, `abc`, `-5`, `1,000`, `1e3`, `nan`, `inf` (`Enter a valid amount.`); `0` and `0.00` (`Amount must be greater than 0.`); `10.999` (`Amount can have at most 2 decimal places.`); `10000000` (`Amount is too large.`)
- [ ] A missing category or one not in the list (for example `Groceries`) is rejected with `Choose a valid category.`
- [ ] A missing date, `2026-1-5`, `2026-02-30` and `abc` are rejected with `Enter a valid date (YYYY-MM-DD).`; tomorrow's date is rejected with `Date cannot be in the future.`; today's date and a past date are accepted
- [ ] A description of 201 characters is rejected with `Description must be 200 characters or fewer.`; one of exactly 200 characters is accepted
- [ ] A blank or whitespace-only description is stored as `NULL` and shows as "—" in the profile table
- [ ] After any validation error the response is 200, the error shows in the `.auth-error` box, the amount, category, date and description fields keep what was entered, and the database is unchanged
- [ ] When several fields are invalid, only the first error in the documented order is shown
- [ ] A POST without the `csrf_token`, or with a wrong one, returns 400 with `Your session expired. Please try again.` and creates no row; a normal page load of the form includes a token that is accepted on submit
- [ ] A `user_id` value posted in the form is ignored: the row is stored for the signed-in user
- [ ] A description such as `<script>alert(1)</script>` is stored as text and shown escaped on the profile page and in the re-rendered form after an error
- [ ] The profile page's "Add expense" button and the empty-state link both open the form
- [ ] "Cancel" returns to `/profile` without creating a row
- [ ] `/expenses/<id>/edit` and `/expenses/<id>/delete` still return their placeholder text, and `/`, `/login`, `/register`, `/terms`, `/privacy` and `/profile` still work
- [ ] A grep of `app.py` finds no string-formatted SQL, and no new hex colour codes are added to the CSS
