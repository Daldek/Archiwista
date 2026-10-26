"""The download job: a run of a producer's command in a store (plan 2026-10-25, A5).

The stand-in producer (``tests/fixtures/actions.py``) fetches a station's
four files into the store it is given (``hydro/<station>/<file>``), keeps a
file the store holds, runs only the positions to download of a plan and
fails a position whose source changed since the plan as stale. While the
store holds ``HOLD`` a run waits after its first new file, so a test can
stop it there. It records the options its ``run_command`` receives. The
index learns the files of a run without a scan of the store. A job of
several calls is ``tests/integration/test_row_jobs.py``.
"""

import io
import json
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths
from archiwista.index import IndexQueries, IndexWriter
from archiwista.jobs import JobSupervisor, worker
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
DOWNLOAD: dict[str, object] = {**CHECK, "plan_job": None}
FOLDER = "hydro/150160180"
FILES = ("2023.csv", "2024.csv", "2025.csv", "stations.json")


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


def _versions(paths: AppPaths) -> int:
    """Return the versions the index holds of the store."""
    with IndexQueries(paths.index_file) as queries:
        (state,) = [item for item in queries.status().stores if item.store == STORE]
    return state.versions


def _until_completed(jobs: JobSupervisor, job_id: str) -> None:
    """Wait until the job reported its first file done."""
    deadline = time.monotonic() + JOB_TIMEOUT_S
    while time.monotonic() < deadline:
        events = jobs.events(job_id)
        if any(e.data.get("status") == "completed" for e in events):
            return
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} reported no file")


def _checked(paths: AppPaths, root: Path, jobs: JobSupervisor) -> str:
    """Plan the station's files in a ``check`` job of this process; its id."""
    job = jobs.submit("check", store=STORE, params=CHECK, actor=LOCAL_OWNER)
    spec = action_spec(paths, root, job.id, "check", job.params)
    worker.run_check(spec, worker.Emitter(io.StringIO()))
    return job.id


def test_a_run_writes_the_store_and_the_index_shows_its_versions_at_once(
    paths: AppPaths, tmp_path: Path
) -> None:
    """Progress and notices are events; no scan of the store is needed."""
    with action_supervisor(paths) as jobs:
        job = jobs.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
        record = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
        events = jobs.events(job.id)

    assert (record.state, record.error) == ("succeeded", None)
    assert record.result is not None
    assert record.result["counts"] == {"new": 4, "unchanged": 0, "relabeled": 0}
    assert [file["path"] for file in record.result["files"]] == [
        f"{FOLDER}/{name}" for name in FILES
    ]
    assert (record.result["status"], record.result["rescanned"]) == ("ok", 1)
    assert sorted(path.name for path in (store_root(tmp_path) / FOLDER).iterdir()) == [
        *sorted(FILES)
    ]
    progress = [e.data for e in events if e.type == "progress"]
    assert [(p["current"], p["total"], p["unit"], p["status"]) for p in progress] == [
        (done, 4, "150160180", "completed") for done in range(1, 5)
    ]
    notices = [e.data["code"] for e in events if e.type == "notice"]
    assert notices == ["run_done"]
    assert _versions(paths) == 4


def test_a_kept_plan_runs_with_the_store_root_and_no_plain_target(
    paths: AppPaths, tmp_path: Path, held: JobSupervisor, standin: ModuleType
) -> None:
    """The producer gets the store's directory and the plan the check kept.

    Only the plan's positions to download are fetched: the newer and the
    missing file; the current and the unverifiable one stay as they are.
    """
    root = store_root(tmp_path)
    plan_job = _checked(paths, root, held)
    params = {**CHECK, "plan_job": plan_job}
    job = held.submit("download", store=STORE, params=params, actor=LOCAL_OWNER)
    with IndexQueries(paths.index_file) as queries:
        (stored,) = queries.plans(plan_job)

    summary = worker.run_download(
        action_spec(paths, root, job.id, "download", job.params),
        worker.Emitter(io.StringIO()),
    )

    (call,) = [call for call in standin.CALLS if call[0] == "run_command"]
    assert call == (
        "run_command",
        "series fetch",
        {**STATION, "root": str(root), "plan": stored.plan.document},
    )
    assert isinstance(summary, dict)
    assert [(f["path"], f["status"]) for f in summary["files"]] == [
        (f"{FOLDER}/2024.csv", "new"),
        (f"{FOLDER}/2025.csv", "new"),
    ]
    assert summary["plan_job"] == plan_job
    assert _versions(paths) == 2


