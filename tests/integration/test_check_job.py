"""The check job: the producer's plans of runs in a store (plan 2026-10-25, A4).

The stand-in producer (``tests/fixtures/actions.py``) plans a fetch of a
station's files into the store it is given: one current, one newer, one
missing of unknown size and one unverifiable; a station whose code starts
with ``9`` cannot be asked about its missing file, station ``999`` about none.
It records the options its ``check_command`` receives. A job of several calls
is ``tests/integration/test_row_jobs.py``; Kartograf's side of the call is
``tests/contract/test_kartograf_check.py``.
"""

import io
import json
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths
from archiwista.error_document import describe
from archiwista.errors import CheckFailedError, OfflineModeError
from archiwista.index import IndexQueries
from archiwista.jobs import MAX_JOB_CALLS, JobSupervisor, worker
from tests.fixtures.actions import (
    CHECK,
    STATION,
    STORE,
    action_paths,
    action_spec,
    action_supervisor,
    station_calls,
    store_root,
)
from tests.fixtures.availability import register_standin
from tests.fixtures.jobs import worker_path

JOB_TIMEOUT_S = 90.0


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    worker_path(monkeypatch)
    return register_standin(monkeypatch)


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return a fresh installation with the stand-in's store."""
    return action_paths(tmp_path)


@pytest.fixture
def held(paths: AppPaths) -> Iterator[JobSupervisor]:
    """Yield a supervisor that runs no network job: they stay queued."""
    with action_supervisor(paths, max_network_jobs=0) as jobs:
        yield jobs


def _station(station: str) -> dict[str, object]:
    """Return the parameters of a check of one station's files."""
    return {"producer": "standin", "calls": station_calls(station)}


def test_the_plan_is_the_producers_plan_of_the_configured_store(
    paths: AppPaths, tmp_path: Path, held: JobSupervisor, standin: ModuleType
) -> None:
    """Every position comes back as the producer planned it; an unknown size is null.

    The producer gets the store's directory as its root and nothing to write
    into; the plan is kept with the job, with the producer's line of the run.
    """
    job = held.submit("check", store=STORE, params=CHECK, actor=LOCAL_OWNER)
    stream = io.StringIO()
    root = store_root(tmp_path)

    summary = worker.run_check(
        action_spec(paths, root, job.id, "check", job.params), worker.Emitter(stream)
    )
    with IndexQueries(paths.index_file) as queries:
        (stored,) = queries.plans(job.id)

    planned = standin.plan_items("150160180", "hydro")
    assert [call for call in standin.CALLS if call[0] == "check_command"] == [
        ("check_command", "series fetch", {**STATION, "root": str(root)})
    ]
    assert stored.call == 0
    assert [
        (e.path, e.unit, e.status, e.local_label, e.available_label, e.size_bytes)
        for e in stored.plan.entries
    ] == [
        (i["file"], i["station"], i["status"], i["local"], i["source"], i["bytes"])
        for i in planned
    ]
    assert [entry.size_bytes for entry in stored.plan.todo] == [5400, None]
    line = f"standin series fetch --station 150160180 --kind hydro --root {root}"
    assert (stored.store, stored.line, stored.plan.root) == (STORE, line, str(root))
    assert isinstance(summary, dict)
    assert summary == {
        "producer": "standin",
        "store": STORE,
        "root": str(root),
        "checked_at": stored.plan.checked_at.isoformat(),
        "ok": True,
        "positions": 4,
        "counts": {
            "current": 1,
            "newer": 1,
            "missing": 1,
            "unverifiable": 1,
            "check_failed": 0,
        },
        "size_bytes": 5400,
        "size_complete": False,
        "failed": [],
        "calls": [
            {
                "command": "series fetch",
                "line": line,
                "status": "ok",
                "positions": 4,
                "todo": 2,
                "error": None,
            }
        ],
        "seconds": summary["seconds"],
    }
    assert [json.loads(line)["data"] for line in stream.getvalue().splitlines()] == [
        {
            "level": "info",
            "code": "plan_cached",
            "message": "The station index answered from the cache.",
        },
        {"current": 1, "total": 1},
    ]


