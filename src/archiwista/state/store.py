"""State database access: accounts, groups, roles, project access and their log.

``StateStore`` reads and changes the state database (``schema``). Every
change runs in one transaction together with its ``permission_log`` entries:
who (``actor``, a principal id, with its kind and session label), when, what
(``action`` and ``target``) and
the state before and after. Removing an account or a group also takes it out
of memberships and project access entries (an account's projects are left
without an owner); each group or project changed that way gets its own
entry. A request that changes nothing writes nothing.

``StateStore`` keeps the data rules (ids, names, known people and groups,
entries that fit the visibility) but decides no permissions: that is
``archiwista.auth.authorize``, called by the services before any change.
"""

import json
import re
import sqlite3
from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from archiwista.auth import LOCAL_PRINCIPAL_ID, Principal, PrincipalKind
from archiwista.errors import (
    ConflictError,
    InvalidChangeError,
    NotFoundError,
    StateError,
)
from archiwista.messages import message
from archiwista.state.schema import connect, initialize

type Role = Literal["admin", "store_writer"]
type Visibility = Literal["public", "users", "group", "private"]
type ChangeAction = Literal[
    "user.add",
    "user.update",
    "user.remove",
    "group.add",
    "group.members",
    "group.remove",
    "project.access",
]

ROLES: tuple[Role, ...] = ("admin", "store_writer")
VISIBILITIES: tuple[Visibility, ...] = ("public", "users", "group", "private")
# Account and group ids: lowercase letters, digits, ".", "_" and "-".
ID_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
NAME_MAX_LENGTH = 200
# ``local`` is the owner of a local installation, never an account.
RESERVED_USER_IDS = frozenset({LOCAL_PRINCIPAL_ID})

_ID = re.compile(ID_PATTERN)
_IDS = "SELECT value FROM json_each(?)"
_USER_SELECT = """
SELECT u.id, u.name, u.disabled, u.created_at, u.updated_at,
    (SELECT json_group_array(role) FROM
        (SELECT role FROM roles r WHERE r.user_id = u.id ORDER BY role)) AS roles,
    (SELECT json_group_array(group_id) FROM
        (SELECT group_id FROM memberships m WHERE m.user_id = u.id
         ORDER BY group_id)) AS groups
FROM users u
"""
_GROUP_SELECT = """
SELECT g.id, g.name, g.created_at, g.updated_at,
    (SELECT json_group_array(user_id) FROM
        (SELECT user_id FROM memberships m WHERE m.group_id = g.id
         ORDER BY user_id)) AS members
FROM groups g
"""
_ACCESS_SELECT = """
SELECT a.project, a.owner, a.visibility, a.updated_at,
    (SELECT json_group_array(user_id) FROM
        (SELECT user_id FROM project_acl_entries e
         WHERE e.project = a.project AND e.user_id IS NOT NULL
         ORDER BY user_id)) AS users,
    (SELECT json_group_array(group_id) FROM
        (SELECT group_id FROM project_acl_entries e
         WHERE e.project = a.project AND e.group_id IS NOT NULL
         ORDER BY group_id)) AS groups
FROM project_acl a
"""


