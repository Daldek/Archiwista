"""The shared queue: no position downloaded twice (plan v0.4 T9, ADR-047 decision 2).

Two people plan downloads of overlapping stations with the stand-in producer
(``tests/fixtures/actions.py``): each station's plan has two positions to
download (``2024.csv`` newer, ``2025.csv`` missing). A planned download claims
its positions when it starts (``job_claims``), so a second one leaves the
first one's positions out and reports them ``taken``. The stand-in waits after
its first new file while the store holds ``HOLD``, and appends each transfer to
``FETCHES``: with a plan it transfers every position it runs, so a position run
by two jobs shows twice there.
"""

import io
import json
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import ALL_PROJECTS, Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppPaths, ConfigStore
from archiwista.index import IndexQueries, IndexWriter
from archiwista.index.schema import connect, initialize
from archiwista.jobs import JobRecord, JobSupervisor, worker
from archiwista.services import jobs as job_controls
from archiwista.state import StateStore
from tests.fixtures.actions import (
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
FIRST, SHARED, OWN = "150160180", "150160190", "150160200"
MAREK = Principal("marek", "user", frozenset({"store_writer"}), frozenset(), "s-marek")
ANNA = Principal("anna", "user", frozenset({"store_writer"}), frozenset(), "s-anna")


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
def jobs(paths: AppPaths) -> Iterator[JobSupervisor]:
    """Yield a started supervisor of real workers."""
    with action_supervisor(paths) as supervisor:
        yield supervisor


def _todo(*stations: str) -> list[str]:
    """Return the positions to download of the stations' plans, in plan order."""
    return [f"hydro/{s}/{name}" for s in stations for name in ("2024.csv", "2025.csv")]


def _params(*stations: str, plan_job: str | None) -> dict[str, object]:
    """Return the parameters of a download of the stations' files."""
    calls = station_calls(*stations)
    return {"producer": "standin", "calls": calls, "plan_job": plan_job}


def _planned(jobs: JobSupervisor, person: Principal, *stations: str) -> str:
    """Plan the stations' files in a ``check`` job of ``person``; its id."""
    params = {"producer": "standin", "calls": station_calls(*stations)}
    job = jobs.submit("check", store=STORE, params=params, actor=person)
    record = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
    assert record.state == "succeeded", record.error
    return job.id


def _download(
    jobs: JobSupervisor, person: Principal, *stations: str, plan_job: str | None
) -> JobRecord:
    """Submit a download of the stations' files by ``person``."""
    params = _params(*stations, plan_job=plan_job)
    return jobs.submit("download", store=STORE, params=params, actor=person)


def _until_completed(jobs: JobSupervisor, job_id: str) -> None:
    """Wait until the job reported a new file: it waits on ``HOLD`` after it."""
    deadline = time.monotonic() + JOB_TIMEOUT_S
    while time.monotonic() < deadline:
        if any(e.data.get("status") == "completed" for e in jobs.events(job_id)):
            return
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} reported no file")


def _ended(jobs: JobSupervisor, *job_ids: str) -> list[JobRecord]:
    """Wait for the jobs to end; return them in their order."""
    return [jobs.wait(job_id, timeout=JOB_TIMEOUT_S) for job_id in job_ids]


def _fetches(root: Path, standin: ModuleType) -> list[str]:
    """Return the paths the stand-in transferred, in sorted order."""
    return sorted((root / standin.FETCHES).read_text(encoding="utf-8").splitlines())


def _claims(paths: AppPaths) -> list[tuple[str, ...]]:
    """Return every claim of a position: job, store, path and unit."""
    connection = sqlite3.connect(paths.index_file)
    try:
        rows = connection.execute(
            "SELECT job_id, store, path, unit FROM job_claims ORDER BY path"
        ).fetchall()
    finally:
        connection.close()
    return [tuple(row) for row in rows]


def _notices(jobs: JobSupervisor, job_id: str) -> list[dict[str, object]]:
    """Return the data of a job's notices, in their order."""
    return [event.data for event in jobs.events(job_id) if event.type == "notice"]


