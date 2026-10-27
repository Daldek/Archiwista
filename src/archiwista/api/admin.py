"""Accounts, groups and project access over HTTP (A-ADR-029, SPEC 9.2).

``GET/POST /users``, ``PATCH/DELETE /users/{id}``, ``POST
/users/{id}/password``, ``DELETE /users/{id}/sessions``, ``GET/POST
/groups``, ``PUT /groups/{id}/members`` and ``DELETE /groups/{id}`` need
``admin``; ``GET/PUT /projects/{id}/access`` the project's owner or
``admin``. Changes need the session's CSRF token, and each lands in the
action log. The routes only translate: ``archiwista.services.access`` asks
``Authorizer`` and changes the state database. ``archiwista users``,
``groups`` and ``share --json`` print these same models. No answer holds a
password hash; a temporary password is answered once, by the route that
generates it.
"""

from datetime import datetime
from typing import Annotated, Self

from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.dependencies import authorizer, index_queries
from archiwista.api.errors import problem_responses
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.auth.passwords import TemporaryPassword as GeneratedPassword
from archiwista.index import IndexQueries
from archiwista.security import current_principal
from archiwista.services import access as access_service
from archiwista.state import (
    ID_PATTERN,
    NAME_MAX_LENGTH,
    GroupRecord,
    PasswordState,
    Role,
    UserRecord,
    Visibility,
)

router = APIRouter(tags=["permissions"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]

_ID_FIELD = f"^{ID_PATTERN}$"
_ID_DESCRIPTION = "Lowercase letters, digits, '.', '_' and '-', at most 64 characters."
_TIMES = {"created_at": "2026-10-18T12:00:00Z", "updated_at": "2026-10-18T12:00:00Z"}


class User(BaseModel):
    """An account of a person, with the state of its password (never the hash)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "anna.nowak",
                    "name": "Anna Nowak",
                    "roles": ["store_writer"],
                    "groups": ["hydro"],
                    "disabled": False,
                    **_TIMES,
                    "password": "temporary",
                    "password_expires_at": "2026-10-21T12:00:00Z",
                }
            ]
        }
    )

    id: str = Field(description="Stable id; the actor of the person's changes.")
    name: str = Field(description="Display name.")
    roles: list[Role] = Field(
        description="`admin` and/or `store_writer`; none for a regular user."
    )
    groups: list[str] = Field(description="Groups the person belongs to.")
    disabled: bool = Field(description="A disabled account acts nowhere.")
    created_at: datetime
    updated_at: datetime
    password: PasswordState = Field(
        description=(
            "`none`: no password (no sign-in with one); `set`; `temporary`: set by"
            " an administrator, changed at the next sign-in; `expired`: a temporary"
            " password past its end."
        )
    )
    password_expires_at: datetime | None = Field(
        description="The end of a temporary password."
    )

    @classmethod
    def of(cls, record: UserRecord) -> Self:
        """Return the model of an account."""
        return cls(
            id=record.id,
            name=record.name,
            roles=list(record.roles),
            groups=list(record.groups),
            disabled=record.disabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
            password=record.password,
            password_expires_at=record.password_expires_at,
        )


class UserList(BaseModel):
    """Every account, ordered by id."""

    items: list[User]


class TemporaryPassword(BaseModel):
    """A temporary password the server generated, answered this once."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "password": "Hk7m-Q2xa-9cPe-Rt4w",
                    "expires_at": "2026-10-21T12:00:00Z",
                }
            ]
        }
    )

    password: str = Field(
        description=(
            "The password, shown only in this answer (Archiwista keeps its hash);"
            " the person changes it at the first sign-in."
        )
    )
    expires_at: datetime = Field(description="Its end, 72 hours from now.")

    @classmethod
    def of(cls, generated: GeneratedPassword) -> Self:
        """Return the model of a generated password."""
        return cls(password=generated.password, expires_at=generated.expires_at)


class NewUser(BaseModel):
    """An account to create."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"id": "anna.nowak", "name": "Anna Nowak", "roles": ["store_writer"]}
            ]
        },
    )

    id: str = Field(pattern=_ID_FIELD, description=_ID_DESCRIPTION)
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=NAME_MAX_LENGTH,
        description="Display name; the id when omitted.",
    )
    roles: list[Role] = Field(default_factory=list)


class UserChange(BaseModel):
    """Changes of an account; omitted fields stay as they are."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"roles": ["admin", "store_writer"]}]},
    )

    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX_LENGTH)
    roles: list[Role] | None = Field(
        default=None, description="The complete new set of roles."
    )
    disabled: bool | None = None


