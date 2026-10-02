"""Tests for step 07: edit expense (GET/POST /expenses/<id>/edit).

Expectations come from .claude/specs/07-edit-expense.md.
"""
import html as html_lib
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from database.db import CATEGORIES

PASSWORD = "password123"

ERR_AMOUNT = "Enter a valid amount."
ERR_ZERO = "Amount must be greater than 0."
ERR_DECIMALS = "Amount can have at most 2 decimal places."
ERR_LARGE = "Amount is too large."
ERR_CATEGORY = "Choose a valid category."
ERR_DATE = "Enter a valid date (YYYY-MM-DD)."
ERR_FUTURE = "Date cannot be in the future."
ERR_DESC = "Description must be 200 characters or fewer."
ERR_CSRF = "Your session expired. Please try again."

TODAY = date.today()
YESTERDAY = (TODAY - timedelta(days=1)).isoformat()
TOMORROW = (TODAY + timedelta(days=1)).isoformat()


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


def insert_expense(db_path, user_id, day, amount=450.5, category="Food",
                   description="Lunch"):
    if isinstance(day, date):
        day = day.isoformat()
    with closing(_connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, day, description),
        )
        conn.commit()
        return cur.lastrowid


def all_expenses(db_path):
    with closing(_connect(db_path)) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM expenses ORDER BY id")]


def get_row(db_path, expense_id):
    with closing(_connect(db_path)) as conn:
        r = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        return dict(r) if r else None


def login(client, email="asha@example.com"):
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code == 302, "login should redirect on success"


def edit_url(expense_id):
    return f"/expenses/{expense_id}/edit"


def form_token(client, expense_id):
    resp = client.get(edit_url(expense_id))
    assert resp.status_code == 200, "edit form should load"
    page = resp.get_data(as_text=True)
    m = re.search(r'<input[^>]*name="csrf_token"[^>]*>', page)
    assert m, "form should contain a hidden csrf_token input"
    assert 'type="hidden"' in m.group(0)
    v = re.search(r'value="([^"]*)"', m.group(0))
    assert v and v.group(1), "csrf token must have a value"
    return html_lib.unescape(v.group(1))


def new_fields(**overrides):
    data = {
        "amount": "99.25",
        "category": "Transport",
        "date": YESTERDAY,
        "description": "Updated",
    }
    data.update(overrides)
    return data


def submit(client, expense_id, token=None, **overrides):
    """POST an edit with a genuine token unless overridden.

    A field set to None is omitted from the body.
    """
    data = {k: v for k, v in new_fields(**overrides).items() if v is not None}
    if token is None:
        token = form_token(client, expense_id)
    data["csrf_token"] = token
    return client.post(edit_url(expense_id), data=data)


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
def other_user_id(db_path, user_id):
    return add_user(db_path, name="Ben", email="ben@example.com")


@pytest.fixture
def expense_id(db_path, user_id):
    return insert_expense(db_path, user_id, TODAY, 450.5, "Food", "Lunch")


@pytest.fixture
def auth_client(client, user_id):
    login(client)
    return client


# --------------------------------------------------------------------------- #
# Auth guard                                                                   #
# --------------------------------------------------------------------------- #

class TestAuthGuard:
    def test_get_signed_out_redirects_to_login(self, client, expense_id):
        resp = client.get(edit_url(expense_id))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")

    def test_login_page_shows_flash(self, client, expense_id):
        resp = client.get(edit_url(expense_id), follow_redirects=True)
        assert resp.status_code == 200
        assert "Please sign in to view that page." in resp.get_data(as_text=True)

    def test_post_signed_out_redirects_and_changes_nothing(self, client, db_path, expense_id):
        before = all_expenses(db_path)
        resp = client.post(edit_url(expense_id), data=dict(new_fields(), csrf_token="x"))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")
        assert all_expenses(db_path) == before

    def test_post_signed_out_shows_flash(self, client, expense_id):
        resp = client.post(
            edit_url(expense_id), data=dict(new_fields(), csrf_token="x"),
            follow_redirects=True,
        )
        assert "Please sign in to view that page." in resp.get_data(as_text=True)

    def test_signed_out_nonexistent_id_still_redirects(self, client, db_path, user_id):
        resp = client.get(edit_url(9999))
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/login")


# --------------------------------------------------------------------------- #
# GET form                                                                     #
# --------------------------------------------------------------------------- #

