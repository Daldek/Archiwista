"""The permissions of v0.4 (plan v0.4 C7) over the services, HTTP and the command line.

``Authorizer.can`` answers each new action for every kind of principal: the
computer's owner and their agent, the scheduler, a person and their agent,
an administrator and their agent. The routes, the services and the command
that need an action answer the same: every person and agent creates a
project (the account owns it), the computer's owner too (nobody owns it),
the scheduler never; the jobs of a store and the scan of every project's
data folder are an administrator's. Later steps of v0.4 add their rows
(``log.read``: T8).
"""

import json
from pathlib import Path

import httpx
import pytest

from archiwista.auth import LOCAL_OWNER, SCHEDULER, Principal, access_key
from archiwista.auth.authorize import ACTIONS, Action, Authorizer, principal_for
from archiwista.cli import main
from archiwista.config import ConfigStore
from archiwista.errors import PermissionDeniedError
from archiwista.index import IndexQueries
from archiwista.services.projects import create_project
from archiwista.sources.registry import load_registry
from archiwista.state import ActionQuery, StateStore
from tests.fixtures.permissions import as_agent
from tests.fixtures.team_projects import (
    ADMIN,
    OTHER,
    OWNER,
    STORE,
    TeamPlace,
    add_team,
    person,
    team_api,
    team_place,
)

WHO = (
    "local",
    "local agent",
    "scheduler",
    "kasia",
    "kasia agent",
    "anna",
    "anna agent",
)
# Who may do each action of C7. The scheduler holds the computer's owner's
# roles; it scans stores on its own and never through a route.
MAY: dict[Action, frozenset[str]] = {
    "project.create": frozenset(WHO) - {"scheduler"},
    "store.scan": frozenset(
        {"local", "local agent", "scheduler", "anna", "anna agent"}
    ),
}
# The jobs of a store (``store.scan``): their routes and bodies.
STORE_JOBS: dict[str, tuple[str, dict[str, str] | None]] = {
    "scan": (f"/stores/{STORE}/scan", {"mode": "full"}),
    "footprints": (f"/stores/{STORE}/footprints", None),
    "link-check": (f"/stores/{STORE}/link-check", {"slot": "nmt/arkusz.asc"}),
}


@pytest.fixture
def place(tmp_path: Path) -> TeamPlace:
    """Return a team's store and project directory."""
    return team_place(tmp_path)


def _principals(index: Path, state: StateStore) -> dict[str, Principal]:
    """Return every kind of principal; the agents act with tokens they got."""
    kasia, anna = person(state, OWNER), person(state, ADMIN)
    return {
        "local": LOCAL_OWNER,
        "local agent": as_agent(index, state, LOCAL_OWNER),
        "scheduler": SCHEDULER,
        "kasia": kasia,
        "kasia agent": as_agent(index, state, kasia),
        "anna": anna,
        "anna agent": as_agent(index, state, anna),
    }


def _answer(response: httpx.Response) -> str:
    """Return a status, with the problem's reason or code."""
    if response.headers.get("content-type") == "application/problem+json":
        body = response.json()
        cause = body.get("details", {}).get("reason", body["code"])
        return f"{response.status_code} {cause}"
    return str(response.status_code)


def test_who_may_do_the_actions_of_v04(place: TeamPlace) -> None:
    """``Authorizer.can`` of each action of C7 for every kind of principal."""
    # Arrange
    state = StateStore(place.paths.state_file)
    add_team(state)
    principals = _principals(place.paths.index_file, state)
    decisions = Authorizer(state, ConfigStore(place.paths.config_file).load)

    # Act
    allowed = {
        action: frozenset(
            who
            for who, principal in principals.items()
            if decisions.can(principal, action)
        )
        for action in MAY
    }

    # Assert
    assert allowed == MAY


@pytest.mark.parametrize("agent", [False, True], ids=["person", "agent"])
@pytest.mark.parametrize("account", [OWNER, ADMIN])
def test_every_person_and_agent_creates_a_project_the_account_owns(
    place: TeamPlace, account: str, agent: bool
) -> None:
    """``201``; the account owns the new project, and it is logged as created."""
    with team_api(place) as served:
        # Arrange
        caller = served.caller(account, agent=agent)

        # Act
        created = caller.request("POST", "/projects", json=place.body("raba"))
        access = served.state.project_access(access_key(place.projects / "raba"))
        entries = served.state.actions(ActionQuery(action="project.create")).entries

    # Assert
    assert created.status_code == 201, created.text
    assert access is not None
    assert (access.owner, access.visibility) == (account, "public")
    (entry,) = entries
    assert (entry.actor, entry.actor_kind) == (account, "agent" if agent else "user")
    assert entry.details == {"producer": "kartograf", "owner": account}


