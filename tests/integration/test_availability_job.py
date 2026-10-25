"""The availability job and the stored report (plan 2026-10-25, A2).

The stand-in producer (``tests/fixtures/availability.py``) records the options
its ``check_availability`` receives and reports two variants of 2023 and one
of 2022, checked now. Kartograf's side of the call (its metadata cache, the
area as a box) is the contract test ``tests/contract/test_kartograf_actions.py``.
"""

import io
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths
from archiwista.errors import OfflineModeError
from archiwista.index import IndexQueries, IndexWriter, initialize
from archiwista.jobs import JobSupervisor, worker
from archiwista.messages import message
from tests.fixtures.availability import (
    AREA,
    PARAMS,
    area_paths,
    availability_spec,
    availability_supervisor,
    register_standin,
)

JOB_TIMEOUT_S = 90.0


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in here and in workers; return its producer library."""
    return register_standin(monkeypatch)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return a fresh installation whose index keeps the area ``AREA``."""
    return area_paths(tmp_path)


@pytest.fixture
def held(paths: AppPaths) -> Iterator[JobSupervisor]:
    """Yield a supervisor that runs no network job: they stay queued."""
    with availability_supervisor(paths, max_network_jobs=0) as jobs:
        yield jobs


def test_the_job_asks_the_producer_and_keeps_the_report(
    paths: AppPaths, standin: ModuleType
) -> None:
    """The producer gets the area as the index keeps it; the report is kept whole."""
    stream = io.StringIO()

    summary = worker.run_availability(
        availability_spec(paths, force=True), worker.Emitter(stream)
    )
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
    worker.run_availability(
        availability_spec(paths, force=False), worker.Emitter(io.StringIO())
    )
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
    with availability_supervisor(paths, offline=True) as jobs:
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
    with availability_supervisor(paths) as jobs:
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
        connection.execute("PRAGMA user_version = 7")
        connection.commit()

    rebuilt = initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.write_area(AREA)
    worker.run_availability(
        availability_spec(paths, force=False), worker.Emitter(io.StringIO())
    )
    with IndexQueries(paths.index_file) as queries:
        stored = queries.availability(AREA.id, "dem", producer="standin")

    assert rebuilt == "rebuilt"
    assert stored is not None
    assert len(stored.report.combinations) == 3
