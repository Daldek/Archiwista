"""A generated store with a job supervisor whose workers carry test hooks.

``jobs_env`` writes a Kartograf store and settings into the test directory
and starts a ``JobSupervisor`` running ``tests.fixtures.job_worker`` (the real
worker plus the hooks of its environment variables).
"""

import os
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
    StoreKind,
)
from archiwista.index import IndexQueries, SlotQuery, StoreIndexState
from archiwista.jobs import ACTIVE_STATES, JobEvent, JobRecord, JobSupervisor
from archiwista.sources.registry import load_registry
from tests.fixtures.job_worker import CRASH_ENV, DELAY_ENV, NO_NETWORK_ENV
from tests.fixtures.make_store import StoreManifest, make_store

REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_WORKER: tuple[str, ...] = (sys.executable, "-m", "tests.fixtures.job_worker")
STORE = "zespol"
SLOTS = 24
SEED = 7
JOB_TIMEOUT_S = 90.0
# Seconds per scanned entry of a slowed scan: the store's 80 entries take
# about four seconds.
SLOW_ENTRY_S = 0.05

__all__ = [
    "CRASH_ENV",
    "DELAY_ENV",
    "NO_NETWORK_ENV",
    "SLOW_ENTRY_S",
    "STORE",
    "TEST_WORKER",
    "JobsEnv",
    "jobs_env",
    "store_settings",
    "worker_path",
]


def worker_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let worker processes import ``tests`` (started outside the repository)."""
    paths = [str(REPO_ROOT), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(path for path in paths if path))


def store_settings(
    store: StoreManifest, *, kind: StoreKind = "local", **options: Any
) -> AppSettings:
    """Return settings with the generated store as ``zespol``."""
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store.root, kind=kind)
    return AppSettings(stores=(config,), project_dirs=(store.projects_dir,), **options)


@dataclass
class JobsEnv:
    """A generated store, its settings and a started job supervisor."""

    store: StoreManifest
    paths: AppPaths
    settings: SettingsService
    jobs: JobSupervisor
    queries: IndexQueries

    def wait(self, job_id: str) -> JobRecord:
        """Wait for a job to end and return it."""
        record = self.jobs.wait(job_id, timeout=JOB_TIMEOUT_S)
        assert record.state not in ACTIVE_STATES, record
        return record

    def run(self, kind: str, *, actor: str = "local", **params: Any) -> JobRecord:
        """Submit a job and wait for its end."""
        job = self.jobs.submit(kind, store=STORE, params=params, actor=actor)
        return self.wait(job.id)

    def scan(self, mode: str = "incremental") -> JobRecord:
        """Scan the store and require success."""
        record = self.run("scan", mode=mode)
        assert record.state == "succeeded", record
        return record

    def state(self) -> StoreIndexState:
        """Return the store's index state."""
        return next(s for s in self.queries.status().stores if s.store == STORE)

    def rows(self) -> list[tuple[object, ...]]:
        """Return every version row of the catalog, with the store's problems."""
        rows: list[tuple[object, ...]] = []
        cursor = None
        while True:
            page = self.queries.slots(
                SlotQuery(versions="all", limit=200, cursor=cursor),
                visible=ALL_PROJECTS,
            )
            for row in page.items:
                version = row.version
                rows.append(
                    (
                        row.slot,
                        row.status,
                        row.location,
                        None
                        if version is None
                        else (version.path, version.is_current, version.state),
                    )
                )
            cursor = page.next_cursor
            if cursor is None:
                break
        issues = sorted(
            (issue.code, issue.path, issue.origin)
            for issue in self.queries.issues(STORE)
        )
        return [*rows, *issues]

    def follow(self, job_id: str, until: Callable[[JobEvent], bool]) -> JobEvent:
        """Wait for the first event of a job that ``until`` accepts."""
        deadline = time.monotonic() + JOB_TIMEOUT_S
        seen = 0
        while time.monotonic() < deadline:
            for event in self.jobs.events(job_id, after=seen):
                seen = event.seq
                if until(event):
                    return event
            time.sleep(0.02)
        raise AssertionError(f"no awaited event of job {job_id}")


@contextmanager
def jobs_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    kind: StoreKind = "local",
    **supervisor: Any,
) -> Iterator[JobsEnv]:
    """Yield a fresh store, empty index and started supervisor of test workers."""
    worker_path(monkeypatch)
    store = make_store(tmp_path / "store", slots=SLOTS, seed=SEED)
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    ConfigStore(paths.config_file).save(store_settings(store, kind=kind))
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    with (
        JobSupervisor(
            paths, settings, worker_command=TEST_WORKER, **supervisor
        ) as jobs,
        IndexQueries(paths.index_file) as queries,
    ):
        yield JobsEnv(store, paths, settings, jobs, queries)
