"""Migrations of the state database: version 4 from 3 (A-ADR-049 decision 14).

Version 4 indexes the action log by target and by the project of a job's
entries. A version 3 database keeps every entry, and a project's activity
reads them through the new indexes.
"""

import sqlite3
from pathlib import Path

from archiwista.state import MIGRATIONS, STATE_SCHEMA_VERSION, StateStore
from archiwista.state import initialize as initialize_state

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


def _version_3_database(path: Path) -> None:
    initialize_state(path, migrations=MIGRATIONS[:3])
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO action_log"
            " (id, at, actor, actor_kind, action, target, outcome, details)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(entry[0], AT, *entry[1:]) for entry in ENTRIES],
        )
    connection.close()


def _schema(path: Path) -> tuple[int, dict[str, str]]:
    with sqlite3.connect(path) as connection:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        rows = connection.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE type = 'index' AND tbl_name = 'action_log'"
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
    _version_3_database(path)
    before, _ = _schema(path)

    # Act
    state = StateStore(path)
    activity = state.project_activity(PROJECT_DIR, "raba")

    # Assert
    after, indexes = _schema(path)
    assert (before, after) == (3, STATE_SCHEMA_VERSION) == (3, 4)
    assert set(indexes) >= {"action_log_target", "action_log_project"}
    assert "(target, at)" in indexes["action_log_target"]
    assert "json_extract(details, '$.project'), at" in indexes["action_log_project"]
    assert [entry.id for entry in state.actions().entries] == [4, 3, 2, 1]
    assert [entry.id for entry in activity.entries] == [2, 1]
    assert activity.next_cursor is None