@dataclass(frozen=True, slots=True)
class UserRecord:
    """An account of a person; accounts cannot sign in before v0.4.

    Attributes
    ----------
    id : str
        Stable id (``anna.nowak``), the ``Principal.id`` of the person.
    name : str
        Display name.
    roles : tuple[Role, ...]
        ``admin`` and/or ``store_writer``, sorted; none for a regular user.
    groups : tuple[str, ...]
        Ids of the groups the person belongs to, sorted.
    disabled : bool
        A disabled account acts nowhere.
    created_at, updated_at : datetime
        Creation and last change (UTC).
    """

    id: str
    name: str
    roles: tuple[Role, ...]
    groups: tuple[str, ...]
    disabled: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class GroupRecord:
    """A group of people, e.g. a department.

    Attributes
    ----------
    id : str
        Stable id (``hydro``).
    name : str
        Display name.
    members : tuple[str, ...]
        Account ids, sorted.
    created_at, updated_at : datetime
        Creation and last change (UTC).
    """

    id: str
    name: str
    members: tuple[str, ...]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectAccessRecord:
    """The access entry of one project.

    Attributes
    ----------
    project : str
        Project key: its directory after ``realpath`` (``access_key``).
    owner : str or None
        Account owning the project; ``None``: only administrators manage it.
    visibility : Visibility
        ``public`` (everyone), ``users`` (the listed people), ``group``
        (members of the listed groups) or ``private`` (the owner only);
        administrators see every project.
    users, groups : tuple[str, ...]
        Listed account ids (``users``) or group ids (``group``), sorted.
    updated_at : datetime
        Last change (UTC).
    """

    project: str
    owner: str | None
    visibility: Visibility
    users: tuple[str, ...]
    groups: tuple[str, ...]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class PermissionChange:
    """One entry of the permission log.

    Attributes
    ----------
    id : int
        Order of the entry.
    at : datetime
        When (UTC).
    actor : str
        Who: the acting principal's id (``local`` in local mode).
    actor_kind : {"local_owner", "user", "agent"} or None
        How: the owner, a person, or an agent acting for ``actor``; ``None``
        for entries written before Archiwista recorded it.
    session : str or None
        Label of the session the change came from; ``None`` at the terminal.
    action : ChangeAction
        What: ``user.add``, ``user.update``, ``user.remove``,
        ``group.add``, ``group.members``, ``group.remove`` or
        ``project.access``.
    target : str
        The account id, group id or project key changed.
    before, after : dict[str, object] or None
        The state before and after; ``None`` before an addition and after a
        removal.
    """

    id: int
    at: datetime
    actor: str
    actor_kind: PrincipalKind | None
    session: str | None
    action: ChangeAction
    target: str
    before: dict[str, object] | None
    after: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """The whole state database, read in one transaction (backups)."""

    users: tuple[UserRecord, ...]
    groups: tuple[GroupRecord, ...]
    projects: tuple[ProjectAccessRecord, ...]
    changes: tuple[PermissionChange, ...]


