"""The jobs of a project over HTTP and by commands (plan of 2026-10-25, A8).

``POST /projects/{project}/jobs`` and ``archiwista project-download``,
``project-repin``, ``project-check`` and ``project-verify`` with the real
Kartograf adapter over Kartograf's fixture store and project
(``kartograf.testing``: two tasks, each pinning one version). Who may start
which job (SPEC 13 v0.3 criterion 7), the refusals before a job exists, the
retry that asks the same again, and the commands printing what the route's
job ends as. A verification and a download of pins the store holds run in
real worker processes whose sockets refuse every connection; the jobs
themselves are ``tests/integration/test_project_jobs.py``.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import kartograf
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, build_project

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.index import IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.index.types import ManifestStamp
from archiwista.jobs import JobSupervisor
from archiwista.sources import ProjectInfo
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.job_worker import NO_NETWORK_ENV
from tests.fixtures.jobs import TEST_WORKER, worker_path
from tests.fixtures.permissions import (
    LISTED,
    OWNER,
    WHO,
    WRITER,
    Who,
    add_people,
    principal,
    share,
)

STORE = "zespol"
PL_TASK = "nmt-pl"
CZ_TASK = "nmt-cz"
JOB_TIMEOUT_S = 90.0
# The body of each kind of job.
BODIES: dict[str, dict[str, Any]] = {
    "download": {"kind": "download"},
    "repin": {"kind": "repin", "tasks": [PL_TASK]},
    "check": {"kind": "check"},
    "verify": {"kind": "verify", "tasks": [PL_TASK, CZ_TASK]},
}
# What each person gets of a project shared with the listed person, everyone
# allowed to write the stores: who sees it asks its status, checks and
# verifies it, only who may change it writes it, and who does not see it
# finds no such project.
_SEES = {"status": 200, "check": 202, "verify": 202}
MATRIX: dict[Who, dict[str, int]] = {
    "owner": {**_SEES, "download": 202, "repin": 202},
    "listed": {**_SEES, "download": 403, "repin": 403},
    "other": dict.fromkeys(("status", *BODIES), 404),
    "admin": {**_SEES, "download": 202, "repin": 202},
}


@dataclass(frozen=True)
class Place:
    """An installation with the fixture project recorded in its index."""

    paths: AppPaths
    built: FixtureStore
    projects: Path
    directory: Path
    key: str
    attempts: Path

    def corrupt(self, task: int) -> None:
        """Change the bytes of the version a task pinned."""
        pin = kartograf.open_project(self.directory).tasks[task].files[0]
        version = self.built.root / pin.version
        version.chmod(0o644)
        version.write_bytes(b"0" * 10)


@pytest.fixture
def place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Place:
    """Give the fixture project in a configured store; workers refuse the network."""
    worker_path(monkeypatch)
    attempts = tmp_path / "network.log"
    monkeypatch.setenv(NO_NETWORK_ENV, str(attempts))
    built = build_fixture_store(tmp_path / "nas" / "kartograf")
    projects = tmp_path / "nas" / "projekty"
    directory = build_project(projects / "raba", built)
    config = StoreConfig(id=STORE, name="Zespół", kartograf=built.root, kind="local")
    settings = AppSettings(stores=(config,), project_dirs=(projects,))
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        key = _record(paths, writer, directory, settings)
    return Place(paths, built, projects, directory, key, attempts)


def _record(
    paths: AppPaths, writer: IndexWriter, directory: Path, settings: AppSettings
) -> str:
    """Record a project in the index as a scan reads it; return its key."""
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    return record_project(adapter, writer, directory, stores=settings.stores)


def _change_settings(paths: AppPaths, **changed: Any) -> None:
    """Save the installation's settings with some values changed."""
    config = ConfigStore(paths.config_file)
    config.save(config.load().model_copy(update=changed))


@contextmanager
def _api(paths: AppPaths, **supervisor: Any) -> Iterator[tuple[Api, JobSupervisor]]:
    """Serve the API with a supervisor of test workers and the people of the tests."""
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    with (
        JobSupervisor(
            paths, settings, worker_command=TEST_WORKER, **supervisor
        ) as jobs,
        running_api(paths, registry, jobs=jobs) as api,
    ):
        add_people(api.state)
        yield api, jobs


