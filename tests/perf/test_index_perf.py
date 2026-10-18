r"""Index writer throughput and query latency on the 50 000-slot store (SPEC 4.5).

Run explicitly on the reference machine, against the generated store in an
explicit data directory (never in the repository or ``/tmp``)::

    python -m tests.fixtures.make_store --slots 50000 --seed 1 --projects 30 \\
        <katalog-danych>/store-50k
    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_index_perf.py -s

The index is built next to the store (``<katalog-danych>/perf-index/``) by a
plain sequential pass, so the writer's share of a scan is measured apart
from reading the store; the scanner's own targets belong to step 6a.
"""

import os
import shutil
import statistics
import time
import warnings
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.errors import ProducerError
from archiwista.index import (
    AreaFilter,
    IndexQueries,
    IndexWriter,
    ManifestStamp,
    MapQuery,
    SlotQuery,
)
from archiwista.sources import (
    GeoJSONGeometry,
    ScanScope,
    SegmentedAdapter,
    SourceAdapter,
    SourceEntry,
)
from archiwista.sources.registry import load_registry

pytestmark = pytest.mark.perf

STORE = "perf"
BATCH = 1000
RUNS = 40
LIST_MS = SEARCH_MS = CARD_MS = 200.0
MAP_MS = 300.0


@dataclass
class _Build:
    path: Path
    seconds: float
    write_seconds: float
    footprint_write_seconds: float
    entries: int
    versions_written: int
    rescan_write_seconds: float
    rescan_versions_written: int
    size_bytes: int


@pytest.fixture(scope="module")
def built() -> Iterator[_Build]:
    """Index the 50k store once: a full pass, then an unchanged rescan."""
    variable = os.environ.get("ARCHIWISTA_PERF_STORE")
    if not variable:
        pytest.skip("ARCHIWISTA_PERF_STORE names the generated 50 000-slot store")
    output = Path(variable)
    root = output / "data"
    work = output.parent / "perf-index"
    shutil.rmtree(work, ignore_errors=True)
    path = work / "index.sqlite"
    registry = load_registry(cache_dir=work / "cache")
    adapter = registry.adapter("kartograf")
    assert isinstance(adapter, SegmentedAdapter)
    warnings.filterwarnings("ignore", module="rasterio")
    with IndexWriter(path) as writer:
        writer.sync_stores({STORE: {"kartograf": root}})
        segments = adapter.segments(root)
        writer.write_segments(
            STORE, "kartograf", [adapter.describe_segment(name) for name in segments]
        )
        started = time.perf_counter()
        first = _pass(writer, adapter, root, segments, full=True)
        seconds = time.perf_counter() - started
        for manifest in sorted((output / "projects").glob("*/kartograf-project.json")):
            try:
                info = adapter.read_project(manifest.parent)
            except ProducerError:  # an invalid manifest stays out of this index
                continue
            stat = manifest.stat()
            writer.write_project(
                info,
                store=STORE if Path(info.store) == root else None,
                stamp=ManifestStamp(stat.st_mtime_ns, stat.st_size),
            )
        rescan = _pass(writer, adapter, root, segments, full=False)
    size = sum(
        item.stat().st_size for item in work.glob("index.sqlite*") if item.is_file()
    )
    yield _Build(
        path=path,
        seconds=seconds,
        write_seconds=first.write_seconds,
        footprint_write_seconds=first.footprint_seconds,
        entries=first.entries,
        versions_written=first.versions_written,
        rescan_write_seconds=rescan.write_seconds,
        rescan_versions_written=rescan.versions_written,
        size_bytes=size,
    )


@dataclass
class _PassTimes:
    entries: int = 0
    versions_written: int = 0
    write_seconds: float = 0.0
    footprint_seconds: float = 0.0


def _pass(
    writer: IndexWriter,
    adapter: SourceAdapter,
    root: Path,
    segments: tuple[str, ...],
    *,
    full: bool,
) -> _PassTimes:
    times = _PassTimes()
    writer.begin_pass(STORE, "kartograf", full=full)
    for segment in segments:
        known: Mapping[str, tuple[str, ...]] = {}
        if not full:
            known = writer.known_versions(segment)
        batch: list[SourceEntry] = []
        entries = adapter.iter_entries(
            root, scope=ScanScope(segment=segment, known_versions=known)
        )
        for entry in [*entries, None]:
            if entry is not None:
                batch.append(entry)
                if len(batch) < BATCH:
                    continue
            if not batch:
                break
            started = time.perf_counter()
            result = writer.write_entries(batch)
            times.write_seconds += time.perf_counter() - started
            times.entries += len(batch)
            times.versions_written += result.versions_written
            located = [
                (item, adapter.footprint(item)) for item in result.needs_footprint
            ]
            started = time.perf_counter()
            writer.write_footprints(STORE, located)
            times.footprint_seconds += time.perf_counter() - started
            batch = []
    started = time.perf_counter()
    writer.finish_pass()
    times.write_seconds += time.perf_counter() - started
    return times


def _p95(run: Callable[[], object]) -> tuple[float, float]:
    run()
    samples = []
    for _ in range(RUNS):
        started = time.perf_counter()
        run()
        samples.append((time.perf_counter() - started) * 1000)
    samples.sort()
    return samples[int(0.95 * (len(samples) - 1))], statistics.median(samples)


