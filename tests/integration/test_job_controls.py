"""Job controls: cancel, retry and the log (plan of 2026-10-25, A6; ADR-038).

``POST /jobs/{job}/cancel``, ``POST /jobs/{job}/retry``, ``GET
/jobs/{job}/log`` and ``archiwista jobs list|show|cancel|retry|log`` over a
generated Kartograf store with a supervisor of test workers
(``tests.fixtures.job_worker``: slowed scans, crashes) that runs one job at a
time, over the stand-in producer's downloads (``tests.fixtures.actions``) and
over the own data of projects (``tests.fixtures.own_data_api``), offline.
"""

import json
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pytest

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.jobs import FINISHED_STATES, JobRecord, JobSupervisor
from archiwista.jobs.protocol import STOP_TIMEOUT_S
from archiwista.messages import message
from archiwista.refs import version_ref
from archiwista.services import jobs as job_controls
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.actions import (
    STATION,
    action_paths,
    action_supervisor,
    standin_in_settings,
)
from tests.fixtures.actions import STORE as STANDIN_STORE
from tests.fixtures.api_session import Api, Caller, assert_problem, running_api
from tests.fixtures.api_store import STORE as GENERATED_STORE
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.jobs import (
    CRASH_ENV,
    DELAY_ENV,
    SLOW_ENTRY_S,
    STORE,
    TEST_WORKER,
    store_settings,
    worker_path,
)
from tests.fixtures.jobs_api import JobsApi, jobs_api
from tests.fixtures.local_server import NoSources
from tests.fixtures.make_store import make_store
from tests.fixtures.own_data_api import own_data_api
from tests.fixtures.permissions import OTHER, WHO, WRITER, add_people, principal, share
from tests.fixtures.preview_api import entry_of

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WAIT_S = 60.0
FULL = {"mode": "full", "segment": None}
DOWNLOAD: dict[str, Any] = {
    "kind": "download",
    "producer": "standin",
    "store": STANDIN_STORE,
    "calls": [{"command": "series fetch", "options": STATION}],
}

type Unsuccessful = Literal["cancelled", "failed", "interrupted"]


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[JobsApi]:
    """Serve a fresh store with a supervisor of test workers running one job."""
    with jobs_api(tmp_path, monkeypatch, max_jobs=1) as created:
        yield created


def _await(condition: Callable[[], bool], timeout: float = WAIT_S) -> None:
    """Wait until ``condition`` holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "the condition never held"
        time.sleep(0.05)


def _progressed(served: JobsApi, job: str) -> None:
    """Wait for the first progress of a job: its worker runs."""
    served.env.follow(job, lambda event: event.type == "progress")


def _slow_scan(served: JobsApi, monkeypatch: pytest.MonkeyPatch) -> str:
    """Start a slowed full scan over HTTP and wait until its worker runs."""
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    started = served.owner.request("POST", f"/stores/{STORE}/scan", json=FULL)
    assert started.status_code == 202, started.text
    job = str(started.json()["id"])
    _progressed(served, job)
    return job


def _states(served: JobsApi, job: str) -> list[object]:
    """Return the states a job went through, from its events."""
    events = served.env.jobs.events(job)
    return [event.data["state"] for event in events if event.type == "state"]


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista jobs … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        ["jobs", *argv, "--json"],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def test_cancel_ends_a_waiting_job_at_once_without_a_worker(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job that waits for a worker is cancelled at once: it never ran, no log."""
    # Arrange: a slowed scan takes the only worker, a link check waits.
    served.env.scan("full")
    running = _slow_scan(served, monkeypatch)
    link = served.env.store.by_kind("link")[0].path
    waiting = served.owner.request(
        "POST", f"/stores/{STORE}/link-check", json={"slot": link}
    ).json()

    # Act
    answered = served.owner.request("POST", f"/jobs/{waiting['id']}/cancel")
    log = served.owner.request("GET", f"/jobs/{waiting['id']}/log")
    still = served.env.jobs.get(running)
    served.env.jobs.cancel(running)
    served.env.wait(running)

    # Assert
    assert waiting["state"] == "queued"
    assert answered.status_code == 202, answered.text
    assert answered.headers["location"] == f"/api/v1/jobs/{waiting['id']}"
    detail = answered.json()
    assert (detail["state"], detail["started_at"]) == ("cancelled", None)
    assert detail["error"]["code"] == "cancelled"
    assert _states(served, waiting["id"]) == ["queued", "cancelled"]
    assert not (served.env.paths.jobs_dir / f"{waiting['id']}.log").exists()
    assert_problem(log, 404, "not_found")
    assert log.json()["detail"] == message("job.no_log", "en", job=waiting["id"])
    assert still is not None and still.state == "running"


