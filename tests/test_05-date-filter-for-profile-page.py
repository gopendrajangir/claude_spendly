"""Tests for step 05: date filter on GET /profile.

Expectations come from .claude/specs/05-date-filter-for-profile-page.md.
"""
import re
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from werkzeug.security import generate_password_hash

PASSWORD = "password123"
ERR_FORMAT = "Enter dates in YYYY-MM-DD format."
ERR_ORDER = "Start date must be on or before end date."


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def add_user(db_path, name, email):
    with closing(_connect(db_path)) as conn:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, generate_password_hash(PASSWORD)),
        )
        conn.commit()
        return cur.lastrowid


def add_expense(db_path, user_id, day, amount, category="Food", description=None):
    if isinstance(day, date):
        day = day.isoformat()
    with closing(_connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, category, day, description),
        )
        conn.commit()


def snapshot(db_path):
    with closing(_connect(db_path)) as conn:
        users = [tuple(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]
        exps = [tuple(r) for r in conn.execute("SELECT * FROM expenses ORDER BY id")]
    return users, exps


def login(client, email):
    resp = client.post("/login", data={"email": email, "password": PASSWORD})
    assert resp.status_code == 302, "login should redirect on success"


def get_page(client, **params):
    """GET /profile with the given query params (use dict for 'from')."""
    resp = client.get("/profile", query_string=params)
    return resp, resp.get_data(as_text=True)


def stat(html, label):
    """Text of the main value span of a summary stat card."""
    m = re.search(
        re.escape(label) + r"</span>\s*<span class=\"profile-stat-value\">(.*?)</span>",
        html,
        re.S,
    )
    assert m, f"stat card {label!r} not found"
    return m.group(1).strip()


def table_rows(html):
    """Number of body rows in the recent expenses table."""
    return len(re.findall(r'<td class="num">', html))


def chips(html):
    """Return {label: (href, tag_html)} for the preset chips."""
    out = {}
    for m in re.finditer(r"<a ([^>]*)>([^<]+)</a>", html):
        attrs, label = m.group(1), m.group(2).strip()
        if label in ("Last 7 days", "Last 30 days", "This month", "Last month", "All time"):
            href = re.search(r'href="([^"]*)"', attrs).group(1)
            out[label] = (href.replace("&amp;", "&"), attrs)
    return out


def chip_query(href):
    q = parse_qs(urlparse(href).query)
    return {k: v[0] for k, v in q.items()}


def is_active(attrs):
    return "active" in attrs or "aria-current" in attrs


def active_labels(html):
    return [label for label, (_, attrs) in chips(html).items() if is_active(attrs)]


def last_month_range(today):
    first_this = today.replace(day=1)
    end = first_this - timedelta(days=1)
    return end.replace(day=1), end


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

@pytest.fixture
def user_id(db_path):
    return add_user(db_path, "Alice Tester", "alice@example.com")


@pytest.fixture
def sept(db_path, user_id):
    """Alice's expenses around September 2026 (boundaries included)."""
    add_expense(db_path, user_id, "2026-08-31", 1000.00, "Shopping", "BEFORE_FROM")
    add_expense(db_path, user_id, "2026-09-01", 100.00, "Food", "ON_FROM")
    add_expense(db_path, user_id, "2026-09-15", 200.00, "Food", "MID_SEP")
    add_expense(db_path, user_id, "2026-09-20", 100.00, "Bills", "BILLS_SEP")
    add_expense(db_path, user_id, "2026-09-30", 100.00, "Transport", "ON_TO")
    add_expense(db_path, user_id, "2026-10-01", 2000.00, "Health", "AFTER_TO")
    return user_id


@pytest.fixture
def auth_client(client, sept):
    login(client, "alice@example.com")
    return client


# --------------------------------------------------------------------------- #
# Auth guard                                                                   #
# --------------------------------------------------------------------------- #

class TestAuthGuard:
    @pytest.mark.parametrize(
        "query", ["from=2026-09-01", "from=2026-09-01&to=2026-09-30", "from=abc", ""]
    )
    def test_profile_signed_out_redirects_to_login(self, client, db_path, query):
        resp = client.get("/profile?" + query)
        assert resp.status_code == 302, "signed-out request must redirect"
        assert urlparse(resp.headers["Location"]).path == "/login"


# --------------------------------------------------------------------------- #
# No filter / baseline                                                         #
# --------------------------------------------------------------------------- #

class TestNoFilter:
    def test_no_params_shows_all_time_caption_and_200(self, auth_client):
        resp, html = get_page(auth_client)
        assert resp.status_code == 200
        assert "Showing all time" in html
        assert ERR_FORMAT not in html and ERR_ORDER not in html

    def test_no_params_all_time_chip_is_active_only(self, auth_client):
        _, html = get_page(auth_client)
        assert active_labels(html) == ["All time"]

    def test_no_params_totals_cover_all_expenses(self, auth_client):
        _, html = get_page(auth_client)
        assert stat(html, "Total spent") == "₹3,600.00"
        assert stat(html, "Expenses") == "6"
        assert stat(html, "Top category") == "Health"
        for desc in ("BEFORE_FROM", "ON_FROM", "MID_SEP", "BILLS_SEP", "ON_TO", "AFTER_TO"):
            assert desc in html, f"{desc} should appear without a filter"

    def test_blank_values_behave_as_no_filter_without_error(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "", "to": ""})
        assert resp.status_code == 200
        assert ERR_FORMAT not in html and ERR_ORDER not in html
        assert "Showing all time" in html
        assert stat(html, "Expenses") == "6"
        assert active_labels(html) == ["All time"]

    def test_whitespace_only_value_is_not_an_error(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "", "to": "2026-09-30"})
        assert resp.status_code == 200
        assert ERR_FORMAT not in html
        assert "Showing up to 30 Sep 2026" in html


