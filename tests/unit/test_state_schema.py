"""The schema of the state database: version 1, and the number 5 before it.

Until every format went back to version 1 (Nogat REL-1.4), the schema of
version 1 was numbered 5. A database of that number opens as version 1 with
its accounts, log and reports, and ``archiwista doctor`` reads it without
changing it. The table of the feedback reports ("Zgłoś uwagę") keeps
Hydrograf's limits by its checks.
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict, cast

import pytest

from archiwista.state import (
    STATE_SCHEMA_VERSION,
    FeedbackRecord,
    StateStore,
    read_users,
)


class Report(TypedDict):
    """The values of a feedback report besides its account."""

    message: str
    contact: str | None
    page_url: str | None
    user_agent: str | None
    diagnostics: dict[str, object] | None


AT = "2026-10-30T08:00:00+00:00"
PROJECT_DIR = "/projekty/raba"
# The entries of the log: a project's and a job's, another project's job, a
# refusal about the project.
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


def _numbered_5(path: Path) -> FeedbackRecord:
    """Write a database as one written before the renumbering; return its report."""
    report = StateStore(path).add_feedback(user_id="ada", **AT_THE_LIMITS)
    with closing(sqlite3.connect(path)) as connection, connection:
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
        connection.execute("PRAGMA user_version = 5")
    return report


def _user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def test_state_schema_initialize_renumbers_a_database_of_5(tmp_path: Path) -> None:
    """It opens as the current version; the accounts, log and reports stay."""
    # Arrange
    path = tmp_path / "state.sqlite"
    report = _numbered_5(path)

    # Act
    state = StateStore(path)
    activity = state.project_activity(PROJECT_DIR, "raba")

    # Assert
    assert _user_version(path) == STATE_SCHEMA_VERSION
    assert state.user("ada") is not None
    assert [entry.id for entry in state.actions().entries] == [4, 3, 2, 1]
    assert [entry.id for entry in activity.entries] == [2, 1]
    assert state.feedback(limit=10).items == (report,)


def test_state_store_read_users_reads_a_database_of_5_unchanged(
    tmp_path: Path,
) -> None:
    """``archiwista doctor`` reads its accounts before a start renumbers it."""
    # Arrange
    path = tmp_path / "state.sqlite"
    _numbered_5(path)
    before = path.read_bytes()

    # Act
    users = read_users(path)

    # Assert
    assert users is not None
    assert [user.id for user in users] == ["ada"]
    assert path.read_bytes() == before


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
def test_state_schema_feedback_checks_keep_the_limits(
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
