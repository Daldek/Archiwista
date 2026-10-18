"""Permission decisions: visibility matrix, roles, settings (A-ADR-029)."""

from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER, Principal
from archiwista.auth.authorize import Action, Authorizer, principal_for
from archiwista.config import AppSettings
from archiwista.errors import PermissionDeniedError
from archiwista.index.schema import initialize
from archiwista.state import StateStore, Visibility
from tests.fixtures.permissions import (
    ADMIN,
    MANAGES,
    OTHER,
    OWNER,
    SEES,
    VISIBILITY_VALUES,
    WHO,
    WRITER,
    Who,
    add_people,
    as_agent,
    principal,
    share,
)

PROJECT = "/projekty/raba"
UNLISTED = "/projekty/odra"


def _authorizer(state: StateStore, **settings: object) -> Authorizer:
    current = AppSettings.model_validate(settings)
    return Authorizer(state, lambda: current)


@pytest.fixture
def state(tmp_path: Path) -> StateStore:
    """Return a state database with the four people and the group."""
    store = StateStore(tmp_path / "state.sqlite")
    add_people(store)
    return store


@pytest.mark.parametrize("kind", ["user", "agent"])
@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("visibility", VISIBILITY_VALUES)
def test_visibility_matrix(
    tmp_path: Path, state: StateStore, visibility: Visibility, who: Who, kind: str
) -> None:
    """Each identity, and an agent with its token, sees and manages per the matrix."""
    # Arrange
    share(state, PROJECT, visibility)
    authorizer = _authorizer(state)
    acting = principal(state, who)
    if kind == "agent":
        index = tmp_path / "index.sqlite"
        initialize(index)
        acting = as_agent(index, acting)

    # Act
    can_view = authorizer.can(acting, "project.view", PROJECT)
    listed = authorizer.visible_projects(acting).sees(PROJECT)
    can_share = authorizer.can(acting, "project.share", PROJECT)

    # Assert
    assert acting.kind == kind
    assert can_view is listed is (who in SEES[visibility])
    assert can_share is (who in MANAGES)


@pytest.mark.parametrize(
    ("default", "seen_by"),
    [("public", {"owner", "listed", "other", "admin"}), ("private", {"admin"})],
)
def test_unlisted_project_follows_default_visibility(
    state: StateStore, default: str, seen_by: set[str]
) -> None:
    """A project without an entry is public or for administrators only."""
    # Arrange
    authorizer = _authorizer(state, default_project_visibility=default)

    # Act
    seeing = {
        who
        for who in WHO
        if authorizer.visible_projects(principal(state, who)).sees(UNLISTED)
        and authorizer.can(principal(state, who), "project.view", UNLISTED)
    }
    sharing = {
        who
        for who in WHO
        if authorizer.can(principal(state, who), "project.share", UNLISTED)
    }

    # Assert
    assert seeing == seen_by
    # Nobody owns it, so only an administrator manages its access.
    assert sharing == {"admin"}


@pytest.mark.parametrize(
    ("roles", "for_all", "allowed"),
    [
        (frozenset({"store_writer"}), False, True),
        (frozenset(), False, False),
        (frozenset({"admin"}), False, False),
        (frozenset(), True, True),
    ],
)
def test_store_write_needs_role_or_setting(
    state: StateStore, roles: frozenset[str], for_all: bool, allowed: bool
) -> None:
    """``store.write``: the ``store_writer`` role or ``store_write_for_all``."""
    # Arrange
    authorizer = _authorizer(state, store_write_for_all=for_all)
    person = Principal(id=OTHER, kind="user", roles=roles, groups=frozenset())

    # Act
    result = authorizer.can(person, "store.write")

    # Assert
    assert result is allowed


@pytest.mark.parametrize("action", ["users.manage", "groups.manage", "settings.write"])
def test_administration_needs_admin_role(state: StateStore, action: Action) -> None:
    """Accounts, groups and settings: administrators and the local owner only."""
    # Arrange
    authorizer = _authorizer(state)

    # Act
    allowed = {who for who in WHO if authorizer.can(principal(state, who), action)}

    # Assert
    assert allowed == {"admin"}
    assert authorizer.can(LOCAL_OWNER, action)
    with pytest.raises(PermissionDeniedError) as refused:
        authorizer.require(principal(state, "owner"), action)
    assert str(refused.value)


def test_local_owner_sees_and_manages_every_project(state: StateStore) -> None:
    """Local mode: the owner of the computer sees everything, private included."""
    # Arrange
    share(state, PROJECT, "private")
    authorizer = _authorizer(state, default_project_visibility="private")

    # Act
    visible = authorizer.visible_projects(LOCAL_OWNER)

    # Assert
    assert visible.everything
    assert authorizer.can(LOCAL_OWNER, "project.share", PROJECT)
    assert authorizer.can(LOCAL_OWNER, "store.write")


def test_principal_for_reads_roles_and_groups(state: StateStore) -> None:
    """Roles and groups come from the state; unknown or disabled accounts get none."""
    # Arrange
    state.update_user(OWNER, roles=WRITER, actor="local")
    state.update_user(OTHER, disabled=True, actor="local")

    # Act
    owner = principal_for(state, OWNER)
    listed = principal_for(state, "lena")
    admin = principal_for(state, ADMIN)

    # Assert
    assert owner == Principal(OWNER, "user", frozenset({"store_writer"}), frozenset())
    assert listed is not None and listed.groups == frozenset({"hydro"})
    assert admin is not None and admin.roles == frozenset({"admin"})
    assert principal_for(state, OTHER) is None
    assert principal_for(state, "nikt") is None


def test_project_action_without_project_is_a_mistake(state: StateStore) -> None:
    """Asking about a project action without naming the project is refused."""
    # Arrange
    authorizer = _authorizer(state)

    # Act / Assert
    with pytest.raises(ValueError, match="project"):
        authorizer.can(principal(state, "owner"), "project.view")