class TestForm:
    def test_get_prefills_stored_values(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, "2024-03-05", 450.5, "Health", "Pharmacy")
        resp = auth_client.get(edit_url(eid))
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert input_value(page, "amount") == "450.50"
        assert selected_category(page) == "Health"
        assert input_value(page, "date") == "2024-03-05"
        assert input_value(page, "description") == "Pharmacy"

    def test_integer_amount_shown_with_two_decimals(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 120, "Food", "x")
        page = auth_client.get(edit_url(eid)).get_data(as_text=True)
        assert input_value(page, "amount") == "120.00"

    def test_null_description_prefilled_empty(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 10, "Food", None)
        page = auth_client.get(edit_url(eid)).get_data(as_text=True)
        assert input_value(page, "description") == ""
        assert "None" not in page, "NULL must not render as 'None'"

    def test_headings_button_and_action(self, auth_client, expense_id):
        page = auth_client.get(edit_url(expense_id)).get_data(as_text=True)
        assert "Edit expense" in page
        assert "Save changes" in page
        assert "<title>Edit expense" in page
        assert f'action="{edit_url(expense_id)}"' in page
        assert "coming in Step" not in page, "stub text must be gone"

    def test_cancel_link_points_to_profile(self, auth_client, expense_id):
        page = auth_client.get(edit_url(expense_id)).get_data(as_text=True)
        assert re.search(r'<a href="/profile"[^>]*>\s*Cancel\s*</a>', page)

    def test_hidden_csrf_token_present(self, auth_client, expense_id):
        assert len(form_token(auth_client, expense_id)) > 10

    def test_category_select_options(self, auth_client, expense_id):
        page = auth_client.get(edit_url(expense_id)).get_data(as_text=True)
        select = re.search(r"<select[^>]*>(.*?)</select>", page, re.S)
        options = re.findall(r'<option value="([^"]*)"', select.group(1))
        assert options[1:] == list(CATEGORIES)

    def test_get_changes_nothing(self, auth_client, db_path, expense_id):
        before = all_expenses(db_path)
        auth_client.get(edit_url(expense_id))
        assert all_expenses(db_path) == before

    def test_xss_description_escaped_in_prefilled_form(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 5, "Food", "<script>alert(1)</script>")
        page = auth_client.get(edit_url(eid)).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert input_value(page, "description") == "<script>alert(1)</script>"

    def test_xss_description_escaped_on_profile(self, auth_client, db_path, user_id):
        insert_expense(db_path, user_id, YESTERDAY, 5, "Food", "<script>alert(1)</script>")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


# --------------------------------------------------------------------------- #
# Ownership / 404                                                              #
# --------------------------------------------------------------------------- #

class TestOwnershipAnd404:
    @pytest.fixture
    def foreign_id(self, db_path, other_user_id):
        return insert_expense(db_path, other_user_id, YESTERDAY, 70, "Bills", "Ben's")

    def test_get_foreign_expense_is_404(self, auth_client, foreign_id):
        assert auth_client.get(edit_url(foreign_id)).status_code == 404

    def test_get_nonexistent_is_404(self, auth_client, expense_id):
        assert auth_client.get(edit_url(99999)).status_code == 404

    @pytest.mark.parametrize("bad", ["abc", "1.5", "-1x", "1%20"])
    def test_get_non_integer_id_is_404(self, auth_client, bad):
        assert auth_client.get(f"/expenses/{bad}/edit").status_code == 404

    def test_post_foreign_expense_404_and_unchanged(self, auth_client, db_path, expense_id, foreign_id):
        token = form_token(auth_client, expense_id)
        before = get_row(db_path, foreign_id)
        resp = auth_client.post(
            edit_url(foreign_id), data=dict(new_fields(), csrf_token=token)
        )
        assert resp.status_code == 404
        assert get_row(db_path, foreign_id) == before

    def test_post_nonexistent_404_and_nothing_changes(self, auth_client, db_path, expense_id):
        token = form_token(auth_client, expense_id)
        before = all_expenses(db_path)
        resp = auth_client.post(edit_url(99999), data=dict(new_fields(), csrf_token=token))
        assert resp.status_code == 404
        assert all_expenses(db_path) == before

    def test_post_non_integer_id_is_404(self, auth_client, expense_id):
        token = form_token(auth_client, expense_id)
        resp = auth_client.post(
            "/expenses/abc/edit", data=dict(new_fields(), csrf_token=token)
        )
        assert resp.status_code == 404

    @pytest.mark.parametrize("target", ["foreign", "missing"])
    def test_404_comes_before_csrf_check(self, auth_client, db_path, foreign_id, target):
        eid = foreign_id if target == "foreign" else 99999
        resp = auth_client.post(
            edit_url(eid), data=dict(new_fields(), csrf_token="wrong-token")
        )
        assert resp.status_code == 404, "404 must win over the CSRF 400"

    def test_404_for_foreign_does_not_leak_existence(self, auth_client, foreign_id):
        # Same status as a nonexistent id: never 403.
        assert auth_client.get(edit_url(foreign_id)).status_code == auth_client.get(
            edit_url(99999)
        ).status_code == 404

    def test_posted_user_id_and_id_are_ignored(self, auth_client, db_path, user_id,
                                               other_user_id, expense_id):
        before = get_row(db_path, expense_id)
        token = form_token(auth_client, expense_id)
        data = dict(new_fields(), csrf_token=token, user_id=str(other_user_id), id="9999")
        resp = auth_client.post(edit_url(expense_id), data=data)
        assert resp.status_code == 302
        row = get_row(db_path, expense_id)
        assert row["user_id"] == user_id
        assert row["id"] == expense_id
        assert row["amount"] == 99.25
        assert row["created_at"] == before["created_at"]
        assert get_row(db_path, 9999) is None


