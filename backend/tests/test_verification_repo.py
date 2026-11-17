"""Verification storage: optimistic Case File saves and UTF-8 JSON, without a database."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from backend.database import migrations
from backend.database.repositories import verification_repo as repo


class FakeCursor:
    def __init__(self, rowcount):
        self.rowcount = rowcount
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append((sql, params))


class FakeConn:
    def __init__(self, rowcount=1):
        self.cursor_obj = FakeCursor(rowcount)
        self.committed = False
        self.rolled_back = False

    def cursor(self, **_):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def fake_conn(conn):
    @contextmanager
    def _get_conn():
        yield conn

    return _get_conn


def test_first_save_inserts_version_one_with_utf8_json():
    conn = FakeConn()
    with patch.object(repo, "_get_conn", fake_conn(conn)):
        assert repo.save_case_file("C1", {"name": "ಬಸವರಾಜ"}, expected_version=0) == 1
    sql, params = conn.cursor_obj.executed[0]
    assert sql.startswith("INSERT IGNORE INTO verification_case_files")
    assert "ಬಸವರಾಜ" in params[2]  # stored as UTF-8, not \\u escapes
    assert json.loads(params[2]) == {"name": "ಬಸವರಾಜ"}
    assert conn.committed


def test_save_against_stale_version_is_refused():
    conn = FakeConn(rowcount=0)
    with (
        patch.object(repo, "_get_conn", fake_conn(conn)),
        pytest.raises(repo.StaleCaseFileError),
    ):
        repo.save_case_file("C1", {}, expected_version=3)
    sql, params = conn.cursor_obj.executed[0]
    assert "WHERE case_id = %s AND version = %s" in sql
    assert params[-2:] == ("C1", 3)
    assert conn.rolled_back and not conn.committed


def test_verification_tables_are_additive_and_idempotent():
    for table in (
        "verification_case_files",
        "verification_runs",
        "verification_events",
        "due_diligence_reports",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migrations.CREATE_TABLES_SQL
    assert "utf8mb4" in migrations.CREATE_TABLES_SQL.split("verification_case_files")[1]
