"""Contract of the synthetic store: what Kartograf's readers see in it.

The store is checked against ``kartograf.iter_store`` and the other public
readers (offline), not against Archiwista's index.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

import pytest
from kartograf import (
    ValidationError,
    file_footprint,
    iter_store,
    link_target,
    open_project,
)

from tests.fixtures.make_store import (
    BDOT_GPKG,
    MIN_PROJECTS,
    MIN_SLOTS,
    Case,
    Family,
    ProblemCode,
    StoreFixtureError,
    StoreManifest,
    entry_row,
    main,
    make_store,
    verify_store,
)

SLOTS = MIN_SLOTS + 40
PROJECTS = MIN_PROJECTS + 2


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> StoreManifest:
    """One generated store shared by the read-only checks of this module."""
    return make_store(
        tmp_path_factory.mktemp("store"), slots=SLOTS, seed=11, projects=PROJECTS
    )


def test_store_fixture_iter_store_yields_exactly_the_manifest(
    store: StoreManifest,
) -> None:
    """Kartograf yields every expected entry once, problems included."""
    entries = list(iter_store(store.root))

    assert {entry_row(entry, store.root) for entry in entries} == store.rows
    assert len(entries) == len(store.entries)
    assert {entry.problem for entry in entries if entry.kind == "problem"} == set(
        get_args(ProblemCode)
    )


def test_store_fixture_sidecars_give_expected_metadata(store: StoreManifest) -> None:
    """Sidecars read by Kartograf carry the generator's metadata."""
    expected = {entry.row: entry for entry in store.entries}

    for found in iter_store(store.root):
        wanted = expected[entry_row(found, store.root)]
        if found.kind == "problem":
            continue
        meta = found.sidecar
        assert (meta.sha256, meta.dataset_key, meta.unit, meta.data_year) == (
            wanted.sha256,
            wanted.dataset_key,
            wanted.unit,
            wanted.data_year,
        ), wanted.path


def test_store_fixture_has_every_family_case_and_requested_slots(
    store: StoreManifest,
) -> None:
    """Every family and case is present; ``slots`` counts regular links."""
    regular_links = [e for e in store.by_kind("link") if e.case == "regular"]
    versions = store.by_kind("version")

    assert {e.family for e in store.entries if e.family} == set(get_args(Family))
    assert {e.case for e in store.entries} == set(get_args(Case))
    assert len(regular_links) == SLOTS
    assert len(versions) > len(store.by_kind("link"))
    assert sum(e.current for e in versions) == len(store.by_kind("link")) - 2
    assert store.by_kind("full_sheet")


def test_store_fixture_data_year_never_comes_from_download(
    store: StoreManifest,
) -> None:
    """Download-labelled versions have no data year; data years differ."""
    versions = [
        found.sidecar
        for found in iter_store(store.root)
        if found.kind == "version" and found.sidecar is not None
    ]
    by_download = [
        meta
        for meta in versions
        if meta.extra["version"]["label_source"] == "downloaded"
    ]

    assert by_download and all(meta.data_year is None for meta in by_download)
    assert any(
        meta.data_year is not None and meta.data_year != int(meta.downloaded_at[:4])
        for meta in versions
    )


def test_store_fixture_known_versions_are_listed_without_reading_sidecars(
    store: StoreManifest,
) -> None:
    """Known version directories come back skipped, without sidecars."""
    known = {
        entry.path.rsplit("/", 1)[0]
        for entry in store.by_kind("version")
        if entry.case == "regular"
    }

    skipped = [
        entry
        for entry in iter_store(store.root, skip_versions=known)
        if entry.kind == "version" and entry.skipped
    ]

    assert {entry_row(e, store.root)[3].rsplit("/", 1)[0] for e in skipped} == known
    assert all(entry.sidecar is None for entry in skipped)


def test_store_fixture_unit_scope_returns_only_that_slot(store: StoreManifest) -> None:
    """A TERYT unit scan yields that slot's link and versions only."""
    [link] = [e for e in store.by_kind("link") if e.segment == BDOT_GPKG][:1]
    wanted = {
        e.row
        for e in store.entries
        if e.segment == BDOT_GPKG and e.unit == link.unit and e.kind != "problem"
    }

    found = iter_store(store.root, segment=BDOT_GPKG, units=[f"teryt/{link.unit}"])

    assert {entry_row(entry, store.root) for entry in found} == wanted
    assert len(wanted) >= 2


def test_store_fixture_links_are_confirmed_except_the_mismatch(
    store: StoreManifest,
) -> None:
    """Every link is confirmed by content, except the mismatched one."""
    for entry in store.by_kind("link") + store.by_kind("full_sheet"):
        confirmed = link_target(store.root / entry.path)
        if entry.case == "link_mismatch" or entry.version_path is None:
            assert confirmed is None, entry.path
        else:
            assert confirmed == store.root / entry.version_path, entry.path


def _versions_of(store: StoreManifest, family: Family) -> list[Any]:
    """Kartograf's version entries of one family."""
    paths = {e.path for e in store.by_family(family) if e.kind == "version"}
    return [
        entry
        for entry in iter_store(store.root)
        if entry.kind == "version" and entry_row(entry, store.root)[3] in paths
    ]


@pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")
@pytest.mark.parametrize(
    ("family", "source"),
    [
        ("gpkg_teryt", "header"),
        ("jpg_sheet", "header"),
        ("jgw_sheet", "header"),
        ("asc_sheet", "sheet"),
        ("tif_sheet", "sheet"),
        ("tif_bbox", "request"),
        ("laz_tile", "request"),
        ("hsg_bbox", "request"),
    ],
)
def test_store_fixture_files_give_offline_footprints(
    store: StoreManifest, family: Family, source: str
) -> None:
    """Files are well formed: Kartograf finds their outline offline.

    GDAL warns that a JPEG has no geotransform: Kartograf reads the world
    file itself.
    """
    entries = _versions_of(store, family)

    footprints = [file_footprint(entry) for entry in entries]

    assert entries
    assert all(f is not None and f.source == source for f in footprints), family
    assert all(f.native.min_x < f.native.max_x for f in footprints)


