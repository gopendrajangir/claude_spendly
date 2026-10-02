"""Tests for step 06: add expense (GET/POST /expenses/add).

Expectations come from .claude/specs/06-add-expense.md.
"""
import html as html_lib
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.db import CATEGORIES

PASSWORD = "password123"
URL = "/expenses/add"

ERR_AMOUNT = "Enter a valid amount."
ERR_ZERO = "Amount must be greater than 0."
ERR_DECIMALS = "Amount can have at most 2 decimal places."
ERR_LARGE = "Amount is too large."
ERR_CATEGORY = "Choose a valid category."
ERR_DATE = "Enter a valid date (YYYY-MM-DD)."
ERR_FUTURE = "Date cannot be in the future."
ERR_DESC = "Description must be 200 characters or fewer."
ERR_CSRF = "Your session expired. Please try again."


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def add_user(db_path, name="Asha", email="asha@example.com"):
    with closing(_connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(PASSWORD)),
        )
        conn.commit()
        return cur.lastrowid


def insert_expense(db_path, user_id, day, amount, category="Food", description=None):
    if isinstance(day, date):
        day = day.isoformat()
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, day, description),
        )
        conn.commit()


def all_expenses(db_path):
    with closing(_connect(db_path)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM expenses ORDER BY id")]


def login(client, email="asha@example.com"):
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code == 302, "login should redirect on success"


def form_token(client):
    """GET the form and read the hidden csrf_token from the page."""
    resp = client.get(URL)
    assert resp.status_code == 200, "form page should load"
    page = resp.get_data(as_text=True)
    m = re.search(r'<input[^>]*name="csrf_token"[^>]*>', page)
    assert m, "form should contain a hidden csrf_token input"
    assert 'type="hidden"' in m.group(0), "csrf_token input must be hidden"
    v = re.search(r'value="([^"]*)"', m.group(0))
    assert v and v.group(1), "csrf_token input must carry a non-empty value"
    return html_lib.unescape(v.group(1))


def valid_fields(**overrides):
    data = {
        "amount": "450.50",
        "category": CATEGORIES[0],
        "date": date.today().isoformat(),
        "description": "Lunch",
    }
    data.update(overrides)
    return data


def submit(client, token=None, **overrides):
    """POST the form with a genuine token (fetched via GET) unless overridden.

    Pass a field set to None to omit it from the POST body.
    """
    data = valid_fields(**overrides)
    data = {k: v for k, v in data.items() if v is not None}
    if token is None:
        token = form_token(client)
    data["csrf_token"] = token
    return client.post(URL, data=data)


def error_text(resp):
    page = resp.get_data(as_text=True)
    m = re.search(r'<div class="auth-error">(.*?)</div>', page, re.S)
    return html_lib.unescape(m.group(1).strip()) if m else None


def input_value(page, name):
    m = re.search(r'<input[^>]*name="%s"[^>]*>' % re.escape(name), page)
    assert m, f"input {name!r} not found"
    v = re.search(r'value="([^"]*)"', m.group(0))
    return html_lib.unescape(v.group(1)) if v else ""


def selected_category(page):
    m = re.search(r'<option value="([^"]*)"\s+selected', page)
    return m.group(1) if m else None


def stat(page, label):
    m = re.search(
        re.escape(label) + r"</span>\s*<span class=\"profile-stat-value\">(.*?)</span>",
        page,
        re.S,
    )
    assert m, f"stat card {label!r} not found"
    return html_lib.unescape(m.group(1).strip())


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def user_id(db_path):
    return add_user(db_path)


@pytest.fixture
def auth_client(client, user_id):
    login(client)
    return client


# --------------------------------------------------------------------------- #
# Auth guard                                                                   #
# --------------------------------------------------------------------------- #

class TestAuthGuard:
    def test_get_signed_out_redirects_to_login(self, client):
        resp = client.get(URL)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")

    def test_login_page_shows_flash_after_redirect(self, client):
        resp = client.get(URL, follow_redirects=True)
        assert resp.status_code == 200
        assert "Please sign in to view that page." in resp.get_data(as_text=True)

    def test_post_signed_out_redirects_and_creates_no_row(self, client, db_path, user_id):
        resp = client.post(URL, data=dict(valid_fields(), csrf_token="whatever"))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")
        assert all_expenses(db_path) == [], "no row may be created when signed out"

    def test_post_signed_out_shows_flash_on_login_page(self, client, user_id):
        resp = client.post(
            URL, data=dict(valid_fields(), csrf_token="x"), follow_redirects=True
        )
        assert "Please sign in to view that page." in resp.get_data(as_text=True)


# --------------------------------------------------------------------------- #
# GET form                                                                     #
# --------------------------------------------------------------------------- #

class TestForm:
    def test_get_returns_200_with_title_and_button(self, auth_client):
        resp = auth_client.get(URL)
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Add expense" in page
        assert 'class="btn-submit"' in page
        assert "coming in Step" not in page, "placeholder text must be gone"

    def test_date_defaults_to_today(self, auth_client):
        page = auth_client.get(URL).get_data(as_text=True)
        assert 'type="date"' in page
        assert input_value(page, "date") == date.today().isoformat()

    def test_category_select_has_blank_then_all_categories_in_order(self, auth_client):
        page = auth_client.get(URL).get_data(as_text=True)
        select = re.search(r"<select[^>]*>(.*?)</select>", page, re.S)
        assert select, "a <select> is expected"
        options = re.findall(r'<option value="([^"]*)"', select.group(1))
        assert options[0] == "", "first option must be the blank choice"
        assert "Select a category" in select.group(1)
        assert options[1:] == list(CATEGORIES)
        assert len(CATEGORIES) == 7

    def test_amount_and_description_controls(self, auth_client):
        page = auth_client.get(URL).get_data(as_text=True)
        assert re.search(r'<input[^>]*name="amount"[^>]*inputmode="decimal"', page)
        assert re.search(r'<input[^>]*name="description"[^>]*maxlength="200"', page)

    def test_form_contains_hidden_csrf_token(self, auth_client):
        assert len(form_token(auth_client)) > 10

    def test_token_is_stable_within_a_session(self, auth_client):
        assert form_token(auth_client) == form_token(auth_client)

    def test_get_creates_no_row(self, auth_client, db_path):
        auth_client.get(URL)
        assert all_expenses(db_path) == []

    def test_cancel_link_points_to_profile(self, auth_client):
        page = auth_client.get(URL).get_data(as_text=True)
        assert re.search(r'<a href="/profile"[^>]*>\s*Cancel\s*</a>', page)

    def test_cancel_target_works_and_creates_no_row(self, auth_client, db_path):
        resp = auth_client.get("/profile")
        assert resp.status_code == 200
        assert all_expenses(db_path) == []


# --------------------------------------------------------------------------- #
# Happy path and DB side effects                                               #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_valid_submit_redirects_to_profile(self, auth_client):
        resp = submit(auth_client)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")

    def test_valid_submit_inserts_exactly_one_row(self, auth_client, db_path, user_id):
        today = date.today().isoformat()
        submit(auth_client, description="Lunch at cafe")
        rows = all_expenses(db_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["user_id"] == user_id
        assert row["amount"] == 450.5
        assert row["category"] == CATEGORIES[0]
        assert row["date"] == today
        assert row["description"] == "Lunch at cafe"
        assert row["created_at"], "created_at should be defaulted"

    def test_flash_message_on_profile(self, auth_client):
        resp = submit(auth_client)
        page = auth_client.get(resp.headers["Location"]).get_data(as_text=True)
        assert "Expense added." in page

    def test_follow_redirects_lands_on_profile_with_flash(self, auth_client):
        data = dict(valid_fields(), csrf_token=form_token(auth_client))
        resp = auth_client.post(URL, data=data, follow_redirects=True)
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert "Expense added." in page
        assert "Recent expenses" in page

    def test_token_from_page_load_is_accepted_repeatedly(self, auth_client, db_path):
        token = form_token(auth_client)
        submit(auth_client, token=token)
        submit(auth_client, token=token)
        assert len(all_expenses(db_path)) == 2

    def test_ignores_posted_user_id(self, auth_client, db_path, user_id):
        other = add_user(db_path, "Ben", "ben@example.com")
        data = dict(valid_fields(), csrf_token=form_token(auth_client), user_id=str(other))
        resp = auth_client.post(URL, data=data)
        assert resp.status_code == 302
        rows = all_expenses(db_path)
        assert len(rows) == 1
        assert rows[0]["user_id"] == user_id, "row must belong to the signed-in user"

    def test_other_users_rows_untouched(self, auth_client, db_path):
        other = add_user(db_path, "Ben", "ben@example.com")
        insert_expense(db_path, other, date.today(), 99.0, "Bills", "theirs")
        submit(auth_client)
        rows = all_expenses(db_path)
        assert len(rows) == 2
        assert [r["description"] for r in rows if r["user_id"] == other] == ["theirs"]

    @pytest.mark.parametrize("category", list(CATEGORIES))
    def test_every_category_is_accepted(self, auth_client, db_path, category):
        resp = submit(auth_client, category=category)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["category"] == category

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("450", 450.0),
            ("450.5", 450.5),
            ("450.50", 450.5),
            ("0.01", 0.01),
            ("0.1", 0.1),
            ("10.10", 10.1),
            ("  12.5  ", 12.5),
            ("9999999.99", 9999999.99),
            ("9999999", 9999999.0),
        ],
    )
    def test_accepted_amounts_are_stored_as_floats(self, auth_client, db_path, raw, expected):
        resp = submit(auth_client, amount=raw)
        assert resp.status_code == 302, f"{raw!r} should be accepted"
        rows = all_expenses(db_path)
        assert len(rows) == 1
        assert rows[0]["amount"] == pytest.approx(expected)
        assert isinstance(rows[0]["amount"], float)

    @pytest.mark.parametrize(
        "offset_days", [0, -1, -30, -400], ids=["today", "yesterday", "month_ago", "past_year"]
    )
    def test_today_and_past_dates_accepted(self, auth_client, db_path, offset_days):
        day = (date.today() + timedelta(days=offset_days)).isoformat()
        resp = submit(auth_client, date=day)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["date"] == day

    def test_leap_day_accepted(self, auth_client, db_path):
        resp = submit(auth_client, date="2024-02-29")
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["date"] == "2024-02-29"

    def test_date_with_surrounding_whitespace_is_stripped(self, auth_client, db_path):
        today = date.today().isoformat()
        resp = submit(auth_client, date=f"  {today}  ")
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["date"] == today

    def test_sql_injection_in_description_stored_as_text(self, auth_client, db_path):
        evil = "x'); DROP TABLE expenses; --"
        resp = submit(auth_client, description=evil)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] == evil

    def test_sql_injection_in_category_rejected(self, auth_client, db_path):
        resp = submit(auth_client, category="Food'; DROP TABLE expenses; --")
        assert resp.status_code == 200
        assert error_text(resp) == ERR_CATEGORY
        assert all_expenses(db_path) == []


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #

