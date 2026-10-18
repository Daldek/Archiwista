"""The one place deciding what a principal may do (A-ADR-029, SPEC 10.2).

``Authorizer.can(principal, action, resource)`` answers, ``require`` raises
``PermissionDeniedError`` (``403 permission_denied``), and
``visible_projects(principal)`` returns the ``ProjectVisibility`` that index
queries and services filter projects and pins with. Routers and the command
line never decide on their own: they pass the principal to the services,
which ask here.

Rules (v0.1):

- ``admin`` manages accounts, groups and settings, sees every project and
  manages the access of each (``users.manage``, ``groups.manage``,
  ``settings.write``, ``project.view``, ``project.share``);
- a project's owner sees it and manages its access;
- ``public`` projects are seen by everyone, ``users`` by the listed people,
  ``group`` by members of the listed groups, ``private`` by the owner only;
  a project without an access entry follows ``default_project_visibility``
  (``public``: everyone, ``private``: administrators);
- ``store.write`` needs the ``store_writer`` role or the setting
  ``store_write_for_all`` (enforced from v0.3);
- an ``agent`` acts with the roles, groups and id of the principal that
  minted its token, so it may do exactly what they may.
"""

from collections.abc import Callable
from typing import Literal

from archiwista.auth.principal import Principal
from archiwista.auth.visibility import ALL_PROJECTS, ProjectVisibility
from archiwista.config import AppSettings, DefaultProjectVisibility
from archiwista.errors import PermissionDeniedError
from archiwista.messages import MESSAGES
from archiwista.state import ProjectAccessRecord, StateStore

type Action = Literal[
    "project.view",
    "project.share",
    "users.manage",
    "groups.manage",
    "settings.write",
    "store.write",
]

ACTIONS: tuple[Action, ...] = (
    "project.view",
    "project.share",
    "users.manage",
    "groups.manage",
    "settings.write",
    "store.write",
)
ADMIN = "admin"
STORE_WRITER = "store_writer"

_ADMIN_ACTIONS: frozenset[Action] = frozenset(
    {"users.manage", "groups.manage", "settings.write"}
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

    def can(
        self, principal: Principal, action: Action, resource: str | None = None
    ) -> bool:
        """Return whether ``principal`` may perform ``action``.

        Parameters
        ----------
        principal : Principal
            Who acts.
        action : Action
            ``project.view``, ``project.share``, ``users.manage``,
            ``groups.manage``, ``settings.write`` or ``store.write``.
        resource : str or None, optional
            For ``project.*``: the project's access key (``access_key`` of
            its directory, ``ProjectRef.access_key``); unused otherwise.

        Raises
        ------
        ValueError
            A project action without a project.
        """
        if action in _ADMIN_ACTIONS:
            return ADMIN in principal.roles
        if action == "store.write":
            return (
                STORE_WRITER in principal.roles or self._settings().store_write_for_all
            )
        if resource is None:
            raise ValueError(f"{action} needs the project's access key")
        if ADMIN in principal.roles:
            return True
        access = self.state.project_access(resource)
        if action == "project.share":
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
            With a Polish message naming what the action needs.
        """
        if not self.can(principal, action, resource):
            key = "permission_" + action.replace(".", "_")
            raise PermissionDeniedError(MESSAGES[key])

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
