"""The action log: every action logged once, who reads and exports it (T8).

Each name of ``ActionName`` has a case in ``CASES`` that performs the action
through the API, the command line or (for the pruning) the server's scheduler
and finds exactly one entry of it with its actor, the actor's kind, the
session's label, the client address, the target and the outcome; a name
without a case fails ``test_each_action_is_logged_once``. The world is a
marked Kartograf store ``zespol`` (empty), a project directory, the four
people of ``tests.fixtures.permissions`` and a supervisor that starts no job,
so jobs wait to be cancelled and retried; the download of a file uses a
generated store scanned into the index (``served_store``); signing in,
passwords, sessions and agents' tokens use a team server with TLS behind a
trusted proxy (``team``). Reading the log: its pages and both formats of its
export hold the same entries, a CSV cell that could start a formula is
escaped, only administrators read it, the command line prints what the
routes answer, and times bound it in any zone. Offline.
"""

import csv
import io
import json
import os
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args
from urllib.parse import quote

import httpx
import kartograf
import pytest
from fastapi import FastAPI

from archiwista.api.errors import DenialLog
from archiwista.auth import LOCAL_OWNER, access_key, passwords
from archiwista.cli import main
from archiwista.config import (
    DEFAULT_ACTION_LOG_RETENTION_DAYS,
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.jobs import JobSupervisor, ScanScheduler
from archiwista.services.log import FIELDS
from archiwista.sources.registry import SourceRegistry, load_registry
from archiwista.state import ActionEntry, ActionName, StateSnapshot, StateStore
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.api_store import served_store
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    ADMIN,
    GROUP,
    LISTED,
    OTHER,
    add_people,
    last_entry,
    log_entries,
    principal,
)
from tests.fixtures.preview_api import entry_of
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    PERSON_PEER,
    add_admin,
    add_person,
    cheap_hasher,
    save_team,
    team_client,
)

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

STORE = "zespol"
CLIENT = "testclient"
TASK = "teren"
# A task Kartograf checks without the network: a box of 1 km² in PL-1992.
TASK_BODY: dict[str, Any] = {
    "name": TASK,
    "command": "elevation download",
    "options": {
        "product": "nmt",
        "country": "pl",
        "bbox": [500000, 250000, 501000, 251000],
        "bbox_crs": "EPSG:2180",
        "sheet_system": "1992",
        "resolution": "1m",
        "vertical_crs": "EVRF2007",
        "year": 2023,
    },
}
ACTION_NAMES: tuple[str, ...] = get_args(ActionName.__value__)
# The team server of the cases of signing in (plan v0.4 T3, T4): Kasia signs in
# with her password from PERSON_PEER, Anna (ADMIN_ACCOUNT) administers, and the
# proxy at PROXY_PEER would name people in HEADER.
PERSON = "kasia"
PERSON_PASSWORD = "wiosla-w-szuwarach-Wisly"
NEW_PASSWORD = "most-na-Sanie-w-Przemyslu"
WRONG_PASSWORD = "to-nie-jest-to-haslo"
HEADER = "X-Remote-User"
PROXY_PEER = "10.0.0.2"
OTHER_PEER = "10.0.0.9"


@dataclass(frozen=True)
class Logged:
    """The entry an action leaves: who, how, from where, about what, the outcome.

    ``details``, ``before`` and ``after`` are compared when given.
    """

    actor: str
    actor_kind: str
    session: str | None
    client: str | None
    target: str
    outcome: str = "ok"
    details: dict[str, Any] | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


@dataclass(frozen=True)
class Performed:
    """An action done: its log, the newest entry before it and what it logged."""

    state: StateStore
    since: int
    expected: Logged


@dataclass(frozen=True)
class World:
    """The API over an empty marked store with a project, people and idle jobs."""

    api: Api
    paths: AppPaths
    settings: SettingsService
    registry: SourceRegistry
    jobs: JobSupervisor
    owner: Caller
    person: Caller
    admin: Caller
    project: str
    directory: Path


