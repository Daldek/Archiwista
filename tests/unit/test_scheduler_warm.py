"""The scheduler's warm-up of previews after a scan (plan of 2026-10-25, A9).

With the setting ``preview_warm_after_scan`` on, a store's newest succeeded
scan that wrote versions gets one ``preview_warm`` job of the versions indexed
since it started (SPEC 5.7, ADR-041). The scans are rows of the jobs table;
no job runs (``max_jobs=0``) and no producer is installed, so the tick plans
no scan of its own.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from archiwista.auth import SCHEDULER
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.jobs import JobRecord, JobSupervisor, ScanScheduler
from tests.fixtures.local_server import NoSources

STORE = "zespol"
OTHER = "archiwum"
NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)


def _scan(paths: AppPaths, job: str, store: str, *, written: int, age: float) -> str:
    """Record a full scan of ``store`` ended ``age`` minutes ago; return its start."""
    started = NOW - timedelta(minutes=age + 2)
    finished = NOW - timedelta(minutes=age)
    summary = {"entries": 40, "versions_written": written, "missing": 0}
    with sqlite3.connect(paths.index_file) as db:
        db.execute(
            "INSERT INTO jobs (id, kind, actor, actor_kind, store, params, state,"
            " created_at, started_at, finished_at, summary)"
            " VALUES (?, 'scan', 'scheduler', 'scheduler', ?, ?, 'succeeded', ?, ?,"
            " ?, ?)",
            (
                job,
                store,
                json.dumps({"mode": "full"}),
                started.isoformat(),
                started.isoformat(),
                finished.isoformat(),
                json.dumps(summary),
            ),
        )
    db.close()
    return started.isoformat()


def _warm_ups(submitted: tuple[JobRecord, ...]) -> list[tuple[str, dict[str, object]]]:
    """Return the actor and the parameters of each warm-up a tick submitted."""
    return [(job.actor, job.params) for job in submitted if job.kind == "preview_warm"]


def test_the_scheduler_warms_after_each_scan_that_wrote_versions_when_asked(
    tmp_path: Path,
) -> None:
    """Off: no warm-up. On: one per scan that wrote versions, of those versions.

    A scan is followed once; a scan that wrote nothing gets no warm-up; each
    store's own newest scan counts.
    """
    # Arrange
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    stores = tuple(
        StoreConfig(id=name, name=name, kartograf=tmp_path / name, kind="local")
        for name in (STORE, OTHER)
    )
    for store in stores:
        assert store.kartograf is not None
        store.kartograf.mkdir()
    ConfigStore(paths.config_file).save(AppSettings(stores=stores))
    service = SettingsService(ConfigStore(paths.config_file), NoSources())

    with JobSupervisor(paths, service, max_jobs=0) as jobs:
        scheduler = ScanScheduler(
            jobs, service, NoSources(), index_path=paths.index_file
        )
        try:
            first = _scan(paths, "scan-1", STORE, written=12, age=30)
            _scan(paths, "scan-2", OTHER, written=0, age=20)

            # Act
            off = scheduler.tick(NOW)
            service.update(
                service.get().model_copy(update={"preview_warm_after_scan": True})
            )
            on = scheduler.tick(NOW + timedelta(minutes=1))
            again = scheduler.tick(NOW + timedelta(minutes=2))
            _scan(paths, "scan-3", STORE, written=0, age=-5)
            nothing_new = scheduler.tick(NOW + timedelta(minutes=10))
            later = _scan(paths, "scan-4", OTHER, written=3, age=-10)
            other = scheduler.tick(NOW + timedelta(minutes=15))
        finally:
            scheduler.stop()

    # Assert
    assert _warm_ups(off) == []
    store_only = {"product": None, "segment": None, "project": None, "area_id": None}
    assert _warm_ups(on) == [
        (SCHEDULER.id, {"store": STORE, **store_only, "since": first})
    ]
    assert _warm_ups(again) == []
    assert _warm_ups(nothing_new) == []
    assert _warm_ups(other) == [
        (SCHEDULER.id, {"store": OTHER, **store_only, "since": later})
    ]
