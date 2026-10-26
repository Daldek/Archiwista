"""``POST /jobs`` and ``archiwista jobs start`` of a download (plan 2026-10-25, A5).

The routes and the command run over the stand-in producer
(``tests/fixtures/actions.py``), which records the calls it receives
(``standin_producer.CALLS``, this process only). A download writes the store,
so it needs ``store.write``: the role ``store_writer`` or the setting
``store_write_for_all`` (SPEC 13 v0.3, criterion 7); the command acts as the
owner of the installation, who holds the role. A supervisor that runs no
network job keeps what a request started queued; the tests of a run let it end
in a worker of ``ACTION_WORKER``. The job itself is
``tests/integration/test_download_job.py``; a job of several calls (a report's
row) is ``tests/integration/test_row_jobs.py``.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore
from archiwista.index import IndexWriter, StoredPlan
from archiwista.jobs import JobSupervisor
from archiwista.sources import ActionPlan, PlanEntry
from archiwista.sources.registry import load_registry
from archiwista.state import Role
from tests.fixtures.actions import (
    ACTION_WORKER,
    CHECK,
    STATION,
    STORE,
    action_paths,
    action_supervisor,
    standin_in_settings,
    station_calls,
    store_root,
)
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.jobs import worker_path
from tests.fixtures.permissions import OTHER, WRITER, add_people, principal

JOB_TIMEOUT_S = 90.0
CHECK_BODY: dict[str, Any] = {"kind": "check", "store": STORE, **CHECK}
DOWNLOAD_BODY: dict[str, Any] = {**CHECK_BODY, "kind": "download"}
UNKNOWN_JOB = "0000000000000000"
FOLDER = "hydro/150160180"


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return module


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return a fresh installation with the stand-in's store."""
    return action_paths(tmp_path)


@contextmanager
def _api(
    paths: AppPaths, *, max_network_jobs: int = 0
) -> Iterator[tuple[Api, JobSupervisor]]:
    """Serve the API with a supervisor; by default no network job runs."""
    with action_supervisor(paths, max_network_jobs=max_network_jobs) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            yield api, jobs


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


def _start_argv(body: dict[str, Any]) -> list[str]:
    """Return the arguments of ``jobs start`` that ask what ``body`` asks."""
    argv = ["start", body["kind"], body["producer"], "--store", body["store"]]
    for call in body["calls"]:
        argv += ["--call", json.dumps(call)]
    return [*argv, "--plan", body["plan_job"]] if "plan_job" in body else argv


def _kept_plan(paths: AppPaths, jobs: JobSupervisor, *, project: str | None) -> str:
    """Record a job whose plan of the station's files the index keeps; its id.

    Without ``project`` it is a queued ``check`` of ``CHECK``; with one, a job
    of that project (``own_scan``), which only administrators see.
    """
    if project is None:
        job = jobs.submit("check", store=STORE, params=CHECK, actor=LOCAL_OWNER)
    else:
        job = jobs.submit("own_scan", params={"project": project}, actor=LOCAL_OWNER)
    plan = ActionPlan(
        producer="standin",
        command="series fetch",
        schema="standin-plan/1",
        root=str(store_root(paths.data_dir.parent)),
        checked_at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
        entries=(PlanEntry(f"{FOLDER}/2025.csv", "150160180", "missing"),),
    )
    with IndexWriter(paths.index_file) as writer:
        writer.write_plans([StoredPlan(job.id, 0, STORE, "standin series fetch", plan)])
    return job.id


def test_a_download_runs_the_plan_a_check_kept(paths: AppPaths, tmp_path: Path) -> None:
    """`202` with the job; the run fetches the plan's positions to download only."""
    with _api(paths, max_network_jobs=2) as (api, jobs):
        owner = api.session(LOCAL_OWNER)
        checked = owner.request("POST", "/jobs", json=CHECK_BODY).json()["id"]
        jobs.wait(checked, timeout=JOB_TIMEOUT_S)

        # Act
        started = owner.request(
            "POST", "/jobs", json={**DOWNLOAD_BODY, "plan_job": checked}
        )
        jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
        detail = owner.request("GET", f"/jobs/{started.json()['id']}").json()

    # Assert
    assert started.status_code == 202, started.text
    assert started.headers["location"] == f"/api/v1/jobs/{detail['id']}"
    assert started.json()["params"] == {
        "producer": "standin",
        "calls": [{"command": "series fetch", "options": STATION}],
        "plan_job": checked,
    }
    assert (detail["state"], detail["result"]["plan_job"]) == ("succeeded", checked)
    assert [file["path"] for file in detail["result"]["files"]] == [
        f"{FOLDER}/2024.csv",
        f"{FOLDER}/2025.csv",
    ]
    fetched = sorted(path.name for path in (store_root(tmp_path) / FOLDER).iterdir())
    assert fetched == ["2024.csv", "2025.csv"]