def test_cancel_stops_a_running_job_within_the_stop_timeout(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running job ends ``cancelled`` once its worker stopped; then it is ended."""
    # Arrange
    job = _slow_scan(served, monkeypatch)

    # Act
    asked = time.monotonic()
    answered = served.owner.request("POST", f"/jobs/{job}/cancel")
    record = served.env.wait(job)
    took = time.monotonic() - asked
    again = served.owner.request("POST", f"/jobs/{job}/cancel")

    # Assert
    assert answered.status_code == 202, answered.text
    assert answered.json()["id"] == job
    assert answered.json()["state"] in ("running", "cancelled")
    assert record.state == "cancelled" and took < STOP_TIMEOUT_S
    assert record.error is not None
    assert (record.error.code, record.error.detail) == (
        "cancelled",
        message("job.cancelled"),
    )
    assert _states(served, job) == ["queued", "running", "cancelled"]
    assert_problem(again, 409, "conflict", "job_finished")
    assert again.json()["details"]["job"] == {
        "id": job,
        "kind": "scan",
        "state": "cancelled",
    }
    assert list(served.env.paths.jobs_dir.glob("*.cancel")) == []


def _unsuccessful(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch, state: Unsuccessful
) -> JobRecord:
    """Return a full scan of the store that ended in ``state``."""
    if state == "failed":  # the worker dies after three entries
        monkeypatch.setenv(CRASH_ENV, "3")
        job = served.env.jobs.submit(
            "scan", store=STORE, params={"mode": "full"}, actor=LOCAL_OWNER
        ).id
    elif state == "cancelled":
        job = _slow_scan(served, monkeypatch)
        served.env.jobs.cancel(job)
    else:  # the supervisor running it stops meanwhile, as a server would
        monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
        with JobSupervisor(
            served.env.paths, served.env.settings, worker_command=TEST_WORKER
        ) as other:
            job = other.submit(
                "scan", store=STORE, params={"mode": "full"}, actor=LOCAL_OWNER
            ).id
            _progressed(served, job)
    record = served.env.wait(job)
    monkeypatch.delenv(DELAY_ENV, raising=False)
    monkeypatch.delenv(CRASH_ENV, raising=False)
    assert record.state == state, record
    return record


@pytest.mark.parametrize("state", ["cancelled", "failed", "interrupted"])
def test_retry_starts_a_job_that_did_not_succeed_again(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch, state: Unsuccessful
) -> None:
    """A new job of the session with the same kind, store and parameters runs."""
    # Arrange
    ended = _unsuccessful(served, monkeypatch, state)

    # Act
    answered = served.owner.request("POST", f"/jobs/{ended.id}/retry")
    retried = served.env.wait(answered.json()["id"])
    again = served.owner.request("POST", f"/jobs/{retried.id}/retry")
    kept = served.env.jobs.get(ended.id)

    # Assert
    assert answered.status_code == 202, answered.text
    detail = answered.json()
    assert answered.headers["location"] == f"/api/v1/jobs/{detail['id']}"
    assert detail["id"] != ended.id
    assert (detail["kind"], detail["store"], detail["params"]) == (
        "scan",
        STORE,
        FULL,
    )
    assert (detail["actor"], detail["actor_kind"]) == ("local", "local_owner")
    assert retried.state == "succeeded" and retried.params == ended.params
    assert kept == ended
    assert_problem(again, 409, "conflict", "job_succeeded")
    assert again.json()["details"]["job"] == {
        "id": retried.id,
        "kind": "scan",
        "state": "succeeded",
    }


def test_retry_of_a_job_that_has_not_ended_conflicts(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running job is not retried: `409 job_active`, and no job is recorded."""
    # Arrange
    job = _slow_scan(served, monkeypatch)

    # Act
    answered = served.owner.request("POST", f"/jobs/{job}/retry")
    listed = [record.id for record in served.env.jobs.list().items]
    served.env.jobs.cancel(job)
    served.env.wait(job)

    # Assert
    assert_problem(answered, 409, "conflict", "job_active")
    assert answered.json()["details"]["job"] == {
        "id": job,
        "kind": "scan",
        "state": "running",
    }
    assert listed == [job]


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return module


@contextmanager
def _standin_api(paths: AppPaths) -> Iterator[tuple[Api, JobSupervisor]]:
    """Serve the API with a supervisor that runs no network job: downloads wait."""
    with action_supervisor(paths, max_network_jobs=0) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            yield api, jobs


@pytest.mark.usefixtures("standin")
def test_cancel_and_retry_of_a_download_ask_who_may(tmp_path: Path) -> None:
    """Cancel: who started it or an admin; retry writes the store: ``store.write``."""
    # Arrange: the owner's download waits (no network job runs).
    paths = action_paths(tmp_path)
    with _standin_api(paths) as (api, jobs):
        add_people(api.state)
        owner = api.session(LOCAL_OWNER)
        person = api.session(principal(api.state, "other"))
        started = owner.request("POST", "/jobs", json=DOWNLOAD).json()

        # Act
        stranger = person.request("POST", f"/jobs/{started['id']}/cancel")
        cancelled = owner.request("POST", f"/jobs/{started['id']}/cancel")
        refused = person.request("POST", f"/jobs/{started['id']}/retry")
        api.state.update_user(OTHER, roles=WRITER, actor=LOCAL_OWNER)
        retried = person.request("POST", f"/jobs/{started['id']}/retry")
        listed = [(job.id, job.state) for job in jobs.list().items]
        own = person.request("POST", f"/jobs/{retried.json()['id']}/cancel")

    # Assert
    assert_problem(stranger, 403, "forbidden", "permission_denied")
    assert stranger.json()["detail"] == message("permission.job_cancel", "en")
    assert cancelled.status_code == 202, cancelled.text
    assert cancelled.json()["state"] == "cancelled"
    assert_problem(refused, 403, "forbidden", "permission_denied")
    assert refused.json()["detail"] == message("permission.store_write", "en")
    assert retried.status_code == 202, retried.text
    new = retried.json()
    assert (new["kind"], new["store"], new["state"]) == (
        "download",
        STANDIN_STORE,
        "queued",
    )
    assert new["params"] == started["params"]
    assert new["actor"] == OTHER
    assert listed == [(new["id"], "queued"), (started["id"], "cancelled")]
    assert own.status_code == 202, own.text
    assert own.json()["state"] == "cancelled"


def test_controls_of_a_project_job_follow_its_visibility(tmp_path: Path) -> None:
    """Hidden: `404` for all three; seen in part: no log; cancel: actor or admin.

    The scan of a private project's data folder is the project's job only;
    a ``preview`` job of a store version and a file of the project is seen
    by everyone, but its log only by whoever sees the project too.
    """
    with own_data_api(tmp_path, first=("gpkg_layers",), second=()) as served:
        # Arrange
        project = served.first
        owner = served.owner
        scanned = owner.request("POST", f"/projects/{project.key}/scan").json()["id"]
        sheet = entry_of(served.previews.store, "asc_sheet", "regular")
        content = owner.request("GET", project.url("kanalizacja.gpkg")).json()
        mixed = served.jobs.submit(
            "preview",
            params={
                "refs": [
                    version_ref(GENERATED_STORE, sheet.path),
                    project.ref("kanalizacja.gpkg"),
                ],
                "contents": [sheet.sha256, content["content"]["sha256"]],
                "force": False,
            },
            actor=LOCAL_OWNER,
        ).id
        for job in (scanned, mixed):
            served.wait(job)
        share(served.api.state, project.access_key, "private")
        callers: dict[str, Caller] = {who: served.caller(who) for who in WHO}
        callers["local"] = owner

        # Act
        observed = {
            who: {
                "cancel": caller.request("POST", f"/jobs/{scanned}/cancel"),
                "retry": caller.request("POST", f"/jobs/{scanned}/retry"),
                "log": caller.request("GET", f"/jobs/{scanned}/log"),
                "mixed log": caller.request("GET", f"/jobs/{mixed}/log"),
            }
            for who, caller in callers.items()
        }

    # Assert
    answers = {
        who: {
            name: (
                response.status_code,
                response.json().get("details", {}).get("reason"),
            )
            for name, response in responses.items()
        }
        for who, responses in observed.items()
    }
    hidden = {
        "cancel": (404, None),
        "retry": (404, None),
        "log": (404, None),
        "mixed log": (403, "permission_denied"),
    }
    sees = {
        "cancel": (403, "permission_denied"),
        "retry": (409, "job_succeeded"),
        "log": (200, None),
        "mixed log": (200, None),
    }
    administers = {**sees, "cancel": (409, "job_finished")}
    assert answers == {
        "owner": sees,
        "listed": hidden,
        "other": hidden,
        "admin": administers,
        "local": administers,
    }
    log = observed["local"]["log"].json()
    assert log["job"] == scanned and log["truncated"] is False
    assert log["size_bytes"] == len(log["text"].encode("utf-8"))
    hidden_job = observed["other"]["cancel"].json()["detail"]
    assert hidden_job == message("job.not_found", "en", job=scanned)


def test_cancel_reaches_a_job_another_process_supervises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server's running job, cancelled from another process, ends ``cancelled``."""
    # Arrange: another process supervises a slowed full scan.
    worker_path(monkeypatch)
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    store = make_store(tmp_path / "store", slots=24, seed=7)
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    ConfigStore(paths.config_file).save(store_settings(store))
    command = [sys.executable, "-m", "tests.fixtures.job_owner"]
    with subprocess.Popen(
        [*command, str(paths.config_file), str(paths.data_dir), STORE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as owner:
        assert owner.stdout is not None and owner.stdin is not None
        job = owner.stdout.readline().strip()
        settings = SettingsService(ConfigStore(paths.config_file), NoSources())
        decisions = Authorizer(StateStore(paths.state_file), settings.get)
        with JobSupervisor(paths, settings) as jobs:
            _await(lambda: (jobs.get(job) or _never()).progress is not None)

            # Act
            asked = time.monotonic()
            answered = job_controls.cancel(
                jobs, decisions, job_id=job, actor=LOCAL_OWNER, visible=ALL_PROJECTS
            )
            _await(lambda: (jobs.get(job) or _never()).state in FINISHED_STATES)
            took = time.monotonic() - asked
            record = jobs.get(job)
        owner.stdin.close()
        owner.wait(timeout=WAIT_S)

    # Assert
    assert answered.state == "running"
    assert record is not None and record.state == "cancelled"
    assert record.error is not None and record.error.detail == message("job.cancelled")
    assert took < STOP_TIMEOUT_S
    assert list(paths.jobs_dir.glob("*.cancel")) == []


def _never() -> JobRecord:
    raise AssertionError("the job is gone")


def test_commands_print_the_models_of_the_routes(
    served: JobsApi, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``jobs list|show|log`` agree with the routes; ``cancel`` reaches the server.

    The command cancels the server's running scan through the server's own
    supervisor, retries it in the foreground and refuses what the route
    refuses, with the same error.
    """
    # Arrange
    paths = served.env.paths
    scanned = served.env.scan("full").id
    running = _slow_scan(served, monkeypatch)

    # Act
    cancelled = _cli(capsys, paths, "cancel", running)
    ended = served.env.wait(running)
    monkeypatch.delenv(DELAY_ENV)
    retried = _cli(capsys, paths, "retry", running)
    refused = _cli(capsys, paths, "retry", retried["id"])
    route_refused = served.owner.request("POST", f"/jobs/{retried['id']}/retry")
    listed = _cli(capsys, paths, "list")
    route_listed = served.owner.request("GET", "/jobs").json()
    shown = {job: _cli(capsys, paths, "show", job) for job in (scanned, running)}
    route_shown = {
        job: served.owner.request("GET", f"/jobs/{job}").json()
        for job in (scanned, running)
    }
    log = _cli(capsys, paths, "log", scanned)
    route_log = served.owner.request("GET", f"/jobs/{scanned}/log").json()
    route_retried = served.owner.request("GET", f"/jobs/{retried['id']}").json()

    # Assert
    assert (cancelled["id"], cancelled["state"]) == (running, "running")
    assert ended.state == "cancelled"
    assert retried == route_retried
    assert (retried["state"], retried["params"]) == ("succeeded", FULL)
    assert retried["actor"] == "local" and retried["session"] is None
    assert_same_error(refused, route_refused.json())
    assert refused["details"]["reason"] == "job_succeeded"
    assert listed == route_listed
    assert [item["id"] for item in listed["items"]] == [
        retried["id"],
        running,
        scanned,
    ]
    assert shown == route_shown
    assert log == route_log and log["text"]