def test_a_position_the_source_could_not_tell_about_ends_the_job_partial(
    paths: AppPaths, tmp_path: Path, held: JobSupervisor
) -> None:
    """The plan of the other positions is kept; the failed one carries its text."""
    job = held.submit("check", store=STORE, params=_station("901"), actor=LOCAL_OWNER)

    outcome = worker.run_check(
        action_spec(paths, store_root(tmp_path), job.id, "check", job.params),
        worker.Emitter(io.StringIO()),
    )
    with IndexQueries(paths.index_file) as queries:
        (stored,) = queries.plans(job.id)

    assert isinstance(outcome, worker.PartialResult)
    error = "The source did not answer for hydro/901/2025.csv."
    assert outcome.summary["failed"] == [
        {"call": 0, "path": "hydro/901/2025.csv", "error": error}
    ]
    assert outcome.summary["calls"][0]["status"] == "partial"
    assert outcome.summary["ok"] is False
    assert outcome.summary["counts"]["check_failed"] == 1
    assert (outcome.summary["size_bytes"], outcome.summary["size_complete"]) == (
        5400,
        True,
    )
    assert (stored.plan.entries[2].status, stored.plan.entries[2].error) == (
        "check_failed",
        error,
    )


def test_a_plan_with_no_position_checked_fails_and_is_not_kept(
    paths: AppPaths, tmp_path: Path, held: JobSupervisor
) -> None:
    """None of the source's answers came: ``source_unavailable``, ``check_failed``."""
    job = held.submit("check", store=STORE, params=_station("999"), actor=LOCAL_OWNER)

    with pytest.raises(CheckFailedError) as failed:
        worker.run_check(
            action_spec(paths, store_root(tmp_path), job.id, "check", job.params),
            worker.Emitter(io.StringIO()),
        )
    with IndexQueries(paths.index_file) as queries:
        stored = queries.plans(job.id)

    problem = describe(failed.value)
    assert (problem.code, problem.details["reason"]) == (
        "source_unavailable",
        "check_failed",
    )
    assert "hydro/999/2023.csv" in problem.detail
    assert stored == ()


@pytest.mark.parametrize(
    ("station", "state", "failed"),
    [("901", "partial", 1), ("150160180", "succeeded", 0)],
)
def test_a_worker_process_ends_the_job_with_the_plan_in_its_result(
    paths: AppPaths, station: str, state: str, failed: int
) -> None:
    """A partial plan is a summary, not an error; its final event carries it."""
    with action_supervisor(paths) as jobs:
        job = jobs.submit(
            "check", store=STORE, params=_station(station), actor=LOCAL_OWNER
        )
        record = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
        final = jobs.events(job.id)[-1]
    with IndexQueries(paths.index_file) as queries:
        (stored,) = queries.plans(job.id)

    assert (record.state, record.store, record.error) == (state, STORE, None)
    assert record.result is not None
    assert record.result["counts"]["check_failed"] == failed
    assert final.data == {"state": state, "result": record.result}
    assert len(stored.plan.entries) == record.result["positions"] == 4


def test_offline_mode_refuses_the_check_before_a_job_exists(
    tmp_path: Path, standin: ModuleType
) -> None:
    """The plan needs the source: ``409 offline_mode``, and nothing is recorded."""
    paths = action_paths(tmp_path, offline=True)

    with action_supervisor(paths) as jobs:
        with pytest.raises(OfflineModeError):
            jobs.submit("check", store=STORE, params=CHECK, actor=LOCAL_OWNER)
        listed = jobs.list().items

    assert listed == ()
    assert standin.CALLS == []


@pytest.mark.parametrize(
    ("store", "params"),
    [
        (None, CHECK),
        (STORE, {**CHECK, "calls": [{"command": "", "options": STATION}]}),
        (STORE, {"producer": "standin", "options": STATION}),
        (STORE, {**CHECK, "calls": []}),
        (STORE, {**CHECK, "calls": station_calls("1") * (MAX_JOB_CALLS + 1)}),
        (STORE, {**CHECK, "calls": [{"command": "series fetch", "station": "1"}]}),
        (STORE, {**CHECK, "calls": [{"command": "series fetch", "options": []}]}),
        (STORE, {**CHECK, "calls": ["series fetch --station 1"]}),
        (STORE, {**CHECK, "force": True}),
    ],
)
def test_invalid_check_parameters_are_refused_before_a_job_exists(
    held: JobSupervisor, store: str | None, params: dict[str, object]
) -> None:
    """A store, a producer and 1 to 1000 calls; each a command and options."""
    with pytest.raises(ValueError):
        held.submit("check", store=store, params=params, actor=LOCAL_OWNER)

    assert held.list().items == ()
