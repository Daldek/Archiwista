"""Local SQLite state database: schema and migrations (A-ADR-029, SPEC 4.3).

The state database (``state.sqlite`` next to ``index.sqlite`` in the user
data directory; never on a share or in a store) keeps what no file on disk
can rebuild: accounts, groups and memberships, roles, project access,
passwords, preferences, the action log and the feedback reports. An index
rebuild never touches it. Its schema therefore changes by migrations, each
one taking ``PRAGMA user_version`` a step further, all pending ones in one
transaction, and never by a rebuild; a database written by a newer
Archiwista is refused rather than changed.

Tables (version 1): ``users`` (with ``sessions_revoked_at``, the time before
which the account's sessions end), ``groups``, ``memberships``, ``roles``,
``project_acl`` (key: the project directory after ``realpath``; owner and
visibility), ``project_acl_entries`` (a person or a group per row),
``passwords`` (Argon2id hashes, used by ``archiwista.auth.passwords`` and
copied only by the backup), ``preferences`` per principal, ``action_log``
(who, when, how the actor acted: the owner, a person or an agent, the label
of its session, the client address, what, the outcome, the state before and
after and details as JSON), which a trigger keeps append-only and which is
indexed by target and by the project in the details of a job's entries (a
project's activity, A-ADR-049 decision 14), and ``feedback``: the reports
people send with "Zgłoś uwagę" (the text, an optional contact, the page, the
browser, optional diagnostics as JSON, whether an administrator has read it,
and the account that sent it, ``NULL`` for the owner of a local
installation), with the limits of Hydrograf's table as checks.

Until every format went back to version 1 for the time before the first
release (Nogat REL-1.4, ECO-072), this schema was numbered 5
(``RENUMBERED_VERSION``): a database of that number holds the same tables,
so it is read as version 1 and renumbered when it is opened.
"""

import sqlite3
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from archiwista.errors import StateError
from archiwista.messages import message
from archiwista.paths import private_directory
from archiwista.wal import use_wal

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
        updated_at TEXT NOT NULL,
        sessions_revoked_at TEXT
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
    CREATE TABLE passwords (
        user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        hash TEXT NOT NULL,
        set_at TEXT NOT NULL,
        set_by TEXT NOT NULL,
        temporary INTEGER NOT NULL CHECK (temporary IN (0, 1)),
        expires_at TEXT
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE action_log (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        actor_kind TEXT,
        session TEXT,
        client TEXT,
        action TEXT NOT NULL,
        target TEXT NOT NULL,
        outcome TEXT NOT NULL CHECK (outcome IN ('ok', 'denied', 'failed')),
        before TEXT,
        after TEXT,
        details TEXT
    )
    """,
    "CREATE INDEX action_log_at ON action_log (at)",
    "CREATE INDEX action_log_actor ON action_log (actor, at)",
    "CREATE INDEX action_log_action ON action_log (action, at)",
    "CREATE INDEX action_log_target ON action_log (target, at)",
    """
    CREATE INDEX action_log_project
        ON action_log (json_extract(details, '$.project'), at)
    """,
    """
    CREATE TRIGGER action_log_append_only BEFORE UPDATE ON action_log
    BEGIN SELECT RAISE(ABORT, 'the action log is append-only'); END
    """,
    """
    CREATE TABLE preferences (
        principal TEXT PRIMARY KEY,
        document TEXT NOT NULL,
        updated_at TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE feedback (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        user_id TEXT,
        message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 5000),
        contact TEXT CHECK (length(contact) <= 200),
        page_url TEXT CHECK (length(page_url) <= 500),
        user_agent TEXT CHECK (length(user_agent) <= 500),
        diagnostics TEXT
            CHECK (json_valid(diagnostics) AND length(diagnostics) <= 100000),
        is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1))
    )
    """,
    "CREATE INDEX feedback_created_at ON feedback (created_at DESC, id DESC)",
)


def _version_1(connection: sqlite3.Connection) -> None:
    """Create the tables of the first schema version."""
    for statement in _VERSION_1:
        connection.execute(statement)


# Migration ``i`` takes a database from user_version ``i`` to ``i + 1``.
MIGRATIONS: tuple[Migration, ...] = (_version_1,)
STATE_SCHEMA_VERSION = len(MIGRATIONS)
# The number of version 1 before every format went back to version 1 (Nogat
# REL-1.4): a database of this number holds the tables of version 1.
RENUMBERED_VERSION = 5


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
        State database; its directory is created when missing, and on POSIX
        closed to other accounts (``0700``, ``private_directory``).
    migrations : Sequence[Migration], optional
        Schema steps; migration ``i`` takes ``user_version`` ``i`` to
        ``i + 1``.

    Returns
    -------
    StateSchemaState
        ``created`` for a new database, ``current`` when it is up to date
        (a database of ``RENUMBERED_VERSION`` is renumbered 1, nothing else
        changes), ``migrated`` when pending migrations ran (all in one
        transaction; nothing changes if one fails).

    Raises
    ------
    StateError
        The database comes from a newer Archiwista (a higher
        ``user_version``) or a migration broke a reference between tables;
        the database is left unchanged.
    """
    private_directory(path.parent)
    target = len(migrations)
    connection = connect(path)
    try:
        use_wal(connection, timeout_ms=BUSY_TIMEOUT_MS)
        if _user_version(connection) == target:
            return "current"
        _require_known(path, schema_version(connection, target=target), target)
        # Migrations may rebuild tables; references are checked once at the end.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN IMMEDIATE")
        try:
            version = schema_version(connection, target=target)
            _require_known(path, version, target)
            for migration in migrations[version:]:
                migration(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise StateError(message("state.migration_broken", path=path))
            connection.execute(f"PRAGMA user_version = {target}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        if version == 0:
            return "created"
        return "current" if version == target else "migrated"
    finally:
        connection.close()


def schema_version(
    connection: sqlite3.Connection, *, target: int = STATE_SCHEMA_VERSION
) -> int:
    """Return the schema version of an open state database.

    Parameters
    ----------
    connection : sqlite3.Connection
        The state database.
    target : int, default STATE_SCHEMA_VERSION
        The newest schema version the caller knows.

    Returns
    -------
    int
        Its ``PRAGMA user_version``, except that ``RENUMBERED_VERSION`` above
        ``target`` is 1: such a database was written before the renumbering
        and holds the tables of version 1.
    """
    version = _user_version(connection)
    return 1 if version == RENUMBERED_VERSION > target else version


def _require_known(path: Path, version: int, target: int) -> None:
    if version > target:
        raise StateError(
            message("state.newer", path=path, version=version, supported=target)
        )


def _user_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])