# --------------------------------------------------------------------------- #
# Happy path / DB side effects                                                 #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_valid_post_redirects_to_profile(self, auth_client, expense_id):
        resp = submit(auth_client, expense_id)
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")

    def test_valid_post_updates_all_four_fields(self, auth_client, db_path, expense_id):
        submit(auth_client, expense_id, amount="99.25", category="Transport",
               date=YESTERDAY, description="Taxi")
        row = get_row(db_path, expense_id)
        assert row["amount"] == 99.25
        assert row["category"] == "Transport"
        assert row["date"] == YESTERDAY
        assert row["description"] == "Taxi"

    def test_id_user_and_created_at_unchanged(self, auth_client, db_path, user_id, expense_id):
        before = get_row(db_path, expense_id)
        submit(auth_client, expense_id)
        after = get_row(db_path, expense_id)
        assert after["id"] == before["id"]
        assert after["user_id"] == before["user_id"] == user_id
        assert after["created_at"] == before["created_at"]

    def test_no_other_expense_changes(self, auth_client, db_path, user_id, other_user_id, expense_id):
        mine = insert_expense(db_path, user_id, YESTERDAY, 11, "Bills", "mine other")
        theirs = insert_expense(db_path, other_user_id, YESTERDAY, 22, "Shopping", "theirs")
        b_mine, b_theirs = get_row(db_path, mine), get_row(db_path, theirs)
        submit(auth_client, expense_id)
        assert get_row(db_path, mine) == b_mine
        assert get_row(db_path, theirs) == b_theirs
        assert len(all_expenses(db_path)) == 3, "no row added or removed"

    def test_flash_message_on_profile(self, auth_client, expense_id):
        data = dict(new_fields(), csrf_token=form_token(auth_client, expense_id))
        resp = auth_client.post(edit_url(expense_id), data=data, follow_redirects=True)
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert "Expense updated." in page
        assert "Recent expenses" in page

    def test_amount_and_description_are_stripped(self, auth_client, db_path, expense_id):
        submit(auth_client, expense_id, amount="  12.5  ", description="  padded  ",
               date=f" {YESTERDAY} ")
        row = get_row(db_path, expense_id)
        assert row["amount"] == 12.5
        assert row["description"] == "padded"
        assert row["date"] == YESTERDAY

    @pytest.mark.parametrize("day", [TODAY.isoformat(), "2020-01-01", "2000-02-29"])
    def test_today_and_past_dates_accepted(self, auth_client, db_path, expense_id, day):
        resp = submit(auth_client, expense_id, date=day)
        assert resp.status_code == 302
        assert get_row(db_path, expense_id)["date"] == day

    @pytest.mark.parametrize("amount,expected", [
        ("0.01", 0.01), ("1", 1.0), ("100", 100.0), ("9999999.99", 9999999.99),
        ("10.5", 10.5), ("007.50", 7.5),
    ])
    def test_boundary_amounts_accepted(self, auth_client, db_path, expense_id, amount, expected):
        resp = submit(auth_client, expense_id, amount=amount)
        assert resp.status_code == 302
        assert get_row(db_path, expense_id)["amount"] == expected

    @pytest.mark.parametrize("category", list(CATEGORIES))
    def test_every_category_accepted(self, auth_client, db_path, expense_id, category):
        resp = submit(auth_client, expense_id, category=category)
        assert resp.status_code == 302
        assert get_row(db_path, expense_id)["category"] == category

    def test_description_of_200_chars_accepted(self, auth_client, db_path, expense_id):
        submit(auth_client, expense_id, description="a" * 200)
        assert get_row(db_path, expense_id)["description"] == "a" * 200

    def test_description_omitted_stored_as_null(self, auth_client, db_path, expense_id):
        resp = submit(auth_client, expense_id, description=None)
        assert resp.status_code == 302
        assert get_row(db_path, expense_id)["description"] is None

    @pytest.mark.parametrize("blank", ["", "   ", "\t "])
    def test_blank_description_stored_null_and_dash_on_profile(
        self, auth_client, db_path, expense_id, blank
    ):
        submit(auth_client, expense_id, description=blank)
        assert get_row(db_path, expense_id)["description"] is None
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "—" in page.split("Recent expenses", 1)[1]

    def test_sql_injection_in_description_stored_literally(self, auth_client, db_path, expense_id):
        evil = "x'); DROP TABLE expenses;--"
        submit(auth_client, expense_id, description=evil)
        assert get_row(db_path, expense_id)["description"] == evil

    def test_edited_form_prefill_roundtrips(self, auth_client, expense_id):
        submit(auth_client, expense_id, amount="99.25", category="Transport", date=YESTERDAY)
        page = auth_client.get(edit_url(expense_id)).get_data(as_text=True)
        assert input_value(page, "amount") == "99.25"
        assert selected_category(page) == "Transport"
        assert input_value(page, "date") == YESTERDAY


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #

