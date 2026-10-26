"""A report's row in one check and one download job (ADR-044).

All the lines of a row (or of a pasted list) are the ``calls`` of one job:
one ``check`` job plans the calls one after the other in one worker and keeps
a plan of each, and one ``download`` job runs the plan of each call it names.
The stand-in producer (``tests/fixtures/actions.py``) plans and fetches one
station's files per call: one current, one newer, one missing of unknown size
and one unverifiable; station ``999`` cannot be asked about any of them, one
whose code starts with ``9`` not about its missing file. While the store
holds ``HOLD`` a run waits after its first new file. A job of one call is
``tests/integration/test_check_job.py`` and
``tests/integration/test_download_job.py``.
"""

import io
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore, StoreConfig
from archiwista.error_document import describe
from archiwista.errors import RunFailedError
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor, worker
from archiwista.messages import message
from archiwista.sources.registry import load_registry
from tests.fixtures.actions import (
    ACTION_WORKER,
    STORE,
    action_paths,
    action_spec,
    action_supervisor,
    standin_in_settings,
    station_calls,
    store_root,
)
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.jobs import worker_path

JOB_TIMEOUT_S = 90.0
# A row of 32 lines, as Kartograf gives one per sheet: 32 stations here.
ROW = tuple(f"1501600{place:02d}" for place in range(32))
# Three lines of a row.
STATIONS = ("150160180", "150160190", "150160200")
# The files a station's plan downloads: the newer one and the missing one.
TODO = ("2024.csv", "2025.csv")
# A second configured store of the stand-in.
OTHER_STORE = "zapas"


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers, in every store's settings."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return module


@pytest.fixture
def paths(tmp_path: Path, standin: ModuleType) -> AppPaths:
    """Return an installation with the stand-in's stores ``STORE`` and ``zapas``."""
    created = action_paths(tmp_path)
    other = tmp_path / OTHER_STORE
    other.mkdir()
    config = ConfigStore(created.config_file)
    settings = config.load()
    store = StoreConfig(id=OTHER_STORE, name="Zapas", kartograf=other, kind="local")
    config.save(settings.model_copy(update={"stores": (*settings.stores, store)}))
    return created


@contextmanager
def _api(
    paths: AppPaths, *, max_network_jobs: int = 2
) -> Iterator[tuple[Caller, JobSupervisor]]:
    """Serve the API with the stand-in's workers; yield the owner's session, jobs."""
    with action_supervisor(paths, max_network_jobs=max_network_jobs) as jobs:
        registry = load_registry(cache_dir=paths.cache_dir)
        with running_api(paths, registry, jobs=jobs) as api:
            yield api.session(LOCAL_OWNER), jobs


def _body(kind: str, *stations: str, **more: Any) -> dict[str, Any]:
    """Return the body of ``POST /jobs`` of a fetch of each station's files."""
    calls = station_calls(*stations)
    return {"kind": kind, "producer": "standin", "store": STORE, "calls": calls} | more


def _run(paths: AppPaths, root: Path, job: Any) -> Any:
    """Run a recorded ``check`` or ``download`` job in this process; its outcome."""
    spec = action_spec(paths, root, job.id, job.kind, job.params)
    runner = worker.run_check if job.kind == "check" else worker.run_download
    return runner(spec, worker.Emitter(io.StringIO()))


def _until_completed(jobs: JobSupervisor, job_id: str) -> None:
    """Wait until the job reported its first file done."""
    deadline = time.monotonic() + JOB_TIMEOUT_S
    while time.monotonic() < deadline:
        if any(e.data.get("status") == "completed" for e in jobs.events(job_id)):
            return
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} reported no file")


def test_a_row_of_32_lines_is_checked_by_one_job_and_downloaded_by_one(
    paths: AppPaths, tmp_path: Path
) -> None:
    """One worker plans the 32 calls in their order, one more runs their plans."""
    with _api(paths) as (owner, jobs):
        # Act
        checked = owner.request("POST", "/jobs", json=_body("check", *ROW)).json()
        check = jobs.wait(checked["id"], timeout=JOB_TIMEOUT_S)
        plans = owner.request("GET", f"/jobs/{check.id}/plan").json()
        body = _body("download", *ROW, plan_job=check.id)
        started = owner.request("POST", "/jobs", json=body).json()
        download = jobs.wait(started["id"], timeout=JOB_TIMEOUT_S)
        planning = [e.data for e in jobs.events(check.id) if e.type == "progress"]
        running = [e.data for e in jobs.events(download.id) if e.type == "progress"]
        kinds = [job.kind for job in jobs.list().items]

    # Assert: one job of each kind; the plans of the calls in their order.
    assert kinds == ["download", "check"]
    assert (check.state, download.state) == ("succeeded", "succeeded")
    assert check.result is not None
    assert download.result is not None
    assert [(p["current"], p["total"]) for p in planning] == [
        (done, 32) for done in range(1, 33)
    ]
    assert [call["status"] for call in check.result["calls"]] == ["ok"] * 32
    assert [(call["call"], call["options"]["station"]) for call in plans["calls"]] == [
        *enumerate(ROW)
    ]
    assert (
        plans["counts"]
        == check.result["counts"]
        == {
            "current": 32,
            "newer": 32,
            "missing": 32,
            "unverifiable": 32,
            "check_failed": 0,
        }
    )
    assert (plans["positions"], plans["todo"], plans["ok"]) == (128, 64, True)
    assert (plans["size_bytes"], plans["size_complete"]) == (32 * 5400, False)
    # Each call ran its own plan: the newer and the missing file of its station.
    assert [call["status"] for call in download.result["calls"]] == ["ok"] * 32
    assert [(file["call"], file["path"]) for file in download.result["files"]] == [
        (place, f"hydro/{station}/{name}")
        for place, station in enumerate(ROW)
        for name in TODO
    ]
    assert download.result["counts"] == {"new": 64, "unchanged": 0, "relabeled": 0}
    assert {(p["call"], p["calls"]) for p in running} == {
        (place, 32) for place in range(32)
    }
    for station in ROW:
        folder = store_root(tmp_path) / "hydro" / station
        assert sorted(path.name for path in folder.iterdir()) == list(TODO)


