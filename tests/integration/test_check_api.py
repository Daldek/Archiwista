"""``POST /jobs``, ``GET /jobs/{job}/plan``, ``archiwista jobs`` (plan 2026-10-25, A4).

The routes and the commands run over the stand-in producer
(``tests/fixtures/actions.py``), which records the options each of its calls
receives (``standin_producer.CALLS``, this process only). A supervisor that
runs no network job keeps a check a request started queued, so what each
request started stays to be seen; the tests of a plan let the check run to its
end in a worker of ``ACTION_WORKER``. The job itself is
``tests/integration/test_check_job.py``.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.index import IndexWriter, StoredPlan
from archiwista.jobs import JobSupervisor
from archiwista.sources import ActionPlan, PlanEntry
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    ACTION_WORKER,
    STATION,
    STORE,
    action_paths,
    action_supervisor,
    standin_in_settings,
    store_root,
)
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.jobs import worker_path
from tests.fixtures.network import no_network
from tests.fixtures.permissions import add_people, principal

JOB_TIMEOUT_S = 90.0
BODY: dict[str, Any] = {
    "kind": "check",
    "producer": "standin",
    "store": STORE,
    "command": "series fetch",
    "options": STATION,
}
UNKNOWN_JOB = "0000000000000000"
# A command of the stand-in on a store that has no plan without effects.
SHOW: dict[str, object] = {
    "summary": "Show the files of one station in the store.",
    "summary_pl": "Pokaż pliki jednej stacji w magazynie.",
    "writes": "none",
    "network": False,
    "check": False,
    "options": [
        {"name": "station", "type": "string", "required": True, "description": "."},
        {
            "name": "root",
            "type": "string",
            "required": True,
            "path_role": "root",
            "description": "Store root.",
        },
    ],
    "examples": ["standin series show --station 150160180 --root /data/standin"],
}


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    monkeypatch.setitem(module._COMMANDS, "series show", SHOW)
    return module


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return a fresh installation with the stand-in's store."""
    return action_paths(tmp_path)


@contextmanager
def _api(
    paths: AppPaths, *, max_network_jobs: int = 0
) -> Iterator[tuple[Caller, JobSupervisor]]:
    """Serve the API with a supervisor; yield the owner's session and the jobs.

    By default no network job runs: a check a request starts stays queued.
    """
    with action_supervisor(paths, max_network_jobs=max_network_jobs) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            yield api.session(LOCAL_OWNER), jobs


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
    argv = ["start", body["kind"], body["producer"], body["command"]]
    argv += ["--options", json.dumps(body["options"])]
    return [*argv, "--store", body["store"]] if "store" in body else argv


def test_a_check_starts_with_the_options_as_the_producer_reads_them(
    paths: AppPaths, tmp_path: Path, standin: ModuleType
) -> None:
    """`202` with the job; the producer validated the call with the store's root."""
    # Arrange
    given = {"station": " 150160180 ", "kind": "HYDRO"}

    with _api(paths) as (owner, jobs), no_network() as attempts:
        # Act
        started = owner.request("POST", "/jobs", json={**BODY, "options": given})
        listed = [job.id for job in jobs.list().items]
    received = standin.CALLS

    # Assert
    assert started.status_code == 202, started.text
    job = started.json()
    assert started.headers["location"] == f"/api/v1/jobs/{job['id']}"
    assert (job["kind"], job["state"], job["store"], job["actor"]) == (
        "check",
        "queued",
        STORE,
        "local",
    )
    assert job["params"] == {
        "producer": "standin",
        "command": "series fetch",
        "options": {"station": "150160180", "kind": "hydro"},
    }
    assert listed == [job["id"]]
    root = str(store_root(tmp_path))
    assert received == [("validate_command", "series fetch", {**given, "root": root})]
    assert attempts == []