class TestValidation:
    @pytest.mark.parametrize("amount,msg", [
        ("", ERR_AMOUNT), ("   ", ERR_AMOUNT), ("abc", ERR_AMOUNT), ("-5", ERR_AMOUNT),
        ("+5", ERR_AMOUNT), ("1e3", ERR_AMOUNT), ("1,000", ERR_AMOUNT), (".5", ERR_AMOUNT),
        ("5.", ERR_AMOUNT), ("NaN", ERR_AMOUNT), ("Infinity", ERR_AMOUNT),
        ("٣", ERR_AMOUNT), ("1 2", ERR_AMOUNT),
        ("0", ERR_ZERO), ("0.00", ERR_ZERO), ("000", ERR_ZERO),
        ("1.234", ERR_DECIMALS), ("0.001", ERR_DECIMALS),
        ("10000000", ERR_LARGE), ("9999999.995", ERR_DECIMALS), ("10000000.00", ERR_LARGE),
    ])
    def test_invalid_amounts(self, auth_client, db_path, expense_id, amount, msg):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, amount=amount)
        assert resp.status_code == 200
        assert error_text(resp) == msg
        assert get_row(db_path, expense_id) == before

    def test_amount_missing_field(self, auth_client, db_path, expense_id):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, amount=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_AMOUNT
        assert get_row(db_path, expense_id) == before

    @pytest.mark.parametrize("category", [
        "", "food", "FOOD", "Unknown", " Food", "Food ", "<script>", "Food'; --",
    ])
    def test_invalid_categories(self, auth_client, db_path, expense_id, category):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, category=category)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_CATEGORY
        assert get_row(db_path, expense_id) == before

    def test_category_missing_field(self, auth_client, db_path, expense_id):
        resp = submit(auth_client, expense_id, category=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_CATEGORY

    @pytest.mark.parametrize("day", [
        "", "   ", "not-a-date", "2024-13-01", "2024-02-30", "2023-02-29",
        "2024-1-5", "01-02-2024", "2024/01/05", "20240105", "2024-01-05T10:00",
    ])
    def test_invalid_dates(self, auth_client, db_path, expense_id, day):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, date=day)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DATE
        assert get_row(db_path, expense_id) == before

    def test_date_missing_field(self, auth_client, expense_id):
        resp = submit(auth_client, expense_id, date=None)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DATE

    @pytest.mark.parametrize("length", [201, 250, 1000])
    def test_description_too_long(self, auth_client, db_path, expense_id, length):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, description="a" * length)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_DESC
        assert get_row(db_path, expense_id) == before

    def test_description_length_measured_after_strip(self, auth_client, db_path, expense_id):
        resp = submit(auth_client, expense_id, description="  " + "a" * 200 + "  ")
        assert resp.status_code == 302
        assert get_row(db_path, expense_id)["description"] == "a" * 200

    def test_tomorrow_rejected(self, auth_client, db_path, expense_id):
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, date=TOMORROW)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert get_row(db_path, expense_id) == before

    def test_far_future_rejected(self, auth_client, expense_id):
        resp = submit(auth_client, expense_id, date="9999-12-31")
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE

    @pytest.mark.parametrize("overrides,msg", [
        ({"amount": "abc", "category": "Nope", "date": "bad", "description": "a" * 300}, ERR_AMOUNT),
        ({"category": "Nope", "date": "bad", "description": "a" * 300}, ERR_CATEGORY),
        ({"date": "bad", "description": "a" * 300}, ERR_DATE),
        ({"date": TOMORROW, "description": "a" * 300}, ERR_FUTURE),
        ({"amount": "0", "category": "Nope"}, ERR_ZERO),
        ({"amount": "1.234", "date": "bad"}, ERR_DECIMALS),
        ({"amount": "99999999", "category": "Nope"}, ERR_LARGE),
    ])
    def test_only_first_error_shown(self, auth_client, expense_id, overrides, msg):
        resp = submit(auth_client, expense_id, **overrides)
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert error_text(resp) == msg
        assert page.count('class="auth-error"') == 1, "exactly one error box"

    def test_entered_values_kept_not_stored_ones(self, auth_client, expense_id):
        resp = submit(auth_client, expense_id, amount="12.345", category="Shopping",
                      date="2021-06-07", description="typed text")
        page = resp.get_data(as_text=True)
        assert error_text(resp) == ERR_DECIMALS
        assert input_value(page, "amount") == "12.345"
        assert selected_category(page) == "Shopping"
        assert input_value(page, "date") == "2021-06-07"
        assert input_value(page, "description") == "typed text"
        assert "Edit expense" in page and "Save changes" in page
        assert f'action="{edit_url(expense_id)}"' in page

    def test_entered_xss_value_escaped_on_error(self, auth_client, expense_id):
        resp = submit(auth_client, expense_id, amount="bad",
                      description='"><script>alert(1)</script>')
        page = resp.get_data(as_text=True)
        assert "<script>alert(1)</script>" not in page
        assert input_value(page, "description") == '"><script>alert(1)</script>'

    def test_error_page_has_fresh_usable_token(self, auth_client, db_path, expense_id):
        resp = submit(auth_client, expense_id, amount="bad")
        page = resp.get_data(as_text=True)
        m = re.search(r'<input[^>]*name="csrf_token"[^>]*value="([^"]*)"', page)
        assert m and m.group(1)
        ok = auth_client.post(
            edit_url(expense_id),
            data=dict(new_fields(), csrf_token=html_lib.unescape(m.group(1))),
        )
        assert ok.status_code == 302