def test_a_call_the_source_cannot_tell_about_is_named_and_its_download_skips_it(
    paths: AppPaths, tmp_path: Path
) -> None:
    """The check ends partial without a plan of 999; the download runs the others."""
    root = store_root(tmp_path)
    params = {"producer": "standin", "calls": station_calls("150160180", "999", "901")}
    with action_supervisor(paths, max_network_jobs=0) as held:
        check = held.submit("check", store=STORE, params=params, actor=LOCAL_OWNER)
        checked = _run(paths, root, check)
        download = held.submit(
            "download",
            store=STORE,
            params={**check.params, "plan_job": check.id},
            actor=LOCAL_OWNER,
        )
        ran = _run(paths, root, download)
    with IndexQueries(paths.index_file) as queries:
        kept = [stored.call for stored in queries.plans(check.id)]

    # The check: 999 failed, 901 planned without its missing file.
    assert isinstance(checked, worker.PartialResult)
    sections = checked.summary["calls"]
    assert [call["status"] for call in sections] == ["ok", "failed", "partial"]
    error = sections[1]["error"]
    assert (error["code"], error["reason"]) == ("source_unavailable", "check_failed")
    assert "hydro/999/" in error["detail"]
    assert checked.summary["failed"] == [
        {
            "call": 2,
            "path": "hydro/901/2025.csv",
            "error": "The source did not answer for hydro/901/2025.csv.",
        }
    ]
    assert kept == [0, 2]
    # The download: each kept plan run, the call without one skipped.
    assert isinstance(ran, dict)
    assert [(call["status"], call["reason"]) for call in ran["calls"]] == [
        ("ok", None),
        ("skipped", "not_planned"),
        ("ok", None),
    ]
    assert [(file["call"], file["path"]) for file in ran["files"]] == [
        (0, "hydro/150160180/2024.csv"),
        (0, "hydro/150160180/2025.csv"),
        (2, "hydro/901/2024.csv"),
    ]
    assert not (root / "hydro" / "999").exists()


def test_a_call_whose_run_fails_ends_the_download_partial_and_the_next_runs(
    paths: AppPaths, tmp_path: Path
) -> None:
    """999 fetches nothing and is named with its error; the next call still runs."""
    root = store_root(tmp_path)
    params = {"producer": "standin", "calls": station_calls("999", "150160180")}
    with action_supervisor(paths, max_network_jobs=0) as held:
        job = held.submit(
            "download",
            store=STORE,
            params={**params, "plan_job": None},
            actor=LOCAL_OWNER,
        )
        outcome = _run(paths, root, job)

    assert isinstance(outcome, worker.PartialResult)
    summary = outcome.summary
    assert summary["status"] == "partial"
    assert [call["status"] for call in summary["calls"]] == ["failed", "ok"]
    error = summary["calls"][0]["error"]
    assert (error["code"], error["reason"]) == ("source_unavailable", "run_failed")
    assert (summary["calls"][0]["failed"], summary["failed"]) == (4, 4)
    failed = [item for item in summary["items"] if item["status"] == "failed"]
    assert {item["call"] for item in failed} == {0}
    assert {file["call"] for file in summary["files"]} == {1}
    assert summary["counts"] == {"new": 4, "unchanged": 0, "relabeled": 0}


def test_a_download_none_of_whose_calls_succeeded_fails_with_the_first_error(
    paths: AppPaths, tmp_path: Path
) -> None:
    """Every call that ran failed: the job fails as its first call did."""
    params = {"producer": "standin", "calls": station_calls("999", "999")}
    with action_supervisor(paths, max_network_jobs=0) as held:
        job = held.submit(
            "download",
            store=STORE,
            params={**params, "plan_job": None},
            actor=LOCAL_OWNER,
        )
        with pytest.raises(RunFailedError) as failed:
            _run(paths, store_root(tmp_path), job)

    problem = describe(failed.value)
    assert (problem.code, problem.details["reason"]) == (
        "source_unavailable",
        "run_failed",
    )


