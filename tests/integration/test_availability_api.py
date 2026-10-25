"""``/availability`` and ``archiwista availability`` (plan 2026-10-25, A2).

The routes and the command run over the stand-in producer
(``tests/fixtures/availability.py``) with a supervisor of real workers. A
supervisor that runs no network job keeps a check a request started queued,
so what each request started stays to be seen; one test lets the check run
to its end.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths
from archiwista.index import IndexWriter
from archiwista.jobs import JobSupervisor
from archiwista.services.commands import actions
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.availability import (
    AREA,
    PARAMS,
    area_paths,
    availability_supervisor,
    register_standin,
)
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.network import no_network

JOB_TIMEOUT_S = 90.0
QUERY = f"/availability?area_id={AREA.id}&product=dem&producer=standin"
UNKNOWN_AREA = "0000000000000000"
# The job that asked for the report ``_keep_report`` keeps.
KEPT_BY = "a1b2c3d4e5f60718"


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    return register_standin(monkeypatch)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return a fresh installation whose index keeps the area ``AREA``."""
    return area_paths(tmp_path)


def _keep_report(paths: AppPaths, standin: ModuleType, *, age: timedelta) -> None:
    """Keep the stand-in's report of ``AREA`` as if the source was asked ``age`` ago.

    The producer's call is forgotten, so ``standin.CALLS`` shows the test's.
    """
    adapter = actions(load_registry(cache_dir=paths.cache_dir), "standin")
    report = adapter.availability("dem", area=AREA.geometry, countries=AREA.countries)
    aged = replace(report, checked_at=report.checked_at - age)
    with IndexWriter(paths.index_file) as writer:
        writer.write_availability(AREA.id, aged, product="dem", job_id=KEPT_BY)
    standin.CALLS.clear()


@contextmanager
def _api(
    paths: AppPaths, *, offline: bool = False, max_network_jobs: int = 0
) -> Iterator[tuple[Caller, JobSupervisor]]:
    """Serve the API with a supervisor; yield the owner's session and the jobs.

    By default no network job runs: a check a request starts stays queued.
    """
    with availability_supervisor(
        paths, offline=offline, max_network_jobs=max_network_jobs
    ) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            yield api.session(LOCAL_OWNER), jobs


def test_a_fresh_report_answers_without_a_job_and_force_starts_one(
    paths: AppPaths, standin: ModuleType
) -> None:
    """Six days and 23 hours old: `200` as `GET` returns it; `force`: `202`."""
    # Arrange
    _keep_report(paths, standin, age=timedelta(days=6, hours=23))

    with _api(paths) as (owner, jobs):
        with no_network() as attempts:
            # Act
            answered = owner.request("POST", "/availability", json=PARAMS)
            kept = owner.request("GET", QUERY)
            before = jobs.list().items
        forced = owner.request("POST", "/availability", json={**PARAMS, "force": True})
        after = [job.id for job in jobs.list().items]

    # Assert
    assert answered.status_code == 200, answered.text
    assert answered.json() == kept.json()
    assert (answered.json()["job_id"], answered.json()["area"]["name"]) == (
        KEPT_BY,
        "Kraków",
    )
    assert before == ()
    assert forced.status_code == 202, forced.text
    job = forced.json()
    assert forced.headers["location"] == f"/api/v1/jobs/{job['id']}"
    assert (job["kind"], job["state"], job["store"], job["params"]) == (
        "availability",
        "queued",
        None,
        {**PARAMS, "force": True},
    )
    assert after == [job["id"]]
    assert standin.CALLS == []
    assert attempts == []


def test_a_report_older_than_seven_days_starts_a_check(
    paths: AppPaths, standin: ModuleType
) -> None:
    """Seven days and a minute old: the source is asked again, from its cache."""
    _keep_report(paths, standin, age=timedelta(days=7, minutes=1))

    with _api(paths) as (owner, jobs):
        started = owner.request("POST", "/availability", json=PARAMS)
        listed = [job.id for job in jobs.list().items]

    assert started.status_code == 202, started.text
    assert started.json()["params"] == {**PARAMS, "force": False}
    assert listed == [started.json()["id"]]