@pytest.mark.parametrize(
    ("body", "status", "code", "details"),
    [
        ({**BODY, "store": "brak"}, 404, "not_found", {}),
        (
            {**BODY, "command": "series_fetch"},
            400,
            "validation_error",
            {"reason": "unknown_command", "option": "command"},
        ),
        (
            {**BODY, "command": "stations list", "options": {"kind": "meteo"}},
            422,
            "unsupported",
            {"reason": "no_store"},
        ),
        (
            {**BODY, "command": "series show", "options": {"station": "150160180"}},
            422,
            "unsupported",
            {"reason": "no_check"},
        ),
        (
            {**BODY, "options": {**STATION, "area": "/etc/passwd"}},
            403,
            "forbidden",
            {"reason": "path_outside_root", "option": "area"},
        ),
        (
            {**BODY, "options": {**STATION, "kind": "both"}},
            400,
            "validation_error",
            {"option": "kind"},
        ),
        (
            {**BODY, "producer": "brak"},
            503,
            "missing_dependency",
            {"reason": "source_unavailable"},
        ),
        ({**BODY, "kind": "download"}, 400, "validation_error", {}),
        ({**BODY, "force": True}, 400, "validation_error", {}),
        ({**BODY, "command": ""}, 400, "validation_error", {}),
        (
            {key: value for key, value in BODY.items() if key != "store"},
            400,
            "validation_error",
            {},
        ),
    ],
)
def test_a_request_the_worker_would_refuse_is_refused_before_a_job(
    paths: AppPaths,
    standin: ModuleType,
    capsys: pytest.CaptureFixture[str],
    body: dict[str, Any],
    status: int,
    code: str,
    details: dict[str, object],
) -> None:
    """Nothing is recorded and the producer plans nothing; the command agrees.

    The command line has no way to give a member the body does not know.
    """
    with _api(paths) as (owner, jobs):
        refused = owner.request("POST", "/jobs", json=body)
        if set(body) <= set(BODY):
            assert_same_error(_cli(capsys, paths, *_start_argv(body)), refused.json())
        listed = jobs.list().items

    assert_problem(refused, status, code)
    assert refused.json().get("details", {}).items() >= details.items()
    assert listed == ()
    assert [call for call in standin.CALLS if call[0] == "check_command"] == []


