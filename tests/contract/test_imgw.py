"""Contract with IMGWTools' store API and of Archiwista's IMGW adapter.

The adapter must see exactly what ``imgwtools.iter_store`` sees in the
producer's own offline fixture stores (``imgwtools.testing``): archives,
series and station catalogs as versions, a version the producer cannot read
as its problem and nothing parsed, an observation never as a version. It
judges a directory by the marker file name and schema, and every judgement
is pinned to what the producer itself does with the same directory.
"""

import json
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import imgwtools
import pytest
from imgwtools import (
    IMGWError,
    IMGWStoreConflictError,
    Meta,
    add_project_task,
    init_project,
    init_store,
    iter_store,
    open_store,
    read_meta,
    store_info,
)
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from archiwista.adapter.imgw import (
    PACKAGE,
    PRODUCER,
    SCHEMAS,
    SUPPORTED_VERSIONS,
    load,
)
from archiwista.adapter.imgw.adapter import ImgwAdapter
from archiwista.errors import ProducerError, SourceUnavailableError
from archiwista.sources import (
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
)
from tests.fixtures.imgw_edits import add_version, drop_sidecar, rewrite_sidecar

type Stores = Callable[[str], Path]
type Row = tuple[object, ...]

HYDRO = "pl.imgw.hydro_daily"
ARCHIVE_SLOT = Path("archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024")
HYDRO_SERIES = Path("series/versions/hydro_daily")
PL_CATALOG = Path("stations/versions")
CZ_CATALOG = Path("stations/versions/chmi_stations")
CZ_REGISTER_SLOT = Path(
    "archives/versions/hydrology/historical/data/daily/H_0-203-1-900001_DQ_2023"
)


@pytest.fixture
def adapter(tmp_path: Path) -> ImgwAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "imgw"))
    assert isinstance(created, ImgwAdapter)
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


def _entries(adapter: ImgwAdapter, root: Path) -> list[SourceEntry]:
    return list(adapter.iter_entries(root))


def _copy(imgw_store: Stores, root: Path, variant: str = "complete") -> Path:
    """Copy a shared fixture store so that a test can change it."""
    shutil.copytree(imgw_store(variant), root)
    return root


def test_installed_imgwtools_within_supported_range() -> None:
    """The imported IMGWTools is one the adapter declares it reads."""
    supported = SpecifierSet(SUPPORTED_VERSIONS)

    assert supported.contains(Version(imgwtools.__version__), prereleases=True)
    assert (PRODUCER, PACKAGE) == ("imgw", "imgwtools")
    assert SCHEMAS == ("imgw-store/1", "imgw-meta/1", "imgw-series/1", "imgw-project/1")


def test_adapter_implements_the_source_interface_and_describes_its_datasets(
    adapter: ImgwAdapter,
) -> None:
    """The store has no segments to scan, links, sheets or coordinate operations."""
    assert isinstance(adapter, SourceAdapter)
    assert isinstance(adapter, SegmentDescriptionAdapter)
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


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_entries_equal_what_iter_store_yields(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str
) -> None:
    """Kind, slot, path, label and SHA-256 of every entry are the producer's."""
    root = imgw_store(variant)

    entries = _entries(adapter, root)

    assert _rows(entries) == _producer_rows(root)
    assert {entry.store for entry in entries} == {str(root)}
    assert {entry.producer for entry in entries} == {"imgw"}


