# Spec: Login and Logout

## Overview

Make sign-in and sign-out work. `GET /login` only renders a form today, its `POST /login` goes nowhere, and `/logout` is a placeholder string. This step adds a POST handler that checks the submitted email and password against the `users` table and, on success, stores the user in a Flask session; it also turns `/logout` into a real sign-out. It introduces sessions to the app (a `secret_key`), makes the navbar reflect whether someone is signed in, and adds the flash-message plumbing that registration was missing, so a new user sees a confirmation after signing up. Everything that follows (profile, adding and editing expenses) depends on knowing who the current user is.

## Depends on

- Step 01 — Database setup (`users` table, `get_db()`)
- Step 02 — Registration (users can be created with werkzeug-hashed passwords)

## Routes

- `GET /login` — render the sign-in form; if already signed in, redirect to `/profile` — public (exists, behaviour extended)
- `POST /login` — validate credentials, start a session, redirect to `/profile` on success; re-render the form with an error on failure — public
- `GET /logout` — clear the session, flash a "signed out" message, redirect to `/` — public (exists as a placeholder, becomes real)
- `GET /register` — if already signed in, redirect to `/profile` — public (exists, small change)
- `POST /register` — on success, now also flash "Account created. Please sign in." before redirecting to `/login` — public (exists, small change)

`/profile` is still a placeholder ("coming in Step 4"). It is the redirect target after login and is not protected in this step.

## Database changes

No database changes. Login only reads `id`, `name`, `email` and `password_hash` from the existing `users` table (verified against `database/db.py`).

## Templates

- **Create:** none
- **Modify:**
  - `templates/login.html` — keep the submitted `email` in the form after a failed attempt (`value="{{ email or '' }}"`); never pre-fill the password. The `{% if error %}` / `.auth-error` block already exists.
  - `templates/base.html`
    - Navbar: when `session.user_id` is set, show the user's name and a "Sign out" link (to `url_for('logout')`) instead of "Sign in" / "Get started"; otherwise keep the current links.
    - Render flashed messages (`get_flashed_messages(with_categories=true)`) in a block just above `<main>`'s content, styled by a new CSS class.
  - `static/css/style.css` — add a small `.flash` style (and a variant per category if used) built only from existing CSS variables.

## Files to change

- `app.py` — set `app.secret_key`, import `session`, `flash`, `check_password_hash`; extend `login()` to GET/POST; implement `logout()`; add already-signed-in redirects to `login()` and `register()`; add the success flash to `register()`
- `templates/login.html` — preserve email on error
- `templates/base.html` — signed-in navbar and flash rendering
- `static/css/style.css` — flash message styles

## Files to create

None.

## New dependencies

No new dependencies. Uses Flask's built-in `session` and `flash`, and `werkzeug.security.check_password_hash` (already installed).

## Rules for implementation

- No SQLAlchemy or ORMs
- Parameterised queries only — no f-strings or `%` formatting in SQL
- Passwords hashed with werkzeug; verify with `check_password_hash`, never compare plain text, and never store or log the password
- Use CSS variables — never hardcode hex values
- All templates extend `base.html`
- Use `get_db()` from `database/db.py` and close the connection (`contextlib.closing` or `try/finally`)
- `app.secret_key` must come from the `SECRET_KEY` environment variable, with a clearly named development fallback (e.g. `"dev-only-change-me"`) so the app still starts locally. Do not commit a real secret. `.env` is already gitignored.
- Normalise the submitted email (`.strip().lower()`) before the lookup, to match how registration stores it. Do not strip the password.
- On a failed login show one generic message, "Invalid email or password.", for both an unknown email and a wrong password, so the form does not reveal which emails are registered. Re-render with HTTP 200 and keep the typed email.
- Reject empty email or password with the same generic error (or a "Please fill in all fields." message), without querying the database.
- On success call `session.clear()` first, then set `session["user_id"]` (int) and `session["user_name"]`, so no stale session data survives a login. Store only those two values, never the password hash.
- `logout()` must call `session.clear()`, flash a short confirmation, and redirect to `url_for("landing")`.
- Do not protect any other route and do not add a `login_required` decorator in this step; that arrives with the profile and expense steps.
- Do not change the other placeholder routes (`/profile`, `/expenses/...`) or any route not listed above.

## Definition of done

- [ ] `GET /login` renders the form with status 200
- [ ] Signing in as `demo@spendly.com` / `demo123` redirects to `/profile` and sets a session cookie
- [ ] Signing in with a user created via `/register` works, including when the email is typed with different capitalisation or surrounding spaces
- [ ] A wrong password and an unknown email both re-render `/login` with the same "Invalid email or password." message in the `.auth-error` box, with status 200 and no session cookie set
- [ ] After a failed attempt the email field keeps what was typed and the password field is empty
- [ ] Empty email or password does not cause a 500 and does not sign anyone in
- [ ] While signed in, the navbar shows the user's name and a "Sign out" link, and no "Sign in" / "Get started" links, on `/`, `/terms` and `/privacy`
- [ ] While signed out, the navbar looks exactly as it does today
- [ ] Clicking "Sign out" returns to `/`, shows a "signed out" flash message, and the navbar is back to its signed-out state; reloading shows the message is gone
- [ ] After `/logout`, visiting `/login` shows the form again (session really cleared)
- [ ] Registering a new account now redirects to `/login` with an "Account created. Please sign in." flash message visible
- [ ] While signed in, visiting `/login` or `/register` redirects to `/profile`
- [ ] The app starts without `SECRET_KEY` set (fallback used) and with it set
- [ ] Flash and navbar styles use only CSS variables; a grep of the new CSS finds no hex colour codes
- [ ] A grep of `app.py` finds no string-formatted SQL
- [ ] `/register` validation from step 02 still behaves as before (duplicate email, short password, invalid email)
