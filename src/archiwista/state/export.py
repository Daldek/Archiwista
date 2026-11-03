"""Backups of the state database: the ``archiwista-state/2`` JSON document.

The state cannot be rebuilt from files (A-ADR-029), so ``archiwista state
export`` writes all of it: accounts with their roles, groups with their
members, project access entries, the password hashes, the preferences and
the action log, keeping ids and times. The document is a secret (it holds
the password hashes, A-ADR-047). ``archiwista state import`` restores such a
document into an empty state database only, so a backup never merges into or
overwrites a working state; restoring and exporting again gives the same
document. A document ``archiwista-state/1`` (before v0.4: no passwords or
preferences, the permission log) still imports: its log entries become
entries of the action log with the outcome ``ok``.
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from archiwista.auth import PrincipalKind
from archiwista.errors import StateError
from archiwista.messages import message
from archiwista.state.store import (
    ActionEntry,
    ActionName,
    ActorKind,
    GroupRecord,
    Outcome,
    PasswordRecord,
    PreferenceRecord,
    ProjectAccessRecord,
    Role,
    StateSnapshot,
    StateStore,
    UserRecord,
    Visibility,
)

type StateFormat = Literal["archiwista-state/2"]
type LegacyStateFormat = Literal["archiwista-state/1"]

STATE_DOCUMENT_SCHEMA: StateFormat = "archiwista-state/2"
LEGACY_STATE_DOCUMENT_SCHEMA: LegacyStateFormat = "archiwista-state/1"


class _Part(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserBackup(_Part):
    """An account with its roles; memberships are kept with the groups.

    ``sessions_revoked_at`` is missing from ``archiwista-state/1``.
    """

    id: str
    name: str
    roles: list[Role]
    disabled: bool
    created_at: AwareDatetime
    updated_at: AwareDatetime
    sessions_revoked_at: AwareDatetime | None = None


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


class PasswordBackup(_Part):
    """The password of an account: an Argon2id hash, a secret."""

    user_id: str
    hash: str
    set_at: AwareDatetime
    set_by: str
    temporary: bool
    expires_at: AwareDatetime | None


class PreferenceBackup(_Part):
    """The preferences of one principal (an account id or ``local``)."""

    principal: str
    document: dict[str, Any]
    updated_at: AwareDatetime


class ActionBackup(_Part):
    """An entry of the action log."""

    id: int
    at: AwareDatetime
    actor: str
    actor_kind: ActorKind | None
    session: str | None
    client: str | None
    action: ActionName
    target: str
    outcome: Outcome
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    details: dict[str, Any] | None


class ChangeBackup(_Part):
    """An entry of the permission log of ``archiwista-state/1``.

    ``actor_kind`` and ``session`` are missing from backups of entries
    written before Archiwista recorded them.
    """

    id: int
    at: AwareDatetime
    actor: str
    actor_kind: PrincipalKind | None = None
    session: str | None = None
    action: ActionName
    target: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None


class StateDocument(_Part):
    """The whole state database as one JSON document (``archiwista-state/2``)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: StateFormat = Field(default=STATE_DOCUMENT_SCHEMA, alias="schema")
    exported_at: AwareDatetime
    users: list[UserBackup]
    groups: list[GroupBackup]
    projects: list[ProjectAccessBackup]
    passwords: list[PasswordBackup]
    preferences: list[PreferenceBackup]
    actions: list[ActionBackup]


