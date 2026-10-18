"""Contract with Kartograf's store API and of Archiwista's Kartograf adapter.

The adapter must see exactly what ``kartograf.iter_store`` sees in the
synthetic store (plan v0.1, step 4), read known versions only from their
directory listings, never confirm links during a scan and keep Kartograf's
pinned coordinate operations.
"""

import importlib.metadata
import inspect
import os
import socket
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields, replace
from pathlib import Path
from typing import Any, cast

import kartograf
import numpy as np
import pytest
from packaging.requirements import Requirement
from packaging.version import Version

import archiwista.adapter.kartograf.adapter as adapter_module
from archiwista.adapter.kartograf import load
from archiwista.adapter.kartograf.adapter import UNIT_CACHE_FILE, KartografAdapter
from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.messages import MESSAGES
from archiwista.sources import (
    Footprint,
    GeoJSONGeometry,
    ProjectPin,
    ScanScope,
    SourceContext,
    SourceEntry,
)
from tests.fixtures.make_store import (
    MIN_SLOTS,
    ExpectedEntry,
    StoreManifest,
    make_store,
)

EMPTY = inspect.Parameter.empty
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD
KEYWORD = inspect.Parameter.KEYWORD_ONLY

# KA-1..KA-6 and list_segments (Kartograf ADR-045, ARCH 3.3.1): parameter
# name, kind and default.
STORE_API: dict[str, list[tuple[str, inspect._ParameterKind, object]]] = {
    "list_segments": [("output_dir", POSITIONAL, EMPTY)],
    "iter_store": [
        ("output_dir", POSITIONAL, EMPTY),
        ("segment", KEYWORD, None),
        ("units", KEYWORD, None),
        ("skip_versions", KEYWORD, None),
    ],
    "read_sidecar": [("path", POSITIONAL, EMPTY)],
    "describe_segment": [("segment", POSITIONAL, EMPTY)],
    "file_footprint": [
        ("entry", POSITIONAL, EMPTY),
        ("network", KEYWORD, False),
        ("cache", KEYWORD, None),
    ],
    "link_target": [("path", POSITIONAL, EMPTY)],
    "pinned_transform": [
        ("src_crs", POSITIONAL, EMPTY),
        ("dst_crs", POSITIONAL, EMPTY),
    ],
}
# Record fields the adapter reads.
STORE_RECORDS: dict[str, set[str]] = {
    "StoreEntry": {
        "kind",
        "segment",
        "hierarchy",
        "name",
        "path",
        "version_path",
        "label",
        "sha8",
        "sidecar",
        "problem",
        "skipped",
    },
    "Sidecar": {
        "dataset",
        "dataset_key",
        "country",
        "product",
        "request",
        "license",
        "downloaded_at",
        "extra",
        "sha256",
        "size_bytes",
        "data_year",
        "data_date",
        "campaign",
        "survey_work_id",
        "edition",
        "full_sheet",
        "coverage",
        "unit",
        "horizontal_crs",
        "vertical_crs",
        "resolution",
        "nodata",
        "raw",
    },
    "SegmentInfo": {"segment", "product", "country", "dataset_key", "name", "known"},
    "Footprint": {"native", "wgs84", "source"},
}
PRAGUE_SJTSK = (-743_000.0, -1_043_000.0)
PRAGUE_WGS84 = (14.4185946, 50.0873465)

type Key = tuple[str, str | None, Path, Path | None, str | None, bool]


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> StoreManifest:
    """Synthetic store of step 4, shared read-only by this module."""
    return make_store(tmp_path_factory.mktemp("store"), slots=MIN_SLOTS, seed=1)


@pytest.fixture
def adapter(tmp_path: Path) -> KartografAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, KartografAdapter)
    return created


def _key(entry: SourceEntry) -> Key:
    return (
        entry.kind,
        entry.segment,
        entry.relative_path,
        entry.version_path,
        entry.problem,
        entry.skipped,
    )


def _store_key(entry: Any, root: Path) -> Key:
    version = entry.version_path
    return (
        entry.kind,
        entry.segment,
        Path(entry.path).relative_to(root),
        None if version is None else Path(version).relative_to(root),
        entry.problem,
        entry.skipped,
    )


def _entry(entries: Iterable[SourceEntry], expected: ExpectedEntry) -> SourceEntry:
    return next(e for e in entries if e.relative_path == Path(expected.path))


def _ring(geometry: GeoJSONGeometry | None) -> list[tuple[float, float]]:
    assert geometry is not None and geometry["type"] == "Polygon"
    rings = cast(list[list[list[float]]], geometry["coordinates"])
    return [(x, y) for x, y in rings[0]]