class StateStore:
    """Read and change the state database.

    Parameters
    ----------
    path : Path
        The state database; created, or migrated from an older version,
        when needed.

    Raises
    ------
    StateError
        The database comes from a newer Archiwista.

    Notes
    -----
    Safe to share between threads: each call opens its own connection.
    """

    def __init__(self, path: Path) -> None:
        initialize(path)
        self.path = path

    # Reading.

    def users(self) -> tuple[UserRecord, ...]:
        """Return every account ordered by id."""
        with self._read() as connection:
            return _users(connection)

    def user(self, user_id: str) -> UserRecord | None:
        """Return an account, or ``None`` if unknown."""
        with self._read() as connection:
            return _user(connection, user_id)

    def groups(self) -> tuple[GroupRecord, ...]:
        """Return every group ordered by id."""
        with self._read() as connection:
            return _groups(connection)

    def group(self, group_id: str) -> GroupRecord | None:
        """Return a group, or ``None`` if unknown."""
        with self._read() as connection:
            return _group(connection, group_id)

    def project_accesses(self) -> tuple[ProjectAccessRecord, ...]:
        """Return the access entries of every project ordered by key."""
        with self._read() as connection:
            return _accesses(connection)

    def project_access(self, project: str) -> ProjectAccessRecord | None:
        """Return a project's access entry, or ``None`` without one.

        Parameters
        ----------
        project : str
            Project key (``access_key`` of its directory).
        """
        with self._read() as connection:
            return _access(connection, project)

    def changes(self) -> tuple[PermissionChange, ...]:
        """Return the permission log, oldest entry first."""
        with self._read() as connection:
            return _changes(connection)

    def snapshot(self) -> StateSnapshot:
        """Return everything the database holds, as one consistent read."""
        with self._read() as connection:
            return StateSnapshot(
                users=_users(connection),
                groups=_groups(connection),
                projects=_accesses(connection),
                changes=_changes(connection),
            )

    def is_empty(self) -> bool:
        """Return whether the database holds no account, group, entry or log."""
        with self._read() as connection:
            return _is_empty(connection)

    # Accounts.

    def add_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        roles: Collection[Role] = (),
        actor: Principal,
    ) -> UserRecord:
        """Create an account.

        Parameters
        ----------
        user_id : str
            New id: lowercase letters, digits, ``.``, ``_`` and ``-``, at
            most 64 characters; not ``local``.
        name : str or None, optional
            Display name; the id when omitted.
        roles : Collection[Role], optional
            ``admin`` and/or ``store_writer``.
        actor : Principal
            Who makes the change (for the log).

        Raises
        ------
        InvalidChangeError
            A malformed or reserved id, an empty name or an unknown role.
        ConflictError
            The id is taken.
        """
        _require_user_id(user_id)
        display = _require_name(user_id if name is None else name)
        granted = _require_roles(roles)
        with self._write() as connection:
            if _user(connection, user_id) is not None:
                raise ConflictError(message("state.user_exists", id=user_id))
            now = _now()
            connection.execute(
                "INSERT INTO users (id, name, disabled, created_at, updated_at)"
                " VALUES (?, ?, 0, ?, ?)",
                (user_id, display, now, now),
            )
            _insert_roles(connection, user_id, granted)
            after = _existing_user(connection, user_id)
            _log(connection, actor, "user.add", user_id, None, _user_state(after), now)
        return after

    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        roles: Collection[Role] | None = None,
        disabled: bool | None = None,
        actor: Principal,
    ) -> UserRecord:
        """Change an account's name, roles or whether it is disabled.

        Parameters
        ----------
        user_id : str
            The account.
        name : str or None, optional
            New display name; unchanged when omitted.
        roles : Collection[Role] or None, optional
            The complete new set of roles; unchanged when omitted.
        disabled : bool or None, optional
            Disable or enable the account; unchanged when omitted.
        actor : Principal
            Who makes the change.

        Raises
        ------
        NotFoundError
            Unknown account.
        InvalidChangeError
            An empty name or an unknown role.
        """
        display = None if name is None else _require_name(name)
        granted = None if roles is None else _require_roles(roles)
        with self._write() as connection:
            before = _existing_user(connection, user_id)
            changed = (
                (display is not None and display != before.name)
                or (granted is not None and granted != before.roles)
                or (disabled is not None and disabled != before.disabled)
            )
            if not changed:
                return before
            now = _now()
            connection.execute(
                "UPDATE users SET name = ?, disabled = ?, updated_at = ? WHERE id = ?",
                (
                    before.name if display is None else display,
                    int(before.disabled if disabled is None else disabled),
                    now,
                    user_id,
                ),
            )
            if granted is not None:
                connection.execute("DELETE FROM roles WHERE user_id = ?", (user_id,))
                _insert_roles(connection, user_id, granted)
            after = _existing_user(connection, user_id)
            _log(
                connection,
                actor,
                "user.update",
                user_id,
                _user_state(before),
                _user_state(after),
                now,
            )
        return after

    def remove_user(self, user_id: str, *, actor: Principal) -> None:
        """Remove an account, its roles, memberships and access entries.

        Projects it owned are left without an owner, which only narrows who
        sees them; every group and project changed is logged too.

        Raises
        ------
        NotFoundError
            Unknown account.
        """
        with self._write() as connection:
            before = _existing_user(connection, user_id)
            groups = _groups(
                connection, f"g.id IN ({_IDS})", (json.dumps(list(before.groups)),)
            )
            projects = _accesses(
                connection,
                "a.owner = ? OR a.project IN"
                " (SELECT project FROM project_acl_entries WHERE user_id = ?)",
                (user_id, user_id),
            )
            now = _now()
            connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
            _log(
                connection,
                actor,
                "user.remove",
                user_id,
                _user_state(before),
                None,
                now,
            )
            _log_cascade(connection, actor, groups, projects, now)

    # Groups.

    def add_group(
        self,
        group_id: str,
        *,
        name: str | None = None,
        members: Collection[str] = (),
        actor: Principal,
    ) -> GroupRecord:
        """Create a group, optionally with its members.

        Raises
        ------
        InvalidChangeError
            A malformed id, an empty name or unknown members.
        ConflictError
            The id is taken.
        """
        _require_group_id(group_id)
        display = _require_name(group_id if name is None else name)
        wanted = _distinct(members)
        with self._write() as connection:
            if _group(connection, group_id) is not None:
                raise ConflictError(message("state.group_exists", id=group_id))
            _require_users(connection, wanted)
            now = _now()
            connection.execute(
                "INSERT INTO groups (id, name, created_at, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (group_id, display, now, now),
            )
            _insert_members(connection, group_id, wanted)
            after = _existing_group(connection, group_id)
            _log(
                connection, actor, "group.add", group_id, None, _group_state(after), now
            )
        return after

    def set_members(
        self, group_id: str, members: Collection[str], *, actor: Principal
    ) -> GroupRecord:
        """Replace a group's members.

        Raises
        ------
        NotFoundError
            Unknown group.
        InvalidChangeError
            Unknown members.
        """
        wanted = _distinct(members)
        with self._write() as connection:
            before = _existing_group(connection, group_id)
            _require_users(connection, wanted)
            if wanted == before.members:
                return before
            now = _now()
            connection.execute(
                "DELETE FROM memberships WHERE group_id = ?", (group_id,)
            )
            _insert_members(connection, group_id, wanted)
            connection.execute(
                "UPDATE groups SET updated_at = ? WHERE id = ?", (now, group_id)
            )
            after = _existing_group(connection, group_id)
            _log(
                connection,
                actor,
                "group.members",
                group_id,
                _group_state(before),
                _group_state(after),
                now,
            )
        return after

    def remove_group(self, group_id: str, *, actor: Principal) -> None:
        """Remove a group, its memberships and its project access entries.

        Raises
        ------
        NotFoundError
            Unknown group.
        """
        with self._write() as connection:
            before = _existing_group(connection, group_id)
            projects = _accesses(
                connection,
                "a.project IN"
                " (SELECT project FROM project_acl_entries WHERE group_id = ?)",
                (group_id,),
            )
            now = _now()
            connection.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            _log(
                connection,
                actor,
                "group.remove",
                group_id,
                _group_state(before),
                None,
                now,
            )
            _log_cascade(connection, actor, (), projects, now)

    # Project access.

    def set_project_access(
        self,
        project: str,
        *,
        owner: str | None,
        visibility: Visibility,
        users: Collection[str] = (),
        groups: Collection[str] = (),
        actor: Principal,
    ) -> ProjectAccessRecord:
        """Set a project's owner, visibility and listed people or groups.

        Parameters
        ----------
        project : str
            Project key (``access_key`` of its directory).
        owner : str or None
            Owning account, or ``None``.
        visibility : Visibility
            ``public``, ``users``, ``group`` or ``private``.
        users : Collection[str], optional
            People who see the project; required for ``users`` and only
            allowed there.
        groups : Collection[str], optional
            Groups whose members see the project; required for ``group``
            and only allowed there.
        actor : Principal
            Who makes the change.

        Raises
        ------
        InvalidChangeError
            An unknown visibility, owner, person or group, or entries that do
            not fit the visibility.
        """
        people = _distinct(users)
        teams = _distinct(groups)
        _require_entries(visibility, people, teams, allow_empty=False)
        with self._write() as connection:
            _require_users(connection, (*people, *((owner,) if owner else ())))
            _require_groups(connection, teams)
            before = _access(connection, project)
            if before is not None and (
                before.owner,
                before.visibility,
                before.users,
                before.groups,
            ) == (owner, visibility, people, teams):
                return before
            now = _now()
            connection.execute(
                "INSERT INTO project_acl (project, owner, visibility, updated_at)"
                " VALUES (?, ?, ?, ?) ON CONFLICT (project) DO UPDATE SET"
                " owner = excluded.owner, visibility = excluded.visibility,"
                " updated_at = excluded.updated_at",
                (project, owner, visibility, now),
            )
            connection.execute(
                "DELETE FROM project_acl_entries WHERE project = ?", (project,)
            )
            _insert_entries(connection, project, people, teams)
            after = _existing_access(connection, project)
            _log(
                connection,
                actor,
                "project.access",
                project,
                None if before is None else _access_state(before),
                _access_state(after),
                now,
            )
        return after

    # Backups.

    def restore(self, snapshot: StateSnapshot) -> None:
        """Fill an empty database from a backup, keeping times and the log.

        Raises
        ------
        StateError
            The database is not empty, or the backup is inconsistent (e.g.
            a member without an account); nothing is written.
        """
        with self._write() as connection:
            if not _is_empty(connection):
                raise StateError(
                    message("state.import_not_empty", path=self.path),
                    code="conflict",
                    reason="state_not_empty",
                )
            try:
                _restore(connection, snapshot)
            except (sqlite3.IntegrityError, InvalidChangeError) as error:
                raise StateError(
                    message("state.import_inconsistent", detail=error),
                    code="data_error",
                    reason="invalid_backup",
                ) from error

    # Connections.

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection = connect(self.path)
        try:
            connection.execute("BEGIN")
            try:
                yield connection
            finally:
                connection.execute("ROLLBACK")
        finally:
            connection.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        connection = connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
        finally:
            connection.close()


