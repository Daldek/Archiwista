"""Background jobs in worker processes (plan step 6b).

Every test runs real worker processes (``tests.fixtures.job_worker``: the
real worker with hooks for slow scans, crashes and a refused network) on a
generated Kartograf store, offline.
"""

import hashlib
import io
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kartograf import BBox

from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER, SCHEDULER, Principal
from archiwista.config import AppPaths, ConfigStore, SettingsService, StoreConfig
from archiwista.errors import (
    IndexQueryError,
    JobConflictError,
    NotFoundError,
    OfflineModeError,
)
from archiwista.index import IndexQueries, own_file_id
from archiwista.jobs import JobEvent, JobRecord, JobSupervisor, ScanScheduler
from archiwista.jobs.foreground import run_foreground
from archiwista.jobs.protocol import decode_message
from archiwista.jobs.reindex import reindex_main
from archiwista.messages import label, message
from archiwista.previews.cache import COG_NAME, PreviewCache, cache_key
from archiwista.previews.types import PreviewSource
from archiwista.sources.registry import load_registry
from tests.fixtures.cli_errors import refusal
from tests.fixtures.job_worker import (
    BUILD_PROCESSES_ENV,
    BUILD_TIMEOUT_ENV,
    PREVIEW_SOURCES_ENV,
)
from tests.fixtures.jobs import (
    CRASH_ENV,
    DELAY_ENV,
    NO_NETWORK_ENV,
    SLOW_ENTRY_S,
    STORE,
    TEST_WORKER,
    JobsEnv,
    jobs_env,
    store_settings,
    worker_path,
)
from tests.fixtures.local_server import NoSources, serving
from tests.fixtures.make_store import ExpectedEntry, make_store
from tests.fixtures.store_edits import add_version, remove_version, sidecar_path

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WAIT_S = 60.0


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[JobsEnv]:
    """Yield a fresh store with a started supervisor of test workers."""
    with jobs_env(tmp_path, monkeypatch) as created:
        yield created


def test_worker_protocol_maps_to_sse_events(env: JobsEnv) -> None:
    """Worker lines become numbered job events; the last state carries the result."""
    # Arrange
    heard: list[JobEvent] = []
    env.jobs.subscribe(heard.append)

    # Act
    record = env.run("scan", mode="full")
    stored = env.jobs.events(record.id)
    tail = env.jobs.events(record.id, after=3)

    # Assert
    assert record.state == "succeeded" and record.result is not None
    assert heard == list(stored)
    assert [event.seq for event in stored] == list(range(1, len(stored) + 1))
    assert {event.type for event in stored} == {"state", "progress"}
    states = [event.data for event in stored if event.type == "state"]
    assert states == [
        {"state": "queued"},
        {"state": "running"},
        {"state": "succeeded", "result": record.result},
    ]
    progress = [event.data for event in stored if event.type == "progress"]
    segments = len(record.result["segments"])
    assert progress[0] == {
        "current": 0,
        "total": segments,
        "segment": None,
        "entries": 0,
    }
    assert [item["current"] for item in progress] == list(range(segments + 1))
    assert record.progress == progress[-1]
    assert record.result["entries"] == progress[-1]["entries"] > 0
    assert (record.result["store"], record.result["mode"]) == (STORE, "full")
    assert tail == stored[3:]
    status = env.state()
    assert status.last_scan is not None and status.last_scan.id == record.id
    assert status.last_scan.progress == (segments, segments)
    assert status.running_job is None


