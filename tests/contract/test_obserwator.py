"""Contract with Obserwator's store API and of Archiwista's Obserwator adapter.

The adapter must see exactly what ``obserwator.iter_store`` sees in each root
of the producer's own offline fixture stores (``obserwator.testing``, its
ADR-017): archives and their observations in the raw root, series and station
catalogs in the data root, every version as a version, a version the producer
cannot read as its problem and nothing parsed, an observation never as a
version; each path lies in a tree Archiwista places in that root, and the
origin of each version's data follows its tree and the provider the producer
names (A-ADR-055). It judges a directory as either root by the marker file
names and schemas, and every judgement is pinned to what the producer itself
does with the same directory as a root of that kind.
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import obserwator
import pytest
from obserwator import (
    Meta,
    ObserwatorDataError,
    ObserwatorError,
    ObserwatorStoreConflictError,
    StoreHandle,
    init_store,
    iter_store,
    open_store,
    read_meta,
    store_info,
)
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from archiwista.adapter.obserwator import (
    PACKAGE,
    PRODUCER,
    SCHEMAS,
    SUPPORTED_VERSIONS,
    load,
)
from archiwista.adapter.obserwator.adapter import ObserwatorAdapter
from archiwista.errors import ProducerError, SourceUnavailableError, UnsupportedError
from archiwista.sources import (
    CurrentVersionAdapter,
    DataOriginAdapter,
    DataRootAdapter,
    GeoAdapter,
    LinkCheckAdapter,
    PartitionedAdapter,
    ScanScope,
    SegmentDescriptionAdapter,
    SegmentedAdapter,
    SheetGridAdapter,
    SourceAdapter,
    SourceContext,
    SourceEntry,
    SourceSegment,
    SourceState,
    VersionCommandAdapter,
)
from archiwista.sources.markers import directory_field
from tests.fixtures.network import no_network
from tests.fixtures.obserwator_edits import add_version, drop_sidecar, rewrite_sidecar
from tests.fixtures.obserwator_roots import data_root, raw_root, root_of

type Stores = Callable[[str], Path]
type Row = tuple[object, ...]
# A kind of Obserwator root (its ADR-017): the raw root of the archives, the
# data root of what Obserwator builds from them.
type Kind = Literal["raw", "data"]

KINDS: tuple[Kind, ...] = ("raw", "data")
OTHER: Mapping[Kind, Kind] = {"raw": "data", "data": "raw"}
# The root of each kind in a fixture store, how the adapter judges it, the
# marker Obserwator writes into it, a tree of its layout and the settings field
# Archiwista keeps it in.
ROOTS: Mapping[Kind, Callable[[Path], Path]] = {"raw": raw_root, "data": data_root}
PROBES: Mapping[Kind, Callable[[ObserwatorAdapter, Path], SourceState]] = {
    "raw": ObserwatorAdapter.probe,
    "data": ObserwatorAdapter.probe_data,
}
MARKERS: Mapping[Kind, str] = {
    "raw": "obserwator-store.json",
    "data": "obserwator-data.json",
}
LAYOUTS: Mapping[Kind, str] = {"raw": "archives", "data": "series"}
FIELDS: Mapping[Kind, str] = {"raw": "obserwator", "data": "obserwator_data"}
# The schema of each marker this Obserwator writes, and a later one it refuses.
MARKER_SCHEMAS: Mapping[Kind, str] = {
    "raw": "obserwator-store/1",
    "data": "obserwator-data/1",
}
NEWER_SCHEMAS: Mapping[Kind, str] = {
    "raw": "obserwator-store/2",
    "data": "obserwator-data/2",
}

HYDRO = "pl.imgw.hydro_daily"
ARCHIVE_SLOT = Path("archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024")
ARCHIVE_KEY = "archive:pl.imgw.hydro_daily:2024/codz_2024.zip"
SERIES_KEY = "series:pl.imgw.hydro_daily"
HYDRO_SERIES = Path("series/versions/imgw_hydro_daily")
PL_CATALOG = Path("stations/versions/imgw_stations")
CZ_CATALOG = Path("stations/versions/chmu_stations")
CZ_REGISTER_SLOT = Path(
    "archives/versions/hydrology/historical/data/daily/H_0-203-1-900001_DQ_2023"
)


@pytest.fixture
def adapter(tmp_path: Path) -> ObserwatorAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "obserwator"))
    assert isinstance(created, ObserwatorAdapter)
    return created


def _label(entry: SourceEntry) -> str | None:
    return None if entry.meta is None else entry.meta.label


def _rows(entries: list[SourceEntry]) -> Counter[Row]:
    """Return what the adapter says of each entry: kind, slot, path, label, SHA-256."""
    return Counter(
        (
            entry.kind,
            getattr(entry.handle, "slot", None),
            entry.relative_path,
            _label(entry),
            None if entry.meta is None else entry.meta.sha256,
            entry.problem,
        )
        for entry in entries
    )


def _produced_version(meta: Meta) -> Mapping[str, object]:
    """Return the ``extra.version`` object of the producer's own parse of a sidecar."""
    version = meta.extra["version"]
    assert isinstance(version, Mapping)
    return version


def _produced_label(meta: Meta | None) -> object:
    """Return the version label of the producer's own parse of a sidecar."""
    return None if meta is None else _produced_version(meta)["label"]


def _producer_rows(root: Path) -> Counter[Row]:
    """Return the same rows from the producer's own scan."""
    kinds = {"problem": "problem", "observation": "observation"}
    return Counter(
        (
            kinds.get(entry.kind, "version"),
            entry.slot,
            None if entry.version is None else entry.version.relative_to(root),
            _produced_label(entry.meta),
            None if entry.meta is None else entry.meta.sha256,
            entry.problem_code,
        )
        for entry in iter_store(root)
    )


def _entries(adapter: ObserwatorAdapter, root: Path) -> list[SourceEntry]:
    return list(adapter.iter_entries(root))


def _store_entries(adapter: ObserwatorAdapter, store: Path) -> list[SourceEntry]:
    """Return the entries of both roots of a fixture store, each relative to its root.

    The trees of the two roots differ, so no path of one is a path of the other.
    """
    return [entry for kind in KINDS for entry in _entries(adapter, ROOTS[kind](store))]


def _copy(obserwator_store: Stores, store: Path, variant: str = "complete") -> Path:
    """Copy a shared fixture store, both roots, so that a test can change it."""
    shutil.copytree(obserwator_store(variant), store)
    return store