# --------------------------------------------------------------------------- #
# Future-date exception                                                        #
# --------------------------------------------------------------------------- #

class TestFutureDateException:
    @pytest.fixture
    def future_day(self):
        return (TODAY + timedelta(days=5)).isoformat()

    @pytest.fixture
    def future_id(self, db_path, user_id, future_day):
        return insert_expense(db_path, user_id, future_day, 300, "Bills", "Seeded-like")

    def test_get_future_row_prefills_stored_date(self, auth_client, future_id, future_day):
        page = auth_client.get(edit_url(future_id)).get_data(as_text=True)
        assert input_value(page, "date") == future_day

    def test_resubmitting_same_future_date_accepted(self, auth_client, db_path, future_id, future_day):
        resp = submit(auth_client, future_id, date=future_day, amount="321.00",
                      description="fixed")
        assert resp.status_code == 302
        row = get_row(db_path, future_id)
        assert row["date"] == future_day
        assert row["amount"] == 321.0
        assert row["description"] == "fixed"

    def test_different_future_date_rejected(self, auth_client, db_path, future_id):
        other = (TODAY + timedelta(days=6)).isoformat()
        before = get_row(db_path, future_id)
        resp = submit(auth_client, future_id, date=other)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert get_row(db_path, future_id) == before

    def test_tomorrow_rejected_for_future_row(self, auth_client, db_path, future_id):
        before = get_row(db_path, future_id)
        resp = submit(auth_client, future_id, date=TOMORROW)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert get_row(db_path, future_id) == before

    def test_moving_future_row_to_past_accepted(self, auth_client, db_path, future_id):
        resp = submit(auth_client, future_id, date=YESTERDAY)
        assert resp.status_code == 302
        assert get_row(db_path, future_id)["date"] == YESTERDAY

    def test_exception_does_not_leak_to_other_expenses(self, auth_client, db_path, user_id,
                                                       expense_id, future_id, future_day):
        # expense_id is dated today; the other row's future date is not its own.
        before = get_row(db_path, expense_id)
        resp = submit(auth_client, expense_id, date=future_day)
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert get_row(db_path, expense_id) == before

    def test_exception_requires_exact_stored_value(self, auth_client, db_path, future_id):
        # Another validation error still wins on a future row.
        resp = submit(auth_client, future_id, amount="bad",
                      date=(TODAY + timedelta(days=5)).isoformat())
        assert error_text(resp) == ERR_AMOUNT