class TestAmountValidation:
    @pytest.mark.parametrize(
        "raw, message",
        [
            ("", ERR_AMOUNT),
            ("   ", ERR_AMOUNT),
            ("abc", ERR_AMOUNT),
            ("-5", ERR_AMOUNT),
            ("+5", ERR_AMOUNT),
            ("1,000", ERR_AMOUNT),
            ("1 000", ERR_AMOUNT),
            ("1e3", ERR_AMOUNT),
            ("1E3", ERR_AMOUNT),
            ("nan", ERR_AMOUNT),
            ("NaN", ERR_AMOUNT),
            ("inf", ERR_AMOUNT),
            ("Infinity", ERR_AMOUNT),
            ("12abc", ERR_AMOUNT),
            ("1.2.3", ERR_AMOUNT),
            ("0", ERR_ZERO),
            ("0.00", ERR_ZERO),
            ("10.999", ERR_DECIMALS),
            ("12.345", ERR_DECIMALS),
            ("0.001", ERR_DECIMALS),
            ("10000000", ERR_LARGE),
            ("10000000.00", ERR_LARGE),
            ("9999999.995", ERR_DECIMALS),
        ],
    )
    def test_rejected_amount_shows_message_and_creates_no_row(
        self, auth_client, db_path, raw, message
    ):
        resp = submit(auth_client, amount=raw)
        assert resp.status_code == 200, f"{raw!r} must re-render the form with 200"
        assert error_text(resp) == message, f"wrong message for {raw!r}"
        assert all_expenses(db_path) == []

    def test_missing_amount_field_is_invalid(self, auth_client, db_path):
        resp = submit(auth_client, amount=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_AMOUNT
        assert all_expenses(db_path) == []

    def test_very_long_digit_string_is_too_large(self, auth_client, db_path):
        resp = submit(auth_client, amount="9" * 60)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_LARGE
        assert all_expenses(db_path) == []


class TestCategoryValidation:
    @pytest.mark.parametrize(
        "value",
        ["", "Groceries", "food", "FOOD", " Food", "Food ", "Food,Bills", "<b>Food</b>"],
    )
    def test_invalid_category_rejected(self, auth_client, db_path, value):
        resp = submit(auth_client, category=value)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_CATEGORY
        assert all_expenses(db_path) == []

    def test_missing_category_field_rejected(self, auth_client, db_path):
        resp = submit(auth_client, category=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_CATEGORY
        assert all_expenses(db_path) == []


class TestDateValidation:
    @pytest.mark.parametrize(
        "value",
        ["", "   ", "2026-1-5", "2026-01-5", "2026-02-30", "2026-13-01", "abc",
         "05-01-2026", "2026/01/05", "20260105", "2026-01-05T10:00", "2023-02-29"],
    )
    def test_invalid_date_rejected(self, auth_client, db_path, value):
        resp = submit(auth_client, date=value)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DATE, f"{value!r} should be an invalid date"
        assert all_expenses(db_path) == []

    def test_missing_date_field_rejected(self, auth_client, db_path):
        resp = submit(auth_client, date=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DATE
        assert all_expenses(db_path) == []

    @pytest.mark.parametrize("days_ahead", [1, 2, 365])
    def test_future_date_rejected(self, auth_client, db_path, days_ahead):
        day = (date.today() + timedelta(days=days_ahead)).isoformat()
        resp = submit(auth_client, date=day)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert all_expenses(db_path) == []


class TestDescriptionValidation:
    def test_exactly_200_characters_accepted(self, auth_client, db_path):
        text = "a" * 200
        resp = submit(auth_client, description=text)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] == text

    def test_201_characters_rejected(self, auth_client, db_path):
        resp = submit(auth_client, description="a" * 201)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DESC
        assert all_expenses(db_path) == []

    def test_non_ascii_counted_in_characters_not_bytes(self, auth_client, db_path):
        text = "é" * 200
        resp = submit(auth_client, description=text)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] == text

    def test_200_characters_plus_padding_is_trimmed_and_accepted(self, auth_client, db_path):
        text = "b" * 200
        resp = submit(auth_client, description=f"   {text}   ")
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] == text

    def test_201_characters_after_trimming_rejected(self, auth_client, db_path):
        resp = submit(auth_client, description="  " + "c" * 201 + "  ")
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DESC
        assert all_expenses(db_path) == []

    @pytest.mark.parametrize("value", ["", " ", "   ", "\t  "])
    def test_blank_description_stored_as_null(self, auth_client, db_path, value):
        resp = submit(auth_client, description=value)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] is None

    def test_missing_description_field_stored_as_null(self, auth_client, db_path):
        resp = submit(auth_client, description=None)
        assert resp.status_code == 302
        assert all_expenses(db_path)[0]["description"] is None

    def test_description_is_trimmed(self, auth_client, db_path):
        submit(auth_client, description="  tea  ")
        assert all_expenses(db_path)[0]["description"] == "tea"