def test_a_second_download_leaves_the_positions_of_the_first_and_names_its_person(
    tmp_path: Path, paths: AppPaths, jobs: JobSupervisor, standin: ModuleType
) -> None:
    """Marek's held download claims the shared station; Anna's fetches her own.

    Each position is transferred once; Anna's call of the shared station is
    skipped, its positions ``taken`` by Marek's job, and her job ends
    ``partial``: a retry fetches what his job may fail.
    """
    root = store_root(tmp_path)
    marek_plan = _planned(jobs, MAREK, FIRST, SHARED)
    anna_plan = _planned(jobs, ANNA, SHARED, OWN)
    (root / standin.HOLD).touch()

    first = _download(jobs, MAREK, FIRST, SHARED, plan_job=marek_plan)
    _until_completed(jobs, first.id)
    second = _download(jobs, ANNA, SHARED, OWN, plan_job=anna_plan)
    _until_completed(jobs, second.id)
    held = _claims(paths)
    (root / standin.HOLD).unlink()
    marek, anna = _ended(jobs, first.id, second.id)

    assert held == sorted(
        [(first.id, STORE, path, path.split("/")[1]) for path in _todo(FIRST, SHARED)]
        + [(second.id, STORE, path, OWN) for path in _todo(OWN)],
        key=lambda claim: claim[2],
    )
    assert marek.state == "succeeded", marek.error
    assert marek.result is not None
    assert [(f["path"], f["status"]) for f in marek.result["files"]] == [
        (path, "new") for path in _todo(FIRST, SHARED)
    ]
    assert marek.result["taken"] == []
    assert anna.state == "partial", anna.error
    assert anna.result is not None
    assert [(f["path"], f["status"]) for f in anna.result["files"]] == [
        (path, "new") for path in _todo(OWN)
    ]
    assert anna.result["taken"] == [
        {"path": path, "unit": SHARED, "job": first.id, "actor": "marek"}
        for path in _todo(SHARED)
    ]
    assert [(c["status"], c["reason"]) for c in anna.result["calls"]] == [
        ("skipped", "taken"),
        ("ok", None),
    ]
    (notice,) = [n for n in _notices(jobs, second.id) if n["code"] == "taken_by_job"]
    assert notice["level"] == "info"
    assert "marek" in str(notice["message"]) and first.id in str(notice["message"])
    assert _fetches(root, standin) == sorted(_todo(FIRST, SHARED, OWN))
    assert _claims(paths) == []


def test_a_retry_fetches_a_taken_position_the_other_job_failed(
    tmp_path: Path, paths: AppPaths, jobs: JobSupervisor, standin: ModuleType
) -> None:
    """Marek's job fails a shared file; Anna's retry claims and fetches it."""
    root = store_root(tmp_path)
    marek_plan = _planned(jobs, MAREK, FIRST, SHARED)
    anna_plan = _planned(jobs, ANNA, SHARED, OWN)
    with IndexQueries(paths.index_file) as queries:
        stored = queries.plans(marek_plan)[1]
    document = json.loads(json.dumps(stored.plan.document))
    document["items"][2]["source"] = "2025-10-01"
    with IndexWriter(paths.index_file) as writer:
        writer.write_plans(
            [replace(stored, plan=replace(stored.plan, document=document))]
        )
    (root / standin.HOLD).touch()
    first = _download(jobs, MAREK, FIRST, SHARED, plan_job=marek_plan)
    _until_completed(jobs, first.id)
    second = _download(jobs, ANNA, SHARED, OWN, plan_job=anna_plan)
    _until_completed(jobs, second.id)
    (root / standin.HOLD).unlink()
    marek, anna = _ended(jobs, first.id, second.id)
    decisions = Authorizer(
        StateStore(paths.state_file), ConfigStore(paths.config_file).load
    )

    with IndexQueries(paths.index_file) as queries:
        again = job_controls.retry(
            jobs,
            decisions,
            queries,
            ConfigStore(paths.config_file).load(),
            job_id=second.id,
            actor=ANNA,
            visible=ALL_PROJECTS,
        )
    (retried,) = _ended(jobs, again.id)

    failed = f"hydro/{SHARED}/2025.csv"
    assert marek.state == "partial"
    assert marek.result is not None
    assert [i["id"] for i in marek.result["items"] if i["status"] == "failed"] == [
        failed
    ]
    assert anna.state == "partial"
    assert anna.result is not None
    assert [item["path"] for item in anna.result["taken"]] == _todo(SHARED)
    assert retried.state == "succeeded", retried.error
    assert retried.result is not None
    assert retried.result["taken"] == []
    assert [f["path"] for f in retried.result["files"] if f["status"] == "new"] == [
        failed
    ]
    assert _fetches(root, standin).count(failed) == 1
    assert _claims(paths) == []