# --------------------------------------------------------------------------- #
# CSRF                                                                         #
# --------------------------------------------------------------------------- #

class TestCsrf:
    def _assert_rejected(self, resp, db_path, expense_id, before):
        page = resp.get_data(as_text=True)
        assert resp.status_code == 400
        assert error_text(resp) == ERR_CSRF
        assert get_row(db_path, expense_id) == before
        return page

    def test_missing_token_rejected(self, auth_client, db_path, expense_id):
        form_token(auth_client, expense_id)
        before = get_row(db_path, expense_id)
        resp = auth_client.post(edit_url(expense_id), data=new_fields())
        self._assert_rejected(resp, db_path, expense_id, before)

    @pytest.mark.parametrize("token", ["", "wrong", "a" * 43, "tökén-ñ", "日本語", " "])
    def test_bad_token_rejected(self, auth_client, db_path, expense_id, token):
        form_token(auth_client, expense_id)
        before = get_row(db_path, expense_id)
        resp = auth_client.post(
            edit_url(expense_id), data=dict(new_fields(), csrf_token=token)
        )
        self._assert_rejected(resp, db_path, expense_id, before)

    def test_token_with_valid_token_plus_suffix_rejected(self, auth_client, db_path, expense_id):
        token = form_token(auth_client, expense_id)
        before = get_row(db_path, expense_id)
        resp = auth_client.post(
            edit_url(expense_id), data=dict(new_fields(), csrf_token=token + "x")
        )
        self._assert_rejected(resp, db_path, expense_id, before)

    def test_post_without_any_prior_get_rejected(self, auth_client, db_path, expense_id):
        before = get_row(db_path, expense_id)
        resp = auth_client.post(
            edit_url(expense_id), data=dict(new_fields(), csrf_token="anything")
        )
        self._assert_rejected(resp, db_path, expense_id, before)

    def test_other_session_token_rejected(self, app, auth_client, db_path, user_id, expense_id):
        other = app.test_client()
        login(other)
        foreign_token = form_token(other, expense_id)
        form_token(auth_client, expense_id)
        before = get_row(db_path, expense_id)
        resp = auth_client.post(
            edit_url(expense_id), data=dict(new_fields(), csrf_token=foreign_token)
        )
        self._assert_rejected(resp, db_path, expense_id, before)

    def test_csrf_rejection_keeps_entered_values(self, auth_client, db_path, expense_id):
        form_token(auth_client, expense_id)
        resp = auth_client.post(
            edit_url(expense_id),
            data=dict(new_fields(amount="77.00", category="Health",
                                 description="kept me"), csrf_token="bad"),
        )
        page = resp.get_data(as_text=True)
        assert resp.status_code == 400
        assert input_value(page, "amount") == "77.00"
        assert selected_category(page) == "Health"
        assert input_value(page, "description") == "kept me"

    def test_csrf_checked_before_field_validation(self, auth_client, expense_id):
        form_token(auth_client, expense_id)
        resp = auth_client.post(
            edit_url(expense_id),
            data=dict(new_fields(amount="bad"), csrf_token="wrong"),
        )
        assert resp.status_code == 400
        assert error_text(resp) == ERR_CSRF

    def test_genuine_token_from_get_accepted(self, auth_client, expense_id):
        assert submit(auth_client, expense_id).status_code == 302

    def test_same_token_valid_for_multiple_expenses(self, auth_client, db_path, user_id, expense_id):
        second = insert_expense(db_path, user_id, YESTERDAY, 5, "Food", "two")
        token = form_token(auth_client, expense_id)
        assert submit(auth_client, expense_id, token=token).status_code == 302
        assert submit(auth_client, second, token=token).status_code == 302


# --------------------------------------------------------------------------- #
# Profile page integration                                                     #
# --------------------------------------------------------------------------- #