def _cli(
    capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str
) -> tuple[int, Any]:
    """Run ``archiwista … --json``: its status and model, or its error document."""
    capsys.readouterr()
    registry = load_registry(cache_dir=paths.cache_dir)
    status = main([*argv, "--json"], registry=registry, paths=paths)
    captured = capsys.readouterr()
    if status in (0, 10, 11, 130):
        return status, json.loads(captured.out)
    return status, refusal(captured.out, captured.err, status)


def _start(
    caller: Caller, place: Place, kind: str, jobs: JobSupervisor
) -> httpx.Response:
    """Ask for a job of the project; cancel a started one, so the next may start."""
    answer = caller.request("POST", f"/projects/{place.key}/jobs", json=BODIES[kind])
    if answer.status_code == 202:
        jobs.cancel(answer.json()["id"])
    return answer


@pytest.mark.parametrize("token", ["startup", "agent"])
@pytest.mark.parametrize("who", WHO)
def test_who_sees_a_project_checks_it_and_who_may_change_it_downloads_it(
    place: Place, who: Who, token: Literal["startup", "agent"]
) -> None:
    """The permission matrix of the status and the four jobs.

    A download and a repin need the project's owner or an administrator: a
    person it is shared with sees it, asks its status, checks and verifies it,
    and gets `403 permission_denied` and no job for the rest. A person it is
    not shared with gets `404` for all, as for an unknown project. An agent
    acts with the person who minted its token.
    """
    # Arrange: no job runs, so each one asked is recorded and then cancelled.
    _change_settings(place.paths, store_write_for_all=True)
    with _api(place.paths, max_jobs=0) as (api, jobs):
        share(api.state, access_key(place.directory), "users")
        person = api.session(principal(api.state, who), token=token)

        # Act
        answers = {"status": person.request("GET", f"/projects/{place.key}/status")}
        answers |= {kind: _start(person, place, kind, jobs) for kind in BODIES}
        recorded = sorted(job.kind for job in jobs.list().items)

    # Assert
    statuses = {action: answer.status_code for action, answer in answers.items()}
    assert statuses == MATRIX[who]
    for answer in answers.values():
        if answer.status_code == 403:
            assert_problem(answer, 403, "forbidden", "permission_denied")
        if answer.status_code == 404:
            assert_problem(answer, 404, "not_found")
    started = [kind for kind in BODIES if MATRIX[who][kind] == 202]
    assert recorded == sorted(f"project_{kind}" for kind in started)
    assert not place.attempts.exists()


@pytest.mark.parametrize("token", ["startup", "agent"])
def test_a_download_and_a_repin_need_the_permission_to_write_the_stores(
    place: Place, token: Literal["startup", "agent"]
) -> None:
    """Without `store_writer` the owner gets `403` and no job; a check still starts.

    With the role, read at each request, the same requests start their jobs.
    """
    with _api(place.paths, max_jobs=0) as (api, jobs):
        share(api.state, access_key(place.directory), "private")
        owner = api.session(principal(api.state, "owner"), token=token)

        # Act
        refused = {kind: _start(owner, place, kind, jobs) for kind in BODIES}
        before = sorted(job.kind for job in jobs.list().items)
        api.state.update_user(OWNER, roles=WRITER, actor=LOCAL_OWNER)
        allowed = {kind: _start(owner, place, kind, jobs) for kind in BODIES}

    # Assert
    for kind in ("download", "repin"):
        assert_problem(refused[kind], 403, "forbidden", "permission_denied")
    assert before == ["project_check", "project_verify"]
    statuses = {kind: answer.status_code for kind, answer in allowed.items()}
    assert statuses == dict.fromkeys(BODIES, 202)


