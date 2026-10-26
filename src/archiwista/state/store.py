"""State database access: accounts, groups, roles, project access, the action log.

``StateStore`` reads and changes the state database (``schema``). Every
change runs in one transaction together with its ``action_log`` entries
(A-ADR-047): who (``actor``, a principal id, with its kind, session label and
client address), when, what (``action`` and ``target``), the outcome and
the state before and after. Removing an account or a group also takes it out
of memberships and project access entries (an account's projects are left
without an owner; its password and preferences go); each group or project
changed that way gets its own entry. A request that changes nothing writes
nothing. ``record`` writes the entries of actions that change nothing here
(a sign-in, a refusal); no method changes an entry, and only
``prune_actions`` deletes old ones.

``StateStore`` keeps the data rules (ids, names, known people and groups,
entries that fit the visibility) but decides no permissions: that is
``archiwista.auth.authorize``, called by the services before any change.
Password hashes are written and read for verification by
``archiwista.auth.passwords`` only; ``UserRecord`` tells the state of a
password, never its hash.
"""

import json
import re
import sqlite3
from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
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
from archiwista.state.schema import STATE_SCHEMA_VERSION, connect, initialize

type Role = Literal["admin", "store_writer"]
type Visibility = Literal["public", "users", "group", "private"]
# The actions of the log written so far (A-ADR-047, plan v0.4 C8); each step
# that logs a new action adds its name here.
type ActionName = Literal[
    "session.login",
    "session.login_failed",
    "session.logout",
    "session.password",
    "session.ended",
    "session.proxy_header_ignored",
    "token.issue",
    "token.revoke_all",
    "user.add",
    "user.update",
    "user.remove",
    "user.password_reset",
    "user.sessions_ended",
    "group.add",
    "group.members",
    "group.remove",
    "project.access",
    "project.create",
    "project.data_dir",
]
type ActorKind = PrincipalKind | Literal["anonymous"]
type Outcome = Literal["ok", "denied", "failed"]
type PasswordState = Literal["none", "set", "temporary", "expired"]

ROLES: tuple[Role, ...] = ("admin", "store_writer")
VISIBILITIES: tuple[Visibility, ...] = ("public", "users", "group", "private")
OUTCOMES: tuple[Outcome, ...] = ("ok", "denied", "failed")
# Account and group ids: lowercase letters, digits, ".", "_" and "-".
ID_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
NAME_MAX_LENGTH = 200
# ``local`` is the owner of a local installation, never an account.
RESERVED_USER_IDS = frozenset({LOCAL_PRINCIPAL_ID})
# The actor of an entry written before anyone signed in (a failed sign-in).
ANONYMOUS_ACTOR = "-"

_ID = re.compile(ID_PATTERN)
_IDS = "SELECT value FROM json_each(?)"
_USER_SELECT = """
SELECT u.id, u.name, u.disabled, u.created_at, u.updated_at, u.sessions_revoked_at,
    p.temporary AS password_temporary, p.expires_at AS password_expires_at,
    (SELECT json_group_array(role) FROM
        (SELECT role FROM roles r WHERE r.user_id = u.id ORDER BY role)) AS roles,
    (SELECT json_group_array(group_id) FROM
        (SELECT group_id FROM memberships m WHERE m.user_id = u.id
         ORDER BY group_id)) AS groups
FROM users u LEFT JOIN passwords p ON p.user_id = u.id
"""
_ACTION_COLUMNS = (
    "id, at, actor, actor_kind, session, client, action, target, outcome,"
    " before, after, details"
)
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
    """An account of a person.

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
    password : PasswordState
        ``none`` (the account cannot sign in with a password), ``set``,
        ``temporary`` (to be changed at the next sign-in) or ``expired`` (a
        temporary password past its end); never the hash.
    password_expires_at : datetime or None
        The end of a temporary password.
    sessions_revoked_at : datetime or None
        Sessions of the account started before this time are ended.
    """

    id: str
    name: str
    roles: tuple[Role, ...]
    groups: tuple[str, ...]
    disabled: bool
    created_at: datetime
    updated_at: datetime
    password: PasswordState
    password_expires_at: datetime | None
    sessions_revoked_at: datetime | None


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
class PasswordRecord:
    """The password of an account (``archiwista.auth.passwords``).

    Attributes
    ----------
    user_id : str
        The account.
    hash : str
        Argon2id hash as a PHC string; never shown by ``repr``.
    set_at : datetime
        When it was set (UTC).
    set_by : str
        Who set it: the person, an administrator, or ``local``.
    temporary : bool
        Set by an administrator, to be changed at the next sign-in.
    expires_at : datetime or None
        The end of a temporary password.
    """

    user_id: str
    hash: str = field(repr=False)
    set_at: datetime
    set_by: str
    temporary: bool
    expires_at: datetime | None

    def state(self, now: datetime) -> PasswordState:
        """Return ``set``, ``temporary`` or ``expired`` at the time ``now``."""
        return _password_state(self.temporary, self.expires_at, now)


