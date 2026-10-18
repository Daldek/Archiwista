"""When the scheduler scans a store, and how (plan step 6b, SPEC 4.4)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from archiwista.config import AppSettings, StoreConfig, StoreKind
from archiwista.index import ScanMode
from archiwista.jobs import PlannedScan, ScanHistory, plan_scans

START = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)
STORE = "zespol"


def _settings(kind: StoreKind) -> AppSettings:
    store = StoreConfig(id=STORE, name="Zespół", kartograf=Path("/srv/dane"), kind=kind)
    return AppSettings(stores=(store,))


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
        # The daily control scan replaces a due incremental one.
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