def test_claims_of_jobs_no_longer_active_are_cleared_when_a_supervisor_starts(
    paths: AppPaths,
) -> None:
    """A finished job's claim and a claim of a stopped server's job both go.

    The running job of a process that is gone (no owner lock) ends
    ``interrupted`` and its claim goes with it.
    """
    initialize(paths.index_file)
    connection = connect(paths.index_file)
    for job_id, state in (("left", "running"), ("ended", "succeeded")):
        connection.execute(
            "INSERT INTO jobs (id, kind, actor, actor_kind, store, params, state,"
            " created_at, pid) VALUES (?, 'download', 'marek', 'user', ?, '{}', ?,"
            " '2026-10-26T08:00:00+00:00', 999999)",
            (job_id, STORE, state),
        )
        connection.execute(
            "INSERT INTO job_claims (job_id, store, path, unit) VALUES (?, ?, ?, ?)",
            (job_id, STORE, f"hydro/{job_id}/2025.csv", job_id),
        )
    connection.close()

    with action_supervisor(paths) as jobs:
        left = jobs.get("left")

    assert left is not None
    assert left.state == "interrupted"
    assert _claims(paths) == []


def test_an_unplanned_download_of_a_running_call_waits_then_finds_its_files(
    tmp_path: Path, jobs: JobSupervisor, standin: ModuleType
) -> None:
    """It stays queued with one notice naming the running job; nothing twice.

    A download of another call starts at once beside them.
    """
    root = store_root(tmp_path)
    (root / standin.HOLD).touch()
    first = _download(jobs, MAREK, FIRST, plan_job=None)
    _until_completed(jobs, first.id)
    second = _download(jobs, ANNA, FIRST, plan_job=None)
    queued = jobs.get(second.id)
    (root / standin.HOLD).unlink()
    other = _download(jobs, ANNA, OWN, plan_job=None)
    marek, anna, own = _ended(jobs, first.id, second.id, other.id)

    assert queued is not None
    assert queued.state == "queued"
    assert [(n["code"], n.get("job")) for n in _notices(jobs, second.id)] == [
        ("overlapping_job", first.id),
        ("waiting_for_job", first.id),
        ("run_done", None),
    ]
    assert [n["code"] for n in _notices(jobs, other.id)] == ["run_done"]
    assert marek.state == anna.state == own.state == "succeeded"
    assert anna.started_at is not None and marek.finished_at is not None
    assert anna.started_at >= marek.finished_at
    assert anna.result is not None
    assert {f["status"] for f in anna.result["files"]} == {"unchanged"}
    files = ("2023.csv", "2024.csv", "2025.csv", "stations.json")
    assert _fetches(root, standin) == sorted(
        f"hydro/{station}/{name}" for station in (FIRST, OWN) for name in files
    )


def test_the_producer_runs_only_the_claimed_positions_of_a_plan(
    tmp_path: Path, paths: AppPaths, standin: ModuleType
) -> None:
    """The plan ``run_command`` receives keeps the claimed positions to download.

    The positions a run does not download stay; a call whose positions to
    download are all taken is not run at all; the job ends ``partial`` with
    the positions taken and one notice per holder.
    """
    root = store_root(tmp_path)
    with action_supervisor(paths, max_network_jobs=0) as held:
        params = {"producer": "standin", "calls": station_calls(SHARED, OWN)}
        check = held.submit("check", store=STORE, params=params, actor=ANNA)
        worker.run_check(
            action_spec(paths, root, check.id, "check", check.params),
            worker.Emitter(io.StringIO()),
        )
        job = _download(held, ANNA, SHARED, OWN, plan_job=check.id)
    taken = tuple(
        {"path": path, "unit": path.split("/")[1], "job": "0f1e2d3c", "actor": "marek"}
        for path in [*_todo(SHARED), f"hydro/{OWN}/2024.csv"]
    )
    claimed = (f"hydro/{OWN}/2025.csv",)
    spec = replace(
        action_spec(paths, root, job.id, "download", job.params),
        claimed=claimed,
        taken=taken,
    )
    standin.CALLS.clear()
    said = io.StringIO()

    outcome = worker.run_download(spec, worker.Emitter(said))

    (run,) = [call for call in standin.CALLS if call[0] == "run_command"]
    plan = run[2]["plan"]
    assert isinstance(plan, dict)
    assert [(item["file"], item["status"]) for item in plan["items"]] == [
        (f"hydro/{OWN}/2023.csv", "current"),
        (f"hydro/{OWN}/2025.csv", "missing"),
        (f"hydro/{OWN}/stations.json", "unverifiable"),
    ]
    assert isinstance(outcome, worker.PartialResult)
    assert [f["path"] for f in outcome.summary["files"]] == list(claimed)
    assert outcome.summary["taken"] == list(taken)
    notices = [
        json.loads(line)["data"]
        for line in said.getvalue().splitlines()
        if json.loads(line)["type"] == "notice"
    ]
    assert [n["code"] for n in notices][0] == "taken_by_job"
    assert "(3)" in notices[0]["message"] and "0f1e2d3c" in notices[0]["message"]