def test_a_started_job_names_its_project_and_tasks_and_is_followed_at_its_address(
    place: Place,
) -> None:
    """`202` with `Location`: the job has no store, its project and tasks as asked.

    The verification runs in a worker without the network and ends with the
    state of each pin.
    """
    with _api(place.paths) as (api, jobs):
        owner = api.session(LOCAL_OWNER)

        # Act
        started = owner.request(
            "POST", f"/projects/{place.key}/jobs", json=BODIES["verify"]
        )
        jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
        address = started.headers["location"].removeprefix("/api/v1")
        ended = owner.request("GET", address).json()

    # Assert
    assert started.status_code == 202, started.text
    body = started.json()
    assert started.headers["location"] == f"/api/v1/jobs/{body['id']}"
    assert (body["kind"], body["store"]) == ("project_verify", None)
    assert body["params"] == {"project": place.key, "tasks": [PL_TASK, CZ_TASK]}
    assert ended["state"] == "succeeded", ended
    assert [item["status"] for item in ended["result"]["files"]] == ["ok", "ok"]
    assert not place.attempts.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "repin"},
        {"kind": "repin", "tasks": [PL_TASK, CZ_TASK]},
        {"kind": "download", "tasks": []},
        {"kind": "check", "tasks": [""]},
        {"kind": "move"},
        {"kind": "verify", "store": STORE},
    ],
)
def test_a_request_the_model_refuses_starts_no_job(
    place: Place, body: dict[str, Any]
) -> None:
    """A repin names exactly one task; tasks are names; nothing else is taken."""
    with _api(place.paths, max_jobs=0) as (api, jobs):
        owner = api.session(LOCAL_OWNER)

        # Act
        answer = owner.request("POST", f"/projects/{place.key}/jobs", json=body)
        recorded = jobs.list().items

    # Assert
    assert_problem(answer, 400, "validation_error", "invalid_request")
    assert recorded == ()


def _refusal_setup(case: str, place: Place, monkeypatch: pytest.MonkeyPatch) -> str:
    """Prepare the installation of a refused case; return the project asked for."""
    if case == "unknown_project":
        return "nieznany"
    if case == "offline":
        _change_settings(place.paths, offline=True)
        return place.key
    if case == "unknown_store":
        elsewhere = build_fixture_store(place.projects.parent / "inny" / "kartograf")
        directory = build_project(place.projects / "obcy", elsewhere)
        settings = ConfigStore(place.paths.config_file).load()
        with IndexWriter(place.paths.index_file) as writer:
            return _record(place.paths, writer, directory, settings)
    assert case == "no_project_actions"
    register_standin(monkeypatch)
    info = ProjectInfo(
        producer="standin", store="", path=place.projects / "pomiary", name="pomiary"
    )
    with IndexWriter(place.paths.index_file) as writer:
        return writer.write_project(info, store=None, stamp=ManifestStamp(None, None))


