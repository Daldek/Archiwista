"""The stand-in producer's availability over a kept area (plan 2026-10-25, A2).

The stand-in (``tests/fixtures/action_source``) is registered by its entry
point on ``sys.path``, and on ``PYTHONPATH`` for worker processes. It records
the options its ``check_availability`` receives (``standin_producer.CALLS``)
and reports two variants of 2023 and one of 2022, checked now.
"""

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.config import AppPaths, AppSettings, ConfigStore, SettingsService
from archiwista.index import AreaRecord, IndexWriter
from archiwista.jobs import JobSupervisor
from archiwista.jobs.protocol import JobSpec
from archiwista.sources.registry import load_registry

ACTION_SOURCE = Path(__file__).parent / "action_source"
FIXTURE_MODULES = ("standin_source_plugin", "standin_producer")
AREA = AreaRecord(
    id="5f2b9c0e7d41a3b6",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[19.9, 50.0], [20.0, 50.0], [20.0, 50.05], [19.9, 50.05], [19.9, 50.0]]
        ],
    },
    created_at=datetime(2026, 10, 25, 8, 0, tzinfo=UTC),
    area_km2=39.8,
    countries=("PL",),
    name="Kraków",
)
PARAMS = {"area_id": AREA.id, "producer": "standin", "product": "dem"}


def register_standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(ACTION_SOURCE))
    paths = [str(ACTION_SOURCE), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(path for path in paths if path))
    return importlib.import_module("standin_producer")


def area_paths(tmp_path: Path) -> AppPaths:
    """Return a fresh installation whose index keeps the area ``AREA``."""
    created = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    with IndexWriter(created.index_file) as writer:
        writer.write_area(AREA)
    return created


def availability_supervisor(
    paths: AppPaths, *, offline: bool = False, max_network_jobs: int = 2
) -> JobSupervisor:
    """Return a supervisor of real workers with settings of no store."""
    ConfigStore(paths.config_file).save(AppSettings(offline=offline))
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    return JobSupervisor(paths, settings, max_network_jobs=max_network_jobs)


def availability_spec(
    paths: AppPaths, *, force: bool, job_id: str = "0123456789abcdef"
) -> JobSpec:
    """Return the job a worker of ``availability`` receives for ``PARAMS``."""
    return JobSpec(
        job_id=job_id,
        kind="availability",
        store=None,
        params={**PARAMS, "force": force},
        actor="local",
        actor_kind="local_owner",
        session=None,
        index_path=paths.index_file,
        cache_dir=paths.cache_dir,
        previews_dir=paths.previews_dir,
        work_dir=paths.work_dir,
        settings=AppSettings(),
    )