def test_second_index_job_for_store_conflicts(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a scan writes the index, another scan or footprints job conflicts."""
    # Arrange
    env.scan("full")
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    running = env.jobs.submit("scan", store=STORE, actor=LOCAL_OWNER)
    env.follow(running.id, _after_first_segment)
    link = env.store.by_kind("link")[0].path

    # Act
    conflicts = []
    for kind in ("scan", "footprints"):
        with pytest.raises(JobConflictError) as raised:
            env.jobs.submit(kind, store=STORE, actor=LOCAL_OWNER)
        conflicts.append(raised.value)
    check = env.run("link_check", slot=link)
    env.jobs.cancel(running.id)
    ended = env.wait(running.id)
    monkeypatch.delenv(DELAY_ENV)
    after = env.run("scan")

    # Assert
    assert [(c.job_id, c.kind, c.state) for c in conflicts] == [
        (running.id, "scan", "running")
    ] * 2
    assert all(STORE in str(c) and running.id in str(c) for c in conflicts)
    assert env.jobs.list(kind="footprints").items == ()
    assert check.state == "succeeded"
    assert ended.state == "cancelled"
    assert after.state == "succeeded"


def test_cancelled_scan_leaves_no_partial_state(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled scan abandons its pass: a vanished version is not marked."""
    # Arrange
    env.scan("full")
    gone = next(
        entry
        for entry in env.store.by_kind("version")
        if not entry.current and entry.case == "regular"
    )
    remove_version(env.store.root, gone.path)
    before = env.rows()
    indexed = env.state()
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    job = env.jobs.submit(
        "scan", store=STORE, params={"mode": "full"}, actor=LOCAL_OWNER
    )
    env.follow(job.id, _after_first_segment)

    # Act
    env.jobs.cancel(job.id)
    cancelled = env.wait(job.id)
    after = env.rows()
    state = env.state()
    monkeypatch.delenv(DELAY_ENV)
    rescan = env.scan("full")

    # Assert
    assert cancelled.state == "cancelled"
    assert cancelled.error is not None and cancelled.error.code == "cancelled"
    assert cancelled.finished_at is not None and cancelled.result is None
    assert after == before
    assert (state.status, state.indexed_at) == ("available", indexed.indexed_at)
    assert state.missing_versions == 0
    assert rescan.result is not None and rescan.result["missing"] == 1


def test_worker_crash_fails_job(env: JobsEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """A worker killed mid-scan fails its job; the index and later scans are fine."""
    # Arrange
    env.scan("full")
    before = env.rows()
    monkeypatch.setenv(CRASH_ENV, "5")

    # Act
    crashed = env.run("scan", mode="full")
    after = env.rows()
    monkeypatch.delenv(CRASH_ENV)
    rescan = env.scan("incremental")

    # Assert
    assert crashed.state == "failed"
    assert crashed.error is not None
    assert (crashed.error.code, crashed.error.reason) == (
        "internal_error",
        "worker_crashed",
    )
    assert "SIGKILL" in crashed.error.detail
    assert f"{crashed.id}.log" in crashed.error.detail
    assert after == before
    assert env.state().status == "available"
    assert rescan.result is not None and rescan.result["missing"] == 0


def test_close_interrupts_running_and_waiting_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A waiting job cancels at once; stopping interrupts running and waiting ones."""
    # Arrange
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    with jobs_env(tmp_path, monkeypatch, max_jobs=1) as env:
        running = env.jobs.submit("scan", store=STORE, actor=LOCAL_OWNER)
        link = {"slot": env.store.by_kind("link")[0].path}
        waiting = env.jobs.submit(
            "link_check", store=STORE, params=link, actor=LOCAL_OWNER
        )
        dropped = env.jobs.submit(
            "link_check", store=STORE, params=link, actor=LOCAL_OWNER
        )
        env.follow(running.id, lambda event: event.type == "progress")

        # Act
        cancelled = env.jobs.cancel(dropped.id)
        env.jobs.close()
        with JobSupervisor(env.paths, env.settings) as reader:
            records = {job.id: job for job in reader.list().items}

    # Assert
    assert (waiting.state, dropped.state) == ("queued", "queued")
    assert cancelled.state == "cancelled"
    assert [records[job.id].state for job in (running, waiting, dropped)] == [
        "interrupted",
        "interrupted",
        "cancelled",
    ]
    error = records[running.id].error
    assert error is not None
    assert (error.code, error.reason, error.detail) == (
        "cancelled",
        "interrupted",
        message("job.interrupted_stop"),
    )


def test_restart_marks_running_job_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A job of a server that died is interrupted; its worker stops by itself."""
    # Arrange
    worker_path(monkeypatch)
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    store = make_store(tmp_path / "store", slots=24, seed=7)
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    ConfigStore(paths.config_file).save(store_settings(store))
    with subprocess.Popen(
        [
            sys.executable,
            "-m",
            "tests.fixtures.job_owner",
            str(paths.config_file),
            str(paths.data_dir),
            STORE,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as owner:
        assert owner.stdout is not None
        job_id = owner.stdout.readline().strip()
        settings = SettingsService(ConfigStore(paths.config_file), NoSources())
        with JobSupervisor(paths, settings) as jobs:
            _await(lambda: _progressed(jobs, job_id))
            alive = jobs.get(job_id)
            worker = _worker_pid(paths, job_id)

            # Act
            owner.kill()
            owner.wait()
            _await(lambda: not _running(worker))
            recovered = jobs.recover()
            record = jobs.get(job_id)

    # Assert
    assert alive is not None and alive.state == "running"
    assert recovered == 1
    assert record is not None and record.state == "interrupted"
    assert record.error is not None
    assert (record.error.code, record.error.reason, record.error.detail) == (
        "cancelled",
        "interrupted",
        message("job.interrupted_restart"),
    )
    assert record.finished_at is not None
    with IndexQueries(paths.index_file) as queries:
        state = next(s for s in queries.status().stores if s.store == STORE)
    assert (state.missing_versions, state.indexed_at) == (0, None)


def test_jobs_record_actor(env: JobsEnv) -> None:
    """Each job keeps who asked for it, also as the store's last scan."""
    # Arrange
    link = env.store.by_kind("link")[0].path

    # Act
    agent = Principal(
        id="ada",
        kind="agent",
        roles=frozenset(),
        groups=frozenset(),
        session="5b2d4c60",
    )
    scan = env.run("scan", actor=agent)
    check = env.run("link_check", actor=LOCAL_OWNER, slot=link)
    listed = env.jobs.list(store=STORE)

    # Assert
    assert (scan.actor, scan.actor_kind, scan.session) == ("ada", "agent", "5b2d4c60")
    assert (check.actor, check.actor_kind, check.session) == (
        "local",
        "local_owner",
        None,
    )
    assert [(job.id, job.actor) for job in listed.items] == [
        (check.id, "local"),
        (scan.id, "ada"),
    ]
    last = env.state().last_scan
    assert last is not None and (last.id, last.actor) == (scan.id, "ada")


def test_footprints_job_assigns_cached_unit_outlines(
    env: JobsEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unit outlines put in the local memory after a scan reach their versions."""
    # Arrange
    network = tmp_path / "network.log"
    monkeypatch.setenv(NO_NETWORK_ENV, str(network))
    env.scan("full")
    entries = {entry.path: entry for entry in env.store.entries}
    keys = {
        path: _unit_key(entries[path])
        for path in (
            item.relative_path.as_posix()
            for item in env.queries.entries_without_footprint(STORE)
        )
    }
    cache = UnitBBoxCache(env.paths.cache_dir / "kartograf" / "unit_bboxes.sqlite")
    for kind, code in set(keys.values()):
        cache[(kind, code)] = _unit_box(kind)
    cache.close()

    # Act
    record = env.run("footprints")

    # Assert
    assert {kind for kind, _ in keys.values()} == {"teryt", "ku"}
    assert record.state == "succeeded" and record.result is not None
    assert {name: record.result[name] for name in ("total", "written", "failed")} == {
        "total": len(keys),
        "written": len(keys),
        "failed": 0,
    }
    for path in keys:
        version = env.queries.version(STORE, path, visible=ALL_PROJECTS)
        assert version is not None
        location = version.summary.location
        assert (location.kind, location.source) == ("footprint", "unit")
    assert env.queries.entries_without_footprint(STORE) == ()
    assert not network.exists()


def test_footprints_job_refused_offline(env: JobsEnv) -> None:
    """In offline mode the footprints job is refused before it is recorded."""
    # Arrange
    env.settings.update(env.settings.get().model_copy(update={"offline": True}))

    # Act
    with pytest.raises(OfflineModeError) as raised:
        env.jobs.submit("footprints", store=STORE, actor=LOCAL_OWNER)

    # Assert
    assert str(raised.value) == message("job.offline_mode")
    assert env.jobs.list().items == ()


def test_link_check_reports_mismatch(env: JobsEnv) -> None:
    """A link holding another version than its sidecar names becomes a problem."""
    # Arrange
    env.scan("full")
    mismatch = next(
        entry for entry in env.store.by_case("link_mismatch") if entry.kind == "link"
    )
    regular = next(
        entry for entry in env.store.by_kind("link") if entry.case == "regular"
    )

    # Act
    found = env.run("link_check", slot=mismatch.path)
    fine = env.run("link_check", slot=regular.path)
    notices = [
        event.data for event in env.jobs.events(found.id) if event.type == "notice"
    ]
    env.scan("full")
    issues = [
        (issue.code, issue.origin)
        for issue in env.queries.issues(STORE)
        if issue.path == mismatch.path
    ]

    # Assert
    assert found.result == {
        "store": STORE,
        "slot": mismatch.path,
        "expected": mismatch.version_path,
        "confirmed": None,
        "status": "mismatch",
    }
    assert [notice["code"] for notice in notices] == ["link_mismatch"]
    assert mismatch.path in notices[0]["message"]
    assert fine.result is not None
    assert (fine.result["status"], fine.result["confirmed"]) == (
        "confirmed",
        regular.version_path,
    )
    assert issues == [("link_mismatch", "check")]


def test_reindex_runs_full_scan_in_foreground(env: JobsEnv) -> None:
    """``archiwista reindex`` records a full scan by ``local`` and reports it."""
    # Arrange
    out = io.StringIO()
    err = io.StringIO()

    # Act
    status = reindex_main(env.paths, NoSources(), out, err, worker_command=TEST_WORKER)

    # Assert
    assert status == 0, err.getvalue()
    job = env.jobs.list(kind="scan").items[0]
    assert (job.state, job.actor, job.params) == (
        "succeeded",
        "local",
        {"mode": "full", "segment": None},
    )
    assert f"„{STORE}”: pełny skan zakończony" in out.getvalue()
    assert job.id in err.getvalue()


def test_reindex_conflict_exits_nonzero(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A running index job of the store makes ``reindex`` fail with ``conflict``."""
    # Arrange
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    running = env.jobs.submit("scan", store=STORE, actor=LOCAL_OWNER)
    env.follow(running.id, lambda event: event.type == "progress")
    out, err = io.StringIO(), io.StringIO()

    # Act
    status = reindex_main(env.paths, NoSources(), out, err, store=STORE)
    env.jobs.cancel(running.id)

    # Assert
    document = refusal(out.getvalue(), err.getvalue(), status)
    assert (status, document["code"]) == (4, "conflict")
    assert document["details"]["job"]["id"] == running.id
    assert [job.id for job in env.jobs.list(kind="scan").items] == [running.id]


def test_reindex_unknown_store(env: JobsEnv) -> None:
    """An unknown store is an argument error; nothing is recorded."""
    out, err = io.StringIO(), io.StringIO()

    status = reindex_main(env.paths, NoSources(), out, err, store="brak")

    document = refusal(out.getvalue(), err.getvalue(), status)
    assert (status, document["code"]) == (3, "not_found")
    assert document["details"]["reason"] == "unknown_store"
    assert err.getvalue().splitlines()[0] == message("job.store_unknown", store="brak")
    assert env.jobs.list().items == ()


def test_reindex_on_foreground_helper(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ctrl+C in ``reindex`` cancels its scan, which abandons its pass.

    The scan runs on ``jobs/foreground.py``: its progress reaches standard
    error, Ctrl+C (pressed here while ``wait`` follows the scan) cancels it
    and waits for its end, and ``reindex`` exits 130 with the job's state; a
    version gone since the last scan is not marked missing.
    """
    # Arrange
    env.scan("full")
    gone = next(
        entry
        for entry in env.store.by_kind("version")
        if not entry.current and entry.case == "regular"
    )
    remove_version(env.store.root, gone.path)
    before = env.rows()
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    wait = JobSupervisor.wait
    pressed: list[str] = []

    def ctrl_c(
        self: JobSupervisor, job_id: str, timeout: float | None = None
    ) -> JobRecord:
        if pressed:
            return wait(self, job_id, timeout)
        pressed.append(job_id)
        env.follow(job_id, _after_first_segment)
        raise KeyboardInterrupt

    monkeypatch.setattr(JobSupervisor, "wait", ctrl_c)
    out = io.StringIO()
    err = io.StringIO()

    # Act
    status = reindex_main(
        env.paths, NoSources(), out, err, store=STORE, worker_command=TEST_WORKER
    )
    monkeypatch.setattr(JobSupervisor, "wait", wait)
    record = env.jobs.get(pressed[0])

    # Assert
    assert status == 130 and out.getvalue() == ""
    assert record is not None and record.state == "cancelled"
    lines = err.getvalue().splitlines()
    assert lines[0] == message("reindex.started", store=STORE, job=record.id)
    assert any(line.startswith(f"Magazyn „{STORE}”: segmenty ") for line in lines)
    assert message("reindex.cancelling", job=record.id) in lines
    assert lines[-1].endswith("(kod cancelled)")
    assert env.rows() == before


def test_foreground_follows_joined_job_then_runs_own(
    env: JobsEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request joining another process's running build waits, then runs its own.

    The command's supervisor hands its request to the server's running build
    of the same content; the command follows that job to its end and submits
    again, so its own job runs after it and finds the content built.
    """
    # Arrange
    sources = _preview_sources(
        tmp_path,
        monkeypatch,
        {"a": {"needs_cog": True, "sleep_s": {"build": 1}}},
        copies={"test:a-copy": "a"},
    )
    server = env.jobs.submit(
        "preview", params=_preview_params(sources, "a"), actor=LOCAL_OWNER
    )
    _await(lambda: _state(env.jobs, server.id) == "running")
    submitted: list[JobRecord] = []
    err = io.StringIO()

    # Act
    with JobSupervisor(env.paths, env.settings, worker_command=TEST_WORKER) as jobs:

        def submit() -> JobRecord:
            job = jobs.submit(
                "preview", params=_preview_params(sources, "a-copy"), actor=LOCAL_OWNER
            )
            submitted.append(job)
            return job

        record = run_foreground(
            jobs,
            submit,
            err,
            started=lambda job: f"started {job.id}",
            event=lambda event: None,
            cancelling=lambda job: f"cancelling {job.id}",
            poll_s=0.05,
        )
    first = env.jobs.get(server.id)

    # Assert
    assert [job.id for job in submitted] == [server.id, record.id]
    assert first is not None and first.state == "succeeded"
    assert first.params["refs"] == ["test:a", "test:a-copy"]
    assert record.state == "succeeded" and record.result is not None
    assert (record.result["built"], record.result["cached"]) == (0, 1)
    assert record.started_at is not None and first.finished_at is not None
    assert record.started_at >= first.finished_at
    assert err.getvalue().splitlines() == [
        message(
            "job.foreground_waiting", job=server.id, kind=label("job.kind", "preview")
        ),
        f"started {record.id}",
    ]


def test_job_list_pages_with_cursor_of_its_filters(env: JobsEnv) -> None:
    """Jobs list newest first in pages; a cursor of other filters is refused."""
    # Arrange
    links = [entry.path for entry in env.store.by_kind("link")[:3]]
    done = [env.run("link_check", slot=link) for link in links]

    # Act
    first = env.jobs.list(kind="link_check", limit=2)
    second = env.jobs.list(kind="link_check", limit=2, cursor=first.next_cursor)

    # Assert
    assert [job.id for job in first.items + second.items] == [
        job.id for job in reversed(done)
    ]
    assert second.next_cursor is None
    with pytest.raises(IndexQueryError):
        env.jobs.list(kind="scan", cursor=first.next_cursor)
    with pytest.raises(IndexQueryError):
        env.jobs.list(limit=0)


def test_server_scans_configured_store_at_start(tmp_path: Path) -> None:
    """``archiwista serve`` fully scans a store it never indexed, as ``local``."""
    # Arrange
    store = make_store(tmp_path / "store", slots=24, seed=7)
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    ConfigStore(paths.config_file).save(store_settings(store))

    # Act
    with serving(paths), IndexQueries(paths.index_file) as queries:
        _await(lambda: _last_scan(queries) == "succeeded")
        state = next(s for s in queries.status().stores if s.store == STORE)

    # Assert
    assert state.last_scan is not None and state.last_scan.actor == "local"
    assert state.indexed_at is not None and state.versions > 0


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("scan", {"mode": "quick"}),
        ("scan", {"segment": 7}),
        ("scan", {"mode": "full", "units": ["N-34"]}),
        ("link_check", {}),
        ("link_check", {"slot": ""}),
        ("footprints", {"mode": "full"}),
        ("download", {}),
    ],
)
def test_submit_rejects_invalid_parameters(
    env: JobsEnv, kind: str, params: dict[str, object]
) -> None:
    """A job with an unknown kind or parameters is refused and not recorded."""
    with pytest.raises(ValueError):
        env.jobs.submit(kind, store=STORE, params=params, actor=LOCAL_OWNER)
    with pytest.raises(NotFoundError):
        env.jobs.submit("scan", store="brak", actor=LOCAL_OWNER)

    assert env.jobs.list().items == ()


def test_link_check_finds_outdated_index_and_missing_link(env: JobsEnv) -> None:
    """A link moved after the scan, or deleted, is reported without a problem."""
    # Arrange
    env.scan("full")
    moved, deleted = [
        entry for entry in env.store.by_kind("link") if entry.case == "regular"
    ][:2]
    version = add_version(env.store.root, moved.path, label="2026-10-01_99999")
    (env.store.root / deleted.path).unlink()

    # Act
    outdated = env.run("link_check", slot=moved.path)
    missing = env.run("link_check", slot=deleted.path)
    notices = [
        event.data["code"]
        for event in env.jobs.events(outdated.id)
        if event.type == "notice"
    ]

    # Assert
    assert outdated.result is not None and missing.result is not None
    assert (outdated.result["status"], outdated.result["confirmed"]) == (
        "index_outdated",
        version,
    )
    assert outdated.result["expected"] == moved.version_path
    assert notices == ["index_outdated"]
    assert (missing.result["status"], missing.result["confirmed"]) == ("missing", None)
    assert not [i for i in env.queries.issues(STORE) if i.code == "link_mismatch"]


def test_link_check_refuses_standard_path_leaving_store(
    env: JobsEnv, tmp_path: Path
) -> None:
    """A standard path symlinked outside the store fails the job unchecked."""
    # Arrange
    env.scan("full")
    planted = next(
        entry for entry in env.store.by_kind("link") if entry.case == "regular"
    )
    assert planted.version_path is not None
    outside = tmp_path / "outside" / Path(planted.path).name
    outside.parent.mkdir()
    # The same file as the version: followed, it would be ``confirmed``.
    os.link(env.store.root / planted.version_path, outside)
    slot = env.store.root / planted.path
    slot.unlink()
    slot.symlink_to(outside)

    # Act
    record = env.run("link_check", slot=planted.path)

    # Assert
    assert (record.state, record.result) == ("failed", None)
    assert record.error is not None
    assert (record.error.code, record.error.reason) == (
        "forbidden",
        "path_outside_root",
    )
    assert record.error.detail == message("ref.path_outside_root", path=planted.path)
    assert not [i for i in env.queries.issues(STORE) if i.code == "link_mismatch"]


def test_link_check_follows_symlink_inside_store(env: JobsEnv) -> None:
    """A standard path symlinked to its version in the store is confirmed."""
    # Arrange
    env.scan("full")
    linked = next(
        entry for entry in env.store.by_kind("link") if entry.case == "regular"
    )
    assert linked.version_path is not None
    slot = env.store.root / linked.path
    slot.unlink()
    slot.symlink_to(env.store.root / linked.version_path)

    # Act
    record = env.run("link_check", slot=linked.path)

    # Assert
    assert record.result is not None, record.error
    assert (record.result["status"], record.result["confirmed"]) == (
        "confirmed",
        linked.version_path,
    )


def test_footprints_job_on_disconnected_store_changes_nothing(env: JobsEnv) -> None:
    """With the share gone, the footprints job fails and keeps every reason."""
    # Arrange
    env.scan("full")
    before = env.rows()
    root = env.store.root
    root.rename(root.with_name("data-away"))
    root.mkdir()

    # Act
    record = env.run("footprints")

    # Assert
    assert record.state == "failed"
    assert record.error is not None
    assert (record.error.code, record.error.reason) == (
        "store_unavailable",
        "store_unreadable",
    )
    assert env.state().status == "unavailable"
    assert env.rows() == before


def test_removed_store_cancels_its_jobs(
    env: JobsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing a store from the settings cancels its job and drops its entries."""
    # Arrange
    env.scan("full")
    monkeypatch.setenv(DELAY_ENV, str(SLOW_ENTRY_S))
    job = env.jobs.submit("scan", store=STORE, actor=LOCAL_OWNER)
    env.follow(job.id, _after_first_segment)

    # Act
    env.settings.update(env.settings.get().model_copy(update={"stores": ()}))
    record = env.wait(job.id)

    # Assert
    assert record.state == "cancelled"
    assert env.queries.status().stores == ()


def test_new_store_in_settings_gets_full_scan(env: JobsEnv, tmp_path: Path) -> None:
    """The scheduler scans a store added to the settings fully, as ``local``."""
    # Arrange
    other = make_store(tmp_path / "other", slots=24, seed=8)
    added = StoreConfig(id="drugi", name="Drugi", kartograf=other.root, kind="local")
    registry = load_registry(cache_dir=env.paths.cache_dir)
    scheduler = ScanScheduler(
        env.jobs, env.settings, registry, index_path=env.paths.index_file, tick_s=3600
    )
    scheduler.start()
    try:
        # Act
        settings = env.settings.get()
        env.settings.update(
            settings.model_copy(update={"stores": (*settings.stores, added)})
        )
        jobs = env.jobs.list(store="drugi").items
        record = env.wait(jobs[0].id)
    finally:
        scheduler.stop()

    # Assert
    assert len(jobs) == 1
    assert (record.params["mode"], record.actor, record.state) == (
        "full",
        "local",
        "succeeded",
    )


def test_worker_rejects_unreadable_job() -> None:
    """A worker given no valid job reports a protocol error and exits with 2."""
    finished = subprocess.run(
        [sys.executable, "-m", "archiwista.jobs.worker"],
        input=b'{"protocol": 1}\n',
        capture_output=True,
        timeout=WAIT_S,
        check=False,
    )

    message = decode_message(finished.stdout.decode("utf-8"))
    assert finished.returncode == 2
    assert (message.type, message.data["code"]) == ("error", "internal_error")
    assert message.data["details"] == {"reason": "protocol_error"}


def test_error_of_an_earlier_version_reads_with_a_registry_code(env: JobsEnv) -> None:
    """A stored job error of 0.2.x is read as a registry code and its reason."""
    # Arrange
    link = env.store.by_kind("link")[0].path
    job = env.run("link_check", slot=link)
    old = {
        "code": "snapshot_blocked",
        "detail": "Folder jest tylko do odczytu.",
        "reason": "read_only_folder",
    }
    with sqlite3.connect(env.paths.index_file) as db:
        db.execute(
            "UPDATE jobs SET state = 'failed', summary = NULL, error = ? WHERE id = ?",
            (json.dumps(old), job.id),
        )
        last = db.execute(
            "SELECT max(seq) FROM job_events WHERE job_id = ?", (job.id,)
        ).fetchone()[0]
        db.execute(
            "UPDATE job_events SET data = ? WHERE job_id = ? AND seq = ?",
            (json.dumps({"state": "failed", "error": old}), job.id, last),
        )
    db.close()

    # Act
    record = env.jobs.get(job.id)
    listed = env.jobs.list(kind="link_check").items[0]
    final = env.jobs.events(job.id)[-1]
    with sqlite3.connect(env.paths.index_file) as db:
        stored = db.execute(
            "SELECT error FROM jobs WHERE id = ?", (job.id,)
        ).fetchone()[0]
    db.close()

    # Assert
    current = {
        "code": "conflict",
        "detail": old["detail"],
        "details": {"reason": "snapshot_blocked", "blocked_by": "read_only_folder"},
    }
    assert record is not None and record.error is not None
    assert record.error.to_json() == current
    assert listed.error == record.error
    assert final.data == {"state": "failed", "error": current}
    assert json.loads(stored) == old  # read as current, never rewritten


def test_start_forgets_old_jobs_but_each_store_last(env: JobsEnv) -> None:
    """Finished jobs older than 90 days go, except each store's last of a kind."""
    # Arrange
    links = [entry.path for entry in env.store.by_kind("link")[:2]]
    old, last = [env.run("link_check", slot=link) for link in links]
    recent = env.run("scan")
    env.jobs.close()
    with sqlite3.connect(env.paths.index_file) as db:
        for job, days in ((old, 92), (last, 91)):
            moment = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            db.execute(
                "UPDATE jobs SET created_at = ?, finished_at = ? WHERE id = ?",
                (moment, moment, job.id),
            )
    db.close()

    # Act
    with JobSupervisor(env.paths, env.settings) as jobs:
        kept = [job.id for job in jobs.list().items]
        events = jobs.events(old.id)

    # Assert
    assert kept == [recent.id, last.id]
    assert events == ()


def test_prune_forgets_routine_scans_after_48_hours_but_newest(env: JobsEnv) -> None:
    """Unchanged scheduled scans go after 48 h, but the newest; other scans stay."""
    # Arrange
    first = env.scan("full")
    oldest, young, newest = (
        env.run("scan", actor=SCHEDULER, mode="incremental") for _ in range(3)
    )
    noticed = env.run("scan", actor=SCHEDULER, mode="incremental")
    owners = env.run("scan", mode="incremental")
    full = env.run("scan", actor=SCHEDULER, mode="full")
    link = env.store.by_kind("link")[0].path
    add_version(env.store.root, link, label="2026-10-01_99999")
    changed = env.run("scan", actor=SCHEDULER, mode="incremental")
    now = datetime.now(UTC)
    hours_ago = [
        (first, 60),
        (noticed, 60),
        (owners, 60),
        (full, 60),
        (changed, 60),
        (oldest, 49),
        (young, 47),
        (newest, 46),
    ]
    with sqlite3.connect(env.paths.index_file) as db:
        for job, hours in hours_ago:
            moment = (now - timedelta(hours=hours)).isoformat(timespec="microseconds")
            db.execute(
                "UPDATE jobs SET created_at = ?, finished_at = ? WHERE id = ?",
                (moment, moment, job.id),
            )
        db.execute(
            "INSERT INTO job_events (job_id, seq, type, data, at)"
            " VALUES (?, 1000, 'notice', '{}', ?)",
            (noticed.id, now.isoformat()),
        )
        # Outlines failing again are retried by every scan: no change, no alert.
        db.execute(
            "UPDATE jobs SET summary = json_set(summary, '$.footprints_failed', 2)"
            " WHERE id = ?",
            (oldest.id,),
        )
        db.execute(
            "INSERT INTO job_events (job_id, seq, type, data, at)"
            " VALUES (?, 1000, 'notice', ?, ?)",
            (oldest.id, '{"code": "footprints_failed"}', now.isoformat()),
        )
    db.close()
    log = env.paths.jobs_dir / f"{oldest.id}.log"
    logged = log.exists()

    # Act
    forgotten_now = env.jobs.prune(now)
    kept_now = {job.id for job in env.jobs.list(limit=100).items}
    forgotten_later = env.jobs.prune(now + timedelta(days=10))
    kept_later = {job.id for job in env.jobs.list(limit=100).items}

    # Assert
    assert all(job.state == "succeeded" for job, _ in hours_ago)
    assert changed.result is not None and changed.result["versions_written"] == 1
    assert (forgotten_now, forgotten_later) == (1, 1)
    assert kept_now == {job.id for job, _ in hours_ago} - {oldest.id}
    assert kept_later == kept_now - {young.id}
    assert env.jobs.events(oldest.id) == ()
    assert logged and not log.exists()


def test_preview_build_joins_running_job(
    env: JobsEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build of content a running job has joins it; other content waits after it."""
    # Arrange
    sources = _preview_sources(
        tmp_path,
        monkeypatch,
        {
            "a": {"needs_cog": True, "sleep_s": {"build": 2}},
            "b": {"needs_cog": True},
            "c": {"needs_cog": True},
        },
        copies={"test:a-copy": "a"},
    )
    first = env.jobs.submit(
        "preview", params=_preview_params(sources, "a", "b"), actor=LOCAL_OWNER
    )
    _await(lambda: _state(env.jobs, first.id) == "running")

    # Act
    joined = env.jobs.submit(
        "preview", params=_preview_params(sources, "a-copy"), actor=LOCAL_OWNER
    )
    later = env.jobs.submit(
        "preview", params=_preview_params(sources, "c"), actor=LOCAL_OWNER
    )
    waiting = _state(env.jobs, later.id)
    done = env.wait(first.id)
    after = env.wait(later.id)

    # Assert
    assert joined.id == first.id and joined.state == "running"
    assert joined.params["refs"] == ["test:a", "test:b", "test:a-copy"]
    assert waiting == "queued"
    assert done.result is not None and after.result is not None
    assert (done.result["built"], done.result["cached"], done.result["failed"]) == (
        2,
        0,
        [],
    )
    assert after.result["built"] == 1
    assert done.finished_at is not None and after.started_at is not None
    assert after.started_at >= done.finished_at
    with PreviewCache(env.paths.previews_dir, limit_bytes=1024**3) as cache:
        assert all(
            cache.has(cache_key(source), COG_NAME) for source in sources.values()
        )


def test_preview_build_item_timeout_fails_item_only(
    env: JobsEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A build past its time limit fails that file alone; the others are built."""
    # Arrange
    monkeypatch.setenv(BUILD_TIMEOUT_ENV, "1")
    sources = _preview_sources(
        tmp_path,
        monkeypatch,
        {
            "slow": {"needs_cog": True, "sleep_s": {"build": 60}},
            "ok1": {"needs_cog": True},
            "ok2": {"needs_cog": True},
        },
    )
    started = time.monotonic()

    # Act
    job = env.jobs.submit(
        "preview",
        params=_preview_params(sources, "slow", "ok1", "ok2"),
        actor=LOCAL_OWNER,
    )
    record = env.wait(job.id)
    elapsed_s = time.monotonic() - started

    # Assert
    assert record.state == "succeeded", record
    assert record.result is not None and record.result["built"] == 2
    assert [(item["ref"], item["code"]) for item in record.result["failed"]] == [
        ("test:slow", "timeout")
    ]
    detail = record.result["failed"][0]["detail"]
    assert detail and "/" not in detail
    assert elapsed_s < 30
    with PreviewCache(env.paths.previews_dir, limit_bytes=1024**3) as cache:
        assert not cache.has(cache_key(sources["slow"]), COG_NAME)
        assert cache.has(cache_key(sources["ok1"]), COG_NAME)


def test_preview_builds_at_most_n_children(
    env: JobsEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each file builds in a process of its own, at most ``n`` of them at once."""
    # Arrange
    monkeypatch.setenv(BUILD_PROCESSES_ENV, "2")
    log = tmp_path / "builds.log"
    names = [f"sheet{index}" for index in range(5)]
    steps = {"needs_cog": True, "sleep_s": {"build": 1.0}, "log": str(log)}
    sources = _preview_sources(
        tmp_path, monkeypatch, {name: dict(steps) for name in names}
    )

    # Act
    job = env.jobs.submit(
        "preview", params=_preview_params(sources, *names), actor=LOCAL_OWNER
    )
    record = env.wait(job.id)

    # Assert
    assert record.result is not None and record.result["built"] == 5
    builds = [
        (int(pid), float(start), float(end))
        for pid, op, start, end in (
            line.split() for line in log.read_text(encoding="utf-8").splitlines()
        )
        if op == "build"
    ]
    assert len({pid for pid, _, _ in builds}) == 5
    overlap = max(
        sum(start <= moment < end for _, start, end in builds)
        for _, moment, _ in builds
    )
    assert overlap == 2
    assert record.progress is not None and record.progress["current"] == 5


@pytest.mark.live
def test_footprints_job_fetches_teryt_unit_live(env: JobsEnv) -> None:
    """With the network, a TERYT unit outline comes from PRG and is kept."""
    # Arrange
    env.scan("full")
    path = next(
        item.relative_path.as_posix()
        for item in env.queries.entries_without_footprint(STORE)
        if "/teryt/" in item.relative_path.as_posix()
    )
    sidecar = sidecar_path(env.store.root, path)
    content = json.loads(sidecar.read_text(encoding="utf-8"))
    content["request"]["teryt"] = "1465"  # Warszawa
    sidecar.write_text(json.dumps(content), encoding="utf-8")

    # Act
    record = env.run("footprints")

    # Assert
    assert record.state == "succeeded", record
    version = env.queries.version(STORE, path, visible=ALL_PROJECTS)
    assert version is not None and version.summary.location.source == "unit"
    assert version.footprint is not None
    ring = version.footprint["coordinates"][0]  # type: ignore[index]
    longitudes = [point[0] for point in ring]
    latitudes = [point[1] for point in ring]
    assert min(longitudes) < 21.0 < max(longitudes)
    assert min(latitudes) < 52.2 < max(latitudes)
    cache = UnitBBoxCache(env.paths.cache_dir / "kartograf" / "unit_bboxes.sqlite")
    assert ("teryt", "1465") in cache
    cache.close()


def _after_first_segment(event: JobEvent) -> bool:
    """Accept a scan's progress once its first segment is written."""
    return event.type == "progress" and event.data["current"] >= 1


def _progressed(jobs: JobSupervisor, job_id: str) -> bool:
    record = jobs.get(job_id)
    return record is not None and record.progress is not None


def _last_scan(queries: IndexQueries) -> str | None:
    state = next((s for s in queries.status().stores if s.store == STORE), None)
    return None if state is None or state.last_scan is None else state.last_scan.state


def _unit_key(entry: ExpectedEntry) -> tuple[str, str]:
    """Return ``(kind, code)`` of a unit version's outline in the local memory."""
    assert entry.unit is not None, entry
    return entry.hierarchy.split("/", 1)[0], entry.unit


def _unit_box(kind: str) -> BBox:
    """Return a native box of a unit: in CS92 for TERYT, in Křovák for KU."""
    if kind == "teryt":
        return BBox(500_000.0, 400_000.0, 520_000.0, 420_000.0, "EPSG:2180")
    return BBox(-600_000.0, -1_100_000.0, -590_000.0, -1_090_000.0, "EPSG:5514")


def _worker_pid(paths: AppPaths, job_id: str) -> int:
    """Return the worker process of a job, from the first line of its log."""
    log = (paths.jobs_dir / f"{job_id}.log").read_text(encoding="utf-8")
    match = re.search(r"process (\d+)", log)
    assert match is not None, log
    return int(match.group(1))


def _running(pid: int) -> bool:
    """Whether a process runs (a zombie waiting for its parent does not)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


def _await(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met in time")


def _state(jobs: JobSupervisor, job_id: str) -> str | None:
    record = jobs.get(job_id)
    return None if record is None else record.state


def _preview_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    files: dict[str, dict[str, object]],
    *,
    copies: dict[str, str] | None = None,
) -> dict[str, PreviewSource]:
    """Write data files for the test renderer and let the job resolve them.

    Each file ``<name>.tif`` holds its instructions and its name (so no two
    share a content) and is the source of ``test:<name>``; ``copies`` adds
    refs to the same sources, as two versions of the same bytes.
    """
    directory = tmp_path / "preview-data"
    directory.mkdir()
    sources: dict[str, PreviewSource] = {}
    for name, steps in files.items():
        path = directory / f"{name}.tif"
        path.write_text(json.dumps({"name": name, **steps}), encoding="utf-8")
        content = hashlib.sha256(path.read_bytes()).hexdigest()
        sources[name] = PreviewSource(
            ref=f"test:{name}", content_key=content, paths=(path,)
        )
    table = {source.ref: source.to_json() for source in sources.values()}
    for ref, name in (copies or {}).items():
        table[ref] = {**sources[name].to_json(), "ref": ref}
    resolved = tmp_path / "preview-sources.json"
    resolved.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setenv(PREVIEW_SOURCES_ENV, str(resolved))
    return sources


def _preview_params(
    sources: dict[str, PreviewSource], *names: str
) -> dict[str, object]:
    """Return the parameters of a preview job for ``test:<name>`` refs."""
    refs = [f"test:{name}" for name in names]
    contents = [sources[name.removesuffix("-copy")].content_key for name in names]
    return {"refs": refs, "contents": contents, "force": False}


def test_own_scan_request_joins_waiting_run(env: JobsEnv) -> None:
    """While an ``own_scan`` runs, requests join a waiting run that covers them.

    A project's request joins the waiting run of that project, or of every
    project; another project's request does not join a project's run. The
    run a request joined starts after it, so a change made before the
    request is in the index when that run ends.
    """
    # Arrange
    env.scan("full")
    projects = env.queries.projects(visible=ALL_PROJECTS)
    first, second = projects[0], projects[1]
    folder = Path(first.access_key) / "dane"
    folder.mkdir()
    for number in range(4_000):
        (folder / f"plik_{number:05d}.txt").write_bytes(b"")
    running = env.jobs.submit("own_scan", actor=SCHEDULER)

    # Act
    (folder / "nowy.txt").write_text("zmiana przed zleceniem", encoding="utf-8")
    asked = env.jobs.submit(
        "own_scan", params={"project": first.key}, actor=LOCAL_OWNER
    )
    again = env.jobs.submit(
        "own_scan", params={"project": first.key}, actor=LOCAL_OWNER
    )
    everyone = env.jobs.submit("own_scan", actor=SCHEDULER)
    other = env.jobs.submit(
        "own_scan", params={"project": second.key}, actor=LOCAL_OWNER
    )
    ended = {job.id: env.wait(job.id) for job in (running, asked, everyone)}
    card = env.queries.own_file(
        first.key, own_file_id("nowy.txt"), visible=ALL_PROJECTS
    )

    # Assert
    assert running.state == "running"
    assert (asked.state, again.id, other.id) == ("queued", asked.id, everyone.id)
    assert len({running.id, asked.id, everyone.id}) == 3
    assert all(job.state == "succeeded" for job in ended.values()), ended
    first_run, joined = ended[running.id], ended[asked.id]
    assert joined.params == {"project": first.key}
    assert first_run.finished_at is not None and joined.started_at is not None
    assert joined.started_at >= first_run.finished_at
    assert joined.result is not None and joined.result["projects"] == 1
    every = ended[everyone.id].result
    assert every is not None and every["projects"] == len(projects)
    assert card is not None and card.file.state == "unrecognized"