class TestValidationOrderAndEcho:
    @pytest.mark.parametrize(
        "overrides, message",
        [
            # everything invalid: amount wins
            (dict(amount="abc", category="Nope", date="bad", description="x" * 201), ERR_AMOUNT),
            # amount ok-format but zero beats decimals/category/date/description
            (dict(amount="0", category="Nope", date="bad", description="x" * 201), ERR_ZERO),
            (dict(amount="0.000", category="Nope"), ERR_ZERO),
            # decimals beat too large
            (dict(amount="10000000.001", category="Nope", date="bad"), ERR_DECIMALS),
            # too large beats category
            (dict(amount="10000000", category="Nope", date="bad"), ERR_LARGE),
            # category beats date and description
            (dict(category="Nope", date="bad", description="x" * 201), ERR_CATEGORY),
            # invalid date beats description
            (dict(date="bad", description="x" * 201), ERR_DATE),
            (dict(date=None, description="x" * 201), ERR_DATE),
            # future date beats description
            (
                dict(
                    date=(date.today() + timedelta(days=1)).isoformat(),
                    description="x" * 201,
                ),
                ERR_FUTURE,
            ),
            # category beats future date
            (
                dict(
                    category="Nope",
                    date=(date.today() + timedelta(days=1)).isoformat(),
                ),
                ERR_CATEGORY,
            ),
        ],
    )
    def test_only_first_error_in_documented_order_shown(
        self, auth_client, db_path, overrides, message
    ):
        resp = submit(auth_client, **overrides)
        assert resp.status_code == 200
        assert error_text(resp) == message
        page = resp.get_data(as_text=True)
        assert len(re.findall(r'class="auth-error"', page)) == 1, "only one error box"
        assert all_expenses(db_path) == []

    def test_error_is_in_auth_error_box(self, auth_client):
        resp = submit(auth_client, amount="abc")
        assert '<div class="auth-error">' in resp.get_data(as_text=True)

    def test_entered_values_are_kept_after_error(self, auth_client, db_path):
        day = (date.today() - timedelta(days=3)).isoformat()
        resp = submit(
            auth_client, amount="12.345", category="Bills", date=day, description="kept me"
        )
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DECIMALS
        assert input_value(page, "amount") == "12.345"
        assert selected_category(page) == "Bills"
        assert input_value(page, "date") == day
        assert input_value(page, "description") == "kept me"
        assert all_expenses(db_path) == []

    def test_invalid_entered_values_are_echoed_verbatim(self, auth_client):
        resp = submit(auth_client, amount="abc", date="2026-02-30")
        page = resp.get_data(as_text=True)
        assert input_value(page, "amount") == "abc"
        assert input_value(page, "date") == "2026-02-30"

    def test_token_on_rerendered_form_is_accepted(self, auth_client, db_path):
        resp = submit(auth_client, amount="abc")
        page = resp.get_data(as_text=True)
        token = input_value(page, "csrf_token")
        assert token, "re-rendered form must carry a token"
        resp = submit(auth_client, token=token)
        assert resp.status_code == 302
        assert len(all_expenses(db_path)) == 1

    def test_description_escaped_in_rerendered_form(self, auth_client):
        payload = "<script>alert(1)</script>"
        resp = submit(auth_client, amount="abc", description=payload)
        page = resp.get_data(as_text=True)
        assert payload not in page, "raw script tag must not be echoed"
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page

    def test_attribute_breakout_in_description_is_escaped(self, auth_client):
        payload = '"><img src=x onerror=alert(1)>'
        resp = submit(auth_client, amount="abc", description=payload)
        page = resp.get_data(as_text=True)
        assert "<img src=x" not in page
        assert input_value(page, "description") == payload