@dataclass(frozen=True, slots=True)
class PreferenceRecord:
    """The preferences of one principal (plan v0.4 C12).

    Attributes
    ----------
    principal : str
        Account id, or ``local`` for the owner of a local installation.
    document : dict[str, object]
        The preferences as JSON.
    updated_at : datetime
        Last change (UTC).
    """

    principal: str
    document: dict[str, object]
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ActionEntry:
    """One entry of the action log (A-ADR-047).

    Attributes
    ----------
    id : int
        Order of the entry.
    at : datetime
        When (UTC).
    actor : str
        Who: the acting principal's id (``local`` in local mode), or ``-``
        before a sign-in.
    actor_kind : ActorKind or None
        How: ``local_owner``, ``user``, an ``agent`` acting for ``actor``,
        the ``scheduler``, or ``anonymous``; ``None`` for entries written
        before Archiwista recorded it.
    session : str or None
        Label of the session the action came from; ``None`` at the terminal.
    client : str or None
        Client address of the request; ``None`` at the terminal and for
        entries written before v0.4.
    action : ActionName
        What, e.g. ``user.add`` or ``project.access``.
    target : str
        What the action was about: an account id, a group id, a project key.
    outcome : Outcome
        ``ok``, ``denied`` or ``failed``.
    before, after : dict[str, object] or None
        The state before and after; ``None`` before an addition, after a
        removal and for actions that change no state.
    details : dict[str, object] or None
        What else the action tells, e.g. ``{"temporary": true}``.
    """

    id: int
    at: datetime
    actor: str
    actor_kind: ActorKind | None
    session: str | None
    client: str | None
    action: ActionName
    target: str
    outcome: Outcome
    before: dict[str, object] | None
    after: dict[str, object] | None
    details: dict[str, object] | None


@dataclass(frozen=True, slots=True)
class ActionQuery:
    """Which entries of the action log to read, newest first.

    Attributes
    ----------
    actor : str or None
        Only the entries of this actor (an account id, ``local`` or ``-``).
    action : str or None
        Only this action, or, ending with ``.``, every action of the group
        (``session.``).
    outcome : Outcome or None
        Only the entries with this outcome.
    target : str or None
        Only the entries about this target.
    since, until : datetime or None
        Only the entries at or after ``since`` and before ``until``.
    limit : int
        At most this many entries.
    cursor : int or None
        Only the entries older than this one: ``ActionPage.next_cursor`` of
        the page before.
    """

    actor: str | None = None
    action: str | None = None
    outcome: Outcome | None = None
    target: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    limit: int = 100
    cursor: int | None = None


