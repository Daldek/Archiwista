"""Backups of the state database: the ``archiwista-state/1`` JSON document.

The state cannot be rebuilt from files (A-ADR-029), so ``archiwista state
export`` writes all of it: accounts with their roles, groups with their
members, project access entries and the permission log, keeping ids and
times. ``archiwista state import`` restores such a document into an empty
state database only, so a backup never merges into or overwrites a working
state; restoring and exporting again gives the same document.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from archiwista.auth import PrincipalKind
from archiwista.errors import StateError
from archiwista.messages import message
from archiwista.state.store import (
    ChangeAction,
    GroupRecord,
    PermissionChange,
    ProjectAccessRecord,
    Role,
    StateSnapshot,
    StateStore,
    UserRecord,
    Visibility,
)

type StateFormat = Literal["archiwista-state/1"]

STATE_DOCUMENT_SCHEMA: StateFormat = "archiwista-state/1"


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserBackup(_Part):
    """An account with its roles; memberships are kept with the groups."""

    id: str
    name: str
    roles: list[Role]
    disabled: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime


class GroupBackup(_Part):
    """A group with its members."""

    id: str
    name: str
    members: list[str]
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ProjectAccessBackup(_Part):
    """A project access entry; ``project`` is the directory after realpath."""

    project: str
    owner: str | None
    visibility: Visibility
    users: list[str]
    groups: list[str]
    updated_at: AwareDatetime


class ChangeBackup(_Part):
    """An entry of the permission log.

    ``actor_kind`` and ``session`` are missing from backups of entries
    written before Archiwista recorded them.
    """

    id: int
    at: AwareDatetime
    actor: str
    actor_kind: PrincipalKind | None = None
    session: str | None = None
    action: ChangeAction
    target: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class StateDocument(_Part):
    """The whole state database as one JSON document (``archiwista-state/1``)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: StateFormat = Field(default=STATE_DOCUMENT_SCHEMA, alias="schema")
    exported_at: AwareDatetime
    users: list[UserBackup]
    groups: list[GroupBackup]
    projects: list[ProjectAccessBackup]
    permission_log: list[ChangeBackup]


def export_state(store: StateStore, *, now: datetime | None = None) -> StateDocument:
    """Return the whole state database as a backup document.

    Parameters
    ----------
    store : StateStore
        The state database, read in one transaction.
    now : datetime or None, optional
        Time of the export; the current time when omitted.
    """
    snapshot = store.snapshot()
    return StateDocument(
        exported_at=(now or datetime.now(UTC)).replace(microsecond=0),
        users=[
            UserBackup(
                id=user.id,
                name=user.name,
                roles=list(user.roles),
                disabled=user.disabled,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            for user in snapshot.users
        ],
        groups=[
            GroupBackup(
                id=group.id,
                name=group.name,
                members=list(group.members),
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
            for group in snapshot.groups
        ],
        projects=[
            ProjectAccessBackup(
                project=access.project,
                owner=access.owner,
                visibility=access.visibility,
                users=list(access.users),
                groups=list(access.groups),
                updated_at=access.updated_at,
            )
            for access in snapshot.projects
        ],
        permission_log=[
            ChangeBackup(
                id=change.id,
                at=change.at,
                actor=change.actor,
                actor_kind=change.actor_kind,
                session=change.session,
                action=change.action,
                target=change.target,
                before=change.before,
                after=change.after,
            )
            for change in snapshot.changes
        ],
    )


def dump_state(document: StateDocument) -> str:
    """Return a backup document as indented UTF-8 JSON text."""
    return document.model_dump_json(by_alias=True, indent=2) + "\n"


def import_state(store: StateStore, text: str | bytes) -> StateSnapshot:
    """Restore a backup document into an empty state database.

    Parameters
    ----------
    store : StateStore
        The state database; it must hold no account, group, project entry
        or log entry.
    text : str or bytes
        The JSON written by ``dump_state``.

    Returns
    -------
    StateSnapshot
        What was restored.

    Raises
    ------
    StateError
        The text is not an ``archiwista-state/1`` document, the document is
        inconsistent, or the database is not empty; nothing is written.
    """
    document = parse_state(text)
    snapshot = StateSnapshot(
        users=tuple(
            UserRecord(
                id=user.id,
                name=user.name,
                roles=tuple(user.roles),
                groups=(),
                disabled=user.disabled,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            for user in document.users
        ),
        groups=tuple(
            GroupRecord(
                id=group.id,
                name=group.name,
                members=tuple(group.members),
                created_at=group.created_at,
                updated_at=group.updated_at,
            )
            for group in document.groups
        ),
        projects=tuple(
            ProjectAccessRecord(
                project=access.project,
                owner=access.owner,
                visibility=access.visibility,
                users=tuple(access.users),
                groups=tuple(access.groups),
                updated_at=access.updated_at,
            )
            for access in document.projects
        ),
        changes=tuple(
            PermissionChange(
                id=change.id,
                at=change.at,
                actor=change.actor,
                actor_kind=change.actor_kind,
                session=change.session,
                action=change.action,
                target=change.target,
                before=change.before,
                after=change.after,
            )
            for change in document.permission_log
        ),
    )
    store.restore(snapshot)
    return snapshot


def parse_state(text: str | bytes) -> StateDocument:
    """Read a backup document, explaining what is wrong with it.

    Raises
    ------
    StateError
        Not JSON, another format, or fields that do not fit.
    """
    try:
        data = json.loads(text)
    except (ValueError, UnicodeDecodeError) as error:
        raise StateError(
            message("state.import_not_json", detail=error),
            code="data_error",
            reason="invalid_backup",
        ) from error
    found = data.get("schema") if isinstance(data, dict) else None
    if found != STATE_DOCUMENT_SCHEMA:
        raise StateError(
            message("state.import_schema", found=found, expected=STATE_DOCUMENT_SCHEMA),
            code="data_error",
            reason="invalid_backup",
        )
    try:
        return StateDocument.model_validate(data)
    except ValidationError as error:
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"]) for item in error.errors()
        )
        raise StateError(
            message("state.import_invalid", fields=fields),
            code="data_error",
            reason="invalid_backup",
        ) from error