# --------------------------------------------------------------------------- #
# CSRF                                                                         #
# --------------------------------------------------------------------------- #

class TestCsrf:
    def _assert_rejected(self, resp, db_path):
        assert resp.status_code == 400
        assert error_text(resp) == ERR_CSRF
        assert "Your session expired. Please try again." in resp.get_data(as_text=True)
        assert all_expenses(db_path) == [], "no row may be created on CSRF failure"

    def test_missing_token_rejected(self, auth_client, db_path):
        auth_client.get(URL)  # session has a token, but we do not send it
        resp = auth_client.post(URL, data=valid_fields())
        self._assert_rejected(resp, db_path)

    def test_empty_token_rejected(self, auth_client, db_path):
        auth_client.get(URL)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token=""))
        self._assert_rejected(resp, db_path)

    def test_wrong_token_rejected(self, auth_client, db_path):
        auth_client.get(URL)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token="not-the-token"))
        self._assert_rejected(resp, db_path)

    def test_non_ascii_token_rejected_with_400_not_500(self, auth_client, db_path):
        auth_client.get(URL)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token="tökén-☃"))
        self._assert_rejected(resp, db_path)

    def test_token_with_surrounding_whitespace_rejected(self, auth_client, db_path):
        token = form_token(auth_client)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token=token + " "))
        self._assert_rejected(resp, db_path)

    def test_truncated_token_rejected(self, auth_client, db_path):
        token = form_token(auth_client)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token=token[:-1]))
        self._assert_rejected(resp, db_path)

    def test_post_without_ever_loading_form_rejected(self, auth_client, db_path):
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token="guess"))
        self._assert_rejected(resp, db_path)

    def test_post_without_loading_form_and_without_token_rejected(self, auth_client, db_path):
        resp = auth_client.post(URL, data=valid_fields())
        self._assert_rejected(resp, db_path)

    def test_other_sessions_token_rejected(self, app, auth_client, db_path):
        add_user(db_path, "Ben", "ben@example.com")
        other_client = app.test_client()
        login(other_client, "ben@example.com")
        other_token = form_token(other_client)
        own_token = form_token(auth_client)
        assert other_token != own_token, "tokens must differ between sessions"
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token=other_token))
        self._assert_rejected(resp, db_path)

    def test_csrf_checked_before_field_validation(self, auth_client, db_path):
        auth_client.get(URL)
        resp = auth_client.post(
            URL,
            data=dict(valid_fields(amount="abc", category="Nope"), csrf_token="wrong"),
        )
        self._assert_rejected(resp, db_path)

    def test_form_is_rerendered_on_csrf_failure(self, auth_client):
        auth_client.get(URL)
        resp = auth_client.post(URL, data=dict(valid_fields(), csrf_token="wrong"))
        page = resp.get_data(as_text=True)
        assert 'name="csrf_token"' in page
        assert 'name="amount"' in page

    def test_signed_out_post_with_valid_looking_token_still_redirects(self, client, db_path, user_id):
        resp = client.post(URL, data=dict(valid_fields(), csrf_token="abc"))
        assert resp.status_code == 302, "auth guard takes priority over CSRF"
        assert all_expenses(db_path) == []