@pytest.mark.parametrize(
    ("change", "status"),
    [
        ("same", 202),
        ("reordered", 409),
        ("fewer", 409),
        ("more", 409),
        ("other_store", 409),
    ],
)
def test_a_download_runs_only_the_plans_of_a_check_of_the_same_calls(
    paths: AppPaths, tmp_path: Path, change: str, status: int
) -> None:
    """The store, the producer and the calls in their order, else `plan_mismatch`."""
    with _api(paths, max_network_jobs=0) as (owner, jobs):
        # Arrange: a check of three lines, run here.
        checked = owner.request("POST", "/jobs", json=_body("check", *STATIONS)).json()
        check = jobs.get(checked["id"])
        assert check is not None
        _run(paths, store_root(tmp_path), check)
        body = {
            "same": _body("download", *STATIONS),
            "reordered": _body("download", *reversed(STATIONS)),
            "fewer": _body("download", *STATIONS[:2]),
            "more": _body("download", *STATIONS, "150160210"),
            "other_store": _body("download", *STATIONS, store=OTHER_STORE),
        }[change]

        # Act
        answered = owner.request("POST", "/jobs", json={**body, "plan_job": check.id})
        kinds = [job.kind for job in jobs.list().items]

    # Assert
    if status == 202:
        assert answered.status_code == 202, answered.text
        assert kinds == ["download", "check"]
    else:
        assert_problem(answered, 409, "conflict", "plan_mismatch")
        assert answered.json()["details"]["job"] == check.id
        assert kinds == ["check"]


def test_a_cancelled_download_of_a_row_is_retried_and_fetches_only_the_rest(
    paths: AppPaths, tmp_path: Path, standin: ModuleType
) -> None:
    """Stopped after its first file; the retry runs the same calls and plans."""
    root = store_root(tmp_path)
    with _api(paths) as (owner, jobs):
        # Arrange: the plans of three lines; the run waits after its first file.
        checked = owner.request("POST", "/jobs", json=_body("check", *STATIONS)).json()
        jobs.wait(checked["id"], timeout=JOB_TIMEOUT_S)
        (root / standin.HOLD).touch()
        body = _body("download", *STATIONS, plan_job=checked["id"])
        started = owner.request("POST", "/jobs", json=body).json()
        _until_completed(jobs, started["id"])

        # Act
        owner.request("POST", f"/jobs/{started['id']}/cancel")
        cancelled = jobs.wait(started["id"], timeout=JOB_TIMEOUT_S)
        (root / standin.HOLD).unlink()
        fetched = sorted(path.name for path in (root / "hydro").rglob("*.csv"))
        retried = owner.request("POST", f"/jobs/{started['id']}/retry").json()
        again = jobs.wait(retried["id"], timeout=JOB_TIMEOUT_S)

    # Assert: the retry fetched what the cancelled run had not.
    assert cancelled.state == "cancelled"
    assert fetched == ["2024.csv"]
    assert retried["params"] == started["params"]
    assert again.state == "succeeded", again.error
    assert again.result is not None
    assert [(f["call"], f["path"], f["status"]) for f in again.result["files"]] == [
        (
            place,
            f"hydro/{station}/{name}",
            "unchanged" if (place, name) == (0, "2024.csv") else "new",
        )
        for place, station in enumerate(STATIONS)
        for name in TODO
    ]


def test_jobs_start_takes_a_call_per_line_and_names_failed_and_skipped_calls(
    paths: AppPaths,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--call` once per line; the plan names its failed call, the run skips it.

    The text for a person is Polish, the `--json` model English.
    """
    # Arrange: the command's own supervisor starts the stand-in's workers.
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    registry = load_registry(cache_dir=paths.cache_dir)
    given = [
        argument
        for call in station_calls("150160180", "999")
        for argument in ("--call", json.dumps(call))
    ]
    start = ["jobs", "start", "check", "standin", "--store", STORE, *given]

    # Act
    planned = main([*start, "--json"], registry=registry, paths=paths)
    check = json.loads(capsys.readouterr().out)
    shown = main(["jobs", "show", check["id"]], registry=registry, paths=paths)
    plan_text = capsys.readouterr().out.splitlines()
    run = ["jobs", "start", "download", "standin", "--store", STORE, *given]
    downloaded = main([*run, "--plan", check["id"]], registry=registry, paths=paths)
    run_text = capsys.readouterr().out.splitlines()

    # Assert
    root = store_root(tmp_path)
    lines = [
        f"standin series fetch --station {station} --kind hydro --root {root}"
        for station in ("150160180", "999")
    ]
    error = check["result"]["calls"][1]["error"]
    assert (planned, shown, downloaded) == (10, 0, 0)
    assert check["params"]["calls"] == station_calls("150160180", "999")
    assert (error["code"], error["reason"]) == ("source_unavailable", "check_failed")
    assert message("cli.jobs_line", "pl", line=lines[0]) in plan_text
    named = {"place": 2, "count": 2, "line": lines[1]}
    failed = message("cli.jobs_call_failed", "pl", **named, detail=error["detail"])
    assert failed in plan_text
    assert message("cli.jobs_call_not_planned", "pl", **named) in run_text
