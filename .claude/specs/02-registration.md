# Spec: Registration

## Overview

Make the existing `/register` page functional. Today `GET /register` only renders `register.html`, and the form's `POST /register` goes nowhere. This step adds the POST handler: it validates the submitted name, email and password, hashes the password, inserts a new row into `users`, and sends the visitor to the login page. It is the first feature built on top of the data layer from step 01, and it produces the user accounts that login (next step) and every later feature depend on.

## Depends on

- Step 01 — Database setup (`users` table, `get_db()`, `init_db()` called on startup)

## Routes

- `GET /register` — render the registration form — public (already exists, unchanged)
- `POST /register` — validate input, create the user, redirect to `/login` on success; re-render the form with an error on failure — public

Both are handled by the same `register()` view, which must declare `methods=["GET", "POST"]`.

## Database changes

No database changes. The existing `users` table already has everything needed: `name` (not null), `email` (unique, not null), `password_hash` (not null), `created_at` (defaults to `datetime('now')`). Verified against `database/db.py`.

## Templates

- **Create:** none
- **Modify:** `templates/register.html`
  - Keep the submitted `name` and `email` in the form after a failed submit (`value="{{ name or '' }}"` and `value="{{ email or '' }}"`). Never pre-fill the password field.
  - The `{% if error %}` block and `.auth-error` styling already exist; reuse them as-is.
  - No other markup changes.

## Files to change

- `app.py` — change the `/register` route to accept GET and POST, add the validation and insert logic, import `request`, `redirect`, `url_for`, and `sqlite3`
- `templates/register.html` — preserve `name` and `email` on error (see above)

## Files to create

None.

## New dependencies

No new dependencies. Uses `werkzeug.security.generate_password_hash` (already installed) and the standard library `sqlite3`.

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only — no f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug (`generate_password_hash`); never store or log the plain password
- Use CSS variables — never hardcode hex values (no new CSS is expected for this step; if any is added it must use the variables in `static/css/style.css`)
- All templates extend `base.html`
- Use `get_db()` from `database/db.py` for every database access, and close the connection (`contextlib.closing` or `try/finally`)
- Read form fields with `request.form.get(...)` and `.strip()` the name and email; do not strip the password
- Normalise the email to lowercase before checking and storing it, so `A@x.com` and `a@x.com` cannot both register
- Validation, checked in this order, each failure re-rendering `register.html` with a clear `error` message and HTTP 200:
  1. name, email and password are all non-empty
  2. email looks like an email (contains `@` with text on both sides and a `.` in the domain; a simple check is enough, no regex library)
  3. password is at least 8 characters (matches the form placeholder "Min. 8 characters")
  4. email is not already registered
- The unique-email check must not rely on a pre-check alone: also catch `sqlite3.IntegrityError` on insert and show the same "already registered" error, so two simultaneous sign-ups cannot cause a 500
- On success, redirect to `url_for("login")`. Do not log the user in; sessions are introduced in the login step. Do not add `flash()` or a `secret_key` in this step.
- Do not change the placeholder routes (`/logout`, `/profile`, `/expenses/...`) or any other route

## Definition of done

- [ ] `GET /register` still renders the form and returns 200
- [ ] Submitting a valid name, new email and 8+ character password redirects to `/login` and creates exactly one new row in `users`
- [ ] The new row's `password_hash` is a werkzeug hash (e.g. starts with `scrypt:` or `pbkdf2:`), is not the plain password, and `check_password_hash(hash, password)` is true
- [ ] The new row's email is stored in lowercase, and `created_at` is filled in
- [ ] Registering the same email again (including with different capitalisation) re-renders the form with an "already registered" error and creates no second row
- [ ] Registering with the seeded `demo@spendly.com` shows the "already registered" error
- [ ] A password shorter than 8 characters shows an error and creates no row
- [ ] An empty or whitespace-only name, or an invalid email such as `abc` or `a@b`, shows an error and creates no row
- [ ] After any failed submit, the name and email fields keep what the user typed and the password field is empty
- [ ] Errors appear in the existing `.auth-error` box on the register page; no 500 error occurs for any input above
- [ ] `/`, `/login`, `/terms` and `/privacy` still return 200
- [ ] A grep of `app.py` finds no string-formatted SQL