def test_a_relabeled_version_is_the_same_content_under_a_new_label(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A republished archive is its own version; older ones stay versions."""
    entries = _entries(adapter, imgw_store("complete"))

    versions = [e for e in entries if e.slot_path == ARCHIVE_SLOT]

    assert [e.kind for e in versions] == ["version"] * 3
    metas = {_label(e): e.meta for e in versions}
    assert set(metas) == {"2026-10-17", "2026-10-18", "2026-10-19"}
    first, relabeled, newer = (metas[label] for label in sorted(map(str, metas)))
    assert first is not None and relabeled is not None and newer is not None
    assert first.sha256 == relabeled.sha256 != newer.sha256
    assert {e.relative_path.parent.parent for e in versions} == {ARCHIVE_SLOT}


def test_series_and_catalogs_are_versions_and_nothing_is_a_problem(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """Series (also an outdated one) and the station catalog are versions."""
    entries = _entries(adapter, imgw_store("complete"))

    series = Counter(e.segment for e in entries if e.relative_path.parts[0] == "series")

    assert series == {HYDRO: 2, "pl.imgw.meteo_precip_daily": 1}
    assert {e.kind for e in entries} == {"version"}
    (catalog,) = [e for e in entries if e.segment == "pl.imgw.stations"]
    assert catalog.slot_path == PL_CATALOG
    assert catalog.meta is not None and catalog.meta.provider == "IMGW-PIB"


@pytest.mark.parametrize(
    ("variant", "code", "slot"),
    [
        ("corrupt", "invalid_json", ARCHIVE_SLOT),
        ("unknown_schema", "unknown_schema", HYDRO_SERIES),
    ],
)
def test_a_version_the_producer_cannot_read_is_its_problem_and_nothing_is_parsed(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str, code: str, slot: Path
) -> None:
    """The producer's problem code is the entry's; the rest of the store is read."""
    root = imgw_store(variant)

    entries = _entries(adapter, root)

    (problem,) = [e for e in entries if e.kind == "problem"]
    assert (problem.problem, problem.meta, problem.version_path) == (code, None, None)
    assert (problem.slot_path, problem.segment) == (slot, HYDRO)
    assert _rows(entries) == _producer_rows(root)
    with pytest.raises(ProducerError):
        adapter.read_meta(problem)


def test_an_observation_is_history_and_never_a_version(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A source republished the same content: the register belongs to the slot."""
    entries = _entries(adapter, imgw_store("complete_pl_cz"))

    (observation,) = [e for e in entries if e.kind == "observation"]
    (version,) = [
        e for e in entries if e.kind == "version" and e.slot_path == CZ_REGISTER_SLOT
    ]

    assert (observation.slot_path, observation.segment) == (
        CZ_REGISTER_SLOT,
        "cz.chmi.hydro_daily",
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
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """When the source served the bytes, from where, and their size and digest."""
    entries = _entries(adapter, imgw_store("complete_pl_cz"))

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
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """The key is the producer's own; an archive is its file, a catalog its key."""
    root = imgw_store("complete_pl_cz")

    entries = _entries(adapter, root)

    keys = {e.relative_path: e.slot_key for e in entries}
    assert keys == {
        e.version.relative_to(root): e.slot for e in iter_store(root) if e.version
    }
    names = {e.slot_key: e.slot_name for e in entries}
    assert names["archive:pl.imgw.hydro_daily:2024/codz_2024.zip"] == "codz_2024.zip"
    cz_file = "precipitation/dly-0-203-0-90001-SRA.csv"
    assert (
        names[f"archive:cz.chmi.meteo_daily:{cz_file}"] == "dly-0-203-0-90001-SRA.csv"
    )
    assert names["catalog:pl.imgw.stations"] == "pl.imgw.stations"
    assert names["catalog:cz.chmi.stations"] == "cz.chmi.stations"
    # A series is named by its directory, which says what it is.
    assert names["series:pl.imgw.hydro_daily"] is None
    assert {
        e.slot_path.name
        for e in entries
        if e.slot_key == "series:cz.chmi.hydro_daily" and e.slot_path
    } == {"chmi_hydro_daily"}


def test_a_problem_without_a_slot_has_no_key_and_no_dataset(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """A stray item of the store belongs to no slot, so it has no segment."""
    root = _copy(imgw_store, tmp_path / "store")
    stray = root / "archives" / "versions" / "stray"
    stray.mkdir()
    (stray / "notes.txt").write_text("x", encoding="utf-8")

    entries = _entries(adapter, root)

    (found,) = [e for e in entries if e.relative_path.name == "stray"]
    assert (found.kind, found.problem) == ("problem", "unknown_entry")
    assert (found.slot_key, found.segment, found.slot_path) == (None, None, None)


def test_a_dataset_of_the_registry_is_described_by_its_polish_title_and_country(
    adapter: ImgwAdapter,
) -> None:
    """A segment is a dataset: the registry's name, the provider's country."""
    assert adapter.describe_segment(HYDRO) == SourceSegment(
        HYDRO, None, "PL", HYDRO, "Dane hydrologiczne dobowe", True
    )
    czech = adapter.describe_segment("cz.chmi.hydro_daily")
    assert (czech.country, czech.dataset_key, czech.known) == (
        "CZ",
        "cz.chmi.hydro_daily",
        True,
    )


@pytest.mark.parametrize("key", [dataset.key for dataset in imgwtools.datasets()])
def test_every_dataset_of_the_registry_is_a_known_segment_of_its_providers_country(
    adapter: ImgwAdapter, key: str
) -> None:
    """The registry is the producer's own, so no dataset is left unrecognised."""
    provider = imgwtools.get_provider(imgwtools.get_dataset(key).provider)

    described = adapter.describe_segment(key)

    assert (described.known, described.country, described.dataset_key) == (
        True,
        provider.country,
        key,
    )
    assert described.product is None and described.name not in ("", key)


def test_a_station_catalog_is_named_after_its_provider_and_an_unknown_key_by_itself(
    adapter: ImgwAdapter,
) -> None:
    """The catalogs are slots of the store but no datasets of the registry."""
    assert adapter.describe_segment("pl.imgw.stations") == SourceSegment(
        "pl.imgw.stations",
        None,
        "PL",
        "pl.imgw.stations",
        "Katalog stacji IMGW-PIB",
        True,
    )
    assert adapter.describe_segment("cz.chmi.stations") == SourceSegment(
        "cz.chmi.stations", None, "CZ", "cz.chmi.stations", "Katalog stacji ČHMÚ", True
    )
    assert adapter.describe_segment("pl.imgw.removed_dataset") == SourceSegment(
        "pl.imgw.removed_dataset", None, None, None, "pl.imgw.removed_dataset", False
    )


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz", "corrupt"])
def test_every_dataset_a_fixture_store_names_is_recognised(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str
) -> None:
    """What the producer writes into a store, its registry knows."""
    segments = {e.segment for e in _entries(adapter, imgw_store(variant)) if e.segment}

    assert segments
    assert all(adapter.describe_segment(name).known for name in segments)


def test_the_two_providers_keep_their_datasets_catalogs_and_countries_apart(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """IMGW-PIB and ČHMÚ files and station catalogs do not collide."""
    entries = _entries(adapter, imgw_store("complete_pl_cz"))

    metas = [e.meta for e in entries if e.meta is not None]
    catalogs = {e.segment: e for e in entries if e.relative_path.parts[0] == "stations"}

    assert {(m.provider, m.country) for m in metas} == {
        ("IMGW-PIB", "PL"),
        ("CHMI", "CZ"),
    }
    assert {e.segment[:3] for e in entries if e.segment and e.meta} == {"pl.", "cz."}
    assert {name: e.slot_path for name, e in catalogs.items()} == {
        "pl.imgw.stations": PL_CATALOG,
        "cz.chmi.stations": CZ_CATALOG,
    }
    assert [e.meta.provider for e in catalogs.values() if e.meta] == [
        "IMGW-PIB",
        "CHMI",
    ]
    slots = Counter(e.slot_path for e in entries if e.kind == "version")
    assert slots[PL_CATALOG] == slots[CZ_CATALOG] == 1


def test_the_canonical_content_of_a_chmi_file_is_kept_and_is_none_for_imgw(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """The producer's canonical content rides along; nothing is computed."""
    entries = _entries(adapter, imgw_store("complete_pl_cz"))

    forms = {
        (e.segment, e.meta.content_form, e.meta.content_sha256 is None)
        for e in entries
        if e.meta is not None and e.relative_path.parts[0] == "archives"
    }

    assert ("cz.chmi.hydro_daily", "chmi-json/1", False) in forms
    assert (HYDRO, None, True) in forms
    assert ("cz.chmi.meteo_daily", None, True) in forms


@pytest.mark.parametrize("slot", [ARCHIVE_SLOT, HYDRO_SERIES, PL_CATALOG], ids=str)
def test_read_meta_carries_the_common_core_for_an_archive_a_series_and_a_catalog(
    imgw_store: Stores, adapter: ImgwAdapter, slot: Path
) -> None:
    """DEV-19.16: the fields every sidecar has, read again on demand."""
    root = imgw_store("complete")
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
        "imgwtools",
        imgwtools.__version__,
    )
    assert (meta.label, meta.label_source) == (
        _produced_label(produced),
        _produced_version(produced)["label_source"],
    )
    assert meta.raw_sidecar is not None
    assert meta.raw_sidecar["schema"] == "imgw-meta/1"
    assert meta.raw_sidecar["producer"] == "imgwtools"
    assert meta.raw_sidecar["producer_version"] == produced.producer_version
    assert meta.raw_sidecar["request"] == produced.request
    assert meta.raw_sidecar["extra"] == produced.extra
    assert bool(meta.source_files) == (slot == HYDRO_SERIES)


def test_an_unknown_dataset_key_has_no_current_key(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """``dataset_key`` is ``None`` for a key the producer does not know."""
    root = _copy(imgw_store, tmp_path / "store")
    sidecar = next(root.glob(f"{ARCHIVE_SLOT}/*/codz_2024.zip.meta.json"))
    document = json.loads(sidecar.read_text(encoding="utf-8"))
    document["dataset"] = "pl.imgw.removed_dataset"
    sidecar.write_text(json.dumps(document), encoding="utf-8")

    entries = _entries(adapter, root)

    (renamed,) = [
        e.meta
        for e in entries
        if e.meta and e.meta.dataset == "pl.imgw.removed_dataset"
    ]
    assert renamed.dataset_key is None
    assert all(e.meta.dataset_key for e in entries if e.meta and e.meta is not renamed)


def test_footprint_of_an_archive_and_a_series_is_their_country(
    imgw_store: Stores, adapter: ImgwAdapter
) -> None:
    """A file of IMGW-PIB or ČHMÚ covers a country; a catalog has no place."""
    entries = _entries(adapter, imgw_store("complete_pl_cz"))

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


def test_scan_errors_and_scopes(adapter: ImgwAdapter, tmp_path: Path) -> None:
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


@pytest.mark.parametrize("variant", ["complete", "complete_pl_cz"])
def test_known_versions_come_back_skipped_with_no_sidecar_read(
    imgw_store: Stores, adapter: ImgwAdapter, variant: str
) -> None:
    """``known_versions`` is ``skip_versions``: the same entries, no version read."""
    root = imgw_store(variant)
    full = _entries(adapter, root)

    again = list(
        adapter.iter_entries(root, scope=ScanScope(known_versions=_known(full)))
    )

    assert _places(again) == _places(full)
    versions = [e for e in again if e.kind == "version"]
    assert versions and all(e.skipped and e.meta is None for e in versions)
    assert not any(e.skipped for e in again if e.kind != "version")


def test_what_is_not_known_is_read_in_full(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """Read what is not known in full; a known version is not looked at.

    A new version has its meta and a new broken one is a problem; the caller
    vouches for a known one, and a scan that names none sees what broke.
    """
    root = _copy(imgw_store, tmp_path / "store")
    known = _known(_entries(adapter, root))
    fresh = add_version(root, ARCHIVE_SLOT.as_posix(), label="2026-10-22")
    broken = add_version(root, ARCHIVE_SLOT.as_posix(), label="2026-10-23")
    drop_sidecar(root, broken)
    (series,) = [p for p in known if p.startswith(f"{HYDRO_SERIES}/")][:1]
    vouched = f"{series}/series.json"
    drop_sidecar(root, vouched)

    scoped = list(adapter.iter_entries(root, scope=ScanScope(known_versions=known)))
    unscoped = _entries(adapter, root)

    by_path = {e.relative_path.as_posix(): e for e in scoped}
    assert (by_path[fresh].skipped, by_path[fresh].meta is not None) == (False, True)
    assert (by_path[vouched].skipped, by_path[vouched].meta) == (True, None)
    problems = [(e.problem, e.relative_path.as_posix()) for e in scoped if e.problem]
    assert problems == [("missing_sidecar", Path(broken).parent.as_posix())]
    assert sorted(e.relative_path.as_posix() for e in unscoped if e.problem) == sorted(
        [Path(broken).parent.as_posix(), series]
    )


def test_a_version_written_by_an_older_release_keeps_its_number(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """The sidecar's ``producer`` and ``producer_version`` are the file's own."""
    root = _copy(imgw_store, tmp_path / "store")
    older = next(e for e in _entries(adapter, root) if e.slot_path == ARCHIVE_SLOT)
    rewrite_sidecar(root, older.relative_path.as_posix(), producer_version="2.9.0")

    entries = {e.relative_path: e for e in _entries(adapter, root)}

    meta = entries[older.relative_path].meta
    assert meta is not None and meta.raw_sidecar is not None
    assert (meta.written_by, meta.producer_version) == ("imgwtools", "2.9.0")
    assert meta.raw_sidecar["producer_version"] == "2.9.0"
    others = {
        e.meta.producer_version
        for path, e in entries.items()
        if e.meta is not None and path != older.relative_path
    }
    assert others == {imgwtools.__version__}


def test_a_path_with_a_link_is_refused_by_the_producer_with_its_message(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """IMGWTools reads no path with a symbolic link; its message is kept."""
    link = tmp_path / "link"
    link.symlink_to(imgw_store("complete"), target_is_directory=True)

    with pytest.raises(ProducerError) as raised:
        list(adapter.iter_entries(link))

    assert (raised.value.package, raised.value.exception) == (
        "imgwtools",
        "IMGWStoreError",
    )
    state = adapter.probe(link)
    assert (state.status, state.detail) == ("error", raised.value.message)


@dataclass(frozen=True)
class Case:
    """A directory of the probe table: how it is built, the verdict, the producer's.

    ``code`` is the first of the ``StoreInfo.problem_codes`` the reader gives
    (``None`` for a store it reads): the adapter judges by it, and by the
    names in the directory where one code covers several directories.
    ``call`` is the IMGWTools writer call that pins the verdict: ``init_store``
    or ``open_store``. ``refused`` says whether the writer refuses the
    directory and ``why`` is the ``details.reason`` of the refusal.
    """

    name: str
    build: Callable[[Path, Path], None]
    status: str
    reason: str | None
    code: str | None
    call: str
    refused: bool
    why: str | None = None


def _marker_of(root: Path) -> dict[str, object]:
    return json.loads((root / "imgw-store.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _empty(root: Path, store: Path) -> None:
    root.mkdir()


def _state_file_only(root: Path, store: Path) -> None:
    root.mkdir()
    (root / "api_keys.json").write_text("{}", encoding="utf-8")


def _whole_store(root: Path, store: Path) -> None:
    shutil.copytree(store, root)


def _no_marker(root: Path, store: Path) -> None:
    shutil.copytree(store, root)
    (root / "imgw-store.json").unlink()


def _layout_only(root: Path, store: Path) -> None:
    (root / "series").mkdir(parents=True)


def _other_schema(root: Path, store: Path) -> None:
    shutil.copytree(store, root)
    marker = _marker_of(root)
    (root / "imgw-store.json").write_text(
        json.dumps({**marker, "schema": "imgw-store/2"}), encoding="utf-8"
    )


def _marker_not_json(root: Path, store: Path) -> None:
    shutil.copytree(store, root)
    (root / "imgw-store.json").write_text("{not json", encoding="utf-8")


def _without_created_by(root: Path, store: Path) -> None:
    shutil.copytree(store, root)
    marker = _marker_of(root)
    del marker["created_by"]
    (root / "imgw-store.json").write_text(json.dumps(marker), encoding="utf-8")


def _kartograf(root: Path, store: Path) -> None:
    root.mkdir()
    marker = {"schema": "kartograf-store/1", "tool": "kartograf"}
    (root / "kartograf-store.json").write_text(json.dumps(marker), encoding="utf-8")


def _kartograf_with_layout(root: Path, store: Path) -> None:
    _kartograf(root, store)
    (root / "archives").mkdir()


def _parent_of_a_store(root: Path, store: Path) -> None:
    root.mkdir()
    shutil.copytree(store, root / "magazyn")


def _other_files(root: Path, store: Path) -> None:
    root.mkdir()
    (root / "notatki.txt").write_text("to nie magazyn", encoding="utf-8")


UNSUPPORTED = ("incompatible", "unsupported_marker")
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
    Case("store", _whole_store, "available", None, None, "open_store", False),
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


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_probe_judges_a_directory_as_the_producer_does(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path, case: Case
) -> None:
    """Each verdict on a directory is pinned to what IMGWTools does with it."""
    root = tmp_path / "root"
    case.build(root, imgw_store("complete"))

    state = adapter.probe(root)

    assert (state.status, state.reason) == (case.status, case.reason)
    assert (state.store, state.package_version) == (str(root), imgwtools.__version__)
    assert (state.supported_versions, state.schemas) == (SUPPORTED_VERSIONS, SCHEMAS)
    assert (state.detail is None) == (case.status == "available")
    assert (state.hint is None) == (case.reason != "no_marker")
    assert next(iter(store_info(root).problem_codes), None) == case.code
    calls = {"init_store": init_store, "open_store": open_store}
    if not case.refused:
        assert calls[case.call](root).root == root
    else:
        with pytest.raises(IMGWError) as refused:
            calls[case.call](root)
        assert refused.value.details.get("reason") == case.why
        assert isinstance(refused.value, IMGWStoreConflictError) == (
            case.call == "init_store"
        )


def test_init_store_turns_a_missing_marker_into_an_available_store(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """``imgw store init`` is the fix the hint names, and after it the store reads."""
    root = tmp_path / "magazyn z spacją"
    _no_marker(root, imgw_store("complete"))

    before = adapter.probe(root)
    init_store(root)
    after = adapter.probe(root)

    assert (before.status, before.reason) == ("incompatible", "no_marker")
    assert before.hint == f"imgw store init --root '{root}'"
    assert before.detail is not None and before.hint in before.detail
    assert (after.status, after.reason, after.hint) == ("available", None, None)
    assert _rows(_entries(adapter, root)) == _producer_rows(root)


def test_an_unsupported_marker_names_both_schemas(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """The text says what the marker has and what this version reads."""
    root = tmp_path / "root"
    _other_schema(root, imgw_store("complete"))

    state = adapter.probe(root)

    assert state.detail is not None
    assert "imgw-store/2" in state.detail and "imgw-store/1" in state.detail


def test_a_directory_that_cannot_be_listed_is_an_error_not_a_verdict(
    adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """A missing directory and a file are ``error`` with no reason."""
    (tmp_path / "file").write_text("x", encoding="utf-8")

    states = [adapter.probe(tmp_path / "missing"), adapter.probe(tmp_path / "file")]

    assert [state.status for state in states] == ["error", "error"]
    assert all(state.detail and state.reason is None for state in states)


def _project(root: Path, project: Path) -> None:
    """Build a project with the producer's own writers: one unpinned task."""
    init_project(project, store_dir=root)
    add_project_task(
        project,
        name="raba",
        command="series select",
        options={"dataset": HYDRO, "stations": ["000000001"], "years": [2024]},
    )


def test_a_project_of_the_producers_writers_is_read(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """Tasks keep their command and options; the store is the project's."""
    root = _copy(imgw_store, tmp_path / "store")
    project = tmp_path / "project"
    _project(root, project)

    info = adapter.read_project(project)

    assert (info.producer, info.store, info.path, info.name) == (
        "imgw",
        str(root),
        project,
        "project",
    )
    assert [(t.task_id, t.command) for t in info.tasks] == [("raba", "series select")]
    assert info.tasks[0].options["dataset"] == HYDRO
    assert (info.pins, info.status) == ((), None)
    with pytest.raises(ProducerError) as missing:
        adapter.read_project(tmp_path)
    assert missing.value.package == "imgwtools"


def test_project_status_follows_the_pins(
    imgw_store: Stores, adapter: ImgwAdapter, tmp_path: Path
) -> None:
    """An unpinned task is ``not_downloaded``; a pin is ok, changed or missing."""
    root = _copy(imgw_store, tmp_path / "store")
    project = tmp_path / "project"
    _project(root, project)
    series = next(
        e
        for e in _entries(adapter, root)
        if e.slot_path == HYDRO_SERIES and e.meta and e.meta.sha256
    )
    assert series.meta is not None
    unpinned = adapter.project_status(project)
    manifest = project / "imgw-project.json"
    document = json.loads(manifest.read_text(encoding="utf-8"))
    pin = {
        "role": "series",
        "path": series.relative_path.as_posix(),
        "sha256": series.meta.sha256,
    }
    document["tasks"][0].update(
        pinned_at="2026-10-25T05:00:00Z",
        imgwtools_version=imgwtools.__version__,
        files=[pin],
    )
    manifest.write_text(json.dumps(document), encoding="utf-8")

    pinned = adapter.project_status(project)
    (root / series.relative_path).write_bytes(b"{}")
    changed = adapter.project_status(project)
    (root / series.relative_path).unlink()
    missing = adapter.project_status(project)

    assert (unpinned.status, [t.status for t in unpinned.tasks]) == (
        "not_downloaded",
        ["not_downloaded"],
    )
    assert [(p.store, p.version_path, p.sha256, p.task_id) for p in pinned.pins] == [
        (str(root), series.relative_path, series.meta.sha256, "raba")
    ]
    assert [
        (p.status, [t.status for t in p.tasks]) for p in (pinned, changed, missing)
    ] == [
        ("ok", ["ok"]),
        ("corrupt", ["corrupt"]),
        ("missing", ["missing"]),
    ]


def test_the_adapter_reads_a_store_without_pyarrow(
    imgw_store: Stores, tmp_path: Path
) -> None:
    """Reading needs no Parquet file: the adapter never imports ``pyarrow``."""
    root = imgw_store("complete_pl_cz")
    script = """
import sys
from pathlib import Path

sys.modules["pyarrow"] = None
from archiwista.adapter.imgw import load
from archiwista.sources import SourceContext

adapter = load(SourceContext(cache_dir=Path(sys.argv[2])))
root = Path(sys.argv[1])
assert adapter.probe(root).status == "available"
entries = list(adapter.iter_entries(root))
for entry in entries:
    if entry.kind == "version":
        adapter.read_meta(entry)
        adapter.footprint(entry)
print(len(entries))
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(root), str(tmp_path / "cache")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert int(result.stdout) > 20