# Validation.


def _require_user_id(user_id: str) -> None:
    if _ID.fullmatch(user_id) is None:
        raise InvalidChangeError(message("state.id_pattern", id=user_id))
    if user_id in RESERVED_USER_IDS:
        raise InvalidChangeError(message("state.user_id_reserved", id=user_id))


def _require_group_id(group_id: str) -> None:
    if _ID.fullmatch(group_id) is None:
        raise InvalidChangeError(message("state.id_pattern", id=group_id))


def _require_name(name: str) -> str:
    stripped = name.strip()
    if not stripped or len(stripped) > NAME_MAX_LENGTH:
        raise InvalidChangeError(message("state.name_invalid", limit=NAME_MAX_LENGTH))
    return stripped


def _require_roles(roles: Collection[str]) -> tuple[Role, ...]:
    unknown = sorted(set(roles) - set(ROLES))
    if unknown:
        raise InvalidChangeError(
            message("state.roles_unknown", roles=", ".join(unknown))
        )
    return tuple(role for role in ROLES if role in roles)


def _require_entries(
    visibility: str,
    users: tuple[str, ...],
    groups: tuple[str, ...],
    *,
    allow_empty: bool,
) -> None:
    """Require entries that fit the visibility.

    ``users`` lists people and ``group`` groups (at least one, unless
    ``allow_empty``: removing an account or a group may empty a list);
    ``public`` and ``private`` list nobody.
    """
    if visibility not in VISIBILITIES:
        raise InvalidChangeError(
            message("state.visibility_unknown", visibility=visibility)
        )
    if visibility == "users" and (groups or not (users or allow_empty)):
        raise InvalidChangeError(message("state.entries_users"))
    if visibility == "group" and (users or not (groups or allow_empty)):
        raise InvalidChangeError(message("state.entries_group"))
    if visibility in ("public", "private") and (users or groups):
        raise InvalidChangeError(message("state.entries_none", visibility=visibility))