@pytest.mark.parametrize("agent", [False, True], ids=["owner", "agent"])
def test_the_computers_owner_and_their_agent_create_projects_nobody_owns(
    tmp_path: Path, agent: bool
) -> None:
    """Local mode: ``201`` without an access entry (the owner has no account)."""
    place = team_place(tmp_path, team=False)
    with team_api(place) as served:
        # Arrange
        caller = served.caller("local", agent=agent)

        # Act
        created = caller.request("POST", "/projects", json=place.body("raba"))
        access = served.state.project_access(access_key(place.projects / "raba"))
        entries = served.state.actions(ActionQuery(action="project.create")).entries

    # Assert
    assert created.status_code == 201, created.text
    assert access is None
    (entry,) = entries
    assert (entry.actor, entry.actor_kind) == (
        "local",
        "agent" if agent else "local_owner",
    )
    assert entry.details == {"producer": "kartograf", "owner": None}


def test_the_command_line_creates_a_project_as_the_computers_owner(
    place: TeamPlace, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista project-init`` in team mode: no owner, logged at the terminal."""
    # Act
    status = main(
        ["project-init", "kartograf", str(place.projects / "raba"), "--store", STORE]
        + ["--json"],
        registry=load_registry(cache_dir=place.paths.cache_dir),
        paths=place.paths,
    )
    printed = json.loads(capsys.readouterr().out)
    state = StateStore(place.paths.state_file)
    access = state.project_access(access_key(place.projects / "raba"))
    entries = state.actions(ActionQuery(action="project.create")).entries

    # Assert
    assert status == 0
    assert printed["project"] == "raba"
    assert access is None
    (entry,) = entries
    assert (entry.actor, entry.actor_kind, entry.session) == (
        "local",
        "local_owner",
        None,
    )
    assert entry.details == {"producer": "kartograf", "owner": None}


def test_the_scheduler_creates_no_project(place: TeamPlace) -> None:
    """``project.create`` is refused to the scheduler; nothing is written."""
    # Arrange
    state = StateStore(place.paths.state_file)
    settings = ConfigStore(place.paths.config_file).load()
    registry = load_registry(cache_dir=place.paths.cache_dir)

    # Act
    with (
        IndexQueries(place.paths.index_file) as queries,
        pytest.raises(PermissionDeniedError),
    ):
        create_project(
            registry,
            settings,
            queries,
            place.paths.index_file,
            Authorizer(state, lambda: settings),
            producer="kartograf",
            path=str(place.projects / "raba"),
            store=STORE,
            actor=SCHEDULER,
        )

    # Assert
    assert not (place.projects / "raba").exists()
    assert state.actions(ActionQuery(action="project.create")).entries == ()


def test_the_jobs_of_a_store_are_an_administrators(place: TeamPlace) -> None:
    """Store scans, unit outlines and link checks need ``store.scan``, a retry too.

    A person and their agent get ``403``. An administrator and their agent
    pass: the scan and the outlines wait as jobs (each cancelled before the
    next, which would write the same index), the link check of a slot the
    index does not know is ``404``. A retry of a store scan, or of the scan
    of every project's data folder, asks again.
    """
    with team_api(place) as served:
        # Arrange
        callers = {
            (account, agent): served.caller(account, agent=agent)
            for account in (OWNER, ADMIN)
            for agent in (False, True)
        }
        every_folder = served.jobs.submit("own_scan", actor=SCHEDULER)
        served.jobs.cancel(every_folder.id)

        # Act
        answers: dict[tuple[str, bool, str], str] = {}
        started: list[str] = []
        for (account, agent), caller in callers.items():
            for name, (path, body) in STORE_JOBS.items():
                answer = caller.request("POST", path, json=body)
                answers[account, agent, name] = _answer(answer)
                if answer.status_code == 202:
                    started.append(answer.json()["id"])
                    served.jobs.cancel(started[-1])
        retries = {
            (job, account): _answer(
                callers[account, False].request("POST", f"/jobs/{job}/retry")
            )
            for job in (started[0], every_folder.id)
            for account in (OWNER, ADMIN)
        }

    # Assert
    refused = "403 permission_denied"
    passed = {"scan": "202", "footprints": "202", "link-check": "404 not_found"}
    assert answers == {
        (account, agent, name): refused if account == OWNER else passed[name]
        for account in (OWNER, ADMIN)
        for agent in (False, True)
        for name in STORE_JOBS
    }
    assert retries == {
        (started[0], OWNER): refused,
        (started[0], ADMIN): "202",
        (every_folder.id, OWNER): refused,
        (every_folder.id, ADMIN): "202",
    }


def test_all_team_actions_follow_the_role_and_resource_matrix(place: TeamPlace) -> None:
    """A project owner, a writer, an admin, agents and a proxy user differ."""
    state = StateStore(place.paths.state_file)
    add_team(state)
    state.update_user(OTHER, roles=["store_writer"], actor=LOCAL_OWNER)
    state.update_user(ADMIN, roles=("admin", "store_writer"), actor=LOCAL_OWNER)
    project = access_key(place.projects / "raba")
    state.set_project_access(
        project, owner=OWNER, visibility="group", groups=("hydro",), actor=LOCAL_OWNER
    )
    kasia = principal_for(state, OWNER)
    marek = principal_for(state, OTHER)
    anna = principal_for(state, ADMIN)
    assert kasia and marek and anna
    principals = {
        "owner": LOCAL_OWNER,
        "owner agent": as_agent(place.paths.index_file, state, LOCAL_OWNER),
        "scheduler": SCHEDULER,
        "admin": anna,
        "admin agent": as_agent(place.paths.index_file, state, anna),
        "writer": marek,
        "writer agent": as_agent(place.paths.index_file, state, marek),
        "user": kasia,
        "user agent": as_agent(place.paths.index_file, state, kasia),
        "proxy writer": Principal(
            id=OTHER,
            kind="user",
            roles=marek.roles,
            groups=marek.groups,
            client="10.0.0.5",
        ),
    }
    privileged = {"owner", "owner agent", "scheduler", "admin", "admin agent"}
    writer = {"writer", "writer agent", "proxy writer"}
    member = {"user", "user agent"}
    expected: dict[Action, set[str]] = {
        "project.view": privileged | member,
        "project.share": privileged | member,
        "project.write": privileged | member,
        "project.create": (privileged - {"scheduler"}) | writer | member,
        "users.manage": privileged,
        "groups.manage": privileged,
        "settings.write": privileged,
        "store.write": privileged | writer,
        "store.scan": privileged,
        "job.cancel": privileged | member,
        "log.read": privileged,
    }
    assert set(expected) == set(ACTIONS)
    authorizer = Authorizer(state, ConfigStore(place.paths.config_file).load)
    for action in ACTIONS:
        resource = OWNER if action == "job.cancel" else project
        allowed = {
            label
            for label, principal in principals.items()
            if authorizer.can(principal, action, resource)
        }
        assert allowed == expected[action], action


def test_team_routes_in_the_plan_are_published_in_openapi(place: TeamPlace) -> None:
    """A planned route missing from the public contract blocks T12 acceptance."""
    expected = {
        ("/session/methods", "get"),
        ("/session/login", "post"),
        ("/session/password", "put"),
        ("/session/proxy", "post"),
        ("/sessions", "get"),
        ("/sessions/{label}", "delete"),
        ("/users/{user_id}/sessions", "delete"),
        ("/users/{user_id}/password", "post"),
        ("/projects", "post"),
        ("/projects/{project}/data-dir", "put"),
        ("/projects/{project}/scan", "post"),
        ("/stores/{store}/scan", "post"),
        ("/stores/{store}/footprints", "post"),
        ("/stores/{store}/link-check", "post"),
        ("/directory", "get"),
        ("/log", "get"),
        ("/log/export", "get"),
        ("/jobs", "get"),
        ("/preferences", "get"),
        ("/preferences", "put"),
        ("/stores/{store}/versions/{version}/file", "get"),
        ("/projects/{project}/files/{file_id}/snapshots/{label}/file", "get"),
        ("/projects/{project}/files/{file_id}/file", "get"),
    }
    with team_api(place) as served:
        response = served.caller(ADMIN).request("GET", "/openapi.json")
        assert response.status_code == 200
        paths = response.json()["paths"]
    actual = {
        (path.removeprefix("/api/v1"), method)
        for path, methods in paths.items()
        for method in methods
    }
    assert expected <= actual, sorted(expected - actual)
    assert ("/settings/year-types", "put") not in actual