@pytest.mark.parametrize("family", ["tif_bbox", "hsg_bbox", "laz_tile"])
def test_store_fixture_raster_and_point_headers_give_the_written_extent(
    store: StoreManifest, family: Family
) -> None:
    """Without the request, Kartograf reads the GeoTIFF or LAS header."""
    for entry in _versions_of(store, family):
        bare = replace(entry, sidecar=replace(entry.sidecar, request=None))

        footprint = file_footprint(bare)

        assert footprint is not None and footprint.source == "header"
        if family != "laz_tile":  # a tile lies inside its requested area
            bbox = entry.sidecar.request["bbox"]
            assert list(footprint.native[:4]) == pytest.approx(bbox)
            assert footprint.native.crs == entry.sidecar.request["bbox_crs"]


def test_store_fixture_country_file_has_no_offline_footprint(
    store: StoreManifest,
) -> None:
    """A national file has no outline (shown as the whole country)."""
    [path] = [e.path for e in store.by_family("zip_country") if e.kind == "link"]
    [entry] = [e for e in iter_store(store.root) if e.path == store.root / path]

    assert file_footprint(entry) is None


def test_store_fixture_projects_open_as_expected(store: StoreManifest) -> None:
    """Valid manifests open with their pins; the invalid one is rejected."""
    for project in store.projects:
        directory = store.output_dir / project.path
        if not project.valid:
            with pytest.raises(ValidationError):
                open_project(directory)
            continue
        opened = open_project(directory)
        store_dir = (store.output_dir / project.store).resolve()
        assert opened.output_dir.resolve() == store_dir
        pins = {(task.name, pin.version) for task in opened.tasks for pin in task.files}
        assert pins == {
            (task.name, pin.version) for task in project.tasks for pin in task.pins
        }
    every_pin = [pin for p in store.projects for t in p.tasks for pin in t.pins]
    assert all((store.root / pin.version).is_file() == pin.present for pin in every_pin)
    assert any(pin.present and not pin.current for pin in every_pin)
    assert {p.case for p in store.projects} == {
        "regular",
        "missing_version",
        "other_store",
        "invalid_manifest",
    }


def test_make_store_same_seed_gives_same_store(tmp_path: Path) -> None:
    """The seed alone decides the store."""
    first = make_store(tmp_path / "a", slots=MIN_SLOTS, seed=5)
    second = make_store(tmp_path / "b", slots=MIN_SLOTS, seed=5)
    other = make_store(tmp_path / "c", slots=MIN_SLOTS, seed=6)

    assert first.entries == second.entries
    assert first.projects == second.projects
    assert first.rows != other.rows


def test_verify_store_rejects_store_kartograf_reads_differently(
    tmp_path: Path,
) -> None:
    """A version without its sidecar stops the generator's verification."""
    manifest = make_store(tmp_path / "store", slots=MIN_SLOTS, seed=2)
    version = next(e for e in manifest.by_kind("version") if e.case == "regular")
    (manifest.root / f"{version.path}.meta.json").unlink()

    with pytest.raises(StoreFixtureError, match=version.path):
        verify_store(manifest)


def test_verify_store_rejects_accepted_invalid_manifest(tmp_path: Path) -> None:
    """An invalid manifest that opens stops the generator's verification."""
    manifest = make_store(tmp_path / "store", slots=MIN_SLOTS, seed=2)
    invalid = next(p for p in manifest.projects if not p.valid)
    path = manifest.output_dir / invalid.path / "kartograf-project.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["tasks"][0]["command"] = "elevation download"
    path.write_text(json.dumps(doc), encoding="utf-8")

    with pytest.raises(StoreFixtureError, match=invalid.name):
        verify_store(manifest)


@pytest.mark.parametrize(
    ("slots", "projects"), [(MIN_SLOTS - 1, MIN_PROJECTS), (MIN_SLOTS, 3)]
)
def test_make_store_rejects_too_small_request(
    tmp_path: Path, slots: int, projects: int
) -> None:
    """Too few slots or projects are refused before anything is written."""
    with pytest.raises(ValueError, match="at least"):
        make_store(tmp_path / "store", slots=slots, seed=1, projects=projects)

    assert not (tmp_path / "store").exists()


def test_make_store_refuses_non_empty_directory(tmp_path: Path) -> None:
    """The generator never mixes its store into existing data."""
    (tmp_path / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(ValueError, match="not empty"):
        make_store(tmp_path, slots=MIN_SLOTS, seed=1)

    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_make_store_cli_prints_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The command line writes the store and reports its size."""
    status = main(
        ["--slots", str(MIN_SLOTS), "--seed", "3", "--projects", "4", str(tmp_path)]
    )

    out = capsys.readouterr().out
    assert status == 0
    assert f"slots: {MIN_SLOTS + 6} ({MIN_SLOTS} regular)" in out
    assert (tmp_path / "data").is_dir()
    assert len(list((tmp_path / "projects").iterdir())) == 4


def test_make_store_cli_refuses_repository_directory() -> None:
    """The command line never writes test data into the repository."""
    inside = Path(__file__).resolve().parents[1] / "store-in-repo"

    with pytest.raises(SystemExit) as exit_info:
        main(["--slots", str(MIN_SLOTS), str(inside)])

    assert exit_info.value.code == 2
    assert not inside.exists()