# --------------------------------------------------------------------------- #
# Valid ranges                                                                 #
# --------------------------------------------------------------------------- #

class TestRange:
    def test_full_range_includes_both_ends_and_excludes_outside(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert resp.status_code == 200
        for desc in ("ON_FROM", "MID_SEP", "BILLS_SEP", "ON_TO"):
            assert desc in html, f"{desc} should be inside the range"
        assert "BEFORE_FROM" not in html, "day before from must be excluded"
        assert "AFTER_TO" not in html, "day after to must be excluded"

    def test_full_range_totals_match_direct_sql(self, auth_client, db_path, user_id):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        with closing(_connect(db_path)) as conn:
            total, count = conn.execute(
                "SELECT SUM(amount), COUNT(*) FROM expenses "
                "WHERE user_id = ? AND date >= ? AND date <= ?",
                (user_id, "2026-09-01", "2026-09-30"),
            ).fetchone()
            top = conn.execute(
                "SELECT category FROM expenses WHERE user_id = ? AND date >= ? "
                "AND date <= ? GROUP BY category ORDER BY SUM(amount) DESC LIMIT 1",
                (user_id, "2026-09-01", "2026-09-30"),
            ).fetchone()[0]
        assert stat(html, "Total spent") == f"₹{total:,.2f}"
        assert stat(html, "Expenses") == str(count)
        assert stat(html, "Top category") == top == "Food"

    def test_full_range_caption(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert "Showing 01 Sep 2026 – 30 Sep 2026" in html

    def test_only_from_includes_everything_on_or_after(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "2026-09-30"})
        assert resp.status_code == 200
        assert "ON_TO" in html and "AFTER_TO" in html
        assert "MID_SEP" not in html and "BEFORE_FROM" not in html
        assert stat(html, "Expenses") == "2"
        assert stat(html, "Total spent") == "₹2,100.00"
        assert "Showing from 30 Sep 2026" in html

    def test_only_to_includes_everything_on_or_before(self, auth_client):
        resp, html = get_page(auth_client, **{"to": "2026-08-31"})
        assert resp.status_code == 200
        assert "BEFORE_FROM" in html
        assert "ON_FROM" not in html and "AFTER_TO" not in html
        assert stat(html, "Expenses") == "1"
        assert "Showing up to 31 Aug 2026" in html

    def test_single_day_range_from_equals_to_is_valid(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "2026-09-15", "to": "2026-09-15"})
        assert resp.status_code == 200
        assert ERR_ORDER not in html and ERR_FORMAT not in html
        assert "MID_SEP" in html and "ON_FROM" not in html
        assert stat(html, "Expenses") == "1"

    def test_category_percentages_use_filtered_total(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        # Filtered total 500: Food 300 (60%), Bills 100 (20%), Transport 100 (20%)
        assert "60%" in html
        assert html.count("20%") >= 4, "20% label and 20% bar width for two categories"
        assert "width: 60%" in html, "bar width must match the percentage"
        assert "width: 20%" in html
        # All-time percentages (Health 2000/3600 = 56%) must not appear
        assert "56%" not in html
        assert "Health" not in html.split("Spending by category")[1]

    def test_future_range_with_no_expenses_is_not_an_error(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "2999-01-01", "to": "2999-12-31"})
        assert resp.status_code == 200
        assert ERR_FORMAT not in html and ERR_ORDER not in html
        assert "Showing 01 Jan 2999 – 31 Dec 2999" in html

    def test_recent_table_limited_to_10_newest_first_within_range(
        self, client, db_path, user_id
    ):
        for i in range(1, 13):
            add_expense(db_path, user_id, f"2026-09-{i:02d}", 10.0, "Food", f"ROW_{i:02d}")
        add_expense(db_path, user_id, "2026-10-05", 10.0, "Food", "OUTSIDE_NEWER")
        login(client, "alice@example.com")
        _, html = get_page(client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert table_rows(html) == 10
        assert "OUTSIDE_NEWER" not in html
        assert "ROW_12" in html and "ROW_03" in html
        assert "ROW_02" not in html and "ROW_01" not in html, "oldest two dropped"
        assert html.index("ROW_12") < html.index("ROW_11") < html.index("ROW_03")

    def test_stat_count_reflects_full_range_not_table_limit(self, client, db_path, user_id):
        for i in range(1, 13):
            add_expense(db_path, user_id, f"2026-09-{i:02d}", 10.0, "Food", f"R{i}")
        login(client, "alice@example.com")
        _, html = get_page(client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert stat(html, "Expenses") == "12"
        assert stat(html, "Total spent") == "₹120.00"


# --------------------------------------------------------------------------- #
# "This month" card                                                            #
# --------------------------------------------------------------------------- #

class TestThisMonthCard:
    def test_this_month_card_unchanged_by_filter(self, client, db_path, user_id):
        today = date.today()
        add_expense(db_path, user_id, today.replace(day=1), 250.00, "Food", "CUR_MONTH")
        add_expense(db_path, user_id, "2020-01-10", 999.00, "Bills", "OLD")
        login(client, "alice@example.com")
        _, unfiltered = get_page(client)
        _, filtered = get_page(client, **{"from": "2020-01-01", "to": "2020-01-31"})
        assert stat(unfiltered, "This month") == "₹250.00"
        assert stat(filtered, "This month") == stat(unfiltered, "This month")
        assert stat(filtered, "Total spent") == "₹999.00"

    def test_this_month_card_unchanged_by_invalid_filter(self, client, db_path, user_id):
        add_expense(db_path, user_id, date.today().replace(day=1), 80.00, "Food", "CUR")
        login(client, "alice@example.com")
        _, base = get_page(client)
        _, bad = get_page(client, **{"from": "abc"})
        assert stat(bad, "This month") == stat(base, "This month") == "₹80.00"


# --------------------------------------------------------------------------- #
# Presets                                                                      #
# --------------------------------------------------------------------------- #

class TestPresets:
    def test_all_five_chips_are_rendered(self, auth_client):
        _, html = get_page(auth_client)
        assert set(chips(html)) == {
            "Last 7 days", "Last 30 days", "This month", "Last month", "All time",
        }

    def test_preset_links_match_spec_for_todays_date(self, auth_client):
        today = date.today()
        lm_start, lm_end = last_month_range(today)
        expected = {
            "Last 7 days": ((today - timedelta(days=6)), today),
            "Last 30 days": ((today - timedelta(days=29)), today),
            "This month": (today.replace(day=1), today),
            "Last month": (lm_start, lm_end),
        }
        _, html = get_page(auth_client)
        found = chips(html)
        for label, (start, end) in expected.items():
            q = chip_query(found[label][0])
            assert urlparse(found[label][0]).path == "/profile"
            assert q == {"from": start.isoformat(), "to": end.isoformat()}, label

    def test_all_time_chip_links_to_plain_profile(self, auth_client):
        _, html = get_page(auth_client)
        assert chips(html)["All time"][0] == "/profile"

    @pytest.mark.parametrize(
        "label,start_off,end_off",
        [("Last 7 days", 6, 0), ("Last 30 days", 29, 0)],
    )
    def test_rolling_preset_chip_active_when_url_matches(
        self, auth_client, label, start_off, end_off
    ):
        today = date.today()
        start = today - timedelta(days=start_off)
        _, html = get_page(auth_client, **{"from": start.isoformat(), "to": today.isoformat()})
        assert active_labels(html) == [label]

    def test_this_month_chip_active_when_url_matches(self, auth_client):
        today = date.today()
        _, html = get_page(
            auth_client, **{"from": today.replace(day=1).isoformat(), "to": today.isoformat()}
        )
        assert "This month" in active_labels(html)

    def test_last_month_chip_active_when_url_matches(self, auth_client):
        start, end = last_month_range(date.today())
        _, html = get_page(auth_client, **{"from": start.isoformat(), "to": end.isoformat()})
        assert active_labels(html) == ["Last month"]

    def test_chip_not_active_when_range_only_partially_matches(self, auth_client):
        today = date.today()
        _, html = get_page(auth_client, **{"from": (today - timedelta(days=6)).isoformat()})
        assert active_labels(html) == [], "from-only is not an exact preset match"

    def test_custom_range_activates_no_chip(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        # Only a coincidental preset could match; Sep 2026 is not a preset unless
        # today makes it one, so compute that.
        today = date.today()
        lm_start, lm_end = last_month_range(today)
        coincidence = (lm_start.isoformat(), lm_end.isoformat()) == ("2026-09-01", "2026-09-30")
        if not coincidence:
            assert active_labels(html) == []

    def test_clicking_last_month_shows_only_previous_month_expenses(
        self, client, db_path, user_id
    ):
        today = date.today()
        lm_start, lm_end = last_month_range(today)
        add_expense(db_path, user_id, lm_start, 10.0, "Food", "LM_FIRST")
        add_expense(db_path, user_id, lm_end, 20.0, "Food", "LM_LAST")
        add_expense(db_path, user_id, lm_start - timedelta(days=1), 40.0, "Food", "TWO_MONTHS")
        add_expense(db_path, user_id, today.replace(day=1), 80.0, "Food", "THIS_MONTH_ROW")
        login(client, "alice@example.com")
        _, html = get_page(client)
        href = chips(html)["Last month"][0]
        resp = client.get(href)
        page = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "LM_FIRST" in page and "LM_LAST" in page
        assert "TWO_MONTHS" not in page and "THIS_MONTH_ROW" not in page
        assert stat(page, "Total spent") == "₹30.00"
        assert stat(page, "Expenses") == "2"

    def test_clicking_last_7_days_excludes_older_expenses(self, client, db_path, user_id):
        today = date.today()
        add_expense(db_path, user_id, today - timedelta(days=6), 5.0, "Food", "D_MINUS_6")
        add_expense(db_path, user_id, today - timedelta(days=7), 7.0, "Food", "D_MINUS_7")
        add_expense(db_path, user_id, today, 9.0, "Food", "D_ZERO")
        login(client, "alice@example.com")
        _, html = get_page(client)
        page = client.get(chips(html)["Last 7 days"][0]).get_data(as_text=True)
        assert "D_MINUS_6" in page and "D_ZERO" in page
        assert "D_MINUS_7" not in page


# --------------------------------------------------------------------------- #
# Custom form / Clear link                                                     #
# --------------------------------------------------------------------------- #

class TestCustomForm:
    def test_form_is_get_to_profile_with_date_inputs_and_apply_button(self, auth_client):
        _, html = get_page(auth_client)
        form = re.search(r"<form[^>]*>", html).group(0)
        assert 'method="get"' in form.lower()
        assert 'action="/profile"' in form
        assert re.search(r'<input[^>]*type="date"[^>]*name="from"', html) or re.search(
            r'<input[^>]*name="from"[^>]*type="date"', html
        )
        assert re.search(r'<input[^>]*type="date"[^>]*name="to"', html) or re.search(
            r'<input[^>]*name="to"[^>]*type="date"', html
        )
        assert "Apply" in html

    def test_inputs_prefilled_with_values_in_use(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert re.search(r'name="from"[^>]*value="2026-09-01"', html)
        assert re.search(r'name="to"[^>]*value="2026-09-30"', html)

    def test_inputs_empty_without_filter(self, auth_client):
        _, html = get_page(auth_client)
        assert not re.search(r'name="from"[^>]*value="[^"]+"', html)
        assert not re.search(r'name="to"[^>]*value="[^"]+"', html)

    def test_inputs_not_prefilled_with_invalid_values(self, auth_client):
        _, html = get_page(auth_client, **{"from": "abc", "to": "2026-09-30"})
        assert "abc" not in html, "invalid input must not be echoed back"
        assert not re.search(r'name="to"[^>]*value="2026-09-30"', html), (
            "whole request falls back to no filter, so nothing is pre-filled"
        )

    def test_submitting_form_params_equals_typed_url(self, auth_client):
        typed = auth_client.get("/profile?from=2026-09-01&to=2026-09-30").get_data(as_text=True)
        _, via_form = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        for label in ("Total spent", "Expenses", "Top category", "This month"):
            assert stat(typed, label) == stat(via_form, label)

    def test_clear_link_goes_to_plain_profile(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert re.search(r'<a [^>]*href="/profile"[^>]*>\s*Clear\s*</a>', html)

    def test_following_clear_link_returns_all_time(self, auth_client):
        resp = auth_client.get("/profile")
        html = resp.get_data(as_text=True)
        assert "Showing all time" in html and stat(html, "Expenses") == "6"


# --------------------------------------------------------------------------- #
# Validation                                                                   #
# --------------------------------------------------------------------------- #

class TestValidation:
    @pytest.mark.parametrize(
        "params",
        [
            {"from": "abc"},
            {"to": "abc"},
            {"to": "2026-02-30"},
            {"from": "2026-02-30"},
            {"from": "2026-1-5"},
            {"to": "2026-9-05"},
            {"from": "2026/09/01"},
            {"from": "20260901"},
            {"from": "2026-13-01"},
            {"from": "2026-09-01", "to": "garbage"},
            {"from": "garbage", "to": "2026-09-30"},
            {"from": "2026-09-01' OR '1'='1"},
            {"from": "'; DROP TABLE expenses; --"},
        ],
    )
    def test_invalid_date_shows_format_error_and_all_time_data(self, auth_client, params):
        resp, html = get_page(auth_client, **params)
        assert resp.status_code == 200
        assert ERR_FORMAT in html
        assert "Showing all time" in html
        assert stat(html, "Expenses") == "6"
        assert stat(html, "Total spent") == "₹3,600.00"
        assert active_labels(html) == ["All time"]

    def test_invalid_date_error_is_in_auth_error_box(self, auth_client):
        _, html = get_page(auth_client, **{"from": "abc"})
        assert re.search(r'class="[^"]*auth-error[^"]*"[^>]*>\s*' + re.escape(ERR_FORMAT), html)

    def test_valid_date_alongside_invalid_one_is_also_ignored(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "nope"})
        assert "AFTER_TO" in html and "BEFORE_FROM" in html, "no partial filtering"

    @pytest.mark.parametrize(
        "params",
        [
            {"from": "2026-09-30", "to": "2026-09-01"},
            {"from": "2026-09-02", "to": "2026-09-01"},
        ],
    )
    def test_from_after_to_shows_order_error_and_all_time_data(self, auth_client, params):
        resp, html = get_page(auth_client, **params)
        assert resp.status_code == 200
        assert ERR_ORDER in html
        assert ERR_FORMAT not in html
        assert "Showing all time" in html
        assert stat(html, "Expenses") == "6"
        assert re.search(r'class="[^"]*auth-error[^"]*"[^>]*>\s*' + re.escape(ERR_ORDER), html)

    def test_format_error_takes_priority_over_order_error(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-30", "to": "2026-02-30"})
        assert ERR_FORMAT in html and ERR_ORDER not in html

    def test_valid_range_shows_no_error_box(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert ERR_FORMAT not in html and ERR_ORDER not in html
        assert "auth-error" not in html

    @pytest.mark.parametrize(
        "value",
        [
            "<script>alert(1)</script>",
            '"><img src=x onerror=alert(1)>',
            "a" * 5000,
            "%00",
            "☃",
        ],
    )
    def test_hostile_query_values_return_200(self, auth_client, value):
        for key in ("from", "to"):
            resp, html = get_page(auth_client, **{key: value})
            assert resp.status_code == 200, f"{key}={value!r} must not 400/500"
            assert ERR_FORMAT in html

    def test_script_in_query_is_not_reflected_unescaped(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "<script>alert(1)</script>"})
        assert resp.status_code == 200
        assert "<script>alert(1)</script>" not in html

    def test_repeated_params_do_not_crash(self, auth_client):
        resp = auth_client.get("/profile?from=2026-09-01&from=abc&to=2026-09-30&to=x")
        assert resp.status_code == 200

    def test_unknown_params_ignored(self, auth_client):
        resp, html = get_page(auth_client, foo="bar")
        assert resp.status_code == 200
        assert "Showing all time" in html and ERR_FORMAT not in html


# --------------------------------------------------------------------------- #
# Empty states                                                                 #
# --------------------------------------------------------------------------- #

class TestEmptyStates:
    def test_valid_range_without_matches_shows_zero_state(self, auth_client):
        resp, html = get_page(auth_client, **{"from": "2025-01-01", "to": "2025-01-31"})
        assert resp.status_code == 200
        assert stat(html, "Total spent") == "₹0.00"
        assert stat(html, "Expenses") == "0"
        assert stat(html, "Top category") == "—"
        assert "No expenses in this period" in html
        assert ERR_FORMAT not in html and ERR_ORDER not in html
        assert "Spending by category" not in html
        assert "Recent expenses" not in html

    def test_empty_period_card_has_working_clear_filter_link(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2025-01-01", "to": "2025-01-31"})
        m = re.search(r'<a [^>]*href="([^"]*)"[^>]*>\s*Clear filter\s*</a>', html)
        assert m, "Clear filter link expected"
        assert m.group(1) == "/profile"
        page = auth_client.get(m.group(1)).get_data(as_text=True)
        assert "Showing all time" in page and stat(page, "Expenses") == "6"

    def test_empty_period_still_shows_filter_bar(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2025-01-01", "to": "2025-01-31"})
        assert "Apply" in html and "Showing 01 Jan 2025 – 31 Jan 2025" in html

    def test_period_card_not_shown_when_matches_exist(self, auth_client):
        _, html = get_page(auth_client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert "No expenses in this period" not in html

    def test_user_without_expenses_sees_step_04_empty_card_and_no_filter_bar(
        self, client, db_path
    ):
        add_user(db_path, "Empty Eve", "eve@example.com")
        login(client, "eve@example.com")
        for params in ({}, {"from": "2026-09-01", "to": "2026-09-30"}, {"from": "abc"}):
            resp, html = get_page(client, **params)
            assert resp.status_code == 200
            assert "No expenses yet" in html
            assert "Apply" not in html
            assert "Showing " not in html
            assert "No expenses in this period" not in html
            assert 'type="date"' not in html


# --------------------------------------------------------------------------- #
# Isolation between users                                                      #
# --------------------------------------------------------------------------- #

class TestUserIsolation:
    def test_other_users_expenses_never_appear_with_same_range(
        self, client, db_path, sept
    ):
        bob = add_user(db_path, "Bob Other", "bob@example.com")
        add_expense(db_path, bob, "2026-09-10", 777.00, "Shopping", "BOB_SECRET")
        add_expense(db_path, bob, "2026-09-01", 55.00, "Food", "BOB_ON_FROM")
        login(client, "alice@example.com")
        _, html = get_page(client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert "BOB_SECRET" not in html and "BOB_ON_FROM" not in html
        assert stat(html, "Total spent") == "₹500.00"
        assert stat(html, "Expenses") == "4"

    def test_second_user_sees_only_their_own_filtered_data(self, client, db_path, sept):
        bob = add_user(db_path, "Bob Other", "bob@example.com")
        add_expense(db_path, bob, "2026-09-10", 777.00, "Shopping", "BOB_SECRET")
        login(client, "bob@example.com")
        _, html = get_page(client, **{"from": "2026-09-01", "to": "2026-09-30"})
        assert "BOB_SECRET" in html
        assert "MID_SEP" not in html and "ON_FROM" not in html
        assert stat(html, "Total spent") == "₹777.00"
        assert stat(html, "Expenses") == "1"
        assert stat(html, "Top category") == "Shopping"

    def test_other_users_expenses_do_not_leak_when_filter_invalid(
        self, client, db_path, sept
    ):
        bob = add_user(db_path, "Bob Other", "bob@example.com")
        add_expense(db_path, bob, "2026-09-10", 777.00, "Shopping", "BOB_SECRET")
        login(client, "alice@example.com")
        _, html = get_page(client, **{"from": "abc"})
        assert "BOB_SECRET" not in html
        assert stat(html, "Total spent") == "₹3,600.00"

    def test_other_users_expenses_do_not_leak_into_this_month_card(
        self, client, db_path, user_id
    ):
        bob = add_user(db_path, "Bob Other", "bob@example.com")
        add_expense(db_path, bob, date.today().replace(day=1), 500.00, "Food", "BOB_CUR")
        login(client, "alice@example.com")
        _, html = get_page(client, **{"from": "2020-01-01", "to": "2030-01-01"})
        assert stat(html, "This month") == "₹0.00"


# --------------------------------------------------------------------------- #
# Read-only behaviour                                                          #
# --------------------------------------------------------------------------- #

class TestReadOnly:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"from": "2026-09-01", "to": "2026-09-30"},
            {"from": "abc"},
            {"from": "2026-09-30", "to": "2026-09-01"},
            {"from": "2025-01-01", "to": "2025-01-31"},
            {"from": "'; DROP TABLE expenses; --"},
        ],
    )
    def test_profile_filter_never_changes_database(self, auth_client, db_path, params):
        before = snapshot(db_path)
        resp, _ = get_page(auth_client, **params)
        assert resp.status_code == 200
        assert snapshot(db_path) == before, "GET /profile must be read-only"

    def test_sql_injection_attempt_leaves_tables_intact(self, auth_client, db_path):
        get_page(auth_client, **{"to": "2026-09-30' OR '1'='1"})
        with closing(_connect(db_path)) as conn:
            n = conn.execute("SELECT COUNT(*) FROM expenses").fetchone()[0]
        assert n == 6


# --------------------------------------------------------------------------- #
# Regression: other pages still work                                           #
# --------------------------------------------------------------------------- #

class TestOtherPagesStillWork:
    @pytest.mark.parametrize("path", ["/", "/login", "/register", "/terms", "/privacy"])
    def test_public_pages_return_200(self, client, path):
        assert client.get(path).status_code == 200, path

    def test_login_with_wrong_password_still_rejected(self, client, user_id):
        resp = client.post(
            "/login", data={"email": "alice@example.com", "password": "wrong-password"}
        )
        assert resp.status_code == 200
        assert "Invalid email or password." in resp.get_data(as_text=True)

    def test_logout_then_profile_redirects_to_login(self, auth_client):
        auth_client.get("/logout")
        resp = auth_client.get("/profile?from=2026-09-01")
        assert resp.status_code == 302
        assert urlparse(resp.headers["Location"]).path == "/login"