def test_installed_obserwator_within_supported_range() -> None:
    """The imported Obserwator is one the adapter declares it reads."""
    supported = SpecifierSet(SUPPORTED_VERSIONS)

    assert supported.contains(Version(obserwator.__version__), prereleases=True)
    assert (PRODUCER, PACKAGE) == ("obserwator", "obserwator")
    assert SCHEMAS == (
        "obserwator-store/1",
        "obserwator-data/1",
        "obserwator-meta/1",
        "obserwator-series/1",
    )


def test_the_supported_range_starts_at_obserwator_3_2() -> None:
    """Obserwator 3.1.x is outside the range: the adapter reads what 3.2.0 writes.

    The sidecar's ``tier`` and ``publication``, the captures, the hourly series of one
    version per month and ČHMÚ's groundwater came with 3.2.0 (A-ADR-059); the range
    starts at the release, its development versions outside it (REL-5.6).
    """
    supported = SpecifierSet(SUPPORTED_VERSIONS)

    assert not supported.contains(Version("3.1.0"), prereleases=True)
    assert not supported.contains(Version("3.2.0.dev0"), prereleases=True)
    assert supported.contains(Version("3.2.0"), prereleases=True)
    assert not supported.contains(Version("4.0.0"), prereleases=True)


def test_adapter_implements_the_source_interface_and_describes_its_datasets(
    adapter: ObserwatorAdapter,
) -> None:
    """The store has no segments to scan, links, sheets or coordinate operations."""
    assert isinstance(adapter, SourceAdapter)
    assert isinstance(adapter, DataRootAdapter)
    assert isinstance(adapter, SegmentDescriptionAdapter)
    assert isinstance(adapter, CurrentVersionAdapter)
    assert not any(
        isinstance(adapter, capability)
        for capability in (
            SegmentedAdapter,
            PartitionedAdapter,
            GeoAdapter,
            LinkCheckAdapter,
            SheetGridAdapter,
        )
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_entries_equal_what_iter_store_yields(
    obserwator_store: Stores, adapter: ObserwatorAdapter, variant: str, kind: Kind
) -> None:
    """Kind, slot, path, label and SHA-256 of every entry of a root are the producer's.

    Each path lies in a tree that Archiwista places in that root by its first
    part (``directory_field``, A-ADR-056), so the index reads it there again.
    """
    root = ROOTS[kind](obserwator_store(variant))

    entries = _entries(adapter, root)

    assert _rows(entries) == _producer_rows(root)
    assert {entry.store for entry in entries} == {str(root)}
    assert {entry.producer for entry in entries} == {"obserwator"}
    assert {directory_field(PRODUCER, e.relative_path) for e in entries} == {
        FIELDS[kind]
    }


def test_a_relabeled_version_is_the_same_content_under_a_new_label(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """A republished archive is its own version; older ones stay versions."""
    entries = _entries(adapter, raw_root(obserwator_store("complete")))

    versions = [e for e in entries if e.slot_path == ARCHIVE_SLOT]

    assert [e.kind for e in versions] == ["version"] * 3
    metas = {_label(e): e.meta for e in versions}
    assert set(metas) == {"2026-10-17", "2026-10-18", "2026-10-19"}
    first, relabeled, newer = (metas[label] for label in sorted(map(str, metas)))
    assert first is not None and relabeled is not None and newer is not None
    assert first.sha256 == relabeled.sha256 != newer.sha256
    assert {e.relative_path.parent.parent for e in versions} == {ARCHIVE_SLOT}


def test_series_and_catalogs_are_versions_and_nothing_is_a_problem(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """Series (also an outdated one) and the station catalog are versions."""
    entries = _store_entries(adapter, obserwator_store("complete"))

    series = Counter(e.segment for e in entries if e.relative_path.parts[0] == "series")

    assert series == {HYDRO: 2, "pl.imgw.meteo_precip_daily": 1}
    assert {e.kind for e in entries} == {"version"}
    (catalog,) = [e for e in entries if e.segment == "pl.imgw.stations"]
    assert catalog.slot_path == PL_CATALOG
    assert catalog.meta is not None and catalog.meta.provider == "IMGW"


@pytest.mark.parametrize(
    ("variant", "code", "slot"),
    [
        ("corrupt", "invalid_json", ARCHIVE_SLOT),
        ("unknown_schema", "unknown_schema", HYDRO_SERIES),
    ],
)
def test_a_version_the_producer_cannot_read_is_its_problem_and_nothing_is_parsed(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    variant: str,
    code: str,
    slot: Path,
) -> None:
    """The producer's problem code is the entry's; the rest of its root is read."""
    root = root_of(obserwator_store(variant), slot)

    entries = _entries(adapter, root)

    (problem,) = [e for e in entries if e.kind == "problem"]
    assert (problem.problem, problem.meta, problem.version_path) == (code, None, None)
    assert (problem.slot_path, problem.segment) == (slot, HYDRO)
    assert _rows(entries) == _producer_rows(root)
    with pytest.raises(ProducerError):
        adapter.read_meta(problem)


def test_an_observation_is_history_and_never_a_version(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """A source republished the same content: the register belongs to the slot."""
    entries = _entries(adapter, raw_root(obserwator_store("complete_pl_cz")))

    (observation,) = [e for e in entries if e.kind == "observation"]
    (version,) = [
        e for e in entries if e.kind == "version" and e.slot_path == CZ_REGISTER_SLOT
    ]

    assert (observation.slot_path, observation.segment) == (
        CZ_REGISTER_SLOT,
        "cz.chmu.hydro_daily",
    )
    assert observation.relative_path.parent == CZ_REGISTER_SLOT / "observations"
    assert observation.meta is None
    assert observation.version_path == version.relative_path
    record = getattr(observation.handle, "observation", None)
    assert (
        record is not None
        and record.same_content_as == version.relative_path.parent.name
    )
    assert adapter.footprint(observation).location == "none"


def test_an_observation_carries_the_signal_the_producer_kept(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """When the source served the bytes, from where, and their size and digest."""
    entries = _entries(adapter, raw_root(obserwator_store("complete_pl_cz")))

    (observation,) = [e for e in entries if e.kind == "observation"]

    produced = getattr(observation.handle, "observation", None)
    assert produced is not None and observation.observation is not None
    seen = datetime.strptime(produced.seen_at, "%Y-%m-%dT%H:%M:%SZ")
    assert observation.observation.seen_at == seen.replace(tzinfo=UTC)
    assert (
        observation.observation.url,
        observation.observation.etag,
        observation.observation.last_modified,
        observation.observation.size_bytes,
        observation.observation.sha256,
    ) == (
        produced.url,
        produced.etag,
        produced.last_modified,
        produced.size_bytes,
        produced.sha256,
    )
    assert all(e.observation is None for e in entries if e.kind != "observation")


def test_a_slot_has_the_producers_key_and_a_name_for_people(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """The key is the producer's own; an archive is its file, a catalog its key."""
    store = obserwator_store("complete_pl_cz")

    entries = _store_entries(adapter, store)

    keys = {(e.store, e.relative_path): e.slot_key for e in entries}
    assert keys == {
        (str(root), e.version.relative_to(root)): e.slot
        for root in (raw_root(store), data_root(store))
        for e in iter_store(root)
        if e.version
    }
    names = {e.slot_key: e.slot_name for e in entries}
    assert names["archive:pl.imgw.hydro_daily:2024/codz_2024.zip"] == "codz_2024.zip"
    cz_file = "precipitation/dly-0-203-0-90001-SRA.csv"
    assert (
        names[f"archive:cz.chmu.meteo_daily:{cz_file}"] == "dly-0-203-0-90001-SRA.csv"
    )
    assert names["catalog:pl.imgw.stations"] == "pl.imgw.stations"
    assert names["catalog:cz.chmu.stations"] == "cz.chmu.stations"
    # A series is named by its directory, which says what it is.
    assert names["series:pl.imgw.hydro_daily"] is None
    assert {
        e.slot_path.name
        for e in entries
        if e.slot_key == "series:cz.chmu.hydro_daily" and e.slot_path
    } == {"chmu_hydro_daily"}


def test_a_problem_without_a_slot_has_no_key_and_no_dataset(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """A stray item of the store belongs to no slot, so it has no segment."""
    root = raw_root(_copy(obserwator_store, tmp_path / "store"))
    stray = root / "archives" / "versions" / "stray"
    stray.mkdir()
    (stray / "notes.txt").write_text("x", encoding="utf-8")

    entries = _entries(adapter, root)

    (found,) = [e for e in entries if e.relative_path.name == "stray"]
    assert (found.kind, found.problem) == ("problem", "unknown_entry")
    assert (found.slot_key, found.segment, found.slot_path) == (None, None, None)


def test_a_dataset_of_the_registry_is_described_by_its_polish_title_country_and_family(
    adapter: ObserwatorAdapter,
) -> None:
    """A segment is a dataset: its name, its provider's country and its family."""
    assert adapter.describe_segment(HYDRO) == SourceSegment(
        HYDRO, "hydro", "PL", HYDRO, "Dane hydrologiczne dobowe", True
    )
    czech = adapter.describe_segment("cz.chmu.hydro_daily")
    assert (czech.country, czech.dataset_key, czech.known) == (
        "CZ",
        "cz.chmu.hydro_daily",
        True,
    )
    assert {
        key: adapter.describe_segment(key).product
        for key in (
            "pl.imgw.meteo_precip_daily",
            "cz.chmu.meteo_daily",
            "cz.chmu.hydro_stations",
            "pl.imgw.pmaxtp",
        )
    } == {
        "pl.imgw.meteo_precip_daily": "meteo",
        "cz.chmu.meteo_daily": "meteo",
        "cz.chmu.hydro_stations": "hydro",
        "pl.imgw.pmaxtp": "imgw_pmaxtp",
    }


@pytest.mark.parametrize("key", [dataset.key for dataset in obserwator.datasets()])
def test_every_dataset_of_the_registry_is_a_known_segment_of_its_providers_country(
    adapter: ObserwatorAdapter, key: str
) -> None:
    """The registry is the producer's own, so no dataset is left unrecognised."""
    dataset = obserwator.get_dataset(key)
    provider = obserwator.get_provider(dataset.provider)

    described = adapter.describe_segment(key)

    assert (described.known, described.country, described.dataset_key) == (
        True,
        provider.country,
        key,
    )
    # The family the producer declares; a dataset without one (PMAXTP, and from
    # Obserwator 3.3.0 Gdańskie Wody's station list and month files) is its own,
    # named by its slug.
    assert described.product == (dataset.kind or dataset.slug)
    assert described.name not in ("", key)


def test_a_station_catalog_is_named_after_its_provider_and_an_unknown_key_by_itself(
    adapter: ObserwatorAdapter,
) -> None:
    """The catalogs are slots of the store but no datasets of the registry."""
    assert adapter.describe_segment("pl.imgw.stations") == SourceSegment(
        "pl.imgw.stations",
        "stations",
        "PL",
        "pl.imgw.stations",
        "Katalog stacji IMGW-PIB",
        True,
    )
    assert adapter.describe_segment("cz.chmu.stations") == SourceSegment(
        "cz.chmu.stations",
        "stations",
        "CZ",
        "cz.chmu.stations",
        "Katalog stacji ČHMÚ",
        True,
    )
    assert adapter.describe_segment("pl.imgw.removed_dataset") == SourceSegment(
        "pl.imgw.removed_dataset", None, None, None, "pl.imgw.removed_dataset", False
    )


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz", "corrupt"])
def test_every_dataset_a_fixture_store_names_is_recognised(
    obserwator_store: Stores, adapter: ObserwatorAdapter, variant: str
) -> None:
    """What the producer writes into a store, its registry knows."""
    entries = _store_entries(adapter, obserwator_store(variant))

    segments = {e.segment for e in entries if e.segment}

    assert segments
    assert all(adapter.describe_segment(name).known for name in segments)


def test_the_two_providers_keep_their_datasets_catalogs_and_countries_apart(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """IMGW-PIB and ČHMÚ files and station catalogs do not collide."""
    entries = _store_entries(adapter, obserwator_store("complete_pl_cz"))

    metas = [e.meta for e in entries if e.meta is not None]
    catalogs = {e.segment: e for e in entries if e.relative_path.parts[0] == "stations"}

    assert {(m.provider, m.country) for m in metas} == {
        ("IMGW", "PL"),
        ("CHMU", "CZ"),
    }
    assert {e.segment[:3] for e in entries if e.segment and e.meta} == {"pl.", "cz."}
    assert {name: e.slot_path for name, e in catalogs.items()} == {
        "pl.imgw.stations": PL_CATALOG,
        "cz.chmu.stations": CZ_CATALOG,
    }
    assert {name: e.meta.provider for name, e in catalogs.items() if e.meta} == {
        "pl.imgw.stations": "IMGW",
        "cz.chmu.stations": "CHMU",
    }
    slots = Counter(e.slot_path for e in entries if e.kind == "version")
    assert slots[PL_CATALOG] == slots[CZ_CATALOG] == 1


def test_the_canonical_content_of_a_chmu_file_is_kept_and_is_none_for_imgw(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """The producer's canonical content rides along; nothing is computed."""
    entries = _entries(adapter, raw_root(obserwator_store("complete_pl_cz")))

    forms = {
        (e.segment, e.meta.content_form, e.meta.content_sha256 is None)
        for e in entries
        if e.meta is not None and e.relative_path.parts[0] == "archives"
    }

    assert ("cz.chmu.hydro_daily", "chmu-json/1", False) in forms
    assert (HYDRO, None, True) in forms
    assert ("cz.chmu.meteo_daily", None, True) in forms


def test_the_origin_of_a_version_is_its_trees_form_of_its_providers_data(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """An archive is the file as published, a series or catalog a processed form."""
    entries = _store_entries(adapter, obserwator_store("complete_pl_cz"))

    origins = {
        (
            e.relative_path.parts[0],
            e.meta.provider,
            adapter.data_origin(e.relative_path.as_posix(), e.segment),
        )
        for e in entries
        if e.kind == "version" and e.meta is not None
    }

    assert isinstance(adapter, DataOriginAdapter)
    assert origins == {
        ("archives", "IMGW", "imgw_file"),
        ("series", "IMGW", "imgw_processed"),
        ("stations", "IMGW", "imgw_stations"),
        ("archives", "CHMU", "chmu_file"),
        ("series", "CHMU", "chmu_processed"),
        ("stations", "CHMU", "chmu_processed"),
    }
    cell = "pmaxtp/versions/POT/751_317/2026-10-25_3f9c2a71/cell.json"
    assert adapter.data_origin(cell, None) == "pmaxtp"
    assert adapter.data_origin("archives/versions/a/b.zip", "xx.other.data") is None


@pytest.mark.parametrize("slot", [ARCHIVE_SLOT, HYDRO_SERIES, PL_CATALOG], ids=str)
def test_read_meta_carries_the_common_core_for_an_archive_a_series_and_a_catalog(
    obserwator_store: Stores, adapter: ObserwatorAdapter, slot: Path
) -> None:
    """DEV-19.16: the fields every sidecar has, read again on demand."""
    root = root_of(obserwator_store("complete"), slot)
    entry = next(e for e in _entries(adapter, root) if e.slot_path == slot)

    meta = adapter.read_meta(replace(entry, meta=None, handle=None))

    produced = read_meta(root / entry.relative_path)
    assert meta == entry.meta
    assert (meta.dataset, meta.dataset_key, meta.country, meta.provider) == (
        produced.dataset,
        produced.dataset_key,
        produced.country,
        produced.provider,
    )
    assert (meta.sha256, meta.size_bytes, meta.downloaded_at) == (
        produced.sha256,
        produced.size_bytes,
        produced.downloaded_at,
    )
    assert (meta.license, meta.attribution) == (
        produced.license.id,
        produced.license.attribution,
    )
    assert (meta.written_by, meta.producer_version) == (
        produced.producer,
        produced.producer_version,
    )
    assert (meta.written_by, meta.producer_version) == (
        "obserwator",
        obserwator.__version__,
    )
    assert (meta.label, meta.label_source) == (
        _produced_label(produced),
        _produced_version(produced)["label_source"],
    )
    assert meta.raw_sidecar is not None
    assert meta.raw_sidecar["schema"] == "obserwator-meta/1"
    assert meta.raw_sidecar["producer"] == "obserwator"
    assert meta.raw_sidecar["producer_version"] == produced.producer_version
    assert meta.raw_sidecar["request"] == produced.request
    assert meta.raw_sidecar["extra"] == produced.extra
    assert bool(meta.source_files) == (slot == HYDRO_SERIES)


def test_an_unknown_dataset_key_has_no_current_key(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """``dataset_key`` is ``None`` for a key the producer does not know."""
    store = _copy(obserwator_store, tmp_path / "store")
    sidecar = next(raw_root(store).glob(f"{ARCHIVE_SLOT}/*/codz_2024.zip.meta.json"))
    document = json.loads(sidecar.read_text(encoding="utf-8"))
    document["dataset"] = "pl.imgw.removed_dataset"
    sidecar.write_text(json.dumps(document), encoding="utf-8")

    entries = _store_entries(adapter, store)

    (renamed,) = [
        e.meta
        for e in entries
        if e.meta and e.meta.dataset == "pl.imgw.removed_dataset"
    ]
    assert renamed.dataset_key is None
    assert all(e.meta.dataset_key for e in entries if e.meta and e.meta is not renamed)


def test_footprint_of_an_archive_and_a_series_is_their_country(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """A file of IMGW-PIB or ČHMÚ covers a country; a catalog has no place."""
    entries = _store_entries(adapter, obserwator_store("complete_pl_cz"))

    found = {
        (e.relative_path.parts[0], adapter.footprint(e).location)
        for e in entries
        if e.kind == "version"
    }

    assert found == {
        ("archives", "country"),
        ("series", "country"),
        ("stations", "none"),
    }
    catalog = adapter.footprint(
        next(e for e in entries if e.segment == "pl.imgw.stations")
    )
    assert (catalog.location, catalog.reason) == ("none", "no_source")
    country = adapter.footprint(next(e for e in entries if e.segment == HYDRO))
    assert (country.location, country.source) == ("country", "country")


def test_scan_errors_and_scopes(adapter: ObserwatorAdapter, tmp_path: Path) -> None:
    """A missing store is unavailable; the store has no segments to scan."""
    with pytest.raises(SourceUnavailableError):
        list(adapter.iter_entries(tmp_path / "missing"))
    for scope in (
        ScanScope(segment=HYDRO),
        ScanScope(units=("1",)),
        ScanScope(partition="a"),
    ):
        with pytest.raises(ValueError, match="no segments"):
            adapter.iter_entries(tmp_path, scope=scope)


def _known(entries: list[SourceEntry]) -> dict[str, tuple[str, ...]]:
    """Return the versions an index reports to a scan: directory → data files."""
    known: dict[str, list[str]] = {}
    for entry in entries:
        if entry.kind == "version":
            directory = entry.relative_path.parent.as_posix()
            known.setdefault(directory, []).append(entry.relative_path.name)
    return {directory: tuple(names) for directory, names in known.items()}


def _places(entries: list[SourceEntry]) -> Counter[Row]:
    """Return where each entry lies and what it is, not what was read of it."""
    return Counter(
        (e.kind, e.segment, e.slot_path, e.relative_path, e.problem) for e in entries
    )


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_known_versions_come_back_skipped_with_no_sidecar_read(
    obserwator_store: Stores, adapter: ObserwatorAdapter, variant: str, kind: Kind
) -> None:
    """``known_versions`` is ``skip_versions``: the same entries, no version read."""
    root = ROOTS[kind](obserwator_store(variant))
    full = _entries(adapter, root)

    again = list(
        adapter.iter_entries(root, scope=ScanScope(known_versions=_known(full)))
    )

    assert _places(again) == _places(full)
    versions = [e for e in again if e.kind == "version"]
    assert versions and all(e.skipped and e.meta is None for e in versions)
    assert not any(e.skipped for e in again if e.kind != "version")


def test_what_is_not_known_is_read_in_full(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """Read what is not known in full; a known version is not looked at.

    A new version has its meta and a new broken one is a problem; the caller
    vouches for a known one, and a scan that names none sees what broke.
    """
    store = _copy(obserwator_store, tmp_path / "store")
    raw, data = raw_root(store), data_root(store)
    known = {root: _known(_entries(adapter, root)) for root in (raw, data)}
    fresh = add_version(raw, ARCHIVE_SLOT.as_posix(), label="2026-10-22")
    broken = add_version(raw, ARCHIVE_SLOT.as_posix(), label="2026-10-23")
    drop_sidecar(raw, broken)
    (series,) = [p for p in known[data] if p.startswith(f"{HYDRO_SERIES}/")][:1]
    vouched = f"{series}/series.json"
    drop_sidecar(data, vouched)

    scoped = [
        entry
        for root, versions in known.items()
        for entry in adapter.iter_entries(
            root, scope=ScanScope(known_versions=versions)
        )
    ]
    unscoped = _store_entries(adapter, store)

    by_path = {e.relative_path.as_posix(): e for e in scoped}
    assert (by_path[fresh].skipped, by_path[fresh].meta is not None) == (False, True)
    assert (by_path[vouched].skipped, by_path[vouched].meta) == (True, None)
    problems = [(e.problem, e.relative_path.as_posix()) for e in scoped if e.problem]
    assert problems == [("missing_sidecar", Path(broken).parent.as_posix())]
    assert sorted(e.relative_path.as_posix() for e in unscoped if e.problem) == sorted(
        [Path(broken).parent.as_posix(), series]
    )


def test_a_version_written_by_an_older_release_keeps_its_number(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """The sidecar's ``producer`` and ``producer_version`` are the file's own."""
    store = _copy(obserwator_store, tmp_path / "store")
    raw = raw_root(store)
    older = next(e for e in _entries(adapter, raw) if e.slot_path == ARCHIVE_SLOT)
    rewrite_sidecar(raw, older.relative_path.as_posix(), producer_version="2.9.0")

    entries = {e.relative_path: e for e in _store_entries(adapter, store)}

    meta = entries[older.relative_path].meta
    assert meta is not None and meta.raw_sidecar is not None
    assert (meta.written_by, meta.producer_version) == ("obserwator", "2.9.0")
    assert meta.raw_sidecar["producer_version"] == "2.9.0"
    others = {
        e.meta.producer_version
        for path, e in entries.items()
        if e.meta is not None and path != older.relative_path
    }
    assert others == {obserwator.__version__}


@pytest.mark.parametrize("kind", KINDS)
def test_a_path_with_a_link_is_refused_by_the_producer_with_its_message(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path, kind: Kind
) -> None:
    """Obserwator reads no path with a symbolic link; its message is kept."""
    link = tmp_path / "link"
    link.symlink_to(ROOTS[kind](obserwator_store("complete")), target_is_directory=True)

    with pytest.raises(ProducerError) as raised:
        list(adapter.iter_entries(link))

    assert (raised.value.package, raised.value.exception) == (
        "obserwator",
        "ObserwatorStoreError",
    )
    state = PROBES[kind](adapter, link)
    assert (state.status, state.detail) == ("error", raised.value.message)


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_the_current_version_of_every_slot_is_the_producers_relative_to_its_root(
    obserwator_store: Stores, adapter: ObserwatorAdapter, variant: str
) -> None:
    """The adapter asks Obserwator and answers with the path of a version it lists.

    Each slot is asked of the root it lies in: an archive of the raw root, a
    series and a station catalog of the data root.
    """
    entries = _store_entries(adapter, obserwator_store(variant))
    roots = {e.slot_key: Path(e.store) for e in entries if e.slot_key}

    answers = {key: adapter.current_version(root, key) for key, root in roots.items()}

    produced = {
        key: obserwator.current_version(root, slot=key) for key, root in roots.items()
    }
    assert roots and all(answers.values())
    assert answers == {
        key: found.version.relative_to(roots[key])
        for key, found in produced.items()
        if found is not None and found.version is not None
    }
    listed = {(e.slot_key, e.relative_path) for e in entries if e.kind == "version"}
    assert {(key, answer) for key, answer in answers.items() if answer} <= listed
    # Of the three versions of an archive, the newest is the current one.
    by_label = {
        _label(e): e.relative_path for e in entries if e.slot_path == ARCHIVE_SLOT
    }
    assert answers[ARCHIVE_KEY] == by_label[max(map(str, by_label))]


@pytest.mark.parametrize(
    ("key", "kind"),
    [(ARCHIVE_KEY, "data"), (SERIES_KEY, "raw"), ("catalog:pl.imgw.stations", "raw")],
    ids=["archive", "series", "catalog"],
)
def test_a_slot_asked_of_the_root_of_the_other_kind_is_the_producers_refusal(
    obserwator_store: Stores, adapter: ObserwatorAdapter, key: str, kind: Kind
) -> None:
    """Not a slot without a version: Obserwator refuses the root (``wrong_root``)."""
    root = ROOTS[kind](obserwator_store("complete"))
    with pytest.raises(ObserwatorError) as produced:
        obserwator.current_version(root, slot=key)

    with pytest.raises(ProducerError) as raised:
        adapter.current_version(root, key)

    assert produced.value.details["reason"] == "wrong_root"
    assert (raised.value.exception, raised.value.message) == (
        type(produced.value).__name__,
        str(produced.value),
    )


def test_a_version_without_its_sidecar_is_skipped_and_the_older_one_answers(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """An interrupted publication is no version: the version before it is current."""
    root = raw_root(_copy(obserwator_store, tmp_path / "store"))
    before = adapter.current_version(root, ARCHIVE_KEY)
    newest = add_version(root, ARCHIVE_SLOT.as_posix(), label="2026-10-30")
    assert adapter.current_version(root, ARCHIVE_KEY) == Path(newest)

    drop_sidecar(root, newest)

    assert before is not None and before != Path(newest)
    assert adapter.current_version(root, ARCHIVE_KEY) == before


@pytest.mark.parametrize(
    ("variant", "key", "kind"),
    [("corrupt", ARCHIVE_KEY, "raw"), ("unknown_schema", SERIES_KEY, "data")],
)
def test_a_broken_version_leaves_its_slot_without_a_current_version(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    variant: str,
    key: str,
    kind: Kind,
) -> None:
    """The producer refuses to choose, and an older version is not chosen instead."""
    root = ROOTS[kind](obserwator_store(variant))
    older = [e for e in _entries(adapter, root) if e.slot_key == key and e.meta]

    with pytest.raises(ObserwatorDataError):
        obserwator.current_version(root, slot=key)

    assert older
    assert adapter.current_version(root, key) is None


@pytest.mark.parametrize(
    "damage",
    [
        lambda root, version: rewrite_sidecar(root, version, size_bytes=7),
        lambda root, version: rewrite_sidecar(root, version, dataset="no dataset"),
        lambda root, version: (root / version).with_name("notes.txt").write_text("x"),
    ],
    ids=["size_mismatch", "invalid_meta", "stray_file"],
)
def test_every_way_a_version_is_broken_leaves_the_slot_without_a_current_version(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    damage: Callable[[Path, str], object],
) -> None:
    """A size that differs, an invalid field and a stray file are all refused."""
    root = raw_root(_copy(obserwator_store, tmp_path / "store"))
    version = adapter.current_version(root, ARCHIVE_KEY)
    assert version is not None

    damage(root, version.as_posix())

    with pytest.raises(ObserwatorDataError):
        obserwator.current_version(root, slot=ARCHIVE_KEY)
    assert adapter.current_version(root, ARCHIVE_KEY) is None


def test_a_slot_the_producer_cannot_read_has_no_current_version_and_no_error(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """A slot an earlier scan indexed must not fail the scan that finds it gone."""
    store = _copy(obserwator_store, tmp_path / "store")
    raw, data = raw_root(store), data_root(store)
    directory = raw / ARCHIVE_SLOT
    moved = directory.with_name("codz_2024_moved")
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)

    assert adapter.current_version(raw, ARCHIVE_KEY) is None
    assert adapter.current_version(data, "series:pl.imgw.removed_dataset") is None
    assert adapter.current_version(raw, "no grammar of the producer") is None
    absent = "archive:pl.imgw.hydro_daily:1999/codz_1999.zip"
    assert adapter.current_version(raw, absent) is None


@pytest.mark.parametrize(("kind", "key"), [("raw", ARCHIVE_KEY), ("data", SERIES_KEY)])
def test_a_root_that_is_no_store_anymore_is_the_producers_refusal(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    kind: Kind,
    key: str,
) -> None:
    """The root, not the slot, is the problem: the error of Obserwator is kept."""
    root = ROOTS[kind](_copy(obserwator_store, tmp_path / "store"))
    (root / MARKERS[kind]).unlink()

    with pytest.raises(ProducerError) as raised:
        adapter.current_version(root, key)

    assert (raised.value.package, raised.value.exception) == (
        "obserwator",
        "ObserwatorStoreError",
    )


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_a_sidecar_the_system_cannot_read_is_an_unavailable_store(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """A file that cannot be read is the system's problem, as in a scan."""
    root = raw_root(_copy(obserwator_store, tmp_path / "store"))
    version = adapter.current_version(root, ARCHIVE_KEY)
    assert version is not None
    sidecar = root / f"{version.as_posix()}.meta.json"
    sidecar.chmod(0)

    try:
        with pytest.raises(SourceUnavailableError):
            adapter.current_version(root, ARCHIVE_KEY)
    finally:
        sidecar.chmod(0o644)


type Build = Callable[[Path, Path, Kind], None]


@dataclass(frozen=True)
class Case:
    """A directory of the probe table: how it is built, the verdict, the producer's.

    The directory is judged as a root of either kind (``probe`` the raw root,
    ``probe_data`` the data root): ``build`` makes it, for the kind judged, of
    the fixture store's roots, and the verdict is the same for both kinds.
    ``code`` is the first of the ``StoreInfo.problem_codes`` the reader gives
    (``None`` for a root it reads): the adapter judges by it, and by the
    names in the directory where one code covers several directories.
    ``call`` is the Obserwator writer call that pins the verdict, given the
    kind judged: ``init_store`` or ``open_store``. ``refused`` says whether the
    writer refuses the directory and ``why`` is the ``details.reason`` of the
    refusal.
    """

    name: str
    build: Build
    status: str
    reason: str | None
    code: str | None
    call: str
    refused: bool
    why: str | None = None


def _marker_of(root: Path, kind: Kind) -> dict[str, object]:
    return json.loads((root / MARKERS[kind]).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _empty(root: Path, store: Path, kind: Kind) -> None:
    root.mkdir()


def _state_file_only(root: Path, store: Path, kind: Kind) -> None:
    root.mkdir()
    (root / "api_keys.json").write_text("{}", encoding="utf-8")


def _whole_root(root: Path, store: Path, kind: Kind) -> None:
    shutil.copytree(ROOTS[kind](store), root)


def _other_root(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, OTHER[kind])


def _with_other_trees(root: Path, store: Path, kind: Kind) -> None:
    """Copy the root with the trees of the other kind beside its own: not yet split."""
    _whole_root(root, store, kind)
    for tree in ROOTS[OTHER[kind]](store).iterdir():
        if tree.is_dir() and not tree.name.startswith("."):
            shutil.copytree(tree, root / tree.name)


def _other_root_with_these_trees(root: Path, store: Path, kind: Kind) -> None:
    _with_other_trees(root, store, OTHER[kind])


def _no_marker(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, kind)
    (root / MARKERS[kind]).unlink()


def _layout_only(root: Path, store: Path, kind: Kind) -> None:
    (root / LAYOUTS[kind]).mkdir(parents=True)


def _other_layout_only(root: Path, store: Path, kind: Kind) -> None:
    _layout_only(root, store, OTHER[kind])


def _other_schema(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, kind)
    marker = {**_marker_of(root, kind), "schema": NEWER_SCHEMAS[kind]}
    (root / MARKERS[kind]).write_text(json.dumps(marker), encoding="utf-8")


def _marker_not_json(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, kind)
    (root / MARKERS[kind]).write_text("{not json", encoding="utf-8")


def _without_created_by(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, kind)
    marker = _marker_of(root, kind)
    del marker["created_by"]
    (root / MARKERS[kind]).write_text(json.dumps(marker), encoding="utf-8")


def _both_markers(root: Path, store: Path, kind: Kind) -> None:
    _whole_root(root, store, kind)
    other = OTHER[kind]
    shutil.copy(ROOTS[other](store) / MARKERS[other], root)


def _kartograf(root: Path, store: Path, kind: Kind) -> None:
    root.mkdir()
    marker = {"schema": "kartograf-store/1", "tool": "kartograf"}
    (root / "kartograf-store.json").write_text(json.dumps(marker), encoding="utf-8")


def _kartograf_with_layout(root: Path, store: Path, kind: Kind) -> None:
    _kartograf(root, store, kind)
    (root / LAYOUTS[kind]).mkdir()


def _parent_of_a_store(root: Path, store: Path, kind: Kind) -> None:
    root.mkdir()
    shutil.copytree(ROOTS[kind](store), root / "magazyn")


def _other_files(root: Path, store: Path, kind: Kind) -> None:
    root.mkdir()
    (root / "notatki.txt").write_text("to nie magazyn", encoding="utf-8")


UNSUPPORTED = ("incompatible", "unsupported_marker")
WRONG_ROOT = ("incompatible", "wrong_root")
NO_MARKER = "missing_marker"
CASES = [
    Case("empty", _empty, "available", None, NO_MARKER, "init_store", False),
    Case(
        "state_file_only",
        _state_file_only,
        "available",
        None,
        NO_MARKER,
        "init_store",
        False,
    ),
    Case("root", _whole_root, "available", None, None, "open_store", False),
    Case(
        "with_other_trees",
        _with_other_trees,
        "available",
        None,
        None,
        "open_store",
        False,
    ),
    Case(
        "other_root",
        _other_root,
        *WRONG_ROOT,
        None,
        "open_store",
        True,
        "wrong_root",
    ),
    Case(
        "other_root_with_these_trees",
        _other_root_with_these_trees,
        *WRONG_ROOT,
        None,
        "open_store",
        True,
        "wrong_root",
    ),
    Case(
        "no_marker",
        _no_marker,
        "incompatible",
        "no_marker",
        NO_MARKER,
        "open_store",
        True,
        "no_marker",
    ),
    Case(
        "layout_only",
        _layout_only,
        "incompatible",
        "no_marker",
        NO_MARKER,
        "open_store",
        True,
        "no_marker",
    ),
    Case(
        "other_layout_only",
        _other_layout_only,
        "incompatible",
        "not_a_store",
        NO_MARKER,
        "init_store",
        True,
        "not_empty",
    ),
    Case(
        "other_schema",
        _other_schema,
        *UNSUPPORTED,
        "unsupported_store",
        "open_store",
        True,
        "unsupported",
    ),
    Case(
        "marker_not_json",
        _marker_not_json,
        *UNSUPPORTED,
        "invalid_marker",
        "open_store",
        True,
        "invalid_marker",
    ),
    Case(
        "both_markers",
        _both_markers,
        *UNSUPPORTED,
        "conflicting_markers",
        "init_store",
        True,
        "nested_store",
    ),
    Case(
        "no_created_by",
        _without_created_by,
        "available",
        None,
        None,
        "open_store",
        False,
    ),
    Case(
        "kartograf",
        _kartograf,
        "incompatible",
        "foreign_store",
        NO_MARKER,
        "init_store",
        True,
        "nested_store",
    ),
    Case(
        "kartograf_with_layout",
        _kartograf_with_layout,
        "incompatible",
        "foreign_store",
        NO_MARKER,
        "init_store",
        True,
        "nested_store",
    ),
    Case(
        "parent_of_a_store",
        _parent_of_a_store,
        "incompatible",
        "not_a_store",
        NO_MARKER,
        "init_store",
        True,
        "nested_store",
    ),
    Case(
        "other_files",
        _other_files,
        "incompatible",
        "not_a_store",
        NO_MARKER,
        "init_store",
        True,
        "not_empty",
    ),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_probe_judges_a_directory_as_the_producer_does(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    case: Case,
    kind: Kind,
) -> None:
    """Each verdict on a directory as either root is pinned to what Obserwator does."""
    root = tmp_path / "root"
    case.build(root, obserwator_store("complete"), kind)

    state = PROBES[kind](adapter, root)

    assert (state.status, state.reason) == (case.status, case.reason)
    assert (state.store, state.package_version) == (str(root), obserwator.__version__)
    assert (state.supported_versions, state.schemas) == (SUPPORTED_VERSIONS, SCHEMAS)
    assert (state.detail is None) == (case.status == "available")
    assert (state.hint is None) == (case.reason != "no_marker")
    assert next(iter(store_info(root).problem_codes), None) == case.code
    calls: Mapping[str, Callable[..., StoreHandle]] = {
        "init_store": init_store,
        "open_store": open_store,
    }
    if not case.refused:
        assert calls[case.call](root, kind=kind).root == root
    else:
        with pytest.raises(ObserwatorError) as refused:
            calls[case.call](root, kind=kind)
        assert refused.value.details.get("reason") == case.why
        assert isinstance(refused.value, ObserwatorStoreConflictError) == (
            case.call == "init_store"
        )


@pytest.mark.parametrize(
    ("kind", "options"),
    [("raw", {}), ("data", {"kind": "data"})],
    ids=["raw", "data"],
)
def test_init_store_turns_a_missing_marker_into_an_available_store(
    obserwator_store: Stores,
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    kind: Kind,
    options: dict[str, str],
) -> None:
    """``obserwator store init`` of the kind, the hint, makes the root readable.

    The hint is a command line that Obserwator itself reads as that call.
    """
    root = tmp_path / "magazyn z spacją"
    _no_marker(root, obserwator_store("complete"), kind)

    before = PROBES[kind](adapter, root)
    init_store(root, kind=kind)
    after = PROBES[kind](adapter, root)

    assert (before.status, before.reason) == ("incompatible", "no_marker")
    assert before.hint is not None and shlex.split(before.hint)[0] == "obserwator"
    hinted = obserwator.parse_command(before.hint)
    assert (hinted.command, dict(hinted.options)) == (
        "store init",
        {"root": str(root), **options},
    )
    assert before.detail is not None and before.hint in before.detail
    assert (after.status, after.reason, after.hint) == ("available", None, None)
    assert _rows(_entries(adapter, root)) == _producer_rows(root)


@pytest.mark.parametrize("kind", KINDS)
def test_an_unsupported_marker_names_both_schemas(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path, kind: Kind
) -> None:
    """The text says what the marker has and what this version reads."""
    root = tmp_path / "root"
    _other_schema(root, obserwator_store("complete"), kind)

    state = PROBES[kind](adapter, root)

    assert state.detail is not None
    assert NEWER_SCHEMAS[kind] in state.detail
    assert MARKER_SCHEMAS[kind] in state.detail


@pytest.mark.parametrize("kind", KINDS)
def test_a_directory_that_cannot_be_listed_is_an_error_not_a_verdict(
    adapter: ObserwatorAdapter, tmp_path: Path, kind: Kind
) -> None:
    """A missing directory and a file are ``error`` with no reason."""
    (tmp_path / "file").write_text("x", encoding="utf-8")

    states = [PROBES[kind](adapter, tmp_path / name) for name in ("missing", "file")]

    assert [state.status for state in states] == ["error", "error"]
    assert all(state.detail and state.reason is None for state in states)


def test_the_adapter_reads_a_store_without_pyarrow(
    obserwator_store: Stores, tmp_path: Path
) -> None:
    """Reading needs no Parquet file: the adapter never imports ``pyarrow``."""
    store = obserwator_store("complete_pl_cz")
    script = """
import sys
from pathlib import Path

sys.modules["pyarrow"] = None
from archiwista.adapter.obserwator import load
from archiwista.sources import SourceContext

adapter = load(SourceContext(cache_dir=Path(sys.argv[3])))
raw, data = Path(sys.argv[1]), Path(sys.argv[2])
assert adapter.probe(raw).status == "available"
assert adapter.probe_data(data).status == "available"
entries = [*adapter.iter_entries(raw), *adapter.iter_entries(data)]
for entry in entries:
    if entry.kind == "version":
        adapter.read_meta(entry)
        adapter.footprint(entry)
print(len(entries))
"""
    roots = [str(raw_root(store)), str(data_root(store))]

    result = subprocess.run(
        [sys.executable, "-c", script, *roots, str(tmp_path / "cache")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert int(result.stdout) > 20


def _stored(root: Path, slot: str) -> str:
    """Return the first version in ``root`` of a slot whose key begins with ``slot``."""
    return next(
        entry.version.relative_to(root).as_posix()
        for entry in iter_store(root)
        if entry.version is not None
        and entry.slot is not None
        and entry.slot.startswith(slot)
    )


def test_command_for_version_of_an_archive_is_obserwator_call_without_the_root(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """The call Obserwator rebuilds offline, the store root left to the caller."""
    # Arrange
    root = raw_root(obserwator_store("complete"))
    version = _stored(root, ARCHIVE_KEY)
    produced = obserwator.command_for_version(version, root=root)

    # Act
    with no_network() as attempts:
        call = adapter.command_for_version(version, root=root)

    # Assert
    assert isinstance(adapter, VersionCommandAdapter)
    assert attempts == []
    assert (call.producer, call.command) == ("obserwator", produced.command)
    assert "root" in produced.options
    assert dict(call.options) == {
        name: value for name, value in produced.options.items() if name != "root"
    }
    assert call.options["datasets"] == [HYDRO]


def test_command_for_version_of_a_catalog_built_from_a_users_file_is_refused(
    obserwator_store: Stores, adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """``unsupported``, ``command_not_rebuildable``, Obserwator's text unchanged."""
    # Arrange
    root = data_root(_copy(obserwator_store, tmp_path / "store"))
    version = _stored(root, "catalog:")
    request = dict(read_meta(root / version).request)
    rewrite_sidecar(root, version, request={**request, "user_locations": "moje.csv"})
    with pytest.raises(ObserwatorError) as produced:
        obserwator.command_for_version(version, root=root)

    # Act
    with pytest.raises(UnsupportedError) as raised:
        adapter.command_for_version(version, root=root)

    # Assert
    error = raised.value
    assert (error.code, error.details["reason"]) == (
        "unsupported",
        "command_not_rebuildable",
    )
    assert error.message == str(produced.value)
    assert error.details["version"] == version


@pytest.mark.parametrize("kind", ["series", "catalog"])
def test_command_for_version_of_a_series_or_a_catalog_is_refused_as_built_offline(
    obserwator_store: Stores, adapter: ObserwatorAdapter, kind: str
) -> None:
    """``unsupported``, ``command_not_rebuildable``: Archiwista runs no build.

    Obserwator rebuilds the call of a version of the data root, a build from the
    raw root, which is no command of the adapter (A-ADR-056).
    """
    # Arrange
    root = data_root(obserwator_store("complete"))
    version = _stored(root, f"{kind}:")
    produced = obserwator.command_for_version(version, root=root)

    # Act
    with pytest.raises(UnsupportedError) as raised:
        adapter.command_for_version(version, root=root)

    # Assert
    error = raised.value
    assert (error.code, error.details["reason"]) == (
        "unsupported",
        "command_not_rebuildable",
    )
    assert (error.details["producer"], error.details["version"]) == (
        "obserwator",
        version,
    )
    assert produced.command not in {command.command for command in adapter.commands()}


def test_command_for_version_of_no_version_is_obserwator_refusal_with_its_code(
    obserwator_store: Stores, adapter: ObserwatorAdapter
) -> None:
    """A path that is no stored version: ``ProducerError``, never ``unsupported``."""
    # Arrange
    root = raw_root(obserwator_store("complete"))
    version = "archives/versions/nic/2026-01-01_00000000/nic.zip"
    with pytest.raises(ObserwatorError) as produced:
        obserwator.command_for_version(version, root=root)

    # Act
    with pytest.raises(ProducerError) as raised:
        adapter.command_for_version(version, root=root)

    # Assert
    assert raised.value.code == produced.value.code
    assert raised.value.code != "unsupported"


def test_command_for_version_outside_a_store_keeps_obserwator_hint(
    adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """A root that is no store: Obserwator's code, text and hint unchanged."""
    # Arrange
    root = tmp_path / "missing"
    version = "archives/versions/nic/2026-01-01_00000000/nic.zip"
    with pytest.raises(ObserwatorError) as produced:
        obserwator.command_for_version(version, root=root)

    # Act
    with pytest.raises(ProducerError) as raised:
        adapter.command_for_version(version, root=root)

    # Assert
    assert produced.value.hint
    assert (raised.value.code, raised.value.message, raised.value.hint) == (
        produced.value.code,
        str(produced.value),
        produced.value.hint,
    )
