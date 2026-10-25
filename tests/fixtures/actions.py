"""The stand-in producer's actions on a configured store (plan 2026-10-25, A4).

A store's settings name only the directories of the producers Archiwista
configures (Kartograf's, IMGW's). ``StandinStore`` gives the stand-in
(``tests/fixtures/action_source``) the store's Kartograf directory in the test's
own process; the settings reach a worker process as JSON, so the workers of
``ACTION_WORKER`` (``tests.fixtures.action_worker``) do the same themselves.
The stand-in is registered by ``tests.fixtures.availability.register_standin``
and the worker imports ``tests`` through ``tests.fixtures.jobs.worker_path``.
"""

import sys
from pathlib import Path

from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
)
from archiwista.jobs import JobSupervisor
from archiwista.jobs.protocol import JobKind, JobSpec, JsonObject
from archiwista.sources.registry import load_registry

STORE = "pomiary"
STATION = {"station": "150160180", "kind": "hydro"}
CHECK: JsonObject = {
    "producer": "standin",
    "command": "series fetch",
    "options": STATION,
}
ACTION_WORKER: tuple[str, ...] = (sys.executable, "-m", "tests.fixtures.action_worker")


def standin_roots(roots: dict[str, Path]) -> dict[str, Path]:
    """Return a store's directories with its Kartograf directory as the stand-in's."""
    return {"standin": roots["kartograf"]} if "kartograf" in roots else roots


class StandinStore(StoreConfig):
    """A store of the stand-in: its Kartograf directory is the stand-in's."""

    def roots(self) -> dict[str, Path]:
        """Return the stand-in's directory: the one given as Kartograf's."""
        return standin_roots(super().roots())


def store_root(tmp_path: Path) -> Path:
    """Return the directory of the store ``STORE`` of a test."""
    return tmp_path / STORE


def action_paths(tmp_path: Path, *, offline: bool = False) -> AppPaths:
    """Return a fresh installation with the stand-in's store ``STORE``."""
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    root = store_root(tmp_path)
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(store,), offline=offline))
    return paths


def action_supervisor(paths: AppPaths, *, max_network_jobs: int = 2) -> JobSupervisor:
    """Return a supervisor whose workers give the stand-in its store."""
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    return JobSupervisor(
        paths,
        settings,
        worker_command=ACTION_WORKER,
        max_network_jobs=max_network_jobs,
    )


def action_spec(
    paths: AppPaths, root: Path, job_id: str, kind: JobKind, params: JsonObject
) -> JobSpec:
    """Return the job a worker receives, the stand-in's store in its settings."""
    store = StandinStore(id=STORE, name="Pomiary", kartograf=root, kind="local")
    return JobSpec(
        job_id=job_id,
        kind=kind,
        store=STORE,
        params=params,
        actor="local",
        actor_kind="local_owner",
        session=None,
        index_path=paths.index_file,
        cache_dir=paths.cache_dir,
        previews_dir=paths.previews_dir,
        work_dir=paths.work_dir,
        settings=AppSettings(stores=(store,)),
    )
