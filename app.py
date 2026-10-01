import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.db import get_db, init_db, seed_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to view that page.")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.template_filter("inr")
def inr(value):
    return f"₹{(value or 0):,.2f}"


@app.template_filter("display_date")
def display_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (TypeError, ValueError):
        return value


@app.template_filter("month_year")
def month_year(value):
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%B %Y")
    except (TypeError, ValueError):
        return value


def _parse_filter_date(raw):
    """Return (YYYY-MM-DD string or None, is_valid) for a query-string date."""
    value = (raw or "").strip()
    if not value:
        return None, True
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None, False
    # strptime accepts "2026-1-5"; only the canonical zero-padded form is valid
    if parsed.isoformat() != value:
        return None, False
    return value, True


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


def _valid_email(email):
    local, sep, domain = email.partition("@")
    if not sep or not local or "@" in domain:
        return False
    host, dot, tld = domain.rpartition(".")
    return bool(dot and host and tld)


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    def fail(message):
        return render_template("register.html", error=message, name=name, email=email)

    if not name or not email or not password:
        return fail("Please fill in all fields.")
    if not _valid_email(email):
        return fail("Please enter a valid email address.")
    if len(password) < 8:
        return fail("Password must be at least 8 characters.")

    already = "An account with this email already exists."
    with closing(get_db()) as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            return fail(already)
        try:
            conn.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            return fail(already)

    flash("Account created. Please sign in.")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    def fail(message):
        return render_template("login.html", error=message, email=email)

    if not email or not password:
        return fail("Please fill in all fields.")

    with closing(get_db()) as conn:
        user = conn.execute(
            "SELECT id, name, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return fail("Invalid email or password.")

    session.clear()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.")
    return redirect(url_for("landing"))


@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    today = date.today()
    month_start = today.replace(day=1)
    next_month = date(today.year + (today.month == 12), today.month % 12 + 1, 1)

    date_from, from_ok = _parse_filter_date(request.args.get("from"))
    date_to, to_ok = _parse_filter_date(request.args.get("to"))
    filter_error = None
    if not (from_ok and to_ok):
        filter_error = "Enter dates in YYYY-MM-DD format."
    elif date_from and date_to and date_from > date_to:
        filter_error = "Start date must be on or before end date."
    if filter_error:
        date_from = date_to = None

    # Fixed SQL fragments only; the dates themselves are bound as parameters
    where = "WHERE user_id = ?"
    params = [user_id]
    if date_from:
        where += " AND date >= ?"
        params.append(date_from)
    if date_to:
        where += " AND date <= ?"
        params.append(date_to)

    with closing(get_db()) as conn:
        user = conn.execute(
            "SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None:
            session.clear()
            return redirect(url_for("login"))

        has_any = conn.execute(
            "SELECT COUNT(*) FROM expenses WHERE user_id = ?", (user_id,)
        ).fetchone()[0] > 0
        total, count = conn.execute(
            "SELECT COALESCE(SUM(amount), 0), COUNT(*) FROM expenses " + where,
            params,
        ).fetchone()
        month_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM expenses "
            "WHERE user_id = ? AND date >= ? AND date < ?",
            (user_id, month_start.isoformat(), next_month.isoformat()),
        ).fetchone()[0]
        category_rows = conn.execute(
            "SELECT category, SUM(amount) AS total FROM expenses "
            + where + " GROUP BY category ORDER BY total DESC",
            params,
        ).fetchall()
        recent = conn.execute(
            "SELECT id, date, category, description, amount FROM expenses "
            + where + " ORDER BY date DESC, id DESC LIMIT 10",
            params,
        ).fetchall()

    categories = [
        {
            "category": row["category"],
            "total": row["total"],
            "pct": round(row["total"] / total * 100) if total else 0,
        }
        for row in category_rows
    ]

    last_month_end = month_start - timedelta(days=1)
    preset_ranges = [
        ("Last 7 days", today - timedelta(days=6), today),
        ("Last 30 days", today - timedelta(days=29), today),
        ("This month", month_start, today),
        ("Last month", last_month_end.replace(day=1), last_month_end),
        ("All time", None, None),
    ]
    presets = []
    for label, start, end in preset_ranges:
        start_iso = start.isoformat() if start else None
        end_iso = end.isoformat() if end else None
        url = (
            url_for("profile", **{"from": start_iso, "to": end_iso})
            if start
            else url_for("profile")
        )
        presets.append(
            {
                "label": label,
                "url": url,
                "active": (start_iso, end_iso) == (date_from, date_to),
            }
        )

    if date_from and date_to:
        caption = f"Showing {display_date(date_from)} – {display_date(date_to)}"
    elif date_from:
        caption = f"Showing from {display_date(date_from)}"
    elif date_to:
        caption = f"Showing up to {display_date(date_to)}"
    else:
        caption = "Showing all time"

    return render_template(
        "profile.html",
        user=user,
        total=total,
        count=count,
        month_total=month_total,
        top=categories[0] if categories else None,
        categories=categories,
        recent=recent,
        has_any=has_any,
        filter_error=filter_error,
        from_value=date_from or "",
        to_value=date_to or "",
        presets=presets,
        caption=caption,
    )


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
