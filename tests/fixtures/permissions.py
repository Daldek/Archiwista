"""People, a group and project access for permission tests (A-ADR-029).

Four identities cover the visibility matrix: the project's owner, a person
listed in its access entry (by name for ``users``, as a member of the
listed group for ``group``), another person and an administrator.
"""

from pathlib import Path
from typing import Literal

from archiwista.auth import LOCAL_OWNER, Principal
from archiwista.auth.authorize import principal_for, session_principal
from archiwista.security import issue_one_time_token, redeem_one_time_token
from archiwista.state import ActionEntry, ActionQuery, Role, StateStore, Visibility

type Who = Literal["owner", "listed", "other", "admin"]

OWNER = "olga"
LISTED = "lena"
OTHER = "igor"
ADMIN = "ada"
GROUP = "hydro"
ACCOUNTS: dict[Who, str] = {
    "owner": OWNER,
    "listed": LISTED,
    "other": OTHER,
    "admin": ADMIN,
}
VISIBILITY_VALUES: tuple[Visibility, ...] = ("public", "users", "group", "private")
WHO: tuple[Who, ...] = ("owner", "listed", "other", "admin")
# Who sees a project of each visibility (A-ADR-029, SPEC 10.2).
SEES: dict[Visibility, frozenset[Who]] = {
    "public": frozenset({"owner", "listed", "other", "admin"}),
    "users": frozenset({"owner", "listed", "admin"}),
    "group": frozenset({"owner", "listed", "admin"}),
    "private": frozenset({"owner", "admin"}),
}
# Who manages a project's access: its owner and administrators.
MANAGES: frozenset[Who] = frozenset({"owner", "admin"})

ADMIN_ROLE: tuple[Role, ...] = ("admin",)
WRITER: tuple[Role, ...] = ("store_writer",)


def add_people(state: StateStore) -> None:
    """Create the four accounts and the group ``hydro`` with the listed person."""
    state.add_user(OWNER, name="Olga Owczarek", actor=LOCAL_OWNER)
    state.add_user(LISTED, name="Lena Lis", actor=LOCAL_OWNER)
    state.add_user(OTHER, name="Igor Inny", actor=LOCAL_OWNER)
    state.add_user(ADMIN, name="Ada Admin", roles=ADMIN_ROLE, actor=LOCAL_OWNER)
    state.add_group(GROUP, name="Hydrologia", members=(LISTED,), actor=LOCAL_OWNER)


def share(state: StateStore, project: str, visibility: Visibility) -> None:
    """Give a project the owner ``olga``, a visibility and its listed entry."""
    state.set_project_access(
        project,
        owner=OWNER,
        visibility=visibility,
        users=(LISTED,) if visibility == "users" else (),
        groups=(GROUP,) if visibility == "group" else (),
        actor=LOCAL_OWNER,
    )


def principal(state: StateStore, who: Who) -> Principal:
    """Return the principal of one of the four accounts, from the state."""
    found = principal_for(state, ACCOUNTS[who])
    assert found is not None
    return found


def as_agent(index_path: Path, state: StateStore, minter: Principal) -> Principal:
    """Return the agent acting with a token ``minter`` issued (the real flow)."""
    issued = issue_one_time_token(index_path, "agent", minted_by=minter)
    grant = redeem_one_time_token(index_path, issued.token)
    assert grant is not None
    agent = session_principal(
        state, grant.principal_id, grant.kind, session=grant.label
    )
    assert agent is not None
    return agent


def last_entry(state: StateStore) -> int:
    """Return the id of the newest entry of the action log, ``0`` without one."""
    newest = state.actions(ActionQuery(limit=1)).entries
    return newest[0].id if newest else 0


def log_entries(state: StateStore, *, after: int = 0) -> list[ActionEntry]:
    """Return the entries of the action log newer than ``after``, oldest first."""
    page = state.actions(ActionQuery(limit=10_000))
    return [entry for entry in reversed(page.entries) if entry.id > after]
