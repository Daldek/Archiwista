"""When the scheduler scans a store, and how (plan step 6b, SPEC 4.4)."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    StoreConfig,
    StoreKind,
)
from archiwista.index import ScanMode
from archiwista.jobs import (
    JobSupervisor,
    PlannedScan,
    ScanHistory,
    plan_own_scan,
    plan_scans,
)
from archiwista.sources import SourceState

START = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
STORE = "zespol"


def _settings(kind: StoreKind, *, full_scan_interval_h: int = 24) -> AppSettings:
    store = StoreConfig(id=STORE, name="Zespół", kartograf=Path("/srv/dane"), kind=kind)
    return AppSettings(stores=(store,), full_scan_interval_h=full_scan_interval_h)


def _minutes(value: float | None) -> datetime | None:
    return None if value is None else START + timedelta(minutes=value)


@pytest.mark.parametrize(
    ("kind", "last", "full", "now", "expected"),
    [
        # Never scanned: a full scan when the server starts.
        ("local", None, None, 0, "full"),
        # Scanned 10 min before the start: first scan one interval after it.
        ("local", -10, -10, 0, None),
        ("local", -10, -10, 4.9, None),
        ("local", -10, -10, 5, "incremental"),
        ("share", -10, -10, 14.9, None),
        ("share", -10, -10, 15, "incremental"),
        # Scanned more than 15 min before the start: at once.
        ("share", -16, -60, 0, "incremental"),
        # Later: one interval after the last scan ended, by kind.
        ("local", 30, -60, 34.9, None),
        ("local", 30, -60, 35, "incremental"),
        ("share", 30, -60, 44.9, None),
        ("share", 30, -60, 45, "incremental"),
        # The control scan (daily by default) replaces a due incremental one.
        ("local", 30, -24 * 60 + 35, 35, "full"),
        ("local", 30, -24 * 60 + 36, 35, "incremental"),
    ],
)
def test_plan_scans_timing(
    kind: StoreKind,
    last: float | None,
    full: float | None,
    now: float,
    expected: ScanMode | None,
) -> None:
    """Start, interval of the store's kind and daily full scan decide a scan."""
    history = {STORE: ScanHistory(finished_at=_minutes(last), full_at=_minutes(full))}

    planned = plan_scans(
        _settings(kind),
        history,
        (),
        now=START + timedelta(minutes=now),
        started_at=START,
    )

    assert planned == (() if expected is None else (PlannedScan(STORE, expected),))


@pytest.mark.parametrize(("hours", "expected"), [(1, "full"), (24, "incremental")])
def test_plan_scans_full_scan_interval_from_settings(
    hours: int, expected: ScanMode
) -> None:
    """A store fully scanned 2 h ago is scanned fully only under a shorter interval."""
    history = {STORE: ScanHistory(finished_at=_minutes(-30), full_at=_minutes(-120))}

    planned = plan_scans(
        _settings("local", full_scan_interval_h=hours),
        history,
        (),
        now=START,
        started_at=START,
    )

    assert planned == (PlannedScan(STORE, expected),)


def test_plan_scans_leaves_busy_store_alone() -> None:
    """A store whose index a job writes gets no scan, however late."""
    history = {STORE: ScanHistory(finished_at=None, full_at=None, busy=True)}

    planned = plan_scans(
        _settings("local"),
        history,
        {STORE},
        now=START + timedelta(days=2),
        started_at=START,
    )

    assert planned == ()


def test_plan_scans_only_probes_unavailable_store() -> None:
    """An unavailable store is probed at every planning, right after a scan too."""
    history = {STORE: ScanHistory(finished_at=START, full_at=START - timedelta(days=2))}

    planned = plan_scans(
        _settings("share"),
        history,
        {STORE},
        now=START + timedelta(seconds=1),
        started_at=START,
    )

    assert planned == (PlannedScan(STORE, "full", probe=True),)


def test_own_scan_planned_and_pruned(tmp_path: Path) -> None:
    """Data folders: at start when stale, then every local interval; routine runs go.

    A run of every project that the scheduler started and that changed
    nothing goes after 48 hours, but the newest one; a run that changed
    something, a project's run and a recent one stay.
    """
    # Arrange
    settings = AppSettings(scan_interval_local_min=5)
    recent = ScanHistory(finished_at=START - timedelta(minutes=10))
    stale = ScanHistory(finished_at=START - timedelta(minutes=20))
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")
    service = SettingsService(ConfigStore(paths.config_file), _NoSources())
    now = START + timedelta(days=3)
    unchanged = {"new": 0, "changed": 0, "missing": 0, "snapshots": 0, "problems": 0}
    rows = [
        ("old", "scheduler", {}, unchanged, timedelta(days=2, hours=1)),
        ("older", "scheduler", {}, unchanged, timedelta(days=2, hours=2)),
        ("newest", "scheduler", {}, unchanged, timedelta(days=2)),
        ("changed", "scheduler", {}, {**unchanged, "new": 1}, timedelta(days=3)),
        ("project", "scheduler", {"project": "raba"}, unchanged, timedelta(days=3)),
        ("asked", "local_owner", {}, unchanged, timedelta(days=3)),
    ]

    # Act
    def due(history: ScanHistory, minutes: float) -> bool:
        return plan_own_scan(
            settings, history, now=START + timedelta(minutes=minutes), started_at=START
        )

    with JobSupervisor(paths, service) as jobs:
        with sqlite3.connect(paths.index_file) as db:
            db.executemany(
                "INSERT INTO jobs (id, kind, actor, actor_kind, params, state,"
                " created_at, finished_at, summary)"
                " VALUES (?, 'own_scan', 'local', ?, ?, 'succeeded', ?, ?, ?)",
                [
                    (
                        job,
                        kind,
                        json.dumps(params),
                        (now - age).isoformat(),
                        (now - age).isoformat(),
                        json.dumps({**summary, "projects": 1, "files": 3}),
                    )
                    for job, kind, params, summary, age in rows
                ],
            )
        db.close()
        pruned = jobs.prune(now=now)
        left = {job.id for job in jobs.list(kind="own_scan").items}

    # Assert
    assert [due(ScanHistory(), 0), due(stale, 0), due(recent, 0)] == [True, True, False]
    assert [due(recent, 4.9), due(recent, 5)] == [False, True]
    assert due(ScanHistory(finished_at=START, busy=True), 60) is False
    assert pruned == 2
    assert left == {"newest", "changed", "project", "asked"}


class _NoSources:
    """A plugin registry without producers (settings are never validated here)."""

    def states(self) -> tuple[SourceState, ...]:
        """Report no plugin."""
        return ()

    def probe(self, producer: str, root: Path) -> SourceState:
        """Report the producer missing."""
        return SourceState(producer=producer, status="not_installed")