@contextmanager
def world(tmp_path: Path) -> Iterator[World]:
    """Serve an installation whose supervisor starts no job (``max_jobs=0``)."""
    root = tmp_path / "nas" / "kartograf"
    kartograf.init_store(root)
    projects = tmp_path / "nas" / "projekty"
    projects.mkdir()
    paths = local_paths(tmp_path)
    store = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(
        AppSettings(stores=(store,), project_dirs=(projects,))
    )
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    state = StateStore(paths.state_file)
    with (
        JobSupervisor(paths, settings, max_jobs=0, record=state.record) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        add_people(api.state)
        owner = api.session(LOCAL_OWNER)
        directory = projects / "raba"
        created = owner.request(
            "POST",
            "/projects",
            json={"producer": "kartograf", "path": str(directory), "store": STORE},
        )
        assert created.status_code == 201, created.text
        yield World(
            api,
            paths,
            settings,
            registry,
            jobs,
            owner,
            api.session(principal(api.state, "other")),
            api.session(principal(api.state, "admin")),
            created.json()["project"],
            directory,
        )


def label(caller: Caller) -> str:
    """Return the label of a caller's session."""
    return str(caller.request("GET", "/session").json()["label"])


def as_owner(world: World, target: str, **compared: Any) -> Logged:
    """Return the entry of the local owner's session about ``target``."""
    return Logged(
        "local", "local_owner", label(world.owner), CLIENT, target, **compared
    )


def as_person(world: World, target: str, **compared: Any) -> Logged:
    """Return the entry of Igor's session (no roles) about ``target``."""
    return Logged(OTHER, "user", label(world.person), CLIENT, target, **compared)


def as_admin(world: World, target: str, **compared: Any) -> Logged:
    """Return the entry of Ada's session (``admin``) about ``target``."""
    return Logged(ADMIN, "user", label(world.admin), CLIENT, target, **compared)


def started_scan(world: World) -> dict[str, Any]:
    """Start a full scan of the store as Ada; it waits (no job starts).

    A store's scan is an administrator's (``store.scan``).
    """
    started = world.admin.request(
        "POST", f"/stores/{STORE}/scan", json={"mode": "full"}
    )
    assert started.status_code == 202, started.text
    job: dict[str, Any] = started.json()
    return job


@contextmanager
def team(tmp_path: Path) -> Iterator[Api]:
    """Serve team mode with TLS in the server, trusting the proxy at ``PROXY_PEER``.

    Anna (``admin``) and Kasia have passwords; the client's requests come
    from ``PERSON_PEER`` straight to the server.
    """
    paths = local_paths(tmp_path)
    save_team(paths, trusted_proxies=[PROXY_PEER], proxy_user_header=HEADER)
    add_admin(paths)
    add_person(paths, PERSON, PERSON_PASSWORD)
    with running_api(paths) as api:
        yield api


def sign_in(api: Api, account: str, password: str) -> httpx.Response:
    """Send ``POST /session/login``; the client keeps no cookie afterwards."""
    body = {"account": account, "password": password}
    answer: httpx.Response = api.client.post("/api/v1/session/login", json=body)
    api.client.cookies.clear()
    return answer


def signed_in(api: Api, account: str, password: str) -> Caller:
    """Sign in to the team server and return the session."""
    answer = sign_in(api, account, password)
    assert answer.status_code == 200, answer.text
    csrf = answer.json()["csrf_token"]
    return Caller(api.client, answer.cookies[api.cookie], csrf, api.cookie)


def as_account(session: Caller, account: str, target: str, **compared: Any) -> Logged:
    """Return the entry of a person's session on the team server."""
    return Logged(account, "user", label(session), PERSON_PEER, target, **compared)


def session_login(tmp_path: Path) -> Performed:
    """Kasia signs in with her password."""
    with team(tmp_path) as api:
        since = last_entry(api.state)
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        expected = as_account(kasia, PERSON, PERSON, details={"method": "password"})
        return Performed(api.state, since, expected)


def session_login_failed(tmp_path: Path) -> Performed:
    """Kasia's wrong password: a failure of a client not signed in."""
    with team(tmp_path) as api:
        since = last_entry(api.state)
        refused = sign_in(api, PERSON, WRONG_PASSWORD)
        assert_problem(refused, 401, "unauthorized", "login_failed")
        details = {"reason": "login_failed", "method": "password"}
        expected = Logged(
            "-", "anonymous", None, PERSON_PEER, PERSON, "failed", details=details
        )
        return Performed(api.state, since, expected)


def session_logout(tmp_path: Path) -> Performed:
    """Kasia signs out."""
    with team(tmp_path) as api:
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        expected = as_account(kasia, PERSON, PERSON)
        since = last_entry(api.state)
        ended = kasia.request("DELETE", "/session")
        api.client.cookies.clear()
        assert ended.status_code == 204, ended.text
        return Performed(api.state, since, expected)


def session_password(tmp_path: Path) -> Performed:
    """Kasia changes her password, logged by the session she changed it in."""
    with team(tmp_path) as api:
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        details = {"temporary": False, "expires_at": None}
        expected = as_account(kasia, PERSON, PERSON, details=details)
        since = last_entry(api.state)
        body = {"current_password": PERSON_PASSWORD, "new_password": NEW_PASSWORD}
        changed = kasia.request("PUT", "/session/password", json=body)
        api.client.cookies.clear()
        assert changed.status_code == 200, changed.text
        return Performed(api.state, since, expected)


def session_ended(tmp_path: Path) -> Performed:
    """Kasia ends her other session by its label."""
    with team(tmp_path) as api:
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        other = label(signed_in(api, PERSON, PERSON_PASSWORD))
        expected = as_account(kasia, PERSON, PERSON, details={"label": other})
        since = last_entry(api.state)
        ended = kasia.request("DELETE", f"/sessions/{other}")
        assert ended.status_code == 204, ended.text
        return Performed(api.state, since, expected)


def session_proxy_header_ignored(tmp_path: Path) -> Performed:
    """Send the proxy's header from a computer that is no trusted proxy."""
    with team(tmp_path) as api:
        app = api.client.app
        assert isinstance(app, FastAPI)
        stranger = team_client(app, peer=OTHER_PEER)
        stranger.headers[HEADER] = PERSON
        since = last_entry(api.state)
        refused = stranger.post("/api/v1/session/proxy")
        assert_problem(refused, 401, "unauthorized", "login_failed")
        expected = Logged("-", "anonymous", None, OTHER_PEER, OTHER_PEER, "denied")
        return Performed(api.state, since, expected)


def token_issue(tmp_path: Path) -> Performed:
    """Kasia issues a one-time token for her agent."""
    with team(tmp_path) as api:
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        since = last_entry(api.state)
        issued = kasia.request("POST", "/session/tokens")
        assert issued.status_code == 201, issued.text
        details = {"label": issued.json()["label"]}
        expected = as_account(kasia, PERSON, PERSON, details=details)
        return Performed(api.state, since, expected)


def token_revoke_all(tmp_path: Path) -> Performed:
    """Refuse Kasia's unused agent token at the terminal, as the computer's owner."""
    with team(tmp_path) as api:
        kasia = signed_in(api, PERSON, PERSON_PASSWORD)
        issued = kasia.request("POST", "/session/tokens")
        assert issued.status_code == 201, issued.text
        since = last_entry(api.state)
        assert main(["token", "--revoke-all"], paths=api.paths) == 0
        expected = Logged("local", "local_owner", None, None, "*", details={"count": 1})
        return Performed(api.state, since, expected)


def user_add(tmp_path: Path) -> Performed:
    """Add an account as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        added = made.owner.request("POST", "/users", json={"id": "kasia"})
        assert added.status_code == 201, added.text
        return Performed(made.api.state, since, as_owner(made, "kasia"))


def user_update(tmp_path: Path) -> Performed:
    """Give Igor a role as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        body = {"roles": ["store_writer"]}
        changed = made.owner.request("PATCH", f"/users/{OTHER}", json=body)
        assert changed.status_code == 200, changed.text
        return Performed(made.api.state, since, as_owner(made, OTHER))


def user_remove(tmp_path: Path) -> Performed:
    """Remove Igor's account as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        removed = made.owner.request("DELETE", f"/users/{OTHER}")
        assert removed.status_code == 204, removed.text
        return Performed(made.api.state, since, as_owner(made, OTHER))


def user_password_reset(tmp_path: Path) -> Performed:
    """Anna gives Kasia a temporary password."""
    with team(tmp_path) as api:
        anna = signed_in(api, ADMIN_ACCOUNT, ADMIN_PASSWORD)
        since = last_entry(api.state)
        reset = anna.request("POST", f"/users/{PERSON}/password")
        assert reset.status_code == 200, reset.text
        ends = datetime.fromisoformat(reset.json()["expires_at"]).astimezone(UTC)
        details = {"temporary": True, "expires_at": ends.isoformat(timespec="seconds")}
        expected = as_account(anna, ADMIN_ACCOUNT, PERSON, details=details)
        return Performed(api.state, since, expected)


def user_sessions_ended(tmp_path: Path) -> Performed:
    """Anna ends every session of Kasia."""
    with team(tmp_path) as api:
        signed_in(api, PERSON, PERSON_PASSWORD)
        anna = signed_in(api, ADMIN_ACCOUNT, ADMIN_PASSWORD)
        since = last_entry(api.state)
        ended = anna.request("DELETE", f"/users/{PERSON}/sessions")
        assert ended.status_code == 204, ended.text
        expected = as_account(anna, ADMIN_ACCOUNT, PERSON)
        return Performed(api.state, since, expected)


def group_add(tmp_path: Path) -> Performed:
    """Add a group as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        body = {"id": "gis", "members": [OTHER]}
        added = made.owner.request("POST", "/groups", json=body)
        assert added.status_code == 201, added.text
        return Performed(made.api.state, since, as_owner(made, "gis"))


def group_members(tmp_path: Path) -> Performed:
    """Change the members of ``hydro`` as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        body = {"members": [LISTED, OTHER]}
        changed = made.owner.request("PUT", f"/groups/{GROUP}/members", json=body)
        assert changed.status_code == 200, changed.text
        return Performed(made.api.state, since, as_owner(made, GROUP))


def group_remove(tmp_path: Path) -> Performed:
    """Remove the group ``hydro`` as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        removed = made.owner.request("DELETE", f"/groups/{GROUP}")
        assert removed.status_code == 204, removed.text
        return Performed(made.api.state, since, as_owner(made, GROUP))


def project_access(tmp_path: Path) -> Performed:
    """Share the project privately with Igor as its owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        body = {"visibility": "private", "owner": OTHER}
        shared = made.owner.request(
            "PUT", f"/projects/{made.project}/access", json=body
        )
        assert shared.status_code == 200, shared.text
        key = access_key(made.directory)
        return Performed(made.api.state, since, as_owner(made, key))


def created_by_igor(made: World) -> tuple[str, Path]:
    """Create the project ``wisla`` as Igor; return its key and directory."""
    directory = made.directory.with_name("wisla")
    body = {"producer": "kartograf", "path": str(directory), "store": STORE}
    created = made.person.request("POST", "/projects", json=body)
    assert created.status_code == 201, created.text
    return str(created.json()["project"]), directory


def project_create(tmp_path: Path) -> Performed:
    """Igor creates a project of his own and owns it."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        _, directory = created_by_igor(made)
        details = {"producer": "kartograf", "owner": OTHER}
        expected = as_person(made, access_key(directory), details=details)
        return Performed(made.api.state, since, expected)


def project_data_dir(tmp_path: Path) -> Performed:
    """Igor, the project's owner, moves its data folder inside its directory."""
    with world(tmp_path) as made:
        project, directory = created_by_igor(made)
        folder = directory / "robocze"
        folder.mkdir()
        key = access_key(directory)
        default, source = made.settings.get().own_data_dir(key)
        since = last_entry(made.api.state)
        moved = made.person.request(
            "PUT", f"/projects/{project}/data-dir", json={"path": str(folder)}
        )
        assert moved.status_code == 200, moved.text
        expected = as_person(
            made,
            key,
            before={"path": str(default), "source": source},
            after={"path": os.path.realpath(folder), "source": "setting"},
        )
        return Performed(made.api.state, since, expected)


def project_task_add(tmp_path: Path) -> Performed:
    """Add a task to the project as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        added = made.owner.request(
            "POST", f"/projects/{made.project}/tasks", json=TASK_BODY
        )
        assert added.status_code == 201, added.text
        details = {"producer": "kartograf", "task": TASK}
        key = access_key(made.directory)
        return Performed(made.api.state, since, as_owner(made, key, details=details))


def project_task_remove(tmp_path: Path) -> Performed:
    """Remove a task the owner added before."""
    with world(tmp_path) as made:
        added = made.owner.request(
            "POST", f"/projects/{made.project}/tasks", json=TASK_BODY
        )
        assert added.status_code == 201, added.text
        since = last_entry(made.api.state)
        removed = made.owner.request("DELETE", f"/projects/{made.project}/tasks/{TASK}")
        assert removed.status_code == 200, removed.text
        details = {"producer": "kartograf", "task": TASK}
        key = access_key(made.directory)
        return Performed(made.api.state, since, as_owner(made, key, details=details))


def settings_update(tmp_path: Path) -> Performed:
    """Raise ``network_jobs_per_person`` from 2 to 3 as the owner."""
    with world(tmp_path) as made:
        body = made.owner.request("GET", "/settings").json()
        since = last_entry(made.api.state)
        saved = made.owner.request(
            "PUT", "/settings", json={**body, "network_jobs_per_person": 3}
        )
        assert saved.status_code == 200, saved.text
        expected = as_owner(
            made,
            "settings",
            before={"network_jobs_per_person": 2},
            after={"network_jobs_per_person": 3},
        )
        return Performed(made.api.state, since, expected)


def job_start(tmp_path: Path) -> Performed:
    """Start a scan as Ada."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        job = started_scan(made)
        details = {"kind": "scan", "store": STORE}
        return Performed(
            made.api.state, since, as_admin(made, job["id"], details=details)
        )


def job_cancel(tmp_path: Path) -> Performed:
    """Cancel Ada's waiting scan as Ada."""
    with world(tmp_path) as made:
        job = started_scan(made)
        since = last_entry(made.api.state)
        cancelled = made.admin.request("POST", f"/jobs/{job['id']}/cancel")
        assert cancelled.status_code == 202, cancelled.text
        assert cancelled.json()["state"] == "cancelled"
        details = {"kind": "scan", "store": STORE}
        return Performed(
            made.api.state, since, as_admin(made, job["id"], details=details)
        )


def job_retry(tmp_path: Path) -> Performed:
    """Retry Ada's cancelled scan as Ada."""
    with world(tmp_path) as made:
        job = started_scan(made)
        made.admin.request("POST", f"/jobs/{job['id']}/cancel")
        since = last_entry(made.api.state)
        retried = made.admin.request("POST", f"/jobs/{job['id']}/retry")
        assert retried.status_code == 202, retried.text
        again = retried.json()["id"]
        # A retry is no start of its own.
        actions = [entry.action for entry in log_entries(made.api.state, after=since)]
        assert "job.start" not in actions
        details = {"kind": "scan", "store": STORE, "retry_of": job["id"]}
        return Performed(made.api.state, since, as_admin(made, again, details=details))


def permission_denied(tmp_path: Path) -> Performed:
    """Have Igor refused a change of the settings."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        body = made.person.request("GET", "/settings").json()
        refused = made.person.request("PUT", "/settings", json=body)
        assert_problem(refused, 403, "forbidden", "permission_denied")
        details = {"action": "settings.write", "route": "PUT /settings"}
        expected = as_person(made, "settings", outcome="denied", details=details)
        return Performed(made.api.state, since, expected)


def request_refused(tmp_path: Path) -> Performed:
    """Refuse a cross-origin request before routing, without storing the origin."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        response = made.api.client.get(
            "/api/v1/settings", headers={"Origin": "https://outside.invalid"}
        )
        assert_problem(response, 403, "forbidden", "csrf_rejected")
        expected = Logged(
            actor="-",
            actor_kind="anonymous",
            session=None,
            client=CLIENT,
            target="csrf_rejected",
            outcome="denied",
            details={"reason": "csrf_rejected", "route": "GET /api/*"},
        )
        return Performed(made.api.state, since, expected)


