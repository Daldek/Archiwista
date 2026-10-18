"""Accounts, groups and project access for administrators and owners (A-ADR-029).

HTTP (``archiwista/api/admin.py``) and the command line (``archiwista users``,
``groups`` and ``share``) call these functions with the acting principal.
Each asks ``Authorizer`` before reading or changing anything, so neither has
rules of its own: accounts and groups need ``admin``; a project's access
needs its owner or ``admin``. A project the principal does not see is
``NotFoundError`` (``404``), a visible one they may not manage is
``PermissionDeniedError`` (``403``). Every change lands in the permission
log with the principal as the actor: its id, kind and session label.
"""

from collections.abc import Collection
from dataclasses import dataclass

from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries, ProjectRef
from archiwista.messages import MESSAGES
from archiwista.state import GroupRecord, Role, UserRecord, Visibility


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """Who owns a project and who sees it.

    Attributes
    ----------
    project : str
        Project key (``ProjectRef.key``).
    owner : str or None
        Owning account; ``None``: only administrators manage the project.
    visibility : Visibility
        ``public``, ``users``, ``group`` or ``private``.
    users, groups : tuple[str, ...]
        Listed account ids (``users``) or group ids (``group``).
    explicit : bool
        Whether the project has its own access entry; otherwise
        ``default_project_visibility`` applies and nobody owns it.
    """

    project: str
    owner: str | None
    visibility: Visibility
    users: tuple[str, ...]
    groups: tuple[str, ...]
    explicit: bool


def list_users(authorizer: Authorizer, principal: Principal) -> tuple[UserRecord, ...]:
    """Return every account (``users.manage``)."""
    authorizer.require(principal, "users.manage")
    return authorizer.state.users()


def add_user(
    authorizer: Authorizer,
    principal: Principal,
    user_id: str,
    *,
    name: str | None = None,
    roles: Collection[Role] = (),
) -> UserRecord:
    """Create an account (``users.manage``); see ``StateStore.add_user``."""
    authorizer.require(principal, "users.manage")
    return authorizer.state.add_user(user_id, name=name, roles=roles, actor=principal)


def update_user(
    authorizer: Authorizer,
    principal: Principal,
    user_id: str,
    *,
    name: str | None = None,
    roles: Collection[Role] | None = None,
    disabled: bool | None = None,
) -> UserRecord:
    """Change an account (``users.manage``); see ``StateStore.update_user``."""
    authorizer.require(principal, "users.manage")
    return authorizer.state.update_user(
        user_id, name=name, roles=roles, disabled=disabled, actor=principal
    )


def remove_user(authorizer: Authorizer, principal: Principal, user_id: str) -> None:
    """Remove an account (``users.manage``); see ``StateStore.remove_user``."""
    authorizer.require(principal, "users.manage")
    authorizer.state.remove_user(user_id, actor=principal)


def list_groups(
    authorizer: Authorizer, principal: Principal
) -> tuple[GroupRecord, ...]:
    """Return every group (``groups.manage``)."""
    authorizer.require(principal, "groups.manage")
    return authorizer.state.groups()


def add_group(
    authorizer: Authorizer,
    principal: Principal,
    group_id: str,
    *,
    name: str | None = None,
    members: Collection[str] = (),
) -> GroupRecord:
    """Create a group (``groups.manage``); see ``StateStore.add_group``."""
    authorizer.require(principal, "groups.manage")
    return authorizer.state.add_group(
        group_id, name=name, members=members, actor=principal
    )


def set_group_members(
    authorizer: Authorizer,
    principal: Principal,
    group_id: str,
    members: Collection[str],
) -> GroupRecord:
    """Replace a group's members (``groups.manage``)."""
    authorizer.require(principal, "groups.manage")
    return authorizer.state.set_members(group_id, members, actor=principal)


def remove_group(authorizer: Authorizer, principal: Principal, group_id: str) -> None:
    """Remove a group (``groups.manage``); see ``StateStore.remove_group``."""
    authorizer.require(principal, "groups.manage")
    authorizer.state.remove_group(group_id, actor=principal)


def project_access(
    authorizer: Authorizer,
    queries: IndexQueries,
    principal: Principal,
    project: str,
) -> ProjectAccess:
    """Return who owns and who sees a project (its owner or ``admin``).

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    PermissionDeniedError
        The principal sees the project but neither owns it nor is ``admin``.
    """
    ref = _managed_project(authorizer, queries, principal, project)
    return _access(authorizer, ref)


def share_project(
    authorizer: Authorizer,
    queries: IndexQueries,
    principal: Principal,
    project: str,
    *,
    visibility: Visibility,
    users: Collection[str] = (),
    groups: Collection[str] = (),
    owner: str | None = None,
) -> ProjectAccess:
    """Set who sees a project and, optionally, who owns it.

    Parameters
    ----------
    authorizer : Authorizer
        Decisions and the state database.
    queries : IndexQueries
        Reader of the local index (finds the project).
    principal : Principal
        Who acts: the project's owner or an administrator.
    project : str
        Project key (``ProjectRef.key``).
    visibility : Visibility
        ``public``, ``users`` (with ``users``), ``group`` (with ``groups``)
        or ``private``.
    users, groups : Collection[str], optional
        People or groups who see the project.
    owner : str or None, optional
        New owning account; the current owner stays when omitted.

    Raises
    ------
    NotFoundError
        Unknown project, or one the principal does not see.
    PermissionDeniedError
        The principal sees the project but neither owns it nor is ``admin``.
    InvalidChangeError
        Unknown people, groups or owner, or entries that do not fit.
    """
    ref = _managed_project(authorizer, queries, principal, project)
    if owner is None:
        current = authorizer.state.project_access(ref.access_key)
        owner = None if current is None else current.owner
    authorizer.state.set_project_access(
        ref.access_key,
        owner=owner,
        visibility=visibility,
        users=users,
        groups=groups,
        actor=principal,
    )
    return _access(authorizer, ref)


def _managed_project(
    authorizer: Authorizer,
    queries: IndexQueries,
    principal: Principal,
    project: str,
) -> ProjectRef:
    """Find a project the principal sees, then require ``project.share``."""
    record = queries.project(project, visible=authorizer.visible_projects(principal))
    if record is None:
        raise NotFoundError(MESSAGES["project_not_found"].format(project=project))
    authorizer.require(principal, "project.share", record.project.access_key)
    return record.project


def _access(authorizer: Authorizer, ref: ProjectRef) -> ProjectAccess:
    entry = authorizer.state.project_access(ref.access_key)
    if entry is None:
        return ProjectAccess(
            project=ref.key,
            owner=None,
            visibility=authorizer.default_project_visibility,
            users=(),
            groups=(),
            explicit=False,
        )
    return ProjectAccess(
        project=ref.key,
        owner=entry.owner,
        visibility=entry.visibility,
        users=entry.users,
        groups=entry.groups,
        explicit=True,
    )
