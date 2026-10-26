"""The action log: every action logged once, with who, how and from where (T8).

Each name of ``ActionName`` has a case in ``CASES`` that performs the action
through the API (or, for the pruning, the server's scheduler) and finds
exactly one entry of it with its actor, the actor's kind, the session's
label, the client address, the target and the outcome. A name without a case
fails ``test_each_action_is_logged_once``; a name whose trigger is only on
``feature/v0.4-team`` is listed in ``AWAITING_TEAM_MERGE`` and reported as an
expected failure until its case is written. The world is a marked Kartograf
store ``zespol`` (empty), a project directory, the four people of
``tests.fixtures.permissions`` and a supervisor that starts no job, so jobs
wait to be cancelled and retried; the download of a file uses a generated
store scanned into the index (``served_store``). Offline.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, get_args

import kartograf
import pytest

from archiwista.api.errors import DenialLog
from archiwista.auth import LOCAL_OWNER, access_key
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
from archiwista.sources.registry import SourceRegistry, load_registry
from archiwista.state import ActionEntry, ActionName, StateStore
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.api_store import served_store
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import (
    GROUP,
    LISTED,
    OTHER,
    add_people,
    last_entry,
    log_entries,
    principal,
)
from tests.fixtures.preview_api import entry_of

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
# Names whose trigger is on feature/v0.4-team only, with that trigger (plan
# v0.4 T2 commit 2, T3, T4, T7). The coordinator writes the case of each in
# CASES when that branch is merged, and removes the name here; until then each
# is an expected failure of every run, never skipped.
AWAITING_TEAM_MERGE: dict[str, str] = {
    "session.login": "POST /session, /session/login (T3), /session/proxy (T4)",
    "session.login_failed": "POST /session/login (T3), POST /session/proxy (T4)",
    "session.logout": "DELETE /session (T3)",
    "session.password": "PUT /session/password (T3)",
    "session.ended": "DELETE /sessions/{label} (T3)",
    "session.proxy_header_ignored": "the proxy's header from an untrusted peer (T4)",
    "token.issue": "POST /session/tokens, archiwista token --user (T3)",
    "token.revoke_all": "archiwista token --revoke-all (T3)",
    "user.password_reset": "POST /users/{user_id}/password, archiwista users password",
    "user.sessions_ended": "DELETE /users/{user_id}/sessions (T3)",
    "project.create": "POST /projects by any person (T7)",
    "project.data_dir": "PUT /projects/{project}/data-dir by the owner (T7)",
}


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


def started_scan(world: World) -> dict[str, Any]:
    """Start a full scan of the store as Igor; it waits (no job starts)."""
    started = world.person.request(
        "POST", f"/stores/{STORE}/scan", json={"mode": "full"}
    )
    assert started.status_code == 202, started.text
    job: dict[str, Any] = started.json()
    return job


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
    """Start a scan as Igor."""
    with world(tmp_path) as made:
        since = last_entry(made.api.state)
        job = started_scan(made)
        details = {"kind": "scan", "store": STORE}
        return Performed(
            made.api.state, since, as_person(made, job["id"], details=details)
        )


def job_cancel(tmp_path: Path) -> Performed:
    """Cancel Igor's waiting scan as Igor."""
    with world(tmp_path) as made:
        job = started_scan(made)
        since = last_entry(made.api.state)
        cancelled = made.person.request("POST", f"/jobs/{job['id']}/cancel")
        assert cancelled.status_code == 202, cancelled.text
        assert cancelled.json()["state"] == "cancelled"
        details = {"kind": "scan", "store": STORE}
        return Performed(
            made.api.state, since, as_person(made, job["id"], details=details)
        )


def job_retry(tmp_path: Path) -> Performed:
    """Retry Igor's cancelled scan as Igor."""
    with world(tmp_path) as made:
        job = started_scan(made)
        made.person.request("POST", f"/jobs/{job['id']}/cancel")
        since = last_entry(made.api.state)
        retried = made.person.request("POST", f"/jobs/{job['id']}/retry")
        assert retried.status_code == 202, retried.text
        again = retried.json()["id"]
        # A retry is no start of its own.
        actions = [entry.action for entry in log_entries(made.api.state, after=since)]
        assert "job.start" not in actions
        details = {"kind": "scan", "store": STORE, "retry_of": job["id"]}
        return Performed(made.api.state, since, as_person(made, again, details=details))


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


# The case of each name of ``ActionName`` that has its trigger here.
CASES: dict[str, Callable[[Path], Performed]] = {
    "user.add": user_add,
    "user.update": user_update,
    "user.remove": user_remove,
    "group.add": group_add,
    "group.members": group_members,
    "group.remove": group_remove,
    "project.access": project_access,
    "project.task_add": project_task_add,
    "project.task_remove": project_task_remove,
    "settings.update": settings_update,
    "job.start": job_start,
    "job.cancel": job_cancel,
    "job.retry": job_retry,
    "permission.denied": permission_denied,
    "log.prune": log_prune,
    "file.download": file_download,
}


def test_every_case_belongs_to_one_name_of_the_log() -> None:
    """A case or an awaited name is a name of ``ActionName`` or of the team branch."""
    assert not set(CASES) & set(AWAITING_TEAM_MERGE)
    assert set(CASES) <= set(ACTION_NAMES)


@pytest.mark.parametrize("name", sorted({*ACTION_NAMES, *AWAITING_TEAM_MERGE}))
def test_each_action_is_logged_once(name: str, tmp_path: Path) -> None:
    """One entry of the action, with its actor, kind, session, client and target."""
    case = CASES.get(name)
    if case is None:
        assert name in AWAITING_TEAM_MERGE, f"{name} of ActionName has no case"
        trigger = AWAITING_TEAM_MERGE[name]
        pytest.xfail(f"{name}: write its case ({trigger}) at the merge of v0.4-team")

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