class LegacyStateDocument(_Part):
    """A backup written before v0.4 (``archiwista-state/1``)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    format: LegacyStateFormat = Field(alias="schema")
    exported_at: AwareDatetime
    users: list[UserBackup]
    groups: list[GroupBackup]
    projects: list[ProjectAccessBackup]
    permission_log: list[ChangeBackup]

    def upgrade(self) -> StateDocument:
        """Return the same state as ``archiwista-state/2``.

        The permission log becomes the action log with the outcome ``ok``;
        there are no passwords or preferences.
        """
        return StateDocument(
            exported_at=self.exported_at,
            users=self.users,
            groups=self.groups,
            projects=self.projects,
            passwords=[],
            preferences=[],
            actions=[
                ActionBackup(
                    id=change.id,
                    at=change.at,
                    actor=change.actor,
                    actor_kind=change.actor_kind,
                    session=change.session,
                    client=None,
                    action=change.action,
                    target=change.target,
                    outcome="ok",
                    before=change.before,
                    after=change.after,
                    details=None,
                )
                for change in self.permission_log
            ],
        )


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
                sessions_revoked_at=user.sessions_revoked_at,
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
        passwords=[
            PasswordBackup(
                user_id=password.user_id,
                hash=password.hash,
                set_at=password.set_at,
                set_by=password.set_by,
                temporary=password.temporary,
                expires_at=password.expires_at,
            )
            for password in snapshot.passwords
        ],
        preferences=[
            PreferenceBackup(
                principal=preference.principal,
                document=preference.document,
                updated_at=preference.updated_at,
            )
            for preference in snapshot.preferences
        ],
        actions=[
            ActionBackup(
                id=entry.id,
                at=entry.at,
                actor=entry.actor,
                actor_kind=entry.actor_kind,
                session=entry.session,
                client=entry.client,
                action=entry.action,
                target=entry.target,
                outcome=entry.outcome,
                before=entry.before,
                after=entry.after,
                details=entry.details,
            )
            for entry in snapshot.actions
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
        The state database; it must hold no account, group, project entry,
        preferences or log entry.
    text : str or bytes
        The JSON written by ``dump_state``, or an ``archiwista-state/1``
        document.

    Returns
    -------
    StateSnapshot
        What the database holds after the restore.

    Raises
    ------
    StateError
        The text is no ``archiwista-state/2`` or ``/1`` document, the
        document is inconsistent, or the database is not empty; nothing is
        written.
    """
    document = parse_state(text)
    now = datetime.now(UTC)
    passwords = tuple(
        PasswordRecord(
            user_id=password.user_id,
            hash=password.hash,
            set_at=password.set_at,
            set_by=password.set_by,
            temporary=password.temporary,
            expires_at=password.expires_at,
        )
        for password in document.passwords
    )
    password_of = {password.user_id: password for password in passwords}
    store.restore(
        StateSnapshot(
            users=tuple(
                _user(user, password_of.get(user.id), now) for user in document.users
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
            passwords=passwords,
            preferences=tuple(
                PreferenceRecord(
                    principal=preference.principal,
                    document=preference.document,
                    updated_at=preference.updated_at,
                )
                for preference in document.preferences
            ),
            actions=tuple(
                ActionEntry(
                    id=entry.id,
                    at=entry.at,
                    actor=entry.actor,
                    actor_kind=entry.actor_kind,
                    session=entry.session,
                    client=entry.client,
                    action=entry.action,
                    target=entry.target,
                    outcome=entry.outcome,
                    before=entry.before,
                    after=entry.after,
                    details=entry.details,
                )
                for entry in document.actions
            ),
        )
    )
    return store.snapshot()


def parse_state(text: str | bytes) -> StateDocument:
    """Read a backup document, explaining what is wrong with it.

    Returns
    -------
    StateDocument
        The document; an ``archiwista-state/1`` one upgraded
        (``LegacyStateDocument.upgrade``).

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
    if found not in (STATE_DOCUMENT_SCHEMA, LEGACY_STATE_DOCUMENT_SCHEMA):
        raise StateError(
            message(
                "state.import_schema",
                found=found,
                expected=f"{STATE_DOCUMENT_SCHEMA}, {LEGACY_STATE_DOCUMENT_SCHEMA}",
            ),
            code="data_error",
            reason="invalid_backup",
        )
    try:
        if found == LEGACY_STATE_DOCUMENT_SCHEMA:
            return LegacyStateDocument.model_validate(data).upgrade()
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


def _user(
    user: UserBackup, password: PasswordRecord | None, now: datetime
) -> UserRecord:
    return UserRecord(
        id=user.id,
        name=user.name,
        roles=tuple(user.roles),
        groups=(),
        disabled=user.disabled,
        created_at=user.created_at,
        updated_at=user.updated_at,
        password="none" if password is None else password.state(now),
        password_expires_at=None if password is None else password.expires_at,
        sessions_revoked_at=user.sessions_revoked_at,
    )