def _box(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> GeoJSONGeometry:
    ring = [
        [min_lon, min_lat],
        [max_lon, min_lat],
        [max_lon, max_lat],
        [min_lon, max_lat],
        [min_lon, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def test_index_perf_writer_share_of_a_scan(built: _Build) -> None:
    """A full pass writes every version once; an unchanged rescan writes none."""
    print(
        f"\nfull pass (sequential, read+write): {built.seconds:.1f} s;"
        f" write_entries {built.write_seconds:.1f} s for {built.entries} entries"
        f" ({built.write_seconds / built.entries * 1e6:.0f} µs/entry);"
        f" write_footprints {built.footprint_write_seconds:.1f} s"
    )
    print(
        f"unchanged rescan: write_entries {built.rescan_write_seconds:.2f} s,"
        f" versions written {built.rescan_versions_written};"
        f" index {built.size_bytes / 2**20:.0f} MiB"
    )
    assert built.versions_written > 75_000
    assert built.rescan_versions_written == 0
    assert built.rescan_write_seconds < 5.0
    assert built.size_bytes < 500 * 2**20


def test_index_perf_query_latency_p95(built: _Build) -> None:
    """List, search, map and card answers stay under the SPEC 4.5 p95 limits."""
    with IndexQueries(built.path) as queries:
        sample = queries.slots(
            SlotQuery(product="nmt", limit=1), visible=ALL_PROJECTS
        ).items[0]
        assert sample.version is not None and sample.version.sha256 is not None
        sha8 = sample.version.sha256[:8]
        version_path = sample.version.path
        deep = queries.slots(SlotQuery(limit=50), visible=ALL_PROJECTS)
        for _ in range(100):
            assert deep.next_cursor is not None
            deep = queries.slots(
                SlotQuery(limit=50, cursor=deep.next_cursor), visible=ALL_PROJECTS
            )
        area = AreaFilter(_box(19.0, 49.5, 19.5, 50.0), ("PL",))
        cases: dict[str, tuple[float, Callable[[], object]]] = {
            "list: first page": (
                LIST_MS,
                lambda: queries.slots(SlotQuery(limit=50), visible=ALL_PROJECTS),
            ),
            "list: page 101 (cursor)": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(limit=50, cursor=deep.next_cursor), visible=ALL_PROJECTS
                ),
            ),
            "list: product + years": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(product="orto", years=(2020, 2022), limit=50),
                    visible=ALL_PROJECTS,
                ),
            ),
            "list: all versions": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(versions="all", limit=50), visible=ALL_PROJECTS
                ),
            ),
            "list: not current, not pinned": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(versions="noncurrent_unpinned", limit=50),
                    visible=ALL_PROJECTS,
                ),
            ),
            "list: pinned": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(versions="pinned", limit=50), visible=ALL_PROJECTS
                ),
            ),
            "list: without location": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(location="none", limit=50), visible=ALL_PROJECTS
                ),
            ),
            "list: area 0.5°": (
                LIST_MS,
                lambda: queries.slots(
                    SlotQuery(area=area, limit=50), visible=ALL_PROJECTS
                ),
            ),
            "search: sheet code": (
                SEARCH_MS,
                lambda: queries.slots(
                    SlotQuery(q=sample.unit, limit=50), visible=ALL_PROJECTS
                ),
            ),
            "search: SHA-256 prefix": (
                SEARCH_MS,
                lambda: queries.slots(
                    SlotQuery(q=sha8, limit=50), visible=ALL_PROJECTS
                ),
            ),
            "search: common word '2023'": (
                SEARCH_MS,
                lambda: queries.slots(
                    SlotQuery(q="2023", limit=50), visible=ALL_PROJECTS
                ),
            ),
            "search: product name": (
                SEARCH_MS,
                lambda: queries.slots(
                    SlotQuery(q="ortofotomapa", limit=50), visible=ALL_PROJECTS
                ),
            ),
            "map: whole Poland (grid)": (
                MAP_MS,
                lambda: queries.footprints(
                    MapQuery(bbox=(14.0, 49.0, 24.2, 54.9)), visible=ALL_PROJECTS
                ),
            ),
            "map: city view": (
                MAP_MS,
                lambda: queries.footprints(
                    MapQuery(bbox=(19.0, 49.5, 19.6, 49.9)), visible=ALL_PROJECTS
                ),
            ),
            "map: all versions in a view": (
                MAP_MS,
                lambda: queries.footprints(
                    MapQuery(bbox=(19.0, 49.5, 19.6, 49.9), versions="all"),
                    visible=ALL_PROJECTS,
                ),
            ),
            "card: slot": (
                CARD_MS,
                lambda: queries.slot(STORE, sample.slot, visible=ALL_PROJECTS),
            ),
            "card: version": (
                CARD_MS,
                lambda: queries.version(STORE, version_path, visible=ALL_PROJECTS),
            ),
            "store: usage": (CARD_MS, lambda: queries.usage(STORE)),
            "health: status": (CARD_MS, queries.status),
        }
        measured = {name: _p95(run) for name, (_, run) in cases.items()}
    print()
    for name, (p95, median) in measured.items():
        print(f"{name:32} p95 {p95:7.1f} ms   median {median:7.1f} ms")
    over = {
        name: round(measured[name][0], 1)
        for name, (limit, _) in cases.items()
        if measured[name][0] > limit
    }
    assert over == {}