def _require_users(connection: sqlite3.Connection, ids: Iterable[str]) -> None:
    unknown = _unknown(connection, "users", ids)
    if unknown:
        raise InvalidChangeError(message("state.users_unknown", ids=", ".join(unknown)))


def _require_groups(connection: sqlite3.Connection, ids: Iterable[str]) -> None:
    unknown = _unknown(connection, "groups", ids)
    if unknown:
        raise InvalidChangeError(
            message("state.groups_unknown", ids=", ".join(unknown))
        )


def _unknown(
    connection: sqlite3.Connection,
    table: Literal["users", "groups"],
    ids: Iterable[str],
) -> list[str]:
    wanted = sorted(set(ids))
    if not wanted:
        return []
    known = {
        str(row[0])
        for row in connection.execute(
            f"SELECT id FROM {table} WHERE id IN ({_IDS})", (json.dumps(wanted),)
        ).fetchall()
    }
    return [item for item in wanted if item not in known]


def _distinct(ids: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(ids)))


# Reading rows.


def _users(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
) -> tuple[UserRecord, ...]:
    rows = connection.execute(
        f"{_USER_SELECT} WHERE {condition} ORDER BY u.id", params
    ).fetchall()
    return tuple(
        UserRecord(
            id=row["id"],
            name=row["name"],
            roles=tuple(json.loads(row["roles"])),
            groups=tuple(json.loads(row["groups"])),
            disabled=bool(row["disabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    )


def _user(connection: sqlite3.Connection, user_id: str) -> UserRecord | None:
    found = _users(connection, "u.id = ?", (user_id,))
    return found[0] if found else None


def _existing_user(connection: sqlite3.Connection, user_id: str) -> UserRecord:
    user = _user(connection, user_id)
    if user is None:
        raise NotFoundError(message("state.user_not_found", id=user_id))
    return user


def _groups(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
) -> tuple[GroupRecord, ...]:
    rows = connection.execute(
        f"{_GROUP_SELECT} WHERE {condition} ORDER BY g.id", params
    ).fetchall()
    return tuple(
        GroupRecord(
            id=row["id"],
            name=row["name"],
            members=tuple(json.loads(row["members"])),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    )


def _group(connection: sqlite3.Connection, group_id: str) -> GroupRecord | None:
    found = _groups(connection, "g.id = ?", (group_id,))
    return found[0] if found else None


def _existing_group(connection: sqlite3.Connection, group_id: str) -> GroupRecord:
    group = _group(connection, group_id)
    if group is None:
        raise NotFoundError(message("state.group_not_found", id=group_id))
    return group


def _accesses(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
) -> tuple[ProjectAccessRecord, ...]:
    rows = connection.execute(
        f"{_ACCESS_SELECT} WHERE {condition} ORDER BY a.project", params
    ).fetchall()
    return tuple(
        ProjectAccessRecord(
            project=row["project"],
            owner=row["owner"],
            visibility=row["visibility"],
            users=tuple(json.loads(row["users"])),
            groups=tuple(json.loads(row["groups"])),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    )


def _access(connection: sqlite3.Connection, project: str) -> ProjectAccessRecord | None:
    found = _accesses(connection, "a.project = ?", (project,))
    return found[0] if found else None


def _existing_access(
    connection: sqlite3.Connection, project: str
) -> ProjectAccessRecord:
    access = _access(connection, project)
    if access is None:  # pragma: no cover - written in the same transaction
        raise NotFoundError(project)
    return access


def _changes(connection: sqlite3.Connection) -> tuple[PermissionChange, ...]:
    rows = connection.execute(
        "SELECT id, at, actor, actor_kind, session, action, target, before, after"
        " FROM permission_log ORDER BY id"
    ).fetchall()
    return tuple(
        PermissionChange(
            id=int(row["id"]),
            at=datetime.fromisoformat(row["at"]),
            actor=row["actor"],
            actor_kind=row["actor_kind"],
            session=row["session"],
            action=row["action"],
            target=row["target"],
            before=None if row["before"] is None else json.loads(row["before"]),
            after=None if row["after"] is None else json.loads(row["after"]),
        )
        for row in rows
    )


def _is_empty(connection: sqlite3.Connection) -> bool:
    (filled,) = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM users) OR EXISTS (SELECT 1 FROM groups)"
        " OR EXISTS (SELECT 1 FROM project_acl)"
        " OR EXISTS (SELECT 1 FROM permission_log)"
    ).fetchone()
    return not filled


# Writing rows.


def _insert_roles(
    connection: sqlite3.Connection, user_id: str, roles: Iterable[str]
) -> None:
    connection.executemany(
        "INSERT INTO roles (user_id, role) VALUES (?, ?)",
        [(user_id, role) for role in roles],
    )


def _insert_members(
    connection: sqlite3.Connection, group_id: str, members: Iterable[str]
) -> None:
    connection.executemany(
        "INSERT INTO memberships (group_id, user_id) VALUES (?, ?)",
        [(group_id, member) for member in members],
    )


def _insert_entries(
    connection: sqlite3.Connection,
    project: str,
    users: Iterable[str],
    groups: Iterable[str],
) -> None:
    connection.executemany(
        "INSERT INTO project_acl_entries (project, user_id, group_id) VALUES (?, ?, ?)",
        [(project, user, None) for user in users]
        + [(project, None, group) for group in groups],
    )


def _restore(connection: sqlite3.Connection, snapshot: StateSnapshot) -> None:
    for user in snapshot.users:
        _require_user_id(user.id)
        connection.execute(
            "INSERT INTO users (id, name, disabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                user.id,
                _require_name(user.name),
                int(user.disabled),
                _iso(user.created_at),
                _iso(user.updated_at),
            ),
        )
        _insert_roles(connection, user.id, _require_roles(user.roles))
    for group in snapshot.groups:
        _require_group_id(group.id)
        connection.execute(
            "INSERT INTO groups (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (
                group.id,
                _require_name(group.name),
                _iso(group.created_at),
                _iso(group.updated_at),
            ),
        )
        _insert_members(connection, group.id, _distinct(group.members))
    for access in snapshot.projects:
        people, teams = _distinct(access.users), _distinct(access.groups)
        _require_entries(access.visibility, people, teams, allow_empty=True)
        connection.execute(
            "INSERT INTO project_acl (project, owner, visibility, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (access.project, access.owner, access.visibility, _iso(access.updated_at)),
        )
        _insert_entries(connection, access.project, people, teams)
    connection.executemany(
        "INSERT INTO permission_log"
        " (id, at, actor, actor_kind, session, action, target, before, after)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                change.id,
                _iso(change.at),
                change.actor,
                change.actor_kind,
                change.session,
                change.action,
                change.target,
                _json(change.before),
                _json(change.after),
            )
            for change in snapshot.changes
        ],
    )