class Group(BaseModel):
    """A group of people, e.g. a department."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "hydro",
                    "name": "Dział hydrologii",
                    "members": ["anna.nowak", "jan"],
                    **_TIMES,
                }
            ]
        }
    )

    id: str
    name: str = Field(description="Display name.")
    members: list[str] = Field(description="Account ids, ordered.")
    created_at: datetime
    updated_at: datetime

    @classmethod
    def of(cls, record: GroupRecord) -> Self:
        """Return the model of a group."""
        return cls(
            id=record.id,
            name=record.name,
            members=list(record.members),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )


class GroupList(BaseModel):
    """Every group, ordered by id."""

    items: list[Group]


class NewGroup(BaseModel):
    """A group to create, optionally with members."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"id": "hydro", "name": "Dział hydrologii", "members": ["anna.nowak"]}
            ]
        },
    )

    id: str = Field(pattern=_ID_FIELD, description=_ID_DESCRIPTION)
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=NAME_MAX_LENGTH,
        description="Display name; the id when omitted.",
    )
    members: list[str] = Field(default_factory=list)


class GroupMembers(BaseModel):
    """The complete new list of a group's members."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"members": ["anna.nowak", "jan"]}]},
    )

    members: list[str]


class ProjectAccess(BaseModel):
    """Who owns a project and who sees it."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "project": "raba",
                    "owner": "anna.nowak",
                    "visibility": "group",
                    "users": [],
                    "groups": ["hydro"],
                    "explicit": True,
                }
            ]
        }
    )

    project: str = Field(description="Project id, as in /projects/{id}.")
    owner: str | None = Field(
        description="Owning account; null: only administrators manage it."
    )
    visibility: Visibility = Field(
        description=(
            "`public`: everyone; `users`: the listed people; `group`: members of"
            " the listed groups; `private`: the owner only. Administrators see"
            " every project."
        )
    )
    users: list[str]
    groups: list[str]
    explicit: bool = Field(
        description=(
            "Whether the project has its own access entry; otherwise the"
            " setting default_project_visibility applies."
        )
    )

    @classmethod
    def of(cls, access: access_service.ProjectAccess) -> Self:
        """Return the model of a project's access."""
        return cls(
            project=access.project,
            owner=access.owner,
            visibility=access.visibility,
            users=list(access.users),
            groups=list(access.groups),
            explicit=access.explicit,
        )


