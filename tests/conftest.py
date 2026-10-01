import os
import tempfile

import pytest

import database.db as db_module

# app.py runs init_db()/seed_db() at import time. Point the DB at a throwaway
# file BEFORE importing it so the real expense_tracker.db is never touched.
_IMPORT_TMP_DIR = tempfile.mkdtemp(prefix="spendly-import-")
db_module.DB_PATH = os.path.join(_IMPORT_TMP_DIR, "import.db")

from app import app as flask_app  # noqa: E402
from database.db import init_db, seed_db  # noqa: E402


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """Fresh temporary SQLite file per test; schema created, no seed rows."""
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", path)
    init_db()
    return path


@pytest.fixture
def seeded_db_path(tmp_path, monkeypatch):
    """Fresh temporary SQLite file per test with the demo seed data."""
    path = str(tmp_path / "seeded.db")
    monkeypatch.setattr(db_module, "DB_PATH", path)
    init_db()
    seed_db()
    return path


@pytest.fixture
def app(db_path):
    flask_app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