def log_prune(tmp_path: Path) -> Performed:
    """Prune what the scheduler's first tick finds older than the retention."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        kept = len(log_entries(made.api.state))
        scheduler = ScanScheduler(
            made.jobs,
            made.settings,
            made.registry,
            index_path=made.paths.index_file,
            state=made.api.state,
        )
        later = datetime.now(UTC) + timedelta(
            days=DEFAULT_ACTION_LOG_RETENTION_DAYS + 1
        )
        try:
            submitted = scheduler.tick(now=later)
        finally:
            scheduler.stop()
        # The scheduler's own jobs are not logged.
        assert submitted
        actions = [entry.action for entry in log_entries(made.api.state, after=since)]
        assert actions == ["log.prune"]
        pruned = log_entries(made.api.state, after=since)[0]
        assert pruned.details is not None and pruned.details["count"] == kept
        expected = Logged("local", "scheduler", None, None, "log")
        return Performed(made.api.state, since, expected)


def log_export(tmp_path: Path) -> Performed:
    """Export Igor's entries (his sign-in) as CSV as the owner."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        exported = made.owner.request("GET", f"/log/export?format=csv&actor={OTHER}")
        assert exported.status_code == 200, exported.text
        details = {"filters": {"actor": OTHER}, "format": "csv", "count": 1}
        return Performed(made.api.state, since, as_owner(made, "log", details=details))