@dataclass(frozen=True, slots=True)
class ActionPage:
    """A page of the action log, newest entry first.

    Attributes
    ----------
    entries : tuple[ActionEntry, ...]
        The entries of the page.
    next_cursor : int or None
        ``ActionQuery.cursor`` of the next page; ``None`` on the last page.
    """

    entries: tuple[ActionEntry, ...]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    """The whole state database, read in one transaction (backups)."""

    users: tuple[UserRecord, ...]
    groups: tuple[GroupRecord, ...]
    projects: tuple[ProjectAccessRecord, ...]
    passwords: tuple[PasswordRecord, ...]
    preferences: tuple[PreferenceRecord, ...]
    actions: tuple[ActionEntry, ...]


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

    def actions(self, query: ActionQuery | None = None) -> ActionPage:
        """Return a page of the action log, newest entry first.

        Parameters
        ----------
        query : ActionQuery or None, optional
            Filters, the size of the page and where it starts; the newest
            100 entries when omitted.
        """
        wanted = query or ActionQuery()
        condition, params = _action_filter(wanted)
        with self._read() as connection:
            found = _actions(
                connection, condition, params, newest_first=True, limit=wanted.limit + 1
            )
        entries = found[: wanted.limit]
        more = len(found) > len(entries) and bool(entries)
        return ActionPage(entries, entries[-1].id if more else None)

    def password_record(self, user_id: str) -> PasswordRecord | None:
        """Return an account's password, or ``None`` without one.

        Only ``archiwista.auth.passwords`` calls this: the record holds the
        hash.
        """
        with self._read() as connection:
            found = _passwords(connection, "user_id = ?", (user_id,))
        return found[0] if found else None

    def snapshot(self) -> StateSnapshot:
        """Return everything the database holds, as one consistent read."""
        with self._read() as connection:
            return StateSnapshot(
                users=_users(connection),
                groups=_groups(connection),
                projects=_accesses(connection),
                passwords=_passwords(connection),
                preferences=_preferences(connection),
                actions=_actions(connection),
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
        actor: Principal | None,
        client: str | None = None,
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
        actor : Principal or None
            Who makes the change (for the log); ``None`` before a sign-in
            (an account the reverse proxy names, created at its sign-in).
        client : str or None, optional
            The client address of an entry without ``actor``.

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
            _record(
                connection,
                actor,
                "user.add",
                user_id,
                now,
                after=_user_state(after),
                client=client,
            )
        return after

    def update_user(
        self,
        user_id: str,
        *,
        name: str | None = None,
        roles: Collection[Role] | None = None,
        disabled: bool | None = None,
        actor: Principal,
        keep_admin: bool = False,
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
        keep_admin : bool, optional
            Refuse a change that leaves no enabled account with the role
            ``admin`` (team mode, where no local owner administers).

        Raises
        ------
        NotFoundError
            Unknown account.
        InvalidChangeError
            An empty name or an unknown role.
        ConflictError
            With ``keep_admin``: the account is the last enabled
            administrator and would be disabled or lose the role (reason
            ``last_admin``).
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
            stays_admin = "admin" in (
                before.roles if granted is None else granted
            ) and (not (before.disabled if disabled is None else disabled))
            if keep_admin and _enabled_admin(before) and not stays_admin:
                _require_another_admin(connection, user_id)
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
            _record(
                connection,
                actor,
                "user.update",
                user_id,
                now,
                before=_user_state(before),
                after=_user_state(after),
            )
        return after

    def remove_user(
        self, user_id: str, *, actor: Principal, keep_admin: bool = False
    ) -> None:
        """Remove an account, its roles, memberships, access entries and password.

        Projects it owned are left without an owner, which only narrows who
        sees them; every group and project changed is logged too. Its
        preferences go with it.

        Parameters
        ----------
        user_id : str
            The account.
        actor : Principal
            Who makes the change.
        keep_admin : bool, optional
            Refuse to remove the last enabled administrator (team mode).

        Raises
        ------
        NotFoundError
            Unknown account.
        ConflictError
            With ``keep_admin``: the account is the last enabled
            administrator (reason ``last_admin``).
        """
        with self._write() as connection:
            before = _existing_user(connection, user_id)
            if keep_admin and _enabled_admin(before):
                _require_another_admin(connection, user_id)
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
            connection.execute(
                "DELETE FROM preferences WHERE principal = ?", (user_id,)
            )
            _record(
                connection,
                actor,
                "user.remove",
                user_id,
                now,
                before=_user_state(before),
            )
            _log_cascade(connection, actor, groups, projects, now)

    def set_password(
        self,
        user_id: str,
        password_hash: str,
        *,
        expires_at: datetime | None,
        actor: Principal,
        action: Literal["user.password_reset", "session.password"] = (
            "user.password_reset"
        ),
    ) -> UserRecord:
        """Set an account's password and end the account's sessions.

        Only ``archiwista.auth.passwords`` calls this, with a hash it made.
        The entry tells whether the password is temporary and its end, never
        the hash; the account's revocation time becomes now
        (``revoke_sessions``), in the same transaction.

        Parameters
        ----------
        user_id : str
            The account.
        password_hash : str
            Argon2id hash as a PHC string.
        expires_at : datetime or None
            The end of a temporary password, which must be changed at the
            next sign-in; ``None`` for a password that stays.
        actor : Principal
            Who sets it (``set_by`` and the log).
        action : {"user.password_reset", "session.password"}, optional
            The entry: set for an account (an administrator, the terminal),
            or changed by its person.

        Raises
        ------
        NotFoundError
            Unknown account.
        """
        with self._write() as connection:
            _existing_user(connection, user_id)
            now = _now()
            ends = None if expires_at is None else _iso(expires_at)
            connection.execute(
                "INSERT INTO passwords"
                " (user_id, hash, set_at, set_by, temporary, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (user_id) DO UPDATE SET"
                " hash = excluded.hash, set_at = excluded.set_at,"
                " set_by = excluded.set_by, temporary = excluded.temporary,"
                " expires_at = excluded.expires_at",
                (user_id, password_hash, now, actor.id, int(ends is not None), ends),
            )
            _revoke(connection, user_id)
            _record(
                connection,
                actor,
                action,
                user_id,
                now,
                details={"temporary": ends is not None, "expires_at": ends},
            )
            return _existing_user(connection, user_id)

    def revoke_sessions(self, user_id: str, *, actor: Principal) -> UserRecord:
        """End every session the account started until now.

        Sets the account's ``sessions_revoked_at``; a server ends a session
        started before it at the session's next request, also when the
        command line set it. Logged as ``user.sessions_ended``.

        Raises
        ------
        NotFoundError
            Unknown account.
        """
        with self._write() as connection:
            _existing_user(connection, user_id)
            _revoke(connection, user_id)
            _record(connection, actor, "user.sessions_ended", user_id, _now())
            return _existing_user(connection, user_id)

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
            _record(
                connection, actor, "group.add", group_id, now, after=_group_state(after)
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
            _record(
                connection,
                actor,
                "group.members",
                group_id,
                now,
                before=_group_state(before),
                after=_group_state(after),
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
            _record(
                connection,
                actor,
                "group.remove",
                group_id,
                now,
                before=_group_state(before),
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
            _record(
                connection,
                actor,
                "project.access",
                project,
                now,
                before=None if before is None else _access_state(before),
                after=_access_state(after),
            )
        return after

    def add_project(
        self,
        project: str,
        *,
        owner: str | None,
        visibility: Visibility,
        producer: str,
        actor: Principal,
    ) -> ProjectAccessRecord | None:
        """Record a project a principal created: its owner and ``project.create``.

        With ``owner`` the project gets its access entry (that owner and
        ``visibility``, nobody listed) unless one exists by now, which stays;
        without one it keeps none (a project of the local owner). Either way
        the log gets ``project.create`` with the producer and the owner.

        Parameters
        ----------
        project : str
            Project key (``access_key`` of its directory).
        owner : str or None
            The account that created it, or ``None``.
        visibility : Visibility
            ``public`` or ``private`` (``default_project_visibility``).
        producer : str
            The producer whose manifest made the project.
        actor : Principal
            Who created it.

        Returns
        -------
        ProjectAccessRecord or None
            The project's access entry now; ``None`` without one.

        Raises
        ------
        InvalidChangeError
            An unknown owner, or a visibility that lists people or groups.
        """
        _require_entries(visibility, (), (), allow_empty=False)
        with self._write() as connection:
            if owner is not None:
                _require_users(connection, (owner,))
            now = _now()
            if owner is not None and _access(connection, project) is None:
                connection.execute(
                    "INSERT INTO project_acl (project, owner, visibility, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (project, owner, visibility, now),
                )
            after = _access(connection, project)
            _record(
                connection,
                actor,
                "project.create",
                project,
                now,
                after=None if after is None else _access_state(after),
                details={
                    "producer": producer,
                    "owner": None if after is None else after.owner,
                },
            )
        return after

    # The action log.

    def record(
        self,
        actor: Principal | None,
        action: ActionName,
        target: str,
        *,
        outcome: Outcome = "ok",
        before: Mapping[str, object] | None = None,
        after: Mapping[str, object] | None = None,
        details: Mapping[str, object] | None = None,
        client: str | None = None,
    ) -> ActionEntry:
        """Append an entry to the action log.

        Parameters
        ----------
        actor : Principal or None
            Who acted, with its kind, session label and client address;
            ``None`` before a sign-in (actor ``-``, kind ``anonymous``).
        action : ActionName
            What was done.
        target : str
            What it was about.
        outcome : Outcome, optional
            ``ok`` (default), ``denied`` or ``failed``.
        before, after, details : Mapping[str, object] or None, optional
            The state before and after and other facts, as JSON values.
        client : str or None, optional
            The client address of an entry without ``actor``; a principal's
            entry has the principal's own.

        Returns
        -------
        ActionEntry
            The entry written.
        """
        with self._write() as connection:
            entry_id = _record(
                connection,
                actor,
                action,
                target,
                _now(),
                outcome=outcome,
                before=before,
                after=after,
                details=details,
                client=client,
            )
            return _actions(connection, "id = ?", (entry_id,))[0]

    def prune_actions(self, before: datetime) -> int:
        """Delete the entries of the action log older than ``before``.

        Returns
        -------
        int
            How many entries were deleted.
        """
        with self._write() as connection:
            deleted = connection.execute(
                "DELETE FROM action_log WHERE at < ?", (_iso(before),)
            )
            return deleted.rowcount

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


def read_users(path: Path) -> tuple[UserRecord, ...] | None:
    """Return every account of a state database, changing nothing.

    For ``archiwista doctor``, which writes nothing: unlike ``StateStore`` it
    neither creates the database nor brings an older one up to date.

    Parameters
    ----------
    path : Path
        The state database.

    Returns
    -------
    tuple[UserRecord, ...] or None
        The accounts ordered by id; none when the database does not exist
        yet; ``None`` when its schema is older than this Archiwista's (the
        server's next start or a command that changes it brings it up to
        date).

    Raises
    ------
    StateError
        The database comes from a newer Archiwista.
    sqlite3.Error
        The file cannot be read as a database.
    """
    if not path.exists():
        return ()
    connection = connect(path)
    try:
        connection.execute("PRAGMA query_only = ON")
        (version,) = connection.execute("PRAGMA user_version").fetchone()
        if version > STATE_SCHEMA_VERSION:
            raise StateError(
                message(
                    "state.newer",
                    path=path,
                    version=version,
                    supported=STATE_SCHEMA_VERSION,
                )
            )
        return _users(connection) if version == STATE_SCHEMA_VERSION else None
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


def _enabled_admin(user: UserRecord) -> bool:
    return "admin" in user.roles and not user.disabled


def _require_another_admin(connection: sqlite3.Connection, user_id: str) -> None:
    """Refuse a change that would leave no enabled administrator (``last_admin``)."""
    (others,) = connection.execute(
        "SELECT COUNT(*) FROM users u JOIN roles r ON r.user_id = u.id"
        " WHERE r.role = 'admin' AND u.disabled = 0 AND u.id <> ?",
        (user_id,),
    ).fetchone()
    if not others:
        raise ConflictError(
            message("state.last_admin", id=user_id), reason="last_admin"
        )


# Reading rows.


def _users(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
) -> tuple[UserRecord, ...]:
    rows = connection.execute(
        f"{_USER_SELECT} WHERE {condition} ORDER BY u.id", params
    ).fetchall()
    now = datetime.now(UTC)
    users = []
    for row in rows:
        ends = _moment(row["password_expires_at"])
        temporary = row["password_temporary"]
        users.append(
            UserRecord(
                id=row["id"],
                name=row["name"],
                roles=tuple(json.loads(row["roles"])),
                groups=tuple(json.loads(row["groups"])),
                disabled=bool(row["disabled"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                password=(
                    "none"
                    if temporary is None
                    else _password_state(bool(temporary), ends, now)
                ),
                password_expires_at=ends,
                sessions_revoked_at=_moment(row["sessions_revoked_at"]),
            )
        )
    return tuple(users)


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


def _passwords(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
) -> tuple[PasswordRecord, ...]:
    rows = connection.execute(
        "SELECT user_id, hash, set_at, set_by, temporary, expires_at FROM passwords"
        f" WHERE {condition} ORDER BY user_id",
        params,
    ).fetchall()
    return tuple(
        PasswordRecord(
            user_id=row["user_id"],
            hash=row["hash"],
            set_at=datetime.fromisoformat(row["set_at"]),
            set_by=row["set_by"],
            temporary=bool(row["temporary"]),
            expires_at=_moment(row["expires_at"]),
        )
        for row in rows
    )


def _preferences(connection: sqlite3.Connection) -> tuple[PreferenceRecord, ...]:
    rows = connection.execute(
        "SELECT principal, document, updated_at FROM preferences ORDER BY principal"
    ).fetchall()
    return tuple(
        PreferenceRecord(
            principal=row["principal"],
            document=json.loads(row["document"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
        for row in rows
    )


def _actions(
    connection: sqlite3.Connection,
    condition: str = "1",
    params: tuple[object, ...] = (),
    *,
    newest_first: bool = False,
    limit: int = -1,
) -> tuple[ActionEntry, ...]:
    order = "DESC" if newest_first else "ASC"
    rows = connection.execute(
        f"SELECT {_ACTION_COLUMNS} FROM action_log WHERE {condition}"
        f" ORDER BY id {order} LIMIT ?",
        (*params, limit),
    ).fetchall()
    return tuple(
        ActionEntry(
            id=int(row["id"]),
            at=datetime.fromisoformat(row["at"]),
            actor=row["actor"],
            actor_kind=row["actor_kind"],
            session=row["session"],
            client=row["client"],
            action=row["action"],
            target=row["target"],
            outcome=row["outcome"],
            before=_from_json(row["before"]),
            after=_from_json(row["after"]),
            details=_from_json(row["details"]),
        )
        for row in rows
    )


def _action_filter(query: ActionQuery) -> tuple[str, tuple[object, ...]]:
    """Return the SQL condition and parameters of a query's filters."""
    conditions: list[str] = []
    params: list[object] = []
    for column, value in (
        ("actor", query.actor),
        ("outcome", query.outcome),
        ("target", query.target),
    ):
        if value is not None:
            conditions.append(f"{column} = ?")
            params.append(value)
    if query.action is not None:
        if query.action.endswith("."):
            conditions.append("substr(action, 1, ?) = ?")
            params.extend((len(query.action), query.action))
        else:
            conditions.append("action = ?")
            params.append(query.action)
    if query.since is not None:
        conditions.append("at >= ?")
        params.append(_iso(query.since))
    if query.until is not None:
        conditions.append("at < ?")
        params.append(_iso(query.until))
    if query.cursor is not None:
        conditions.append("id < ?")
        params.append(query.cursor)
    return " AND ".join(conditions) or "1", tuple(params)


def _is_empty(connection: sqlite3.Connection) -> bool:
    (filled,) = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM users) OR EXISTS (SELECT 1 FROM groups)"
        " OR EXISTS (SELECT 1 FROM project_acl)"
        " OR EXISTS (SELECT 1 FROM preferences)"
        " OR EXISTS (SELECT 1 FROM action_log)"
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
            "INSERT INTO users"
            " (id, name, disabled, created_at, updated_at, sessions_revoked_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                user.id,
                _require_name(user.name),
                int(user.disabled),
                _iso(user.created_at),
                _iso(user.updated_at),
                _precise(user.sessions_revoked_at),
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
        "INSERT INTO passwords (user_id, hash, set_at, set_by, temporary, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                password.user_id,
                password.hash,
                _iso(password.set_at),
                password.set_by,
                int(password.temporary),
                None if password.expires_at is None else _iso(password.expires_at),
            )
            for password in snapshot.passwords
        ],
    )
    connection.executemany(
        "INSERT INTO preferences (principal, document, updated_at) VALUES (?, ?, ?)",
        [
            (
                preference.principal,
                _json(preference.document),
                _iso(preference.updated_at),
            )
            for preference in snapshot.preferences
        ],
    )
    connection.executemany(
        f"INSERT INTO action_log ({_ACTION_COLUMNS})"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                entry.id,
                _iso(entry.at),
                entry.actor,
                entry.actor_kind,
                entry.session,
                entry.client,
                entry.action,
                entry.target,
                entry.outcome,
                _json(entry.before),
                _json(entry.after),
                _json(entry.details),
            )
            for entry in snapshot.actions
        ],
    )


# Log.


def _record(
    connection: sqlite3.Connection,
    actor: Principal | None,
    action: ActionName,
    target: str,
    at: str,
    *,
    outcome: Outcome = "ok",
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
    details: Mapping[str, object] | None = None,
    client: str | None = None,
) -> int:
    """Append an entry to the action log; return its id."""
    who: str = ANONYMOUS_ACTOR
    kind: ActorKind = "anonymous"
    session: str | None = None
    if actor is not None:
        who, kind, session, client = actor.id, actor.kind, actor.session, actor.client
    cursor = connection.execute(
        "INSERT INTO action_log"
        " (at, actor, actor_kind, session, client, action, target, outcome,"
        " before, after, details)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            at,
            who,
            kind,
            session,
            client,
            action,
            target,
            outcome,
            _json(before),
            _json(after),
            _json(details),
        ),
    )
    return int(cursor.lastrowid or 0)


def _revoke(connection: sqlite3.Connection, user_id: str) -> None:
    """Set an account's revocation time to now, to the microsecond."""
    connection.execute(
        "UPDATE users SET sessions_revoked_at = ? WHERE id = ?",
        (_precise(datetime.now(UTC)), user_id),
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
        _record(
            connection,
            actor,
            "group.members",
            group.id,
            at,
            before=_group_state(group),
            after=_group_state(after_group),
        )
    for project in projects:
        after_project = _existing_access(connection, project.project)
        connection.execute(
            "UPDATE project_acl SET updated_at = ? WHERE project = ?",
            (at, project.project),
        )
        _record(
            connection,
            actor,
            "project.access",
            project.project,
            at,
            before=_access_state(project),
            after=_access_state(after_project),
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


def _json(value: Mapping[str, object] | None) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _from_json(text: str | None) -> dict[str, object] | None:
    return None if text is None else json.loads(text)


def _password_state(
    temporary: bool, expires_at: datetime | None, now: datetime
) -> PasswordState:
    if not temporary:
        return "set"
    return "temporary" if expires_at is not None and now < expires_at else "expired"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _precise(moment: datetime | None) -> str | None:
    """Return a time to the microsecond: revocations compare with session starts."""
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat(timespec="microseconds")


def _moment(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)