class TestProfile:
    def test_actions_column_and_edit_link_on_every_row(self, auth_client, db_path, user_id):
        ids = [insert_expense(db_path, user_id, YESTERDAY, 10 + i, "Food", f"d{i}") for i in range(4)]
        page = auth_client.get("/profile").get_data(as_text=True)
        assert re.search(r"<th[^>]*>\s*Actions\s*</th>", page)
        for i in ids:
            assert re.search(
                r'<a href="%s"[^>]*>\s*Edit\s*</a>' % re.escape(edit_url(i)), page
            ), f"Edit link for expense {i} missing"
        assert len(re.findall(r">\s*Edit\s*</a>", page)) == len(ids)

    def test_actions_cell_does_not_use_num_class(self, auth_client, db_path, user_id):
        insert_expense(db_path, user_id, YESTERDAY, 10)
        page = auth_client.get("/profile").get_data(as_text=True)
        assert not re.search(r'<th class="num">\s*Actions', page)
        cell = re.search(r"<td([^>]*)>\s*<a [^>]*>\s*Edit\s*</a>", page)
        assert cell and "num" not in cell.group(1).split()

    def test_other_users_expenses_have_no_edit_links(self, auth_client, db_path, user_id, other_user_id):
        mine = insert_expense(db_path, user_id, YESTERDAY, 10)
        theirs = insert_expense(db_path, other_user_id, YESTERDAY, 20)
        page = auth_client.get("/profile").get_data(as_text=True)
        assert edit_url(mine) in page
        assert edit_url(theirs) not in page

    def test_empty_state_has_no_edit_links(self, auth_client):
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "No expenses yet" in page
        assert not re.search(r"/expenses/\d+/edit", page)

    def test_edit_link_leads_to_working_form(self, auth_client, expense_id):
        page = auth_client.get("/profile").get_data(as_text=True)
        href = re.search(r'<a href="(/expenses/\d+/edit)"', page).group(1)
        assert auth_client.get(href).status_code == 200

    def test_totals_and_breakdown_reflect_amount_edit(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 100, "Food", "a")
        insert_expense(db_path, user_id, YESTERDAY, 50, "Bills", "b")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert stat(page, "Total spent") == "₹150.00"
        submit(auth_client, eid, amount="400.00", category="Food", date=YESTERDAY,
               description="a")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert stat(page, "Total spent") == "₹450.00"
        assert stat(page, "Expenses") == "2"
        assert "₹400.00" in page
        assert stat(page, "Top category") == "Food"

    def test_category_edit_moves_breakdown(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 300, "Food", "a")
        insert_expense(db_path, user_id, YESTERDAY, 50, "Bills", "b")
        assert stat(auth_client.get("/profile").get_data(as_text=True), "Top category") == "Food"
        submit(auth_client, eid, amount="300.00", category="Entertainment",
               date=YESTERDAY, description="a")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert stat(page, "Top category") == "Entertainment"
        rows = re.findall(r'<span class="profile-cat-name">(.*?)</span>', page)
        assert "Entertainment" in rows and "Food" not in rows
        assert "Bills" in rows
        assert stat(page, "Total spent") == "₹350.00"

    def test_recent_list_reflects_edited_description_and_date(self, auth_client, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 100, "Food", "old words")
        submit(auth_client, eid, amount="100", category="Food", date="2024-03-05",
               description="brand new words")
        page = auth_client.get("/profile").get_data(as_text=True)
        assert "brand new words" in page
        assert "old words" not in page
        assert "05 Mar 2024" in page

    def test_null_description_shows_dash_in_table(self, auth_client, db_path, user_id):
        insert_expense(db_path, user_id, YESTERDAY, 10, "Food", None)
        page = auth_client.get("/profile").get_data(as_text=True)
        assert re.search(r"<td>—</td>", page)


# --------------------------------------------------------------------------- #
# DB helpers                                                                   #
# --------------------------------------------------------------------------- #

