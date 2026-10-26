"""The one place deciding what a principal may do (A-ADR-029, SPEC 10.2).

``Authorizer.can(principal, action, resource)`` answers, ``require`` raises
``PermissionDeniedError`` (``403 permission_denied``),
``visible_projects(principal)`` returns the ``ProjectVisibility`` that index
queries and services filter projects and pins with, and
``writable_projects(principal)`` answers ``project.write`` for each project
of a listing at once. Routers and the command line never decide on their
own: they pass the principal to the services, which ask here.

Rules (v0.1, ``project.write`` since v0.2, ``project.create`` and
``store.scan`` since v0.4):

- ``admin`` manages accounts, groups and settings, scans the stores, sees
  every project and manages the access and the content of each
  (``users.manage``, ``groups.manage``, ``settings.write``, ``store.scan``,
  ``project.view``, ``project.share``, ``project.write``);
- every principal acting for a person (the local owner, a ``user``, an
  ``agent``; not the scheduler) creates a project where none is yet
  (``project.create``); the service makes an account that creates one (a
  ``user``, or an ``agent`` of one) its owner (ADR-039 erratum 3);
- a project's owner sees it, manages its access and changes it
  (``project.write``: snapshots of own files, ``POST …/snapshots``, manifest
  changes, the data folder); a project without an access entry has no
  owner, so only administrators share or change it;
- ``public`` projects are seen by everyone, ``users`` by the listed people,
  ``group`` by members of the listed groups, ``private`` by the owner only;
  a project without an access entry follows ``default_project_visibility``
  (``public``: everyone, ``private``: administrators);
- ``store.write`` needs the ``store_writer`` role or the setting
  ``store_write_for_all`` (enforced from v0.3);
- ``job.cancel`` (v0.3) is for whoever started the job (its ``actor``) and
  administrators;
- an ``agent`` acts with the roles, groups and id of the principal that
  minted its token, read again for each request (``session_principal``), so
  it may do exactly what they may now.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Literal

from archiwista.auth.principal import (
    LOCAL_OWNER,
    LOCAL_PRINCIPAL_ID,
    Principal,
    PrincipalKind,
)
from archiwista.auth.visibility import (
    ALL_PROJECTS,
    ProjectVisibility,
    WritableProjects,
)
from archiwista.config import AppSettings, DefaultProjectVisibility
from archiwista.errors import PermissionDeniedError
from archiwista.messages import message
from archiwista.state import ProjectAccessRecord, StateStore, UserRecord

type Action = Literal[
    "project.view",
    "project.share",
    "project.write",
    "project.create",
    "users.manage",
    "groups.manage",
    "settings.write",
    "store.write",
    "store.scan",
    "job.cancel",
]

ACTIONS: tuple[Action, ...] = (
    "project.view",
    "project.share",
    "project.write",
    "project.create",
    "users.manage",
    "groups.manage",
    "settings.write",
    "store.write",
    "store.scan",
    "job.cancel",
)
ADMIN = "admin"
STORE_WRITER = "store_writer"

_ADMIN_ACTIONS: frozenset[Action] = frozenset(
    {"users.manage", "groups.manage", "settings.write", "store.scan"}
)


def principal_for(state: StateStore, user_id: str) -> Principal | None:
    """Return the principal of an account with its roles and groups.

    Parameters
    ----------
    state : StateStore
        The state database.
    user_id : str
        The account.

    Returns
    -------
    Principal or None
        A ``user`` principal; ``None`` for an unknown or disabled account,
        which acts nowhere.
    """
    user = state.user(user_id)
    if user is None or user.disabled:
        return None
    return _principal(user)


def session_principal(
    state: StateStore,
    principal_id: str,
    kind: PrincipalKind,
    *,
    session: str | None = None,
    issued_at: datetime | None = None,
) -> Principal | None:
    """Return who a session acts as now, with the current roles and groups.

    Sessions and one-time tokens keep only an id and a kind; every request
    reads the roles and groups again, so a revoked role or membership holds
    for live sessions and agents too.

    Parameters
    ----------
    state : StateStore
        The state database.
    principal_id : str
        Who the session belongs to; ``local`` is the owner of a local
        installation, who has no account.
    kind : {"local_owner", "user", "agent"}
        How the session acts: as that principal or as an agent for it.
    session : str or None, optional
        Label of the session, kept in the principal.
    issued_at : datetime or None, optional
        When the session's credential (sign-in or token) was issued.

    Returns
    -------
    Principal or None
        ``None`` when the account is unknown or disabled, or its sessions
        were revoked after ``issued_at`` (``sessions_revoked_at``): the
        session ends.
    """
    if principal_id == LOCAL_PRINCIPAL_ID:
        base = LOCAL_OWNER
    else:
        user = state.user(principal_id)
        if user is None or user.disabled:
            return None
        revoked = user.sessions_revoked_at
        if issued_at is not None and revoked is not None and issued_at < revoked:
            return None
        base = _principal(user)
    acting = "agent" if kind == "agent" else base.kind
    return replace(base, kind=acting, session=session)


def _principal(user: UserRecord) -> Principal:
    return Principal(
        id=user.id,
        kind="user",
        roles=frozenset(user.roles),
        groups=frozenset(user.groups),
    )


class Authorizer:
    """Decide what principals may do, from their roles and the state database.

    Parameters
    ----------
    state : StateStore
        Accounts, groups and project access entries.
    settings : Callable[[], AppSettings]
        Current settings (``store_write_for_all``,
        ``default_project_visibility``), e.g. ``SettingsService.get``.
    """

    def __init__(self, state: StateStore, settings: Callable[[], AppSettings]) -> None:
        self.state = state
        self._settings = settings

    @property
    def default_project_visibility(self) -> DefaultProjectVisibility:
        """Visibility of projects without their own access entry."""
        return self._settings().default_project_visibility

    @property
    def team(self) -> bool:
        """Whether team mode is on: then no local owner administers the team."""
        return self._settings().team.enabled

    def can(
        self, principal: Principal, action: Action, resource: str | None = None
    ) -> bool:
        """Return whether ``principal`` may perform ``action``.

        Parameters
        ----------
        principal : Principal
            Who acts.
        action : Action
            ``project.view``, ``project.share``, ``project.write``,
            ``project.create``, ``users.manage``, ``groups.manage``,
            ``settings.write``, ``store.write``, ``store.scan`` or
            ``job.cancel``.
        resource : str or None, optional
            For ``project.view``, ``project.share`` and ``project.write``: the
            project's access key (``access_key`` of its directory,
            ``ProjectRef.access_key``); for ``job.cancel``: the job's
            ``actor``; unused otherwise.

        Raises
        ------
        ValueError
            A project action without a project, ``job.cancel`` without the
            job's actor.
        """
        if action in _ADMIN_ACTIONS:
            return ADMIN in principal.roles
        if action == "project.create":
            return principal.kind != "scheduler"
        if action == "store.write":
            return (
                STORE_WRITER in principal.roles or self._settings().store_write_for_all
            )
        if resource is None:
            raise ValueError(f"{action} needs the project's access key or job's actor")
        if ADMIN in principal.roles:
            return True
        if action == "job.cancel":
            return principal.id == resource
        access = self.state.project_access(resource)
        if action in ("project.share", "project.write"):
            return _owns(principal, access)
        if access is None:
            return self.default_project_visibility == "public"
        return _admits(principal, access)

    def require(
        self, principal: Principal, action: Action, resource: str | None = None
    ) -> None:
        """Do nothing when ``can`` allows the action, else refuse it.

        Raises
        ------
        PermissionDeniedError
            With a message naming what the action needs.
        """
        if not self.can(principal, action, resource):
            name = action.replace(".", "_")
            raise PermissionDeniedError(message(f"permission.{name}"))

    def visible_projects(self, principal: Principal) -> ProjectVisibility:
        """Return the projects ``principal`` sees.

        ``ALL_PROJECTS`` for an administrator (the local owner too);
        otherwise the projects whose access entry admits the principal, and
        those without an entry when ``default_project_visibility`` is
        ``public``.
        """
        if ADMIN in principal.roles:
            return ALL_PROJECTS
        granted: set[str] = set()
        denied: set[str] = set()
        for access in self.state.project_accesses():
            (granted if _admits(principal, access) else denied).add(access.project)
        return ProjectVisibility(
            granted=frozenset(granted),
            denied=frozenset(denied),
            unlisted=self.default_project_visibility == "public",
        )

    def writable_projects(self, principal: Principal) -> WritableProjects:
        """Return whether ``principal`` may change each project, by access key.

        The answer of ``can(principal, "project.write", key)`` for every
        project, read from the state database once: every project for an
        administrator (the local owner too), otherwise the projects whose
        access entry names ``principal`` as their owner (a project without an
        entry has no owner).
        """
        if ADMIN in principal.roles:
            return _any_project
        owned = frozenset(
            access.project
            for access in self.state.project_accesses()
            if _owns(principal, access)
        )
        return owned.__contains__


def _any_project(key: str) -> bool:
    """Allow every project: an administrator changes each one."""
    return True


def _owns(principal: Principal, access: ProjectAccessRecord | None) -> bool:
    return access is not None and access.owner == principal.id


def _admits(principal: Principal, access: ProjectAccessRecord) -> bool:
    """Whether an access entry lets a principal (not an admin) see the project."""
    if _owns(principal, access) or access.visibility == "public":
        return True
    if access.visibility == "users":
        return principal.id in access.users
    if access.visibility == "group":
        return not principal.groups.isdisjoint(access.groups)
    return False
