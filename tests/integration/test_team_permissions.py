"""The permissions of v0.4 (plan v0.4 C7, T12) over services, HTTP and the command line.

``Authorizer.can`` answers each new action for every kind of principal: the
computer's owner and their agent, the scheduler, a person and their agent,
an administrator and their agent. The routes, the services and the command
that need an action answer the same: every person and agent creates a
project (the account owns it), the computer's owner too (nobody owns it),
the scheduler never; the jobs of a store and the scan of every project's
data folder are an administrator's. ``MATRIX`` holds every action for an
administrator, a store writer, a person without a role, the agent of each
and a person signed in through the reverse proxy; every route of C9
(``ROUTES``, each in the OpenAPI document) is called by each of them and by
nobody, and answers as ``MATRIX`` says, a refusal changing nothing.
"""

import json
import re
import shutil
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from archiwista.auth import (
    ALL_PROJECTS,
    LOCAL_OWNER,
    SCHEDULER,
    Principal,
    access_key,
    passwords,
)
from archiwista.auth.authorize import ACTIONS, Action, Authorizer, principal_for
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore
from archiwista.errors import PermissionDeniedError
from archiwista.index import IndexQueries, own_file_id
from archiwista.security import SessionStore, issue_one_time_token
from archiwista.services.projects import create_project
from archiwista.sources.registry import load_registry
from archiwista.state import ActionQuery, StateStore
from tests.fixtures.api_session import Caller
from tests.fixtures.api_store import store_settings
from tests.fixtures.local_server import local_paths
from tests.fixtures.own_data import make_own_folder, write_snapshot_fixture
from tests.fixtures.own_data_api import DATA_DIR, FIRST, OwnProject, scan_own
from tests.fixtures.permissions import as_agent
from tests.fixtures.preview_api import entry_of, scanned_store
from tests.fixtures.team_projects import (
    ADMIN,
    GROUP,
    OTHER,
    OWNER,
    STORE,
    TeamApi,
    TeamPlace,
    add_team,
    person,
    team_api,
    team_place,
)
from tests.fixtures.team_server import PERSON_PEER, cheap_hasher, save_team, team_client

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
# Who may do each action of v0.4 (plan v0.4 T12, criterion 2) on the project
# Kasia owns and shares with her group, and on a job of hers (``job.cancel``):
# the computer's owner, the scheduler, Anna (``admin``, ``store_writer``),
# Marek (``store_writer``), Kasia (no role), the agents of each, and Marek
# signed in through the reverse proxy.
PRIVILEGED = frozenset({"owner", "owner agent", "scheduler", "admin", "admin agent"})
WRITER = frozenset({"writer", "writer agent", "proxy writer"})
MEMBER = frozenset({"user", "user agent"})
MATRIX: dict[Action, frozenset[str]] = {
    "project.view": PRIVILEGED | MEMBER,
    "project.share": PRIVILEGED | MEMBER,
    "project.write": PRIVILEGED | MEMBER,
    "project.create": (PRIVILEGED - {"scheduler"}) | WRITER | MEMBER,
    "users.manage": PRIVILEGED,
    "groups.manage": PRIVILEGED,
    "settings.write": PRIVILEGED,
    "store.write": PRIVILEGED | WRITER,
    "store.scan": PRIVILEGED,
    "job.cancel": PRIVILEGED | MEMBER,
    "log.read": PRIVILEGED,
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
    assert entry.details == {"name": "raba", "owner": account}


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
    assert entry.details == {"name": "raba", "owner": None}


def test_the_command_line_creates_a_project_as_the_computers_owner(
    place: TeamPlace, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista project-init`` in team mode: no owner, logged at the terminal."""
    # Act
    status = main(
        ["project-init", str(place.projects / "raba"), "--json"],
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
    assert entry.details == {"name": "raba", "owner": None}


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
            path=str(place.projects / "raba"),
            name=None,
            description="",
            area_id=None,
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
    """``Authorizer.can`` of every action answers ``MATRIX`` for every principal."""
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
    assert set(MATRIX) == set(ACTIONS)
    authorizer = Authorizer(state, ConfigStore(place.paths.config_file).load)
    for action in ACTIONS:
        resource = OWNER if action == "job.cancel" else project
        allowed = {
            label
            for label, principal in principals.items()
            if authorizer.can(principal, action, resource)
        }
        assert allowed == MATRIX[action], action


def test_team_routes_in_the_plan_are_published_in_openapi(place: TeamPlace) -> None:
    """A route of ``ROUTES`` missing from the public contract blocks T12 acceptance."""
    expected = {
        (route.path.partition("?")[0], route.method.lower())
        for route in ROUTES
        if route.method != "HEAD"
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


# Who calls each route over HTTP: nobody (no session), the people of ``MATRIX``
# with their accounts, each person's agent, and Marek through the proxy.
CALLERS = (
    "anonymous",
    "admin",
    "admin agent",
    "writer",
    "writer agent",
    "user",
    "user agent",
    "proxy writer",
)
ACCOUNTS = {"admin": ADMIN, "writer": OTHER, "user": OWNER}
# The account the administrators' routes change, and the passwords of the team.
TARGET = "ola"
PASSWORD = "wiosla-w-szuwarach-Wisly"
NEW_PASSWORD = "most-na-Sanie-w-Przemyslu"
# The reverse proxy names the person in HEADER (plan v0.4 C6).
PROXY_PEER = "10.0.0.2"
HEADER = "X-Remote-User"

type Rule = Literal["public", "proxy", "session", "no agent", "password"]
type Body = Callable[["Scene", str], object]


@dataclass(frozen=True)
class Route:
    """A route of plan v0.4 C9: who may call it, its answer then, its request.

    ``may`` is an action of ``MATRIX``, or a rule: ``public`` (no session
    needed), ``proxy`` (a request of the trusted proxy only), ``session``
    (every session), ``no agent`` (a person's session, through the proxy
    too) or ``password`` (a person's session with a password: no agent, no
    proxy). ``path`` is the route's OpenAPI path; ``fill`` names the value
    of ``Scene.values`` that replaces a parameter when another than the
    parameter's own. ``refused`` answers a session the action is refused to
    (``404`` where a refusal hides what exists; a project's route answers
    ``404`` to a session that does not see the project). ``cancel``: the job
    an allowed call starts is cancelled before the next call (the store's
    jobs would write the same index); a project's scan is joined instead.
    """

    method: str
    path: str
    may: Action | Rule
    status: int
    body: Body | None = None
    fill: tuple[tuple[str, str], ...] = ()
    refused: str = "403 permission_denied"
    cancel: bool = False


def _sign_in(scene: "Scene", who: str) -> object:
    return {"account": OTHER, "password": PASSWORD}


def _token(scene: "Scene", who: str) -> object:
    minter = person(scene.served.state, OTHER)
    issued = issue_one_time_token(
        scene.place.paths.index_file, "agent", minted_by=minter
    )
    return {"token": issued.token}


def _password(scene: "Scene", who: str) -> object:
    return {"current_password": PASSWORD, "new_password": NEW_PASSWORD}


def _renamed(scene: "Scene", who: str) -> object:
    return {"name": "Ola Sowa-Nowak"}


def _new_project(scene: "Scene", who: str) -> object:
    return scene.place.body(f"nowy-{next(scene.made)}")


def _default_folder(scene: "Scene", who: str) -> object:
    return {"path": None}


def _full_scan(scene: "Scene", who: str) -> object:
    return {"mode": "full"}


def _slot(scene: "Scene", who: str) -> object:
    return {"slot": scene.site.slot}


def _settings(scene: "Scene", who: str) -> object:
    return scene.served.caller(ADMIN).request("GET", "/settings").json()


def _preferences(scene: "Scene", who: str) -> object:
    return {}


_VERSION_FILE = "/stores/{store}/versions/{version}/file"
_OWN_FILE = "/projects/{project}/files/{file_id}/file"
_SNAPSHOT_FILE = "/projects/{project}/files/{file_id}/snapshots/{label}/file"
# Every route of C9, in the order of its table.
ROUTES = (
    Route("GET", "/session/methods", "public", 200),
    Route("POST", "/session/login", "public", 200, _sign_in),
    Route("PUT", "/session/password", "password", 200, _password),
    Route("GET", "/sessions", "session", 200),
    Route("GET", "/sessions?user=ola", "users.manage", 200),
    Route(
        "DELETE",
        "/sessions/{label}",
        "users.manage",
        204,
        fill=(("label", "session"),),
        refused="404 not_found",
    ),
    Route("DELETE", "/users/{user_id}/sessions", "users.manage", 204),
    Route("GET", "/session", "session", 200),
    Route("POST", "/session", "public", 200, _token),
    Route("POST", "/session/tokens", "no agent", 201),
    Route("POST", "/users/{user_id}/password", "users.manage", 200),
    Route("GET", "/users", "users.manage", 200),
    Route("PATCH", "/users/{user_id}", "users.manage", 200, _renamed),
    Route(
        "DELETE",
        "/users/{user_id}",
        "users.manage",
        204,
        fill=(("user_id", "account"),),
    ),
    Route("POST", "/session/proxy", "proxy", 200),
    Route("POST", "/projects", "project.create", 201, _new_project),
    Route("PUT", "/projects/{project}/data-dir", "project.write", 200, _default_folder),
    Route("POST", "/projects/{project}/scan", "project.view", 202),
    Route("POST", "/stores/{store}/scan", "store.scan", 202, _full_scan, cancel=True),
    Route("POST", "/stores/{store}/footprints", "store.scan", 202, cancel=True),
    Route("POST", "/stores/{store}/link-check", "store.scan", 202, _slot, cancel=True),
    Route("GET", "/directory", "session", 200),
    Route("GET", "/log", "log.read", 200),
    Route("GET", "/log/export", "log.read", 200),
    Route("GET", "/settings", "session", 200),
    Route("PUT", "/settings", "settings.write", 200, _settings),
    Route("GET", "/jobs", "session", 200),
    Route("GET", _VERSION_FILE, "session", 200),
    Route("HEAD", _VERSION_FILE, "session", 200),
    Route("GET", _OWN_FILE, "project.view", 200),
    Route("HEAD", _OWN_FILE, "project.view", 200),
    Route("GET", _SNAPSHOT_FILE, "project.view", 200),
    Route("HEAD", _SNAPSHOT_FILE, "project.view", 200),
    Route("GET", "/preferences", "session", 200),
    Route("PUT", "/preferences", "session", 200, _preferences),
)


@dataclass(frozen=True)
class Site:
    """A generated store, a project of it with a scanned data folder, team settings.

    Attributes
    ----------
    paths : AppPaths
        The settings (team mode behind the proxy at ``PROXY_PEER``) and the
        index; a test serves a copy.
    projects : Path
        The project directory of the settings.
    version : str
        A version of the store.
    slot : str
        A slot of the store.
    project : OwnProject
        The project and its data folder.
    raster : str
        A working file of the folder.
    snapshot : str
        The label of a snapshot of ``raster``.
    """

    paths: AppPaths
    projects: Path
    version: str
    slot: str
    project: OwnProject
    raster: str
    snapshot: str


@dataclass
class Scene:
    """A team server over a copy of the site, the team, and the proxy's client."""

    site: Site
    place: TeamPlace
    served: TeamApi
    proxy: TestClient
    made: Iterator[int] = field(default_factory=count)

    def values(self, route: Route) -> dict[str, str]:
        """Return the values of the route's path parameters, making what they name."""
        makers: dict[str, Callable[[], str]] = {
            "store": lambda: STORE,
            "version": lambda: self.site.version,
            "project": lambda: self.site.project.key,
            "file_id": lambda: own_file_id(self.site.raster),
            "label": lambda: self.site.snapshot,
            "user_id": lambda: TARGET,
            "account": self._account,
            "session": self._session,
        }
        fill = dict(route.fill)
        names = re.findall(r"{(\w+)}", route.path)
        return {name: makers[fill.get(name, name)]() for name in names}

    def prepare(self, route: Route, who: str) -> Callable[[], httpx.Response]:
        """Open a new session of ``who`` and make the request; return its sending."""
        caller = self._caller(who)
        path = route.path.format(**self.values(route))
        body = None if route.body is None else route.body(self, who)
        client = self.served.api.client

        def send() -> httpx.Response:
            answer: httpx.Response
            if caller is None:
                answer = client.request(route.method, f"/api/v1{path}", json=body)
            else:
                answer = caller.request(route.method, path, json=body)
            client.cookies.clear()
            self.proxy.cookies.clear()
            return answer

        return send

    def effects(self) -> tuple[object, ...]:
        """Return what a call can change: state, sessions, jobs, settings, index."""
        state = self.served.state.snapshot()
        sessions: SessionStore = cast(
            FastAPI, self.served.api.client.app
        ).state.sessions
        with IndexQueries(self.place.paths.index_file) as queries:
            projects = queries.projects(visible=ALL_PROJECTS)
        return (
            state.users,
            state.groups,
            state.projects,
            state.passwords,
            state.preferences,
            [
                (item.action, item.target)
                for item in state.actions
                if item.outcome == "ok"
            ],
            sorted(
                item.label for user in state.users for item in sessions.live(user.id)
            ),
            [(job.id, job.state) for job in self.served.jobs.list(limit=100).items],
            self.place.paths.config_file.read_text(encoding="utf-8"),
            projects,
        )

    def _caller(self, who: str) -> Caller | None:
        if who == "anonymous":
            return None
        if who == "proxy writer":
            answer = self.proxy.post("/api/v1/session/proxy")
            assert answer.status_code == 200, answer.text
            self.proxy.cookies.clear()
            session_id = answer.cookies[self.served.api.cookie]
            csrf = str(answer.json()["csrf_token"])
            return Caller(self.proxy, session_id, csrf, self.served.api.cookie)
        account, _, agent = who.partition(" ")
        return self.served.caller(ACCOUNTS[account], agent=bool(agent))

    def _account(self) -> str:
        account = f"cel-{next(self.made)}"
        self.served.state.add_user(account, actor=LOCAL_OWNER)
        return account

    def _session(self) -> str:
        """Open a session of the target account and return its label."""
        answer = self.served.caller(TARGET).request("GET", "/session")
        return str(answer.json()["label"])


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Site:
    """Generate and scan the store and the data folder once for every route."""
    store, paths = scanned_store(tmp_path_factory.mktemp("team-routes"))
    directory = store.base / store.project(FIRST).path
    folder = make_own_folder(directory / DATA_DIR, families=("tif_2180",))
    raster = folder.file("tif_2180").path
    created = datetime(2026, 10, 20, 12, tzinfo=UTC)
    snapshot = write_snapshot_fixture(folder.root, raster, created_at=created)
    scan_own(paths)
    save_team(
        paths,
        store_settings(store),
        trusted_proxies=[PROXY_PEER],
        proxy_user_header=HEADER,
    )
    return Site(
        paths,
        store.projects_dir,
        entry_of(store, "tif_sheet", "regular").path,
        store.by_kind("link")[0].path,
        OwnProject(FIRST, directory, folder),
        raster,
        snapshot.label,
    )


@pytest.fixture
def scene(
    site: Site, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Scene]:
    """Serve a copy of the site in team mode with the team of ``MATRIX``.

    Anna, Marek and Kasia have passwords; Kasia owns the project and shares
    it with her group, as for ``MATRIX``; Ola is the account the
    administrators' routes change.
    """
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())
    paths = local_paths(tmp_path)
    shutil.copytree(site.paths.config_file.parent, paths.config_file.parent)
    shutil.copytree(site.paths.data_dir, paths.data_dir)
    place = TeamPlace(paths, site.projects, tmp_path / "imgw")
    with team_api(place) as served:
        state = served.state
        state.update_user(OTHER, roles=["store_writer"], actor=LOCAL_OWNER)
        state.update_user(ADMIN, roles=("admin", "store_writer"), actor=LOCAL_OWNER)
        state.add_user(TARGET, name="Ola Sowa", actor=LOCAL_OWNER)
        for account in ACCOUNTS.values():
            passwords.set_password(
                state, account, PASSWORD, temporary=False, actor=LOCAL_OWNER
            )
        state.set_project_access(
            site.project.access_key,
            owner=OWNER,
            visibility="group",
            groups=(GROUP,),
            actor=LOCAL_OWNER,
        )
        proxy = team_client(cast(FastAPI, served.api.client.app), peer=PROXY_PEER)
        proxy.headers[HEADER] = OTHER
        proxy.headers["x-forwarded-for"] = PERSON_PEER
        yield Scene(site, place, served, proxy)


def _expected(route: Route, who: str) -> str:
    """Return the answer ``MATRIX`` and the route's rule give ``who``."""
    allowed = str(route.status)
    if route.may == "public":
        return allowed
    if route.may == "proxy":
        return allowed if who == "proxy writer" else "401 login_failed"
    if who == "anonymous":
        return "401 session_required"
    agent = who.endswith(" agent")
    if route.may == "session":
        return allowed
    if route.may == "no agent":
        return "403 permission_denied" if agent else allowed
    if route.may == "password":
        if agent:
            return "403 permission_denied"
        return "409 proxy_session" if who == "proxy writer" else allowed
    if who in MATRIX[route.may]:
        return allowed
    if route.may.startswith("project.") and who not in MATRIX["project.view"]:
        return "404 not_found"
    return route.refused


@pytest.mark.parametrize(
    "route", ROUTES, ids=[f"{route.method} {route.path}" for route in ROUTES]
)
def test_every_route_of_v04_answers_each_caller_as_the_matrix_says(
    scene: Scene, route: Route
) -> None:
    """Each caller of a route gets what ``MATRIX`` allows, a refusal changes nothing.

    Every call opens a new session of its caller first, so an earlier call
    (a changed password, ended sessions) never decides a later one. A
    ``HEAD`` answers the status alone.
    """
    # Act
    answers: dict[str, str] = {}
    changed: list[str] = []
    for who in CALLERS:
        send = scene.prepare(route, who)
        before = scene.effects()
        response = send()
        refused = response.status_code >= 400
        if refused and scene.effects() != before:
            changed.append(who)
        if route.method == "HEAD":
            answers[who] = str(response.status_code)
        else:
            answers[who] = _answer(response)
        if route.cancel and response.status_code == 202:
            scene.served.jobs.cancel(response.json()["id"])

    # Assert
    expected = {who: _expected(route, who) for who in CALLERS}
    if route.method == "HEAD":
        expected = {who: answer.split()[0] for who, answer in expected.items()}
    assert answers == expected
    assert changed == []
