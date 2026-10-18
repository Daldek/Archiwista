"""Local SQLite state database: schema and migrations (A-ADR-029, SPEC 4.3).

The state database (``state.sqlite`` next to ``index.sqlite`` in the user
data directory; never on a share or in a store) keeps what no file on disk
can rebuild: accounts, groups and memberships, roles, project access and the
permission log. An index rebuild never touches it. Its schema therefore
changes by migrations, each one taking ``PRAGMA user_version`` a step
further, all pending ones in one transaction, and never by a rebuild; a
database written by a newer Archiwista is refused rather than changed.

Tables (version 1): ``users``, ``groups``, ``memberships``, ``roles``,
``project_acl`` (key: the project directory after ``realpath``; owner and
visibility), ``project_acl_entries`` (a person or a group per row) and
``permission_log`` (who, when, what, and the state before and after as
JSON). Accounts have no passwords before v0.4.
"""

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from archiwista.errors import StateError
from archiwista.messages import MESSAGES

type Migration = Callable[[sqlite3.Connection], None]
type StateSchemaState = Literal["created", "current", "migrated"]

BUSY_TIMEOUT_MS = 10_000

_VERSION_1 = (
    """
    CREATE TABLE users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        disabled INTEGER NOT NULL DEFAULT 0 CHECK (disabled IN (0, 1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE memberships (
        group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        PRIMARY KEY (group_id, user_id)
    ) WITHOUT ROWID
    """,
    "CREATE INDEX memberships_user ON memberships (user_id)",
    """
    CREATE TABLE roles (
        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK (role IN ('admin', 'store_writer')),
        PRIMARY KEY (user_id, role)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE project_acl (
        project TEXT PRIMARY KEY,
        owner TEXT REFERENCES users(id) ON DELETE SET NULL,
        visibility TEXT NOT NULL
            CHECK (visibility IN ('public', 'users', 'group', 'private')),
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX project_acl_owner ON project_acl (owner)",
    """
    CREATE TABLE project_acl_entries (
        project TEXT NOT NULL REFERENCES project_acl(project) ON DELETE CASCADE,
        user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
        group_id TEXT REFERENCES groups(id) ON DELETE CASCADE,
        CHECK ((user_id IS NULL) <> (group_id IS NULL))
    )
    """,
    "CREATE UNIQUE INDEX project_acl_entries_user"
    " ON project_acl_entries (project, user_id) WHERE user_id IS NOT NULL",
    "CREATE UNIQUE INDEX project_acl_entries_group"
    " ON project_acl_entries (project, group_id) WHERE group_id IS NOT NULL",
    "CREATE INDEX project_acl_entries_by_user ON project_acl_entries (user_id)",
    "CREATE INDEX project_acl_entries_by_group ON project_acl_entries (group_id)",
    """
    CREATE TABLE permission_log (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT NOT NULL,
        before TEXT,
        after TEXT
    )
    """,
)


def _version_1(connection: sqlite3.Connection) -> None:
    """Create the tables of the first schema version."""
    for statement in _VERSION_1:
        connection.execute(statement)


# Migration ``i`` takes a database from user_version ``i`` to ``i + 1``.
MIGRATIONS: tuple[Migration, ...] = (_version_1,)
STATE_SCHEMA_VERSION = len(MIGRATIONS)


def connect(path: Path) -> sqlite3.Connection:
    """Open the state database with Archiwista's connection settings.

    Parameters
    ----------
    path : Path
        The state database; ``initialize`` must have created it.

    Returns
    -------
    sqlite3.Connection
        In autocommit mode (``isolation_level=None``) with foreign keys on
        and full synchronisation: the state cannot be rebuilt, so every
        committed change is flushed to the disk.
    """
    connection = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_MS / 1000,
        isolation_level=None,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def initialize(
    path: Path, *, migrations: Sequence[Migration] = MIGRATIONS
) -> StateSchemaState:
    """Create the state database or bring an older one up to date.

    Parameters
    ----------
    path : Path
        State database; its directory is created when missing.
    migrations : Sequence[Migration], optional
        Schema steps; migration ``i`` takes ``user_version`` ``i`` to
        ``i + 1``.

    Returns
    -------
    StateSchemaState
        ``created`` for a new database, ``current`` when it is up to date,
        ``migrated`` when pending migrations ran (all in one transaction;
        nothing changes if one fails).

    Raises
    ------
    StateError
        The database comes from a newer Archiwista (a higher
        ``user_version``) or a migration broke a reference between tables;
        the database is left unchanged.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    target = len(migrations)
    connection = connect(path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        version = _user_version(connection)
        if version == target:
            return "current"
        _require_known(path, version, target)
        # Migrations may rebuild tables; references are checked once at the end.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            version = _user_version(connection)
            _require_known(path, version, target)
            for migration in migrations[version:]:
                migration(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise StateError(MESSAGES["state_migration_broken"].format(path=path))
            connection.execute(f"PRAGMA user_version = {target}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        return "created" if version == 0 else "migrated"
    finally:
        connection.close()


def _require_known(path: Path, version: int, target: int) -> None:
    if version > target:
        raise StateError(
            MESSAGES["state_newer"].format(path=path, version=version, supported=target)
        )


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])