class TestDbHelpers:
    def test_get_expense_returns_row_for_owner(self, db_path, user_id, expense_id):
        row = db_module.get_expense(expense_id, user_id)
        assert row is not None
        assert row["id"] == expense_id
        assert row["user_id"] == user_id
        assert row["amount"] == 450.5
        assert row["category"] == "Food"
        assert row["date"] == TODAY.isoformat()
        assert row["description"] == "Lunch"

    def test_get_expense_none_for_other_user(self, db_path, user_id, other_user_id, expense_id):
        assert db_module.get_expense(expense_id, other_user_id) is None

    @pytest.mark.parametrize("missing", [0, 99999, -1])
    def test_get_expense_none_for_missing_id(self, db_path, user_id, missing):
        assert db_module.get_expense(missing, user_id) is None

    def test_get_expense_none_for_unknown_user(self, db_path, expense_id):
        assert db_module.get_expense(expense_id, 99999) is None

    def test_get_expense_null_description_is_none(self, db_path, user_id):
        eid = insert_expense(db_path, user_id, YESTERDAY, 5, "Food", None)
        assert db_module.get_expense(eid, user_id)["description"] is None

    def test_update_expense_owner_returns_1_and_updates(self, db_path, user_id, expense_id):
        before = get_row(db_path, expense_id)
        n = db_module.update_expense(expense_id, user_id, 12.5, "Health", YESTERDAY, "new")
        assert n == 1
        row = get_row(db_path, expense_id)
        assert (row["amount"], row["category"], row["date"], row["description"]) == (
            12.5, "Health", YESTERDAY, "new")
        assert row["id"] == before["id"]
        assert row["user_id"] == before["user_id"]
        assert row["created_at"] == before["created_at"]

    def test_update_expense_accepts_null_description(self, db_path, user_id, expense_id):
        assert db_module.update_expense(expense_id, user_id, 1.0, "Food", YESTERDAY, None) == 1
        assert get_row(db_path, expense_id)["description"] is None

    def test_update_expense_other_user_returns_0_and_changes_nothing(
        self, db_path, user_id, other_user_id, expense_id
    ):
        before = all_expenses(db_path)
        n = db_module.update_expense(expense_id, other_user_id, 1.0, "Health", YESTERDAY, "hax")
        assert n == 0
        assert all_expenses(db_path) == before

    def test_update_expense_missing_id_returns_0_and_changes_nothing(
        self, db_path, user_id, expense_id
    ):
        before = all_expenses(db_path)
        assert db_module.update_expense(99999, user_id, 1.0, "Health", YESTERDAY, "x") == 0
        assert all_expenses(db_path) == before

    def test_update_expense_only_touches_target_row(self, db_path, user_id, expense_id):
        other = insert_expense(db_path, user_id, YESTERDAY, 9, "Bills", "keep")
        before = get_row(db_path, other)
        db_module.update_expense(expense_id, user_id, 1.0, "Health", YESTERDAY, "x")
        assert get_row(db_path, other) == before

    def test_update_expense_sql_injection_is_inert(self, db_path, user_id, expense_id):
        evil = "'; DROP TABLE expenses; --"
        assert db_module.update_expense(expense_id, user_id, 1.0, "Food", YESTERDAY, evil) == 1
        assert get_row(db_path, expense_id)["description"] == evil


# --------------------------------------------------------------------------- #
# Regression                                                                   #
# --------------------------------------------------------------------------- #

class TestRegression:
    def test_delete_stub_unchanged(self, auth_client, expense_id):
        resp = auth_client.get(f"/expenses/{expense_id}/delete")
        assert resp.status_code == 200
        assert "Delete expense — coming in Step 9" in resp.get_data(as_text=True)

    def test_add_form_still_works(self, auth_client, db_path, user_id):
        resp = auth_client.get("/expenses/add")
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "Add expense" in page
        token = re.search(r'name="csrf_token"[^>]*value="([^"]*)"', page).group(1)
        assert input_value(page, "date") == TODAY.isoformat()
        resp = auth_client.post("/expenses/add", data={
            "amount": "10.00", "category": "Food", "date": TODAY.isoformat(),
            "description": "n", "csrf_token": html_lib.unescape(token),
        })
        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/profile")
        assert len(all_expenses(db_path)) == 1

    def test_add_form_still_rejects_any_future_date(self, auth_client, db_path, user_id):
        page = auth_client.get("/expenses/add").get_data(as_text=True)
        token = re.search(r'name="csrf_token"[^>]*value="([^"]*)"', page).group(1)
        resp = auth_client.post("/expenses/add", data={
            "amount": "10.00", "category": "Food", "date": TOMORROW,
            "description": "", "csrf_token": html_lib.unescape(token),
        })
        assert resp.status_code == 200
        assert error_text(resp) == ERR_FUTURE
        assert all_expenses(db_path) == []

    def test_add_page_has_submit_label_and_action(self, auth_client):
        page = auth_client.get("/expenses/add").get_data(as_text=True)
        assert 'action="/expenses/add"' in page
        assert "Save changes" not in page

    @pytest.mark.parametrize("path", ["/", "/login", "/register", "/terms", "/privacy"])
    def test_public_pages_still_work(self, client, path):
        assert client.get(path).status_code == 200

    @pytest.mark.parametrize("path", ["/profile", "/analytics"])
    def test_protected_pages_still_work(self, auth_client, path):
        assert auth_client.get(path).status_code == 200
