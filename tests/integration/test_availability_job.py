"""The availability job and the stored report (plan 2026-10-25, A2).

The stand-in producer (``tests/fixtures/action_source``) is registered by its
entry point on ``sys.path``, and on ``PYTHONPATH`` for worker processes. It
records the options its ``check_availability`` receives
(``standin_producer.CALLS``) and reports two variants of 2023 and one of 2022,
checked now. Kartograf's side of the call (its metadata cache, the area as a
box) is the contract test ``tests/contract/test_kartograf_actions.py``.
"""

import importlib
import io
import json
import os
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore, SettingsService
from archiwista.errors import OfflineModeError
from archiwista.index import (
    SCHEMA_VERSION,
    AreaRecord,
    IndexQueries,
    IndexWriter,
    initialize,
)
from archiwista.jobs import JobSupervisor, worker
from archiwista.jobs.protocol import JobSpec
from archiwista.messages import message
from archiwista.sources.registry import load_registry

FIXTURES = Path(__file__).parents[1] / "fixtures"
ACTION_SOURCE = FIXTURES / "action_source"
FIXTURE_MODULES = ("standin_source_plugin", "standin_producer")
JOB_TIMEOUT_S = 90.0
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


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(ACTION_SOURCE))
    paths = [str(ACTION_SOURCE), os.environ.get("PYTHONPATH", "")]
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(path for path in paths if path))
    return importlib.import_module("standin_producer")


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return a fresh installation whose index keeps the area ``AREA``."""
    created = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    with IndexWriter(created.index_file) as writer:
        writer.write_area(AREA)
    return created


def _supervisor(
    paths: AppPaths, *, offline: bool = False, max_network_jobs: int = 2
) -> JobSupervisor:
    """Return a supervisor of real workers with settings of no store."""
    ConfigStore(paths.config_file).save(AppSettings(offline=offline))
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    return JobSupervisor(paths, settings, max_network_jobs=max_network_jobs)


@pytest.fixture
def held(paths: AppPaths) -> Iterator[JobSupervisor]:
    """Yield a supervisor that runs no network job: they stay queued."""
    with _supervisor(paths, max_network_jobs=0) as jobs:
        yield jobs


def _spec(paths: AppPaths, *, force: bool) -> JobSpec:
    """Return the job a worker of ``availability`` receives."""
    return JobSpec(
        job_id="0123456789abcdef",
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


def test_the_job_asks_the_producer_and_keeps_the_report(
    paths: AppPaths, standin: ModuleType
) -> None:
    """The producer gets the area as the index keeps it; the report is kept whole."""
    stream = io.StringIO()

    summary = worker.run_availability(_spec(paths, force=True), worker.Emitter(stream))
    with IndexQueries(paths.index_file) as queries:
        stored = queries.availability(AREA.id, "dem", producer="standin")
    received = standin.CALLS

    assert received == [
        (
            "check_availability",
            "dem",
            {"area": AREA.geometry, "countries": ["PL"], "refresh": True},
        )
    ]
    assert stored is not None
    report = stored.report
    assert (stored.checked_at, stored.job_id) == (
        report.checked_at.replace(microsecond=0),
        "0123456789abcdef",
    )
    assert [(c.year, c.horizontal, c.complete) for c in report.combinations] == [
        (2023, "PL-1992", True),
        (2023, "PL-2000", True),
        (2022, "PL-1992", False),
    ]
    assert report.combinations[2].sheets_partial == ("S4",)
    assert [json.loads(line) for line in stream.getvalue().splitlines()] == [
        {
            "type": "notice",
            "data": {
                "level": "info",
                "code": "index_cached",
                "message": "The sheet index answered from the cache.",
            },
        }
    ]
    assert summary == {
        "area_id": AREA.id,
        "producer": "standin",
        "product": "dem",
        "checked_at": report.checked_at.isoformat(),
        "ok": True,
        "combinations": 3,
        "kept": True,
        "seconds": summary["seconds"],
    }


def test_an_older_report_never_replaces_a_newer_one(
    paths: AppPaths, standin: ModuleType
) -> None:
    """Two checks ending in the other order keep the newer report."""
    worker.run_availability(_spec(paths, force=False), worker.Emitter(io.StringIO()))
    with IndexQueries(paths.index_file) as queries:
        newer = queries.availability(AREA.id, "dem", producer="standin")
    assert newer is not None
    older = replace(newer.report, checked_at=newer.checked_at - timedelta(days=1))

    with IndexWriter(paths.index_file) as writer:
        kept = writer.write_availability(AREA.id, older, product="dem", job_id="old")
    with IndexQueries(paths.index_file) as queries:
        after = queries.availability(AREA.id, "dem", producer="standin")

    assert kept is False
    assert after == newer


def test_offline_mode_refuses_the_job_and_records_nothing(
    paths: AppPaths, standin: ModuleType
) -> None:
    """The check needs the network: ``409 offline_mode`` before a job exists."""
    with _supervisor(paths, offline=True) as jobs:
        with pytest.raises(OfflineModeError) as raised:
            jobs.submit("availability", params=PARAMS, actor=LOCAL_OWNER)
        listed = jobs.list().items

    assert str(raised.value) == message("job.offline_mode")
    assert raised.value.details["reason"] == "offline_mode"
    assert listed == ()
    assert standin.CALLS == []


def test_a_check_joins_an_active_check_of_the_same_question(
    held: JobSupervisor,
) -> None:
    """``force`` never waits for a check that may answer from the cache."""
    first = held.submit("availability", params=PARAMS, actor=LOCAL_OWNER)
    same = held.submit("availability", params=PARAMS, actor=LOCAL_OWNER)
    forced = held.submit(
        "availability", params={**PARAMS, "force": True}, actor=LOCAL_OWNER
    )
    forced_again = held.submit(
        "availability", params={**PARAMS, "force": True}, actor=LOCAL_OWNER
    )
    plain_again = held.submit("availability", params=PARAMS, actor=LOCAL_OWNER)
    other = held.submit(
        "availability", params={**PARAMS, "product": "laz"}, actor=LOCAL_OWNER
    )

    assert (first.state, first.params) == ("queued", {**PARAMS, "force": False})
    assert (same.id, forced_again.id, plain_again.id) == (first.id, forced.id, first.id)
    assert len({first.id, forced.id, other.id}) == 3
    assert len(held.list().items) == 3


@pytest.mark.parametrize(
    "params",
    [
        {"producer": "standin", "product": "dem"},
        {**PARAMS, "product": ""},
        {**PARAMS, "force": "yes"},
        {**PARAMS, "store": "zespol"},
    ],
)
def test_invalid_parameters_are_refused_before_a_job_exists(
    held: JobSupervisor, params: dict[str, object]
) -> None:
    """An area, a producer and a product are required; ``force`` is a boolean."""
    with pytest.raises(ValueError, match="invalid availability parameters"):
        held.submit("availability", params=params, actor=LOCAL_OWNER)

    assert held.list().items == ()


def test_a_worker_process_runs_the_check_and_its_notice_becomes_an_event(
    paths: AppPaths, standin: ModuleType
) -> None:
    """The job ends ``succeeded`` with the report in the index."""
    with _supervisor(paths) as jobs:
        job = jobs.submit("availability", params=PARAMS, actor=LOCAL_OWNER)
        record = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
        notices = [
            event.data for event in jobs.events(job.id) if event.type == "notice"
        ]
    with IndexQueries(paths.index_file) as queries:
        stored = queries.availability(AREA.id, "dem", producer="standin")

    assert (record.state, record.store, record.error) == ("succeeded", None, None)
    assert record.result is not None
    assert (record.result["combinations"], record.result["kept"]) == (3, True)
    assert stored is not None
    assert stored.job_id == job.id
    assert notices == [
        {
            "level": "info",
            "code": "index_cached",
            "message": "The sheet index answered from the cache.",
        }
    ]


def test_an_index_of_the_previous_schema_is_rebuilt_with_the_reports(
    paths: AppPaths, standin: ModuleType
) -> None:
    """Version 7 had no ``availability``: the index is rebuilt, not migrated."""
    with closing(sqlite3.connect(paths.index_file)) as connection:
        connection.execute("DROP TABLE availability")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
        connection.commit()

    rebuilt = initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.write_area(AREA)
    worker.run_availability(_spec(paths, force=False), worker.Emitter(io.StringIO()))
    with IndexQueries(paths.index_file) as queries:
        stored = queries.availability(AREA.id, "dem", producer="standin")

    assert (SCHEMA_VERSION, rebuilt) == (8, "rebuilt")
    assert stored is not None
    assert len(stored.report.combinations) == 3