def test_offline_mode_refuses_a_check_of_the_source_and_records_nothing(
    paths: AppPaths, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """`409 offline_mode` and exit 4 without a job; a fresh report still answers."""
    # Arrange
    _keep_report(paths, standin, age=timedelta(days=8))
    argv = ["availability", "check", AREA.id, "--product", "dem"]

    with _api(paths, offline=True) as (owner, jobs):
        # Act
        refused = owner.request("POST", "/availability", json=PARAMS)
        capsys.readouterr()
        status = main(
            [*argv, "--producer", "standin", "--json"],
            registry=load_registry(cache_dir=paths.cache_dir),
            paths=paths,
        )
        printed = capsys.readouterr()
        listed = jobs.list().items
        kept = owner.request("GET", QUERY)
        _keep_report(paths, standin, age=timedelta(0))
        answered = owner.request("POST", "/availability", json=PARAMS)

    # Assert
    assert_problem(refused, 409, "conflict", "offline_mode")
    assert_same_error(refusal(printed.out, printed.err, status), refused.json())
    assert listed == ()
    assert kept.json()["job_id"] == KEPT_BY
    assert answered.status_code == 200, answered.text
    assert standin.CALLS == []


@pytest.mark.parametrize(
    ("body", "status", "code", "details"),
    [
        ({**PARAMS, "area_id": UNKNOWN_AREA}, 404, "not_found", {}),
        (
            {**PARAMS, "product": "laz"},
            422,
            "unsupported",
            {"reason": "no_availability", "allowed": ["dem"]},
        ),
        (
            {**PARAMS, "producer": "brak"},
            503,
            "missing_dependency",
            {"reason": "source_unavailable"},
        ),
        ({**PARAMS, "product": ""}, 400, "validation_error", {}),
        ({**PARAMS, "store": "zespol"}, 400, "validation_error", {}),
    ],
)
def test_a_request_the_check_cannot_take_is_refused_before_a_job(
    paths: AppPaths,
    standin: ModuleType,
    body: dict[str, object],
    status: int,
    code: str,
    details: dict[str, object],
) -> None:
    """An unknown area or producer, a product it does not check, a wrong body."""
    with _api(paths) as (owner, jobs):
        refused = owner.request("POST", "/availability", json=body)
        listed = jobs.list().items

    assert_problem(refused, status, code)
    assert refused.json().get("details", {}).items() >= details.items()
    assert listed == ()
    assert standin.CALLS == []


def test_get_without_a_report_is_404(paths: AppPaths, standin: ModuleType) -> None:
    """An area without a report, an unknown area: `404`, and no producer call."""
    with _api(paths) as (owner, _), no_network() as attempts:
        none = owner.request("GET", QUERY)
        unknown = owner.request(
            "GET", f"/availability?area_id={UNKNOWN_AREA}&product=dem"
        )

    assert_problem(none, 404, "not_found")
    assert_problem(unknown, 404, "not_found")
    assert standin.CALLS == []
    assert attempts == []


def test_openapi_documents_the_report_and_the_job_of_post(
    paths: AppPaths, standin: ModuleType
) -> None:
    """`200` is `AvailabilityInfo`, `202` a `JobDetail`; the refusals are problems."""
    with _api(paths) as (owner, _):
        document = owner.request("GET", "/openapi.json").json()

    responses = document["paths"]["/api/v1/availability"]["post"]["responses"]
    schemas = {
        status: responses[status]["content"]["application/json"]["schema"]["$ref"]
        for status in ("200", "202")
    }
    assert schemas == {
        "200": "#/components/schemas/AvailabilityInfo",
        "202": "#/components/schemas/JobDetail",
    }
    problems = {status for status in responses if int(status) >= 400}
    assert problems >= {"400", "401", "403", "404", "409", "422", "503"}
    for status in problems:
        assert list(responses[status]["content"]) == ["application/problem+json"]


def test_the_check_a_request_started_keeps_the_report_that_answers_next(
    paths: AppPaths, standin: ModuleType
) -> None:
    """A worker runs the check; `GET` returns its report, the next `POST` too."""
    with _api(paths, max_network_jobs=2) as (owner, jobs):
        started = owner.request("POST", "/availability", json=PARAMS)
        record = jobs.wait(started.json()["id"], timeout=JOB_TIMEOUT_S)
        kept = owner.request("GET", QUERY)
        again = owner.request("POST", "/availability", json=PARAMS)

    assert started.status_code == 202, started.text
    assert record.state == "succeeded", record.error
    assert kept.status_code == 200, kept.text
    assert kept.json()["job_id"] == record.id
    assert [item["year"] for item in kept.json()["report"]["combinations"]] == [
        2023,
        2023,
        2022,
    ]
    assert (again.status_code, again.json()) == (200, kept.json())


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista availability … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        ["availability", *argv, "--producer", "standin", "--json"],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def test_availability_cli_json_equals_http(
    paths: AppPaths, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """`show` is `GET`, `check` with a fresh report is `POST`; refusals agree."""
    # Arrange
    _keep_report(paths, standin, age=timedelta(days=1))

    with _api(paths) as (owner, jobs):

        def http(method: str, path: str, body: object = None) -> Any:
            return owner.request(method, path, json=body).json()

        # Act
        answers = [
            (
                _cli(capsys, paths, "show", AREA.id, "--product", "dem"),
                http("GET", QUERY),
            ),
            (
                _cli(capsys, paths, "check", AREA.id, "--product", "dem"),
                http("POST", "/availability", PARAMS),
            ),
        ]
        refusals = [
            (
                _cli(capsys, paths, "show", UNKNOWN_AREA, "--product", "dem"),
                http(
                    "GET",
                    f"/availability?area_id={UNKNOWN_AREA}&product=dem&producer=standin",
                ),
            ),
            (
                _cli(capsys, paths, "check", AREA.id, "--product", "laz"),
                http("POST", "/availability", {**PARAMS, "product": "laz"}),
            ),
            (
                _cli(capsys, paths, "check", AREA.id, "--product", ""),
                http("POST", "/availability", {**PARAMS, "product": ""}),
            ),
        ]
        listed = jobs.list().items

    # Assert
    for printed, answered in answers:
        assert printed == answered
    for document, problem in refusals:
        assert_same_error(document, problem)
    assert [document["code"] for document, _ in refusals] == [
        "not_found",
        "unsupported",
        "validation_error",
    ]
    assert listed == ()
    assert standin.CALLS == []


def test_availability_check_force_runs_the_check_in_the_foreground(
    paths: AppPaths, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """A fresh report kept, `--force` asks again: a new report of a new job."""
    # Arrange
    _keep_report(paths, standin, age=timedelta(days=1))
    capsys.readouterr()

    # Act
    status = main(
        [
            "availability",
            "check",
            AREA.id,
            "--product",
            "dem",
            "--producer",
            "standin",
            "--force",
            "--json",
        ],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    printed = capsys.readouterr()

    # Assert
    assert status == 0, printed.err
    info = json.loads(printed.out)
    assert info["job_id"] not in (None, KEPT_BY)
    lines = printed.err.splitlines()
    assert lines == [
        f"Availability check: job {info['job_id']}.",
        "Availability check: The sheet index answered from the cache.",
    ]