def _bounds(geometry: GeoJSONGeometry | None) -> tuple[float, float, float, float]:
    xs, ys = zip(*_ring(geometry), strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def _contains(geometry: GeoJSONGeometry | None, x: float, y: float) -> bool:
    """Ray casting: whether a point lies inside a simple polygon."""
    ring = _ring(geometry)
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def _recorded_opens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    opened: list[str] = []
    real_open = os.open

    def recording(path: Any, *args: Any, **kwargs: Any) -> int:
        opened.append(os.fspath(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording)
    return opened


def _forbidden(message: str) -> Callable[..., Any]:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(message)

    return forbidden


@pytest.mark.parametrize("name", sorted(STORE_API))
def test_kartograf_exports_store_api_with_signatures(name: str) -> None:
    """KA-1..KA-6 and list_segments are public with the agreed signatures."""
    assert name in kartograf.__all__
    parameters = inspect.signature(getattr(kartograf, name)).parameters.values()

    assert [(p.name, p.kind, p.default) for p in parameters] == STORE_API[name]


@pytest.mark.parametrize("name", sorted(STORE_RECORDS))
def test_kartograf_exports_store_records_with_fields(name: str) -> None:
    """The records the adapter maps are public and carry the fields it reads."""
    assert name in kartograf.__all__
    names = {field.name for field in fields(getattr(kartograf, name))}

    assert STORE_RECORDS[name] <= names


def test_kartograf_bbox_and_pinned_transform_shape() -> None:
    """BBox keeps its five values; a pinned operation names its accuracy."""
    pinned = kartograf.pinned_transform("EPSG:2180", "EPSG:4326")

    assert kartograf.BBox._fields == ("min_x", "min_y", "max_x", "max_y", "crs")
    assert "InvalidSidecarError" in kartograf.__all__
    assert isinstance(pinned.description, str)
    assert isinstance(pinned.accuracy_m, float)


def test_installed_kartograf_within_pinned_range() -> None:
    """The imported Kartograf satisfies the pin of the installed Archiwista."""
    pins = [
        Requirement(line)
        for line in importlib.metadata.requires("archiwista") or []
        if Requirement(line).name == "kartograf"
    ]

    assert len(pins) == 1
    assert pins[0].specifier.contains(Version(kartograf.__version__), prereleases=True)


def test_adapter_entries_match_iter_store(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """The adapter yields what Kartograf sees, with metadata of the same pass."""
    root = store.root
    raw = list(kartograf.iter_store(root))

    entries = list(adapter.iter_entries(root))

    assert Counter(map(_key, entries)) == Counter(_store_key(e, root) for e in raw)
    assert {e.store for e in entries} == {str(root)}
    by_path = {Path(e.path).relative_to(root): e for e in raw}
    for entry in entries:
        sidecar = by_path[entry.relative_path].sidecar
        if entry.kind == "problem":
            assert entry.meta is None
            continue
        assert entry.meta is not None
        assert (
            entry.meta.sha256,
            entry.meta.size_bytes,
            entry.meta.data_year,
            entry.meta.unit,
            entry.meta.label,
        ) == (
            sidecar.sha256,
            sidecar.size_bytes,
            sidecar.data_year,
            sidecar.unit,
            by_path[entry.relative_path].label,
        )


def test_adapter_link_and_its_version_share_the_slot(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """A link's current version is found by the link's own slot path."""
    entries = list(adapter.iter_entries(store.root))
    versions = {e.relative_path: e for e in entries if e.kind == "version"}
    expected = {Path(e.path) for e in store.by_kind("link") if e.version_path}

    links = [e for e in entries if e.kind == "link" and e.version_path is not None]

    assert {link.relative_path for link in links} == expected
    for link in links:
        assert link.version_path is not None
        assert versions[link.version_path].slot_path == link.slot_path
        assert link.slot_path == link.relative_path


def test_known_versions_are_not_reread(
    store: StoreManifest, adapter: KartografAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known versions come back skipped, without metadata and unopened."""
    root = store.root
    first = list(adapter.iter_entries(root))
    known = frozenset(e.relative_path for e in first if e.kind == "version")
    opened = _recorded_opens(monkeypatch)

    second = list(adapter.iter_entries(root, scope=ScanScope(known_versions=known)))

    versions = [e for e in second if e.kind == "version"]
    assert {e.relative_path for e in versions} == known
    assert all(e.skipped and e.meta is None for e in versions)
    assert not {str(root / f"{path}.meta.json") for path in known} & set(opened)
    links = [e for e in second if e.kind in ("link", "full_sheet")]
    assert all(link.meta is not None for link in links)
    problems = Counter(_key(e) for e in second if e.kind == "problem")
    assert problems == Counter(_key(e) for e in first if e.kind == "problem")


def test_scan_never_calls_link_target(
    store: StoreManifest, adapter: KartografAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Full and incremental scans take the current version from link sidecars."""
    forbidden = _forbidden("link_target called during a scan")
    monkeypatch.setattr(kartograf, "link_target", forbidden)
    monkeypatch.setattr(adapter_module, "link_target", forbidden)
    expected = {
        Path(e.path): Path(e.version_path)
        for e in store.by_kind("link")
        if e.version_path is not None
    }

    full = list(adapter.iter_entries(store.root))
    known = frozenset(e.relative_path for e in full if e.kind == "version")
    incremental = list(
        adapter.iter_entries(store.root, scope=ScanScope(known_versions=known))
    )

    for scan in (full, incremental):
        links = {e.relative_path: e.version_path for e in scan if e.kind == "link"}
        assert {path: links[path] for path in expected} == expected


def test_segments_cover_full_scan(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """Scanning every segment separately gives exactly one unscoped scan."""
    root = store.root

    by_segment = [
        entry
        for segment in adapter.segments(root)
        for entry in adapter.iter_entries(root, scope=ScanScope(segment=segment))
    ]

    assert Counter(map(_key, by_segment)) == Counter(
        map(_key, adapter.iter_entries(root))
    )
    assert set(adapter.segments(root)) == set(store.segments())


def test_unit_scope_reads_only_the_unit_slots(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """A view refresh by units reads only those units of the segment."""
    teryt = next(e for e in store.by_family("zip_teryt") if e.kind == "link" and e.unit)
    assert teryt.unit is not None
    scope = ScanScope(segment=teryt.segment, units=(f"teryt/{teryt.unit}",))

    entries = list(adapter.iter_entries(store.root, scope=scope))

    assert {e.kind for e in entries} == {"link", "version"}
    assert {e.slot_path for e in entries} == {Path(teryt.path)}


def test_unit_footprint_from_local_cache_offline(
    store: StoreManifest,
    adapter: KartografAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A unit outline kept locally outlines new versions without network."""
    monkeypatch.setattr(socket.socket, "connect", _forbidden("network used"))
    teryt = next(
        e
        for e in store.by_family("zip_teryt")
        if e.kind == "version" and e.case == "regular" and e.unit
    )
    entry = _entry(adapter.iter_entries(store.root), teryt)
    before = adapter.footprint(entry)
    outline = kartograf.BBox(560_000.0, 240_000.0, 580_000.0, 260_000.0, "EPSG:2180")
    cache = UnitBBoxCache(tmp_path / "cache" / "kartograf" / UNIT_CACHE_FILE)
    cache[("teryt", str(teryt.unit))] = outline
    cache.close()

    found = adapter.footprint(entry, network=False)

    assert before == Footprint(location="none", reason="no_source")
    assert (found.location, found.source, found.native_crs) == (
        "footprint",
        "unit",
        "EPSG:2180",
    )
    assert found.native == {
        "type": "Polygon",
        "coordinates": [
            [
                [560_000.0, 240_000.0],
                [580_000.0, 240_000.0],
                [580_000.0, 260_000.0],
                [560_000.0, 260_000.0],
                [560_000.0, 240_000.0],
            ]
        ],
    }
    assert found.wgs84 is not None
    assert _contains(found.wgs84, 19.98, 50.11)
    assert adapter.footprint(replace(entry, handle=None)) == found


def test_footprint_locations_of_sheet_country_and_unreadable_files(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """Sheets are outlined, national files cover the country, problems none."""
    entries = list(adapter.iter_entries(store.root))
    sheet = next(e for e in store.by_family("asc_sheet") if e.kind == "version")
    country = next(e for e in store.by_family("zip_country") if e.kind == "version")
    problem = next(e for e in entries if e.problem == "invalid_sidecar")

    found = adapter.footprint(_entry(entries, sheet))

    assert (found.location, found.source) == ("footprint", "sheet")
    assert adapter.footprint(_entry(entries, country)) == Footprint(
        location="country", source="country"
    )
    assert adapter.footprint(problem) == Footprint(location="none", reason="unreadable")


def test_cz_transformation_uses_pinned_operation(adapter: KartografAdapter) -> None:
    """S-JTSK goes to WGS84 by the pinned datum step, the same in any thread."""
    transformer = adapter.transformer("EPSG:5514", "EPSG:4326")
    xs, ys = np.array([PRAGUE_SJTSK[0]]), np.array([PRAGUE_SJTSK[1]])

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: transformer.transform(xs, ys), range(8)))

    assert "S-JTSK to WGS 84" in transformer.description
    assert "Ballpark" not in transformer.description
    assert transformer.accuracy_m <= 1.0
    for lon, lat in results:
        assert (float(lon[0]), float(lat[0])) == pytest.approx(PRAGUE_WGS84, abs=1e-5)


def test_read_meta_matches_metadata_of_the_scan(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """Metadata read on demand equals the metadata of the scan."""
    entries = list(adapter.iter_entries(store.root))

    for entry in entries:
        if entry.kind != "problem":
            assert adapter.read_meta(replace(entry, meta=None, handle=None)) == (
                entry.meta
            )


def test_confirm_link_detects_link_that_moved_off_its_sidecar(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """On-demand confirmation agrees with a link and rejects a mismatched one."""
    entries = list(adapter.iter_entries(store.root))
    regular = next(
        e for e in store.by_kind("link") if e.case == "regular" and e.version_path
    )
    mismatch = next(e for e in store.by_kind("link") if e.case == "link_mismatch")

    assert adapter.confirm_link(_entry(entries, regular)) == Path(
        str(regular.version_path)
    )
    assert adapter.confirm_link(_entry(entries, mismatch)) is None


def test_probe_accepts_store_and_rejects_its_parent(
    store: StoreManifest, adapter: KartografAdapter, tmp_path: Path
) -> None:
    """Only Kartograf's ``--output`` directory is a store; a new one is empty."""
    empty = tmp_path / "new-store"
    empty.mkdir()

    assert adapter.probe(store.root).status == "available"
    assert adapter.probe(empty).status == "available"
    parent = adapter.probe(store.output_dir)
    assert (parent.status, parent.detail) == (
        "incompatible",
        MESSAGES["kartograf_not_store"],
    )
    assert adapter.probe(tmp_path / "missing").status == "error"


def test_scan_errors_keep_kartograf_messages(
    adapter: KartografAdapter, tmp_path: Path
) -> None:
    """A missing store is unavailable; Kartograf's own errors keep their text."""
    with pytest.raises(SourceUnavailableError):
        list(adapter.iter_entries(tmp_path / "missing"))
    with pytest.raises(ProducerError) as raised:
        list(adapter.iter_entries(tmp_path, scope=ScanScope(units=("1465",))))

    assert (raised.value.package, raised.value.exception) == (
        "kartograf",
        "ValidationError",
    )
    assert "units" in raised.value.message


def test_read_project_gives_tasks_and_pins_of_the_manifest(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """A project lists its tasks and pins, including older versions."""
    expected = store.project("projekt-01")

    project = adapter.read_project(store.output_dir / expected.path)

    assert project.store == str(store.root)
    assert [(t.task_id, t.command) for t in project.tasks] == [
        (t.name, t.command) for t in expected.tasks
    ]
    assert project.pins == tuple(
        ProjectPin(str(store.root), Path(pin.version), pin.sha256, task.name)
        for task in expected.tasks
        for pin in task.pins
    )


def test_project_status_reports_missing_and_undownloaded_tasks(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """Status names the worst pinned file of each task and of the project."""
    expected = store.project("projekt-01")
    regular = adapter.project_status(store.output_dir / expected.path)
    missing = adapter.project_status(store.output_dir / "projects" / "brak-wersji")

    assert {t.task_id: t.status for t in regular.tasks} == {
        task.name: "ok" if task.pins else "not_downloaded" for task in expected.tasks
    }
    assert regular.status == "not_downloaded"
    assert (missing.status, [t.status for t in missing.tasks]) == (
        "missing",
        ["missing"],
    )


def test_invalid_manifest_reports_kartograf_message(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """A broken manifest is Kartograf's validation error, text unchanged."""
    with pytest.raises(ProducerError) as raised:
        adapter.read_project(store.output_dir / "projects" / "zepsuty")

    assert (raised.value.package, raised.value.exception) == (
        "kartograf",
        "ValidationError",
    )
    assert raised.value.message


def test_sheet_grid_outlines_cover_the_area(adapter: KartografAdapter) -> None:
    """Grid sheets of both Polish systems come with WGS84 outlines."""
    area = (19.001, 50.001, 19.002, 50.002)
    grid_1992 = adapter.sheet_grid(area, "1992", "1:10000")
    grid_2000 = adapter.sheet_grid(area, "2000", "1:10000")

    assert grid_1992.sheets == ("M-34-63-C-c-3-3",)
    assert _bounds(grid_1992.outlines[0]) == pytest.approx(
        (19.0, 50.0, 19.03125, 50.0208333)
    )
    assert len(grid_2000.outlines) == len(grid_2000.sheets) == 1
    assert _contains(grid_2000.outlines[0], 19.0015, 50.0015)


def test_countries_of_a_border_area(adapter: KartografAdapter) -> None:
    """Countries come from Kartograf's country extents."""
    assert adapter.countries((18.0, 49.5, 18.5, 50.0)) == ("CZ", "PL")
    assert adapter.countries((20.0, 52.0, 20.1, 52.1)) == ("PL",)