class AccessChange(BaseModel):
    """New visibility of a project and, optionally, its new owner."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"visibility": "users", "users": ["jan"], "groups": []}]
        },
    )

    visibility: Visibility
    users: list[str] = Field(
        default_factory=list, description="With `users`: at least one person."
    )
    groups: list[str] = Field(
        default_factory=list, description="With `group`: at least one group."
    )
    owner: str | None = Field(
        default=None, description="New owning account; unchanged when omitted."
    )


_UserId = Annotated[str, Path(description="Account id.")]
_GroupId = Annotated[str, Path(description="Group id.")]
_ProjectId = Annotated[str, Path(description="Project id, as in /projects/{id}.")]


@router.get("/users", response_model=UserList)
def list_users(principal: _Principal, decisions: _Authorizer) -> UserList:
    """List every account with its roles and groups (``admin``)."""
    users = access_service.list_users(decisions, principal)
    return UserList(items=[User.of(user) for user in users])


@router.post("/users", response_model=User, status_code=201)
def add_user(body: NewUser, principal: _Principal, decisions: _Authorizer) -> User:
    """Create an account (``admin``); a taken id answers ``409 conflict``."""
    user = access_service.add_user(
        decisions, principal, body.id, name=body.name, roles=body.roles
    )
    return User.of(user)


@router.patch(
    "/users/{user_id}", response_model=User, responses=problem_responses(404, 409)
)
def update_user(
    user_id: _UserId,
    body: UserChange,
    principal: _Principal,
    decisions: _Authorizer,
) -> User:
    """Change an account's name, roles or whether it is disabled (``admin``).

    In team mode the last administrator who can sign in can be neither
    disabled nor deprived of the role: ``409 conflict``, reason ``last_admin``.
    """
    user = access_service.update_user(
        decisions,
        principal,
        user_id,
        name=body.name,
        roles=body.roles,
        disabled=body.disabled,
    )
    return User.of(user)


@router.delete(
    "/users/{user_id}", status_code=204, responses=problem_responses(404, 409)
)
def remove_user(
    user_id: _UserId, principal: _Principal, decisions: _Authorizer
) -> None:
    """Remove an account from groups and project entries, then delete it.

    Projects it owned keep their visibility without an owner (``admin``). In
    team mode the last administrator who can sign in stays: ``409 conflict``,
    reason ``last_admin``.
    """
    access_service.remove_user(decisions, principal, user_id)


@router.post(
    "/users/{user_id}/password",
    response_model=TemporaryPassword,
    responses=problem_responses(404),
)
def set_temporary_password(
    user_id: _UserId,
    principal: _Principal,
    decisions: _Authorizer,
    response: Response,
) -> TemporaryPassword:
    """Give an account a temporary password the server generates (``admin``).

    The password is answered this once (``Cache-Control: no-store``) and is
    valid 72 hours; the person must change it at the first sign-in. Every
    session of the account ends, and the action log records
    ``user.password_reset`` (never the password).
    """
    generated = access_service.set_temporary_password(decisions, principal, user_id)
    response.headers["Cache-Control"] = "no-store"
    return TemporaryPassword.of(generated)


@router.delete(
    "/users/{user_id}/sessions", status_code=204, responses=problem_responses(404)
)
def end_user_sessions(
    user_id: _UserId, principal: _Principal, decisions: _Authorizer
) -> None:
    """End every session of an account and of its agents (``admin``).

    The account's revocation time becomes now: each of its sessions, also of
    a one-time token issued before, answers ``401 session_required`` at its
    next request. Logged as ``user.sessions_ended``.
    """
    access_service.end_sessions(decisions, principal, user_id)


@router.get("/groups", response_model=GroupList)
def list_groups(principal: _Principal, decisions: _Authorizer) -> GroupList:
    """List every group with its members (``admin``)."""
    groups = access_service.list_groups(decisions, principal)
    return GroupList(items=[Group.of(group) for group in groups])


@router.post("/groups", response_model=Group, status_code=201)
def add_group(body: NewGroup, principal: _Principal, decisions: _Authorizer) -> Group:
    """Create a group (``admin``); a taken id answers ``409 conflict``."""
    group = access_service.add_group(
        decisions, principal, body.id, name=body.name, members=body.members
    )
    return Group.of(group)


@router.put("/groups/{group_id}/members", response_model=Group)
def set_group_members(
    group_id: _GroupId,
    body: GroupMembers,
    principal: _Principal,
    decisions: _Authorizer,
) -> Group:
    """Replace a group's members (``admin``)."""
    group = access_service.set_group_members(
        decisions, principal, group_id, body.members
    )
    return Group.of(group)


@router.delete("/groups/{group_id}", status_code=204)
def remove_group(
    group_id: _GroupId, principal: _Principal, decisions: _Authorizer
) -> None:
    """Delete a group and the project entries naming it (``admin``)."""
    access_service.remove_group(decisions, principal, group_id)


@router.get("/projects/{project}/access", response_model=ProjectAccess)
def project_access(
    project: _ProjectId,
    principal: _Principal,
    decisions: _Authorizer,
    queries: _Queries,
) -> ProjectAccess:
    """Return a project's owner and visibility (its owner or ``admin``).

    A project the principal does not see answers ``404 not_found``; one they
    see but do not manage ``403 permission_denied``.
    """
    access = access_service.project_access(decisions, queries, principal, project)
    return ProjectAccess.of(access)


@router.put("/projects/{project}/access", response_model=ProjectAccess)
def share_project(
    project: _ProjectId,
    body: AccessChange,
    principal: _Principal,
    decisions: _Authorizer,
    queries: _Queries,
) -> ProjectAccess:
    """Set who sees a project and, optionally, its owner (its owner or ``admin``).

    Unknown people, groups or owner, and lists that do not fit the
    visibility, answer ``422 validation_error``.
    """
    access = access_service.share_project(
        decisions,
        queries,
        principal,
        project,
        visibility=body.visibility,
        users=body.users,
        groups=body.groups,
        owner=body.owner,
    )
    return ProjectAccess.of(access)
