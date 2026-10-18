r"""Scan and view refresh times on the 50 000-slot store (SPEC 4.5, step 6a).

Run explicitly on the reference machine, against the generated store in an
explicit data directory (never in the repository or ``/tmp``)::

    python -m tests.fixtures.make_store --slots 50000 --seed 1 --projects 30 \\
        <katalog-danych>/store-50k
    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_scan_perf.py -s

The store is scanned as a local disk (``kind = "local"``, the SSD targets)
into ``<katalog-danych>/perf-scan/``, rebuilt on each run: a full scan, then
an unchanged incremental scan, then view refreshes of 500 indexed slots.
"""

import os
import shutil
import statistics
import threading
import time
import warnings
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import pytest

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexQueries, IndexWriter, SlotUnit
from archiwista.index.scanner import (
    REFRESH_VIEW_MAX_UNITS,
    ScanSummary,
    refresh_view,
    scan_store,
)
from archiwista.sources import SourceAdapter
from archiwista.sources.registry import load_registry

pytestmark = pytest.mark.perf

STORE = "perf"
SEGMENT = "nmt/pl_1992_1m_evrf2007"
RUNS = 30
FULL_S = 120.0
INCREMENTAL_S = 20.0
REFRESH_S = 1.0
INDEX_BYTES = 500 * 2**20


@dataclass
class _Scanned:
    path: Path
    adapter: SourceAdapter
    settings: AppSettings
    full: ScanSummary
    full_s: float
    incremental: ScanSummary
    incremental_s: float
    peak_rss_mib: float
    peak_anonymous_mib: float


def _memory_kib() -> dict[str, int]:
    """Return the peak and heap memory of this process in KiB.

    ``VmHWM`` is the peak of all resident pages (the mapped index
    included), ``RssAnon`` the resident heap now.
    """
    with open("/proc/self/status", encoding="ascii") as status:
        fields = dict(line.split(":", 1) for line in status)
    return {key: int(fields[key].split()[0]) for key in ("VmHWM", "RssAnon")}


class _AnonymousPeak:
    """Sample the resident heap while scans run (``/proc`` keeps no peak)."""

    def __init__(self) -> None:
        self.kib = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *details: object) -> None:
        self._stop.set()
        self._thread.join()

    def _sample(self) -> None:
        while not self._stop.wait(0.05):
            self.kib = max(self.kib, _memory_kib()["RssAnon"])


@pytest.fixture(scope="module")
def scanned() -> Iterator[_Scanned]:
    """Scan the 50k store fully, then again incrementally without changes."""
    variable = os.environ.get("ARCHIWISTA_PERF_STORE")
    if not variable:
        pytest.skip("ARCHIWISTA_PERF_STORE names the generated 50 000-slot store")
    output = Path(variable)
    work = output.parent / "perf-scan"
    shutil.rmtree(work, ignore_errors=True)
    path = work / "index.sqlite"
    config = StoreConfig(id=STORE, name=STORE, kartograf=output / "data", kind="local")
    settings = AppSettings(stores=(config,), project_dirs=(output / "projects",))
    adapter = load_registry(cache_dir=work / "cache").adapter("kartograf")
    warnings.filterwarnings("ignore", module="rasterio")
    with IndexWriter(path) as writer, _AnonymousPeak() as anonymous:
        writer.sync_stores({STORE: config.roots()})
        started = time.perf_counter()
        full = scan_store(adapter, writer, settings, STORE, mode="full")
        full_s = time.perf_counter() - started
        started = time.perf_counter()
        incremental = scan_store(adapter, writer, settings, STORE)
        incremental_s = time.perf_counter() - started
    yield _Scanned(
        path,
        adapter,
        settings,
        full,
        full_s,
        incremental,
        incremental_s,
        _memory_kib()["VmHWM"] / 1024,
        anonymous.kib / 1024,
    )


def test_scan_perf_full_and_unchanged_incremental(scanned: _Scanned) -> None:
    """Full scan ≤ 120 s and an unchanged incremental scan ≤ 20 s on SSD."""
    full, incremental = scanned.full, scanned.incremental
    size = sum(item.stat().st_size for item in scanned.path.parent.glob("index*"))
    print(
        f"\nfull scan {scanned.full_s:.1f} s: {full.entries} entries,"
        f" {full.versions_written} versions, {full.footprints_written} footprints"
        f" ({full.footprints_failed} failed)"
    )
    print(
        f"unchanged incremental scan {scanned.incremental_s:.1f} s:"
        f" {incremental.entries} entries, {incremental.versions_written} written"
    )
    print(
        f"index {size / 2**20:.0f} MiB; peak RSS {scanned.peak_rss_mib:.0f} MiB"
        f" (with pytest and the mapped index), peak heap (RssAnon)"
        f" {scanned.peak_anonymous_mib:.0f} MiB"
    )
    print("segment                                  entries   full s   incr s")
    times = {item.segment: item for item in incremental.segments}
    for item in full.segments:
        again = times[item.segment]
        print(
            f"{item.segment or '-':40} {item.entries:7} {item.seconds:8.1f}"
            f" {again.seconds:8.1f}"
        )
    assert full.versions_written > 75_000
    assert incremental.versions_written == incremental.links_changed == 0
    assert incremental.finished.missing == 0
    assert size < INDEX_BYTES
    assert scanned.full_s <= FULL_S
    assert scanned.incremental_s <= INCREMENTAL_S


def test_scan_perf_refresh_view_of_500_slots(scanned: _Scanned) -> None:
    """A view refresh of 500 indexed slots takes ≤ 1 s at p95 on SSD."""
    with (
        IndexWriter(scanned.path) as writer,
        IndexQueries(scanned.path) as queries,
    ):
        found = queries.slots_in_bbox(STORE, (14.0, 49.0, 24.2, 54.9), segment=SEGMENT)
        view: list[SlotUnit] = [item for item in found if item.unit][
            :REFRESH_VIEW_MAX_UNITS
        ]
        units = [item.unit or "" for item in view]
        slots = [item.slot for item in view]

        def run(known: list[str]) -> float:
            started = time.perf_counter()
            refresh_view(
                scanned.adapter,
                writer,
                queries,
                scanned.settings,
                STORE,
                SEGMENT,
                units,
                known_slots=known,
            )
            return time.perf_counter() - started

        run(slots)
        known = sorted(run(slots) for _ in range(RUNS))
        unknown = sorted(run([]) for _ in range(RUNS // 3))
    p95 = known[int(0.95 * (len(known) - 1))]
    print(
        f"\nrefresh_view of {len(units)} slots: p95 {p95 * 1000:.0f} ms,"
        f" median {statistics.median(known) * 1000:.0f} ms; without known slots"
        f" median {statistics.median(unknown) * 1000:.0f} ms"
    )
    assert len(units) == REFRESH_VIEW_MAX_UNITS
    assert p95 <= REFRESH_S
