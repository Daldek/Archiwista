"""Contract with Kartograf's store API and of Archiwista's Kartograf adapter.

The adapter must see exactly what ``kartograf.iter_store`` sees in the
synthetic store (plan v0.1, step 4), read known versions only from their
directory listings, never confirm links during a scan and keep Kartograf's
pinned coordinate operations.
"""

import inspect
import json
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
import shapely
from packaging.specifiers import SpecifierSet
from packaging.version import Version

import archiwista.adapter.kartograf.adapter as adapter_module
from archiwista.adapter.kartograf import SUPPORTED_VERSIONS, load
from archiwista.adapter.kartograf.adapter import UNIT_CACHE_FILE, KartografAdapter
from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.sources import (
    Footprint,
    GeoJSONGeometry,
    ScanScope,
    SourceContext,
    SourceEntry,
)
from tests.fixtures.make_store import (
    LEGACY_KARTOGRAF,
    MIN_SLOTS,
    ExpectedEntry,
    StoreManifest,
    make_store,
)

EMPTY = inspect.Parameter.empty
POSITIONAL = inspect.Parameter.POSITIONAL_OR_KEYWORD
KEYWORD = inspect.Parameter.KEYWORD_ONLY

# KA-1..KA-6, list_segments and list_partitions (Kartograf ADR-045, ARCH
# 3.3.1): parameter name, kind and default.
STORE_API: dict[str, list[tuple[str, inspect._ParameterKind, object]]] = {
    "list_segments": [("root", POSITIONAL, EMPTY)],
    "list_partitions": [
        ("root", POSITIONAL, EMPTY),
        ("segment", POSITIONAL, EMPTY),
        ("target", KEYWORD, 32),
    ],
    "iter_store": [
        ("root", POSITIONAL, EMPTY),
        ("segment", KEYWORD, None),
        ("units", KEYWORD, None),
        ("skip_versions", KEYWORD, None),
        ("partition", KEYWORD, None),
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
    # The call of a stored version (KB-6, A-ADR-049 D-10).
    "command_for_file": [("sidecar", POSITIONAL, EMPTY)],
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
        "provider",
        "kartograf_version",
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


def _recorded_listings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    listed: list[str] = []
    real_scandir = os.scandir

    def recording(path: Any = ".") -> Any:
        listed.append(os.path.normpath(os.fspath(path)))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", recording)
    return listed


def _settled(entries: Iterable[SourceEntry]) -> dict[str, tuple[str, ...]]:
    """Version directories of a scan whose every file was a valid version."""
    found: dict[str, list[str]] = {}
    unsettled: set[str] = set()
    for entry in entries:
        directory = entry.relative_path.parent.as_posix()
        if entry.kind == "version":
            found.setdefault(directory, []).append(entry.relative_path.name)
        elif entry.kind == "problem":
            unsettled.add(directory)
    return {
        directory: tuple(names)
        for directory, names in found.items()
        if directory not in unsettled
    }


def _unflagged(entry: SourceEntry) -> tuple[object, ...]:
    """Return an entry's identity whether or not its metadata was read again."""
    return _key(entry)[:-1]


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


def test_installed_kartograf_within_supported_range() -> None:
    """The imported Kartograf is one the adapter declares it reads."""
    supported = SpecifierSet(SUPPORTED_VERSIONS)

    assert supported.contains(Version(kartograf.__version__), prereleases=True)


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
        assert sidecar is not None
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


def test_adapter_carries_the_common_core_of_the_sidecar(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """Provider, writing package and its version come from the sidecar (DEV-19.16)."""
    raw = {
        Path(e.path).relative_to(store.root): e
        for e in kartograf.iter_store(store.root)
    }

    found = {
        entry.relative_path: entry.meta
        for entry in adapter.iter_entries(store.root)
        if entry.meta is not None
    }

    for path, meta in found.items():
        sidecar = raw[path].sidecar
        assert sidecar is not None
        assert (meta.provider, meta.producer_version) == (
            sidecar.provider,
            sidecar.kartograf_version,
        )
        assert meta.written_by == ("kartograf" if sidecar.kartograf_version else None)
    assert {meta.provider for meta in found.values()} >= {"GUGiK", "CUZK"}
    assert {meta.producer_version for meta in found.values()} >= {
        kartograf.__version__,
        LEGACY_KARTOGRAF,
    }


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


def test_known_versions_are_neither_reread_nor_listed(
    store: StoreManifest, adapter: KartografAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Known version directories come back skipped, unopened and unlisted.

    An unchanged store gives the same entries; problems inside unsettled
    directories are found again.
    """
    root = store.root
    first = list(adapter.iter_entries(root))
    known = _settled(first)
    opened = _recorded_opens(monkeypatch)
    listed = _recorded_listings(monkeypatch)

    second = list(adapter.iter_entries(root, scope=ScanScope(known_versions=known)))

    files = {
        f"{directory}/{name}" for directory, names in known.items() for name in names
    }
    skipped = [e for e in second if e.skipped]
    assert {e.relative_path.as_posix() for e in skipped} == files
    assert all(e.kind == "version" and e.meta is None for e in skipped)
    assert not {str(root / f"{path}.meta.json") for path in files} & set(opened)
    assert not {os.path.normpath(root / directory) for directory in known} & set(listed)
    links = [e for e in second if e.kind in ("link", "full_sheet")]
    assert all(link.meta is not None for link in links)
    assert Counter(map(_unflagged, second)) == Counter(map(_unflagged, first))


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
    known = _settled(full)
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


def test_partitions_cover_each_segment_once(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """The parts of a segment read one by one give the segment's scan exactly.

    Their weights count the known version files of the segment.
    """
    root = store.root
    known = _settled(adapter.iter_entries(root))

    for segment in adapter.segments(root):
        mine = {
            directory: names
            for directory, names in known.items()
            if directory.startswith(f"{segment}/versions/")
        }
        parts = adapter.partitions(root, segment, mine)
        joined = [
            entry
            for part in parts
            for entry in adapter.iter_entries(
                root,
                scope=ScanScope(
                    segment=segment, partition=part.key, known_versions=mine
                ),
            )
        ]
        whole = adapter.iter_entries(
            root, scope=ScanScope(segment=segment, known_versions=mine)
        )

        assert Counter(map(_key, joined)) == Counter(map(_key, whole)), segment
        assert sum(part.weight for part in parts) == sum(map(len, mine.values()))
        assert len({part.key for part in parts}) == len(parts)


def test_partitions_of_a_missing_segment_are_none(
    store: StoreManifest, adapter: KartografAdapter
) -> None:
    """A segment gone from the store has no parts to read."""
    assert adapter.partitions(store.root, "nmt/brak_wariantu", {}) == ()


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


@pytest.mark.parametrize(
    ("src_crs", "dst_crs", "northing_first"),
    [
        ("EPSG:5514", "EPSG:3857", False),
        ("EPSG:2180", "EPSG:3857", True),
        ("EPSG:2180", "EPSG:5514", True),
    ],
)
def test_gdal_operation_matches_pinned_transform(
    adapter: KartografAdapter, src_crs: str, dst_crs: str, northing_first: bool
) -> None:
    """GDAL gets Kartograf's pinned operation, in any thread that uses it.

    The pipeline swaps the axes of a northing-first source CRS (EPSG:2180)
    first: GDAL hands coordinates over in the CRS's own axis order.
    """
    # Arrange
    transformer = adapter.transformer(src_crs, dst_crs)
    expected = kartograf.pinned_transform(src_crs, dst_crs).gdal_operation()

    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        pipelines = list(pool.map(lambda _: transformer.gdal_operation(), range(4)))

    # Assert
    assert pipelines == [expected] * 4
    assert expected.startswith("proj=pipeline step ")
    assert expected.startswith("proj=pipeline step proj=axisswap") is northing_first


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


def test_probe_accepts_the_generated_store_and_rejects_its_parent(
    store: StoreManifest, adapter: KartografAdapter, tmp_path: Path
) -> None:
    """Only the store root is a store; the generator marked it, a new one is empty."""
    empty = tmp_path / "new-store"
    empty.mkdir()

    assert adapter.probe(store.root).status == "available"
    assert adapter.probe(empty).status == "available"
    parent = adapter.probe(store.base)  # Kartograf: a store lies below it
    assert (parent.status, parent.reason) == ("incompatible", "foreign_store")
    assert parent.detail is not None and str(store.root) in parent.detail
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


def test_sheet_grid_outlines_each_zone_on_its_own_side(
    adapter: KartografAdapter,
) -> None:
    """Each PL-2000 zone's sheets are outlined only on its own side.

    Across the zone 6/7 boundary (Kartograf ADR-055: zones of powiats) the map
    never draws two grids over each other; a cut sheet keeps the extent of the
    whole sheet, by which ``GET /map/sheets`` sizes a view.
    """
    grid = adapter.sheet_grid((19.3, 51.95, 19.7, 52.05), "2000", "1:2000")
    shapes = [shapely.from_geojson(json.dumps(outline)) for outline in grid.outlines]
    by_zone: dict[int | None, list[Any]] = {}
    for zone, shape in zip(grid.zones, shapes, strict=True):
        by_zone.setdefault(zone, []).append(shape)

    overlap = shapely.intersection(
        shapely.union_all(by_zone[6]), shapely.union_all(by_zone[7])
    )
    assert set(by_zone) == {6, 7}
    assert list(grid.zones) == [int(sheet.split(".")[0]) for sheet in grid.sheets]
    assert shapely.area(overlap) < 1e-12  # square degrees: under 0.01 m2
    assert all(
        shapely.covers(shapely.box(*extent), shape)
        for extent, shape in zip(grid.extents, shapes, strict=True)
    )
    assert any(
        shapely.area(shape) < 0.9 * shapely.area(shapely.box(*extent))
        for extent, shape in zip(grid.extents, shapes, strict=True)
    )


def test_countries_of_a_border_area(adapter: KartografAdapter) -> None:
    """Countries come from Kartograf's country extents."""
    assert adapter.countries((18.0, 49.5, 18.5, 50.0)) == ("CZ", "PL")
    assert adapter.countries((20.0, 52.0, 20.1, 52.1)) == ("PL",)