# --------------------------------------------------------------------------- #
# Profile page interactions                                                    #
# --------------------------------------------------------------------------- #

class TestProfileIntegration:
    def test_new_expense_appears_in_recent_list_and_totals(self, auth_client):
        submit(auth_client, amount="450.50", category="Food", description="Team lunch")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "Team lunch" in page
        assert "₹450.50" in page
        assert stat(page, "Total spent") == "₹450.50"
        assert stat(page, "Expenses") == "1"
        assert stat(page, "Top category") == "Food"

    def test_totals_and_breakdown_include_new_expense_alongside_existing(
        self, auth_client, db_path, user_id
    ):
        insert_expense(db_path, user_id, date.today(), 100.0, "Bills", "rent")
        submit(auth_client, amount="300", category="Transport", description="cab")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert stat(page, "Total spent") == "₹400.00"
        assert stat(page, "Expenses") == "2"
        assert stat(page, "Top category") == "Transport"
        breakdown = re.search(r"Spending by category(.*?)Recent expenses", page, re.S)
        assert breakdown, "category breakdown expected"
        assert "Transport" in breakdown.group(1) and "₹300.00" in breakdown.group(1)
        assert "Bills" in breakdown.group(1)

    def test_this_month_total_includes_expense_dated_today(self, auth_client):
        submit(auth_client, amount="25")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert stat(page, "This month") == "₹25.00"

    def test_expense_inside_active_filter_is_shown(self, auth_client):
        day = date.today() - timedelta(days=6)
        submit(auth_client, date=day.isoformat(), description="inside-range")
        resp = auth_client.get(
            "/profile",
            query_string={
                "from": (day - timedelta(days=1)).isoformat(),
                "to": (day + timedelta(days=1)).isoformat(),
            },
        )
        page = resp.get_data(as_text=True)
        assert "inside-range" in page
        assert stat(page, "Expenses") == "1"

    def test_expense_outside_active_filter_is_hidden(self, auth_client):
        today = date.today()
        submit(auth_client, date=today.isoformat(), description="outside-range")
        resp = auth_client.get(
            "/profile",
            query_string={
                "from": (today - timedelta(days=10)).isoformat(),
                "to": (today - timedelta(days=5)).isoformat(),
            },
        )
        page = resp.get_data(as_text=True)
        assert "outside-range" not in page
        assert stat(page, "Expenses") == "0"

    def test_null_description_shows_dash_in_table(self, auth_client, db_path):
        submit(auth_client, description="   ")
        assert all_expenses(db_path)[0]["description"] is None
        page = auth_client.get("/profile").get_data(as_text=True)
        row = re.search(r"<tbody>(.*?)</tbody>", page, re.S).group(1)
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
        assert cells[2].strip() == "—"

    def test_script_description_stored_as_text_and_escaped_on_profile(
        self, auth_client, db_path
    ):
        payload = "<script>alert(1)</script>"
        submit(auth_client, description=payload)
        assert all_expenses(db_path)[0]["description"] == payload
        page = auth_client.get("/profile").get_data(as_text=True)
        assert payload not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page

    def test_flash_shown_only_once(self, auth_client):
        submit(auth_client)
        first = auth_client.get("/profile").get_data(as_text=True)
        second = auth_client.get("/profile").get_data(as_text=True)
        assert "Expense added." in first
        assert "Expense added." not in second

    def test_other_users_new_expense_not_visible(self, app, auth_client, db_path):
        add_user(db_path, "Ben", "ben@example.com")
        other_client = app.test_client()
        login(other_client, "ben@example.com")
        submit(other_client, description="bens-secret")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "bens-secret" not in page
        assert stat(page, "Expenses") == "0"

    def test_add_expense_button_links_to_form(self, auth_client, db_path, user_id):
        insert_expense(db_path, user_id, date.today(), 10.0)
        page = auth_client.get("/profile").get_data(as_text=True)
        assert re.search(r'<a href="/expenses/add"[^>]*>\s*Add expense\s*</a>', page)

    def test_empty_state_link_links_to_form(self, auth_client):
        page = auth_client.get("/profile").get_data(as_text=True)
        assert re.search(r'<a href="/expenses/add"[^>]*>\s*Add your first expense\s*</a>', page)

    def test_profile_links_open_the_form(self, auth_client):
        resp = auth_client.get("/expenses/add")
        assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Regression: untouched routes                                                 #
