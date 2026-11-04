"""Migrations of the state database: version 4 from 3, version 5 from 4.

Version 4 indexes the action log by target and by the project of a job's
entries (A-ADR-049 decision 14). A version 3 database keeps every entry, and
a project's activity reads them through the new indexes. Version 5 adds the
table of the feedback reports ("Zgłoś uwagę"), empty, whose checks keep
Hydrograf's limits; a version 4 database keeps its accounts and its log.
"""

import sqlite3
from pathlib import Path
from typing import TypedDict, cast

import pytest

from archiwista.state import MIGRATIONS, STATE_SCHEMA_VERSION, StateStore
from archiwista.state import initialize as initialize_state


class Report(TypedDict):
    """The values of a feedback report besides its account."""

    message: str
    contact: str | None
    page_url: str | None
    user_agent: str | None
    diagnostics: dict[str, object] | None


AT = "2026-10-30T08:00:00+00:00"
PROJECT_DIR = "/projekty/raba"
# The entries a version 3 database holds: a project's and a job's, another
# project's job, a refusal about the project.
ENTRIES = [
    (1, "local", "local_owner", "project.create", PROJECT_DIR, "ok", None),
    (
        2,
        "ada",
        "user",
        "job.start",
        "j-1",
        "ok",
        '{"kind":"download","project":"raba"}',
    ),
    (
        3,
        "ada",
        "user",
        "job.start",
        "j-2",
        "ok",
        '{"kind":"download","project":"inny"}',
    ),
    (4, "igor", "user", "permission.denied", PROJECT_DIR, "denied", None),
]
# Diagnostics of exactly 100,000 characters as compact JSON: the most a report keeps.
LARGEST_DIAGNOSTICS: dict[str, object] = {"note": "x" * (100_000 - len('{"note":""}'))}
# A report at every limit of Hydrograf's table.
AT_THE_LIMITS: Report = {
    "message": "m" * 5000,
    "contact": "c" * 200,
    "page_url": "u" * 500,
    "user_agent": "a" * 500,
    "diagnostics": LARGEST_DIAGNOSTICS,
}


def _old_database(path: Path, version: int) -> None:
    """Write a database of ``version`` holding an account and ``ENTRIES``."""
    initialize_state(path, migrations=MIGRATIONS[:version])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO users (id, name, disabled, created_at, updated_at)"
            " VALUES ('ada', 'Ada', 0, ?, ?)",
            (AT, AT),
        )
        connection.executemany(
            "INSERT INTO action_log"
            " (id, at, actor, actor_kind, action, target, outcome, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(entry[0], AT, *entry[1:]) for entry in ENTRIES],
        )
    connection.close()


def _schema(path: Path, table: str) -> tuple[int, dict[str, str]]:
    """Return the database's version and the indexes of ``table`` by name."""
    with sqlite3.connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?",
            (table,),
        )
        indexes = dict(rows.fetchall())
    connection.close()
    return version, indexes


def test_state_migrations_version_4_indexes_the_log_of_version_3(
    tmp_path: Path,
) -> None:
    """The two indexes appear, every entry stays, the activity reads them."""
    # Arrange
    path = tmp_path / "state.sqlite"
    _old_database(path, 3)
    before, _ = _schema(path, "action_log")

    # Act
    state = StateStore(path)
    activity = state.project_activity(PROJECT_DIR, "raba")

    # Assert
    after, indexes = _schema(path, "action_log")
    assert (before, after) == (3, STATE_SCHEMA_VERSION)
    assert set(indexes) >= {"action_log_target", "action_log_project"}
    assert "(target, at)" in indexes["action_log_target"]
    assert "json_extract(details, '$.project'), at" in indexes["action_log_project"]
    assert [entry.id for entry in state.actions().entries] == [4, 3, 2, 1]
    assert [entry.id for entry in activity.entries] == [2, 1]
    assert activity.next_cursor is None


def test_state_migrations_version_5_adds_the_feedback_of_version_4(
    tmp_path: Path,
) -> None:
    """An empty table of reports appears; the account and the log stay."""
    # Arrange
    path = tmp_path / "state.sqlite"
    _old_database(path, 4)
    before, _ = _schema(path, "feedback")

    # Act
    state = StateStore(path)
    empty = state.feedback(limit=10)
    kept = state.add_feedback(user_id="ada", **AT_THE_LIMITS)

    # Assert
    after, indexes = _schema(path, "feedback")
    assert (before, after) == (4, STATE_SCHEMA_VERSION)
    assert "feedback_created_at" in indexes
    assert (empty.items, empty.total, empty.unread) == ((), 0, 0)
    assert state.user("ada") is not None
    assert [entry.id for entry in state.actions().entries] == [4, 3, 2, 1]
    assert (kept.user_id, kept.is_read) == ("ada", False)
    assert kept.diagnostics == LARGEST_DIAGNOSTICS
    assert state.feedback(limit=10).items == (kept,)


@pytest.mark.parametrize(
    "field, value",
    [
        ("message", ""),
        ("message", "m" * 5001),
        ("contact", "c" * 201),
        ("page_url", "u" * 501),
        ("user_agent", "a" * 501),
        ("diagnostics", {"note": "x" * 100_000}),
    ],
)
def test_state_migrations_version_5_checks_keep_the_feedback_limits(
    tmp_path: Path, field: str, value: object
) -> None:
    """A report over a limit of Hydrograf's table is refused by the table itself."""
    # Arrange
    state = StateStore(tmp_path / "state.sqlite")
    report = cast(Report, {**AT_THE_LIMITS, field: value})

    # Act / Assert
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        state.add_feedback(user_id=None, **report)
    assert state.feedback(limit=10).total == 0