@pytest.mark.parametrize(
    ("roles", "for_all", "token", "allowed"),
    [
        ((), False, "startup", False),
        ((), False, "agent", False),
        (WRITER, False, "startup", True),
        (WRITER, False, "agent", True),
        ((), True, "startup", True),
        ((), True, "agent", True),
    ],
)
def test_a_download_needs_the_permission_to_write_the_stores(
    tmp_path: Path,
    standin: ModuleType,
    roles: tuple[Role, ...],
    for_all: bool,
    token: Literal["startup", "agent"],
    allowed: bool,
) -> None:
    """Without it: `403 permission_denied` and no job; a plan needs none.

    An agent acts with the roles of the person who minted its token. The
    session says beforehand what the route decides (`store_write`), so the
    interface shows the download disabled instead of offering a refusal.
    """
    # Arrange
    paths = action_paths(tmp_path)
    config = ConfigStore(paths.config_file)
    config.save(config.load().model_copy(update={"store_write_for_all": for_all}))

    with _api(paths) as (api, jobs):
        add_people(api.state)
        api.state.update_user(OTHER, roles=roles, actor=LOCAL_OWNER)
        person = api.session(principal(api.state, "other"), token=token)

        # Act
        session = person.request("GET", "/session")
        checked = person.request("POST", "/jobs", json=CHECK_BODY)
        answered = person.request("POST", "/jobs", json=DOWNLOAD_BODY)
        kinds = sorted(job.kind for job in jobs.list().items)
    validated = [call for call in standin.CALLS if call[0] == "validate_command"]

    # Assert
    assert session.json()["store_write"] is allowed
    assert checked.status_code == 202, checked.text
    if allowed:
        assert answered.status_code == 202, answered.text
        assert kinds == ["check", "download"]
        assert len(validated) == 2
    else:
        assert_problem(answered, 403, "forbidden", "permission_denied")
        assert kinds == ["check"]
        assert len(validated) == 1


@pytest.mark.parametrize(
    ("case", "status", "code", "reason"),
    [
        ("unknown", 404, "not_found", None),
        ("without_plan", 404, "not_found", None),
        ("another_call", 409, "conflict", "plan_mismatch"),
        ("check", 400, "validation_error", None),
    ],
)
def test_a_plan_the_download_cannot_run_is_refused_before_a_job(
    paths: AppPaths,
    standin: ModuleType,
    capsys: pytest.CaptureFixture[str],
    case: str,
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """Unknown, not kept, of another call, or for a check: the command agrees."""
    with _api(paths) as (api, jobs):
        owner = api.session(LOCAL_OWNER)
        kept = _kept_plan(paths, jobs, project=None)
        queued = jobs.submit("check", store=STORE, params=CHECK, actor=LOCAL_OWNER).id
        body = {
            "unknown": {**DOWNLOAD_BODY, "plan_job": UNKNOWN_JOB},
            "without_plan": {**DOWNLOAD_BODY, "plan_job": queued},
            "another_call": {
                **DOWNLOAD_BODY,
                "calls": station_calls("150160190"),
                "plan_job": kept,
            },
            "check": {**CHECK_BODY, "plan_job": kept},
        }[case]

        # Act
        refused = owner.request("POST", "/jobs", json=body)
        printed = _cli(capsys, paths, *_start_argv(body))
        kinds = [job.kind for job in jobs.list().items]

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    if reason == "plan_mismatch":
        assert refused.json()["details"]["job"] == kept
    assert kinds == ["check", "check"]
    assert [call for call in standin.CALLS if call[0] == "run_command"] == []


def test_the_plan_of_a_job_the_session_does_not_see_is_not_found(
    paths: AppPaths, standin: ModuleType
) -> None:
    """A hidden job is `404` as an unknown one; whoever sees it gets `409`."""
    with _api(paths) as (api, jobs):
        hidden = _kept_plan(paths, jobs, project="raba")
        add_people(api.state)
        api.state.update_user(OTHER, roles=WRITER, actor=LOCAL_OWNER)
        person = api.session(principal(api.state, "other"))
        owner = api.session(LOCAL_OWNER)

        # Act
        answers = [
            caller.request("POST", "/jobs", json={**DOWNLOAD_BODY, "plan_job": job})
            for caller, job in (
                (person, hidden),
                (person, UNKNOWN_JOB),
                (owner, hidden),
            )
        ]

    # Assert
    assert_problem(answers[0], 404, "not_found")
    assert answers[0].json()["detail"] == answers[1].json()["detail"].replace(
        UNKNOWN_JOB, hidden
    )
    assert_problem(answers[2], 409, "conflict", "plan_mismatch")


def test_jobs_start_downloads_in_the_foreground(
    paths: AppPaths,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The job as it ended, `GET /jobs/{job}` alike; failed units exit 10."""
    # Arrange: the command's own supervisor starts the stand-in's workers.
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    checked = _cli(capsys, paths, *_start_argv(CHECK_BODY))["id"]
    planned = {**DOWNLOAD_BODY, "plan_job": checked}
    failing = {**DOWNLOAD_BODY, "calls": station_calls("901")}

    # Act
    outcomes = []
    for body in (planned, failing):
        capsys.readouterr()
        status = main(
            ["jobs", *_start_argv(body), "--json"],
            registry=load_registry(cache_dir=paths.cache_dir),
            paths=paths,
        )
        outcomes.append((status, json.loads(capsys.readouterr().out)))
    with _api(paths) as (api, _):
        owner = api.session(LOCAL_OWNER)
        details = [
            owner.request("GET", f"/jobs/{job['id']}").json() for _, job in outcomes
        ]

    # Assert
    assert [status for status, _ in outcomes] == [0, 10]
    assert [printed for _, printed in outcomes] == details
    assert [detail["state"] for detail in details] == ["succeeded", "partial"]
    assert details[0]["result"]["plan_job"] == checked
    assert details[0]["result"]["counts"] == {"new": 2, "unchanged": 0, "relabeled": 0}
    assert (details[1]["result"]["counts"]["new"], details[1]["result"]["failed"]) == (
        3,
        1,
    )