@pytest.mark.parametrize(
    ("case", "kind", "status", "code", "reason"),
    [
        ("unknown_project", "verify", 404, "not_found", None),
        ("offline", "check", 409, "conflict", "offline_mode"),
        ("unknown_store", "download", 409, "conflict", "unknown_store"),
        ("no_project_actions", "verify", 422, "unsupported", "no_project_actions"),
    ],
)
def test_a_refusal_is_the_same_by_the_api_and_the_command(
    place: Place,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    kind: str,
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """The command's error document says what the route's problem says; no job."""
    project = _refusal_setup(case, place, monkeypatch)
    with _api(place.paths, max_jobs=0) as (api, jobs):
        owner = api.session(LOCAL_OWNER)

        # Act
        refused = owner.request(
            "POST", f"/projects/{project}/jobs", json={"kind": kind}
        )
        _, printed = _cli(capsys, place.paths, f"project-{kind}", project)
        recorded = jobs.list().items

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    assert recorded == ()


def test_a_second_job_of_a_project_is_refused_also_at_the_terminal(
    place: Place, capsys: pytest.CaptureFixture[str]
) -> None:
    """`409 conflict` naming the waiting job, by the route and by the command."""
    with _api(place.paths, max_jobs=0) as (api, _):
        owner = api.session(LOCAL_OWNER)
        first = owner.request(
            "POST", f"/projects/{place.key}/jobs", json=BODIES["download"]
        ).json()

        # Act
        refused = owner.request(
            "POST", f"/projects/{place.key}/jobs", json=BODIES["verify"]
        )
        status, printed = _cli(capsys, place.paths, "project-verify", place.key)

    # Assert
    assert_problem(refused, 409, "conflict")
    assert refused.json()["details"]["job"] == {
        "id": first["id"],
        "kind": "project_download",
        "state": "queued",
    }
    assert status == 4
    assert_same_error(printed, refused.json())


def test_a_retry_of_a_project_job_asks_what_its_kind_needs_again(
    place: Place,
) -> None:
    """A download again: the project's owner or an administrator, with `store.write`.

    The listed person sees the cancelled download but may not change the
    project (`403`); the owner without `store_writer` may not write the store
    (`403`); a person it is not shared with does not see the job (`404`). A
    verification needs only to see the project: the listed person retries it.
    """
    with _api(place.paths, max_jobs=0) as (api, jobs):
        share(api.state, access_key(place.directory), "users")
        api.state.update_user(OWNER, roles=WRITER, actor=LOCAL_OWNER)
        api.state.update_user(LISTED, roles=WRITER, actor=LOCAL_OWNER)
        callers = {who: api.session(principal(api.state, who)) for who in WHO}
        download = _start(callers["owner"], place, "download", jobs).json()["id"]
        verify = _start(callers["listed"], place, "verify", jobs).json()["id"]

        def retry(who: Who, job: str) -> httpx.Response:
            answer = callers[who].request("POST", f"/jobs/{job}/retry")
            if answer.status_code == 202:
                jobs.cancel(answer.json()["id"])
            return answer

        # Act
        by_listed = retry("listed", download)
        by_other = retry("other", download)
        api.state.update_user(OWNER, roles=(), actor=LOCAL_OWNER)
        without_role = retry("owner", download)
        api.state.update_user(OWNER, roles=WRITER, actor=LOCAL_OWNER)
        by_owner = retry("owner", download)
        verified = retry("listed", verify)

    # Assert
    assert_problem(by_listed, 403, "forbidden", "permission_denied")
    assert_problem(by_other, 404, "not_found")
    assert_problem(without_role, 403, "forbidden", "permission_denied")
    assert by_owner.status_code == 202, by_owner.text
    assert (by_owner.json()["kind"], by_owner.json()["actor"]) == (
        "project_download",
        OWNER,
    )
    assert verified.status_code == 202, verified.text
    assert verified.json()["params"] == {
        "project": place.key,
        "tasks": [PL_TASK, CZ_TASK],
    }


def test_the_commands_print_the_job_as_the_route_shows_it_and_exit_with_its_outcome(
    place: Place,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--json` is `GET /jobs/{job}` of the job as it ended; exit 0, 10 and 11.

    A verification and a download of pins the store holds need no network; a
    corrupt pin fails its task (`partial`), two fail the download (`failed`).
    """
    # Arrange: the command's own supervisor starts workers without network.
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", TEST_WORKER)

    # Act
    outcomes = [
        _cli(capsys, place.paths, "project-verify", place.key, PL_TASK),
        _cli(capsys, place.paths, "project-download", place.key),
    ]
    for task in (0, 1):
        place.corrupt(task)
        outcomes.append(_cli(capsys, place.paths, "project-download", place.key))
    with _api(place.paths) as (api, _):
        owner = api.session(LOCAL_OWNER)
        details = [
            owner.request("GET", f"/jobs/{job['id']}").json() for _, job in outcomes
        ]

    # Assert
    assert [status for status, _ in outcomes] == [0, 0, 10, 11]
    assert [printed for _, printed in outcomes] == details
    assert [detail["kind"] for detail in details] == [
        "project_verify",
        "project_download",
        "project_download",
        "project_download",
    ]
    assert details[0]["params"] == {"project": place.key, "tasks": [PL_TASK]}
    assert details[1]["result"]["counts"]["unchanged"] == 2
    assert details[2]["result"]["counts"]["failed"] == 1
    assert details[3]["error"]["details"] == {"reason": "run_failed", "task": PL_TASK}
    assert not place.attempts.exists()


def test_openapi_documents_starting_a_job_of_a_project(place: Place) -> None:
    """`202` with the job; the closed request model; refusals are problems."""
    with _api(place.paths, max_jobs=0) as (api, _):
        document = api.session(LOCAL_OWNER).request("GET", "/openapi.json").json()

    operation = document["paths"]["/api/v1/projects/{project}/jobs"]["post"]
    responses = operation["responses"]
    assert operation["operationId"] == "start_project_job"
    assert responses["202"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/JobDetail"
    }
    problems = {status for status in responses if int(status) >= 400}
    assert problems == {"400", "401", "403", "404", "409", "422", "503"}
    for status in problems:
        assert list(responses[status]["content"]) == ["application/problem+json"]
    body = operation["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/ProjectJobRequest"}
    model = document["components"]["schemas"]["ProjectJobRequest"]
    assert model["additionalProperties"] is False
    assert model["examples"]