# Log.


def _log(
    connection: sqlite3.Connection,
    actor: Principal,
    action: ChangeAction,
    target: str,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    at: str,
) -> None:
    connection.execute(
        "INSERT INTO permission_log"
        " (at, actor, actor_kind, session, action, target, before, after)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            at,
            actor.id,
            actor.kind,
            actor.session,
            action,
            target,
            _json(before),
            _json(after),
        ),
    )


def _log_cascade(
    connection: sqlite3.Connection,
    actor: Principal,
    groups: Iterable[GroupRecord],
    projects: Iterable[ProjectAccessRecord],
    at: str,
) -> None:
    """Log the groups and projects a removal changed (memberships, entries)."""
    for group in groups:
        after_group = _existing_group(connection, group.id)
        connection.execute(
            "UPDATE groups SET updated_at = ? WHERE id = ?", (at, group.id)
        )
        _log(
            connection,
            actor,
            "group.members",
            group.id,
            _group_state(group),
            _group_state(after_group),
            at,
        )
    for project in projects:
        after_project = _existing_access(connection, project.project)
        connection.execute(
            "UPDATE project_acl SET updated_at = ? WHERE project = ?",
            (at, project.project),
        )
        _log(
            connection,
            actor,
            "project.access",
            project.project,
            _access_state(project),
            _access_state(after_project),
            at,
        )


def _user_state(user: UserRecord) -> dict[str, object]:
    return {
        "id": user.id,
        "name": user.name,
        "roles": list(user.roles),
        "groups": list(user.groups),
        "disabled": user.disabled,
    }


def _group_state(group: GroupRecord) -> dict[str, object]:
    return {"id": group.id, "name": group.name, "members": list(group.members)}


def _access_state(access: ProjectAccessRecord) -> dict[str, object]:
    return {
        "project": access.project,
        "owner": access.owner,
        "visibility": access.visibility,
        "users": list(access.users),
        "groups": list(access.groups),
    }


def _json(value: dict[str, object] | None) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")