def test_offline_mode_refuses_a_check_before_a_job(
    tmp_path: Path, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """`409 offline_mode` and exit 4, and nothing is recorded."""
    paths = action_paths(tmp_path, offline=True)

    with _api(paths) as (owner, jobs):
        refused = owner.request("POST", "/jobs", json=BODY)
        printed = _cli(capsys, paths, *_start_argv(BODY))
        listed = jobs.list().items

    assert_problem(refused, 409, "conflict", "offline_mode")
    assert_same_error(printed, refused.json())
    assert printed["exit_code"] == 4
    assert listed == ()


def test_the_plan_of_a_finished_check_is_read_back(
    paths: AppPaths,
    tmp_path: Path,
    standin: ModuleType,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Every position as the producer planned it; an unknown size is null, not 0."""
    with _api(paths, max_network_jobs=2) as (owner, jobs):
        # Act
        started = owner.request("POST", "/jobs", json=BODY)
        record = jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
        with no_network() as attempts:
            plan = owner.request("GET", f"/jobs/{record.id}/plan")
            printed = _cli(capsys, paths, "plan", record.id)
        detail = owner.request("GET", f"/jobs/{record.id}").json()

    # Assert
    assert record.state == "succeeded", record.error
    assert plan.status_code == 200, plan.text
    body = plan.json()
    root = str(store_root(tmp_path))
    line = f"standin series fetch --station 150160180 --kind hydro --root {root}"
    planned = standin.plan_items("150160180", "hydro")
    assert {key: value for key, value in body.items() if key != "checked_at"} == {
        "job_id": record.id,
        "store": STORE,
        "producer": "standin",
        "command": "series fetch",
        "line": line,
        "root": root,
        "schema": "standin-plan/1",
        "ok": True,
        "counts": {
            "current": 1,
            "newer": 1,
            "missing": 1,
            "unverifiable": 1,
            "check_failed": 0,
        },
        "todo": 2,
        "size_bytes": 5400,
        "size_complete": False,
        "entries": [
            {
                "path": item["file"],
                "unit": item["station"],
                "status": item["status"],
                "local_label": item["local"],
                "available_label": item["source"],
                "size_bytes": item["bytes"],
                "error": None,
                "conflict": None,
            }
            for item in planned
        ],
        "notices": [
            {
                "level": "info",
                "code": "plan_cached",
                "message": "The station index answered from the cache.",
            }
        ],
    }
    assert body["entries"][2]["size_bytes"] is None
    assert datetime.fromisoformat(body["checked_at"]) == datetime.fromisoformat(
        detail["result"]["checked_at"]
    )
    assert (detail["result"]["counts"], detail["result"]["line"]) == (
        body["counts"],
        line,
    )
    assert printed == body
    assert attempts == []


def test_a_job_without_a_plan_is_not_found(
    paths: AppPaths, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """A check still queued and an unknown job: `404` and exit 3 alike."""
    with _api(paths) as (owner, _):
        queued = owner.request("POST", "/jobs", json=BODY).json()["id"]
        answers = [
            (
                owner.request("GET", f"/jobs/{job}/plan"),
                _cli(capsys, paths, "plan", job),
            )
            for job in (queued, UNKNOWN_JOB)
        ]

    for answered, printed in answers:
        assert_problem(answered, 404, "not_found")
        assert_same_error(printed, answered.json())
    assert [printed["exit_code"] for _, printed in answers] == [3, 3]
    assert answers[0][0].json()["detail"] != answers[1][0].json()["detail"]


def test_the_plan_of_a_job_the_session_does_not_see_is_not_found(
    paths: AppPaths, tmp_path: Path, standin: ModuleType
) -> None:
    """A job of a project hidden from the person is `404`, its plan kept or not."""
    # Arrange: a job of a project no index knows, which only administrators see.
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    plan = ActionPlan(
        producer="standin",
        command="series fetch",
        schema="standin-plan/1",
        root=str(store_root(tmp_path)),
        checked_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
        entries=(PlanEntry("hydro/150160180/2025.csv", "150160180", "missing"),),
    )

    with JobSupervisor(paths, settings, max_jobs=0) as jobs:
        job = jobs.submit("own_scan", params={"project": "raba"}, actor=LOCAL_OWNER)
        with IndexWriter(paths.index_file) as writer:
            writer.write_plan(StoredPlan(job.id, STORE, "standin series fetch", plan))
        with running_api(paths, registry, jobs=jobs) as api:
            add_people(api.state)
            person = api.session(principal(api.state, "other"))
            owner = api.session(LOCAL_OWNER)

            # Act
            hidden = person.request("GET", f"/jobs/{job.id}/plan")
            unknown = person.request("GET", f"/jobs/{UNKNOWN_JOB}/plan")
            shown = owner.request("GET", f"/jobs/{job.id}/plan")

    # Assert
    assert_problem(hidden, 404, "not_found")
    assert hidden.json()["detail"] == unknown.json()["detail"].replace(
        UNKNOWN_JOB, job.id
    )
    assert shown.status_code == 200, shown.text
    assert shown.json()["entries"][0]["status"] == "missing"


def test_jobs_start_runs_the_check_in_the_foreground(
    paths: AppPaths,
    standin: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The job as it ended, `GET /jobs/{job}` alike; a partial plan exits 10."""
    # Arrange: the command's own supervisor starts the stand-in's workers.
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    partial = {**BODY, "options": {**STATION, "station": "901"}}

    # Act
    outcomes = []
    for body in (BODY, partial):
        capsys.readouterr()
        status = main(
            ["jobs", *_start_argv(body), "--json"],
            registry=load_registry(cache_dir=paths.cache_dir),
            paths=paths,
        )
        outcomes.append((status, capsys.readouterr()))
    with _api(paths) as (owner, _):
        details = [
            owner.request("GET", f"/jobs/{json.loads(printed.out)['id']}").json()
            for _, printed in outcomes
        ]

    # Assert
    assert [status for status, _ in outcomes] == [0, 10]
    for (_, printed), detail in zip(outcomes, details, strict=True):
        assert json.loads(printed.out) == detail
    assert [detail["state"] for detail in details] == ["succeeded", "partial"]
    assert details[1]["result"]["failed"] == [
        {
            "path": "hydro/901/2025.csv",
            "error": "The source did not answer for hydro/901/2025.csv.",
        }
    ]
    job = details[0]["id"]
    assert outcomes[0][1].err.splitlines() == [
        f"Job {job} started: plan of a download.",
        f"Job {job}: The station index answered from the cache.",
    ]


def test_openapi_documents_the_job_and_the_plan(
    paths: AppPaths, standin: ModuleType
) -> None:
    """`202` is `JobDetail`, `200` of the plan `ActionPlanInfo`; refusals: problems."""
    with _api(paths) as (owner, _):
        document = owner.request("GET", "/openapi.json").json()

    started = document["paths"]["/api/v1/jobs"]["post"]["responses"]
    plan = document["paths"]["/api/v1/jobs/{job}/plan"]["get"]["responses"]
    schemas = document["components"]["schemas"]
    assert started["202"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/JobDetail"
    )
    assert plan["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/ActionPlanInfo"
    )
    assert schemas["ActionPlanInfo"]["examples"]
    assert schemas["JobRequest"]["examples"]
    assert {status for status in started if int(status) >= 400} >= {
        "400",
        "401",
        "403",
        "404",
        "409",
        "422",
        "503",
    }
    for responses in (started, plan):
        for status, response in responses.items():
            if int(status) >= 400:
                assert list(response["content"]) == ["application/problem+json"]