def file_download(tmp_path: Path) -> Performed:
    """Download a version's file as the owner."""
    with served_store(tmp_path) as served:
        entry = entry_of(served.store, "tif_sheet", "regular")
        version = f"/stores/{STORE}/versions/{entry.path}"
        ref = served.owner.request("GET", version).json()["ref"]
        since = last_entry(served.api.state)
        fetched = served.owner.request("GET", f"{version}/file")
        assert fetched.status_code == 200
        session = label(served.owner)
        expected = Logged("local", "local_owner", session, CLIENT, ref)
        return Performed(served.api.state, since, expected)


# The case of each name of ``ActionName``.
CASES: dict[str, Callable[[Path], Performed]] = {
    "session.login": session_login,
    "session.login_failed": session_login_failed,
    "session.logout": session_logout,
    "session.password": session_password,
    "session.ended": session_ended,
    "session.proxy_header_ignored": session_proxy_header_ignored,
    "token.issue": token_issue,
    "token.revoke_all": token_revoke_all,
    "user.add": user_add,
    "user.update": user_update,
    "user.remove": user_remove,
    "user.password_reset": user_password_reset,
    "user.sessions_ended": user_sessions_ended,
    "group.add": group_add,
    "group.members": group_members,
    "group.remove": group_remove,
    "project.access": project_access,
    "project.create": project_create,
    "project.data_dir": project_data_dir,
    "project.task_add": project_task_add,
    "project.task_remove": project_task_remove,
    "settings.update": settings_update,
    "job.start": job_start,
    "job.cancel": job_cancel,
    "job.retry": job_retry,
    "permission.denied": permission_denied,
    "request.refused": request_refused,
    "log.export": log_export,
    "log.prune": log_prune,
    "file.download": file_download,
}