def test_a_position_changed_since_the_plan_is_stale_and_the_job_ends_partial(
    paths: AppPaths, tmp_path: Path, held: JobSupervisor
) -> None:
    """The source's newer file is not the plan's: ``conflict``, ``stale_plan``."""
    root = store_root(tmp_path)
    plan_job = _checked(paths, root, held)
    with IndexQueries(paths.index_file) as queries:
        (stored,) = queries.plans(plan_job)
    document = json.loads(json.dumps(stored.plan.document))
    document["items"][1]["source"] = "2024-11-30"
    with IndexWriter(paths.index_file) as writer:
        writer.write_plans(
            [replace(stored, plan=replace(stored.plan, document=document))]
        )
    params = {**CHECK, "plan_job": plan_job}
    job = held.submit("download", store=STORE, params=params, actor=LOCAL_OWNER)

    outcome = worker.run_download(
        action_spec(paths, root, job.id, "download", job.params),
        worker.Emitter(io.StringIO()),
    )

    assert isinstance(outcome, worker.PartialResult)
    assert outcome.summary["status"] == "partial"
    assert outcome.summary["items"] == [
        {
            "id": f"{FOLDER}/2024.csv",
            "status": "failed",
            "code": "conflict",
            "reason": "stale_plan",
            "message": "The source changed since the plan was made: make a new plan.",
            "call": 0,
        },
        {
            "id": f"{FOLDER}/2025.csv",
            "status": "ok",
            "code": None,
            "reason": None,
            "message": None,
            "call": 0,
        },
    ]
    assert outcome.summary["calls"][0]["status"] == "partial"
    assert [f["path"] for f in outcome.summary["files"]] == [f"{FOLDER}/2025.csv"]


def test_a_cancelled_run_ends_cancelled_with_its_files_in_the_index(
    paths: AppPaths, tmp_path: Path, standin: ModuleType
) -> None:
    """The slots of the units the run named are read again when it stops."""
    root = store_root(tmp_path)
    (root / standin.HOLD).touch()

    with action_supervisor(paths) as jobs:
        job = jobs.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
        _until_completed(jobs, job.id)
        jobs.cancel(job.id)
        record = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
        notices = [e.data["code"] for e in jobs.events(job.id) if e.type == "notice"]

    assert record.state == "cancelled"
    assert [path.name for path in (root / FOLDER).iterdir()] == ["2023.csv"]
    assert notices == []
    assert _versions(paths) == 1


def test_a_run_a_stopped_server_interrupted_is_finished_by_the_same_job_again(
    paths: AppPaths, tmp_path: Path, standin: ModuleType
) -> None:
    """``interrupted``; a new job of the same parameters fetches only the rest."""
    root = store_root(tmp_path)
    hold = root / standin.HOLD
    hold.touch()
    with action_supervisor(paths) as jobs:
        first = jobs.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
        _until_completed(jobs, first.id)
    hold.unlink()

    with action_supervisor(paths) as jobs:
        stopped = jobs.get(first.id)
        again = jobs.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
        record = jobs.wait(again.id, timeout=JOB_TIMEOUT_S)

    assert stopped is not None
    assert stopped.state == "interrupted"
    assert record.state == "succeeded", record.error
    assert record.result is not None
    assert [(f["path"], f["status"]) for f in record.result["files"]] == [
        (f"{FOLDER}/2023.csv", "unchanged"),
        (f"{FOLDER}/2024.csv", "new"),
        (f"{FOLDER}/2025.csv", "new"),
        (f"{FOLDER}/stations.json", "new"),
    ]
    assert _versions(paths) == 4


def test_a_download_of_the_call_an_active_download_runs_starts_with_a_warning(
    held: JobSupervisor,
) -> None:
    """The same store and call: a notice naming the job; another call: none."""
    first = held.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
    second = held.submit("download", store=STORE, params=DOWNLOAD, actor=LOCAL_OWNER)
    other = {**DOWNLOAD, "calls": station_calls("150160190")}
    third = held.submit("download", store=STORE, params=other, actor=LOCAL_OWNER)

    notices = {
        job.id: [e.data for e in held.events(job.id) if e.type == "notice"]
        for job in (first, second, third)
    }

    assert notices[first.id] == notices[third.id] == []
    (notice,) = notices[second.id]
    assert (notice["level"], notice["code"], notice["job"]) == (
        "warning",
        "overlapping_job",
        first.id,
    )
    assert first.id in notice["message"]
    assert held.get(second.id) is not None


@pytest.mark.parametrize(
    "params",
    [
        {**DOWNLOAD, "plan_job": ""},
        {**DOWNLOAD, "plan_job": 7},
        {**DOWNLOAD, "output_dir": "/srv/plain"},
        {key: value for key, value in DOWNLOAD.items() if key != "calls"},
    ],
)
def test_invalid_download_parameters_are_refused_before_a_job_exists(
    held: JobSupervisor, params: dict[str, object]
) -> None:
    """A plan job is a job id or none; a target beside the store is no parameter."""
    with pytest.raises(ValueError):
        held.submit("download", store=STORE, params=params, actor=LOCAL_OWNER)

    assert held.list().items == ()