# --------------------------------------------------------------------------- #

class TestRegressions:
    @pytest.mark.parametrize("path", ["/", "/login", "/register", "/terms", "/privacy"])
    def test_public_pages_still_work(self, client, path):
        assert client.get(path).status_code == 200

    def test_profile_still_works(self, auth_client):
        assert auth_client.get("/profile").status_code == 200

    @pytest.mark.parametrize("path", ["/expenses/1/edit", "/expenses/1/delete"])
    def test_edit_and_delete_placeholders_unchanged(self, auth_client, path):
        resp = auth_client.get(path)
        assert resp.status_code == 200
        assert "coming in Step" in resp.get_data(as_text=True)

    def test_login_and_register_forms_have_no_csrf_requirement(self, client, user_id):
        resp = client.post("/login", data={"email": "asha@example.com", "password": PASSWORD})
        assert resp.status_code == 302
        resp = client.post(
            "/register",
            data={"name": "Cy", "email": "cy@example.com", "password": "longenough1"},
        )
        assert resp.status_code == 302

    def test_app_source_has_no_string_formatted_insert(self):
        source = (Path(__file__).resolve().parent.parent / "app.py").read_text()
        pattern = re.compile(
            r"""\bf["'][^"'\n]*\b(INSERT|SELECT|UPDATE|DELETE)\b|"""
            r"""\b(INSERT|SELECT|UPDATE|DELETE)\b[^\n]*["']\s*%\s*[(\w]""",
            re.I,
        )
        assert not pattern.search(source), "SQL must not be built with f-strings or %"

    def test_real_database_not_used(self, db_path):
        assert db_module.DB_PATH == db_path
        assert not db_path.endswith("expense_tracker.db")