def test_every_case_belongs_to_a_name_of_the_log() -> None:
    """No case is left over for a name ``ActionName`` no longer has."""
    assert set(CASES) <= set(ACTION_NAMES)


@pytest.mark.parametrize("name", sorted(ACTION_NAMES))
def test_each_action_is_logged_once(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One entry of the action, with its actor, kind, session, client and target."""
    case = CASES.get(name)
    assert case is not None, f"{name} of ActionName has no case"
    # Argon2id at its lowest cost: the cases check the log, not the hashes.
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())

    # Act
    performed = case(tmp_path)

    # Assert
    found = [
        entry
        for entry in log_entries(performed.state, after=performed.since)
        if entry.action == name
    ]
    assert len(found) == 1, found
    assert_logged(found[0], performed.expected)


def assert_logged(entry: ActionEntry, expected: Logged) -> None:
    """Check an entry against what its action should have left."""
    assert (
        entry.actor,
        entry.actor_kind,
        entry.session,
        entry.client,
        entry.target,
        entry.outcome,
    ) == (
        expected.actor,
        expected.actor_kind,
        expected.session,
        expected.client,
        expected.target,
        expected.outcome,
    )
    for name in ("details", "before", "after"):
        wanted = getattr(expected, name)
        if wanted is not None:
            assert getattr(entry, name) == wanted, name


def test_refusals_are_logged_once_per_person_action_and_minute(tmp_path: Path) -> None:
    """Asking again within a minute adds nothing; another action or person does."""
    moment = [datetime(2026, 10, 26, 14, 0, tzinfo=UTC)]
    with world(tmp_path) as made:
        # Arrange
        app = made.api.client.app
        app.state.denials = DenialLog(made.api.state, clock=lambda: moment[0])  # type: ignore[attr-defined]
        lena = made.api.session(principal(made.api.state, "listed"))
        body = made.person.request("GET", "/settings").json()
        since = last_entry(made.api.state)

        # Act
        for _ in range(3):
            made.person.request("PUT", "/settings", json=body)
        made.person.request("POST", "/users", json={"id": "nowy"})
        lena.request("PUT", "/settings", json=body)
        moment[0] += timedelta(seconds=61)
        made.person.request("PUT", "/settings", json=body)

        # Assert
        logged = [
            (entry.actor, entry.target, (entry.details or {})["action"])
            for entry in log_entries(made.api.state, after=since)
        ]
    assert logged == [
        (OTHER, "settings", "settings.write"),
        (OTHER, "users", "users.manage"),
        (LISTED, "settings", "settings.write"),
        (OTHER, "settings", "settings.write"),
    ]


def pages(caller: Caller, query: str) -> list[dict[str, Any]]:
    """Return the entries of every page of ``GET /log?<query>``, two a page."""
    items: list[dict[str, Any]] = []
    cursor = ""
    while True:
        page = caller.request("GET", f"/log?{query}&limit=2{cursor}").json()
        items += page["items"]
        assert page["total"] >= len(items)
        if page["next_cursor"] is None:
            assert page["total"] == len(items)
            return items
        cursor = f"&cursor={page['next_cursor']}"


def csv_rows(data: bytes) -> list[list[str]]:
    """Return the rows of a CSV export: UTF-8 with a BOM, CRLF, a header first."""
    text = data.decode("utf-8")
    assert text.startswith("\ufeff") and text.endswith("\r\n")
    rows = list(csv.reader(io.StringIO(text.removeprefix("\ufeff"), newline="")))
    assert rows[0] == list(FIELDS)
    return rows[1:]


def csv_document(row: list[str]) -> dict[str, Any]:
    """Return an entry as its CSV row tells it, a formula's escape removed."""
    document: dict[str, Any] = {}
    for name, cell in zip(FIELDS, row, strict=True):
        if cell[:1] == "'" and cell[1:2] in ("=", "+", "-", "@", "\t", "\r", "\n"):
            cell = cell[1:]
        if not cell:
            document[name] = None
        elif name in ("id", "before", "after", "details"):
            document[name] = json.loads(cell)
        else:
            document[name] = cell
    return document


def test_pages_and_both_formats_of_the_export_hold_the_same_entries(
    tmp_path: Path,
) -> None:
    """JSON Lines and CSV of a filter list the pages' entries; ``=1+1`` is ``'=1+1``."""
    with world(tmp_path) as made:
        # Arrange: Igor's sign-in (the world's) and refusal, and an entry
        # about a formula.
        body = made.person.request("GET", "/settings").json()
        made.person.request("PUT", "/settings", json=body)
        made.api.state.record(
            principal(made.api.state, "other"),
            "permission.denied",
            "=1+1",
            outcome="denied",
            details={"action": "store.write", "route": "POST /jobs"},
        )

        # Act
        listed = pages(made.owner, f"actor={OTHER}")
        refusals = pages(made.owner, f"actor={OTHER}&action=permission.&outcome=denied")
        lines = made.owner.request("GET", f"/log/export?actor={OTHER}")
        table = made.owner.request("GET", f"/log/export?actor={OTHER}&format=csv")

    # Assert
    assert [item["action"] for item in listed] == [
        "permission.denied",
        "permission.denied",
        "session.login",
    ]
    assert refusals == listed[:2]
    assert lines.headers["content-type"] == "application/jsonl"
    assert [json.loads(line) for line in lines.text.splitlines()] == listed
    assert table.headers["content-type"] == "text/csv; charset=utf-8"
    assert table.headers["cache-control"] == "private, no-store"
    assert re.fullmatch(
        r'attachment; filename="archiwista-log-\d{8}T\d{6}Z\.csv"',
        table.headers["content-disposition"],
    )
    rows = csv_rows(table.content)
    assert [csv_document(row) for row in rows] == listed
    assert rows[0][FIELDS.index("target")] == "'=1+1"
    assert rows[1][FIELDS.index("target")] == "settings"


def test_only_administrators_read_and_export_the_log(tmp_path: Path) -> None:
    """Igor is refused both routes, logged once; Ada, an administrator, reads it."""
    with world(tmp_path) as made:
        ada = made.api.session(principal(made.api.state, "admin"))
        since = last_entry(made.api.state)

        # Act
        refused = made.person.request("GET", "/log")
        refused_export = made.person.request("GET", "/log/export?format=csv")
        read = ada.request("GET", "/log")
        logged = log_entries(made.api.state, after=since)

    # Assert
    assert_problem(refused, 403, "forbidden", "permission_denied")
    assert_problem(refused_export, 403, "forbidden", "permission_denied")
    assert read.status_code == 200, read.text
    assert [(entry.actor, entry.action, entry.target) for entry in logged] == [
        (OTHER, "permission.denied", "log")
    ]
    assert logged[0].details == {"action": "log.read", "route": "GET /log"}


def test_the_command_line_prints_what_the_routes_answer(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``log list --json`` is ``GET /log``; ``log export`` writes the route's bytes."""
    with world(tmp_path) as made:
        # Arrange
        saved = tmp_path / "eksport" / "dziennik.csv"

        def cli(*argv: str) -> str:
            capsys.readouterr()
            status = main(["log", *argv], registry=made.registry, paths=made.paths)
            captured = capsys.readouterr()
            assert status == 0, captured.err
            return captured.out

        # Act
        route_page = made.owner.request("GET", f"/log?actor={OTHER}").json()
        route_csv = made.owner.request(
            "GET", f"/log/export?format=csv&actor={OTHER}"
        ).content
        since = last_entry(made.api.state)
        listed = cli("list", "--json", "--actor", OTHER)
        exported = cli("export", "--format", "csv", "--actor", OTHER)
        cli("export", "--format", "csv", "--actor", OTHER, "--output", str(saved))
        logged = log_entries(made.api.state, after=since)

    # Assert
    assert json.loads(listed) == route_page
    assert exported.encode() == route_csv
    assert saved.read_bytes() == route_csv
    assert [
        (entry.action, entry.actor, entry.actor_kind, entry.session, entry.client)
        for entry in logged
    ] == [("log.export", "local", "local_owner", None, None)] * 2


def test_since_and_until_bound_the_entries_in_any_zone(tmp_path: Path) -> None:
    """``since`` keeps its moment, ``until`` leaves it out; a time needs a zone."""
    # Arrange: refusals around 22:00 UTC, which is midnight in Warsaw.
    paths = local_paths(tmp_path)
    moments = (
        datetime(2026, 10, 1, 21, 59, 59, tzinfo=UTC),
        datetime(2026, 10, 1, 22, 0, 0, tzinfo=UTC),
        datetime(2026, 10, 1, 22, 0, 1, tzinfo=UTC),
    )
    entries = tuple(
        ActionEntry(
            id=number,
            at=moment,
            actor="-",
            actor_kind="anonymous",
            session=None,
            client="10.0.0.9",
            action="permission.denied",
            target="settings",
            outcome="denied",
            before=None,
            after=None,
            details=None,
        )
        for number, moment in enumerate(moments, start=1)
    )
    restored = StateSnapshot(
        users=(), groups=(), projects=(), passwords=(), preferences=(), actions=entries
    )
    StateStore(paths.state_file).restore(restored)
    midnight = quote("2026-10-02T00:00:00+02:00", safe="")
    with running_api(paths) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        # The owner's sign-in, now, is after midnight too: refusals only.
        refusals = f"/log?since={midnight}&action=permission.denied"
        since = owner.request("GET", refusals).json()
        until = owner.request("GET", f"/log?until={midnight}").json()
        local = owner.request("GET", "/log?since=2026-10-02T00:00:00")

    # Assert
    assert [item["id"] for item in since["items"]] == [3, 2]
    assert [item["id"] for item in until["items"]] == [1]
    assert until["items"][0]["at"] == "2026-10-01T21:59:59Z"
    assert_problem(local, 400, "validation_error")
