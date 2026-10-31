"""Contract of the synthetic store: what Kartograf's readers see in it.

The store is checked against ``kartograf.iter_store`` and the other public
readers (offline), not against Archiwista's index.
"""

import json
import re
import struct
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

import laspy
import pyogrio
import pytest
import rasterio
import shapely
from kartograf import (
    file_footprint,
    init_store,
    iter_store,
    link_target,
)
from rasterio.enums import ColorInterp

from archiwista.errors import ProjectFileError
from archiwista.projects import PROJECT_FILE, read_project_file
from tests.fixtures.make_store import (
    BDOT_GPKG,
    CZ_OUTLINE,
    MIN_PROJECTS,
    MIN_SLOTS,
    PL_OUTLINE,
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
from tests.fixtures.store_files import (
    CLC_CLASSES,
    CLC_NODATA,
    LAZ_CLASSES,
    OVERVIEW_FACTORS,
    SOIL_NODATA,
)
from tests.fixtures.store_marker import MARKED_AT

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


def test_store_fixture_root_has_the_marker_kartograf_writes(
    store: StoreManifest,
) -> None:
    """The generator marks its root through ``init_store``: nothing is left to write."""
    marked = init_store(store.root)

    assert (marked.created, marked.tool) == (False, "kartograf")
    assert marked.marker.name == "kartograf-store.json"
    assert marked.created_at == MARKED_AT.isoformat(timespec="seconds")


def test_store_fixture_sidecars_give_expected_metadata(store: StoreManifest) -> None:
    """Sidecars read by Kartograf carry the generator's metadata."""
    expected = {entry.row: entry for entry in store.entries}

    for found in iter_store(store.root):
        wanted = expected[entry_row(found, store.root)]
        if found.kind == "problem":
            continue
        meta = found.sidecar
        assert meta is not None
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
    linked = [e for e in store.by_kind("link") if e.version_path is not None]
    assert sum(e.current for e in versions) == len(linked)
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
        if (meta.extra or {})["version"]["label_source"] == "downloaded"
    ]

    assert by_download and all(meta.data_year is None for meta in by_download)
    assert any(
        meta.data_year is not None
        and meta.data_year != int((meta.downloaded_at or "")[:4])
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
        ("laz_tile", "header"),
        ("hsg_bbox", "request"),
        ("png_preview", "request"),
        ("tif_classes", "header"),
        ("tif_map", "sheet"),
        ("pdf_map", "sheet"),
        ("tif_oblique", "sheet"),
        ("tif_wgs84", "request"),
        ("laz_compressed", "header"),
        ("gpkg_layers", "header"),
        ("zip_ascii_nmt", "sheet"),
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
    assert all(f is not None and f.native.min_x < f.native.max_x for f in footprints)


@pytest.mark.parametrize(
    "family", ["tif_bbox", "hsg_bbox", "laz_tile", "laz_compressed"]
)
def test_store_fixture_raster_and_point_headers_give_the_written_extent(
    store: StoreManifest, family: Family
) -> None:
    """Without the request, Kartograf reads the GeoTIFF or LAS/LAZ header."""
    for entry in _versions_of(store, family):
        bare = replace(entry, sidecar=replace(entry.sidecar, request=None))

        footprint = file_footprint(bare)

        assert footprint is not None and footprint.source == "header"
        if not family.startswith("laz_"):  # a tile lies inside its requested area
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


@pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")
def test_store_fixture_footprints_lie_in_their_country(store: StoreManifest) -> None:
    """Every offline footprint is centred inside the outline of its country.

    Czech files lie in Czechia; the others, EU and global products included,
    in Poland.
    """
    entries = [entry for entry in iter_store(store.root) if entry.kind != "problem"]

    footprints = [(entry, file_footprint(entry)) for entry in entries]

    placed = [(entry, found) for entry, found in footprints if found is not None]
    countries: dict[Path, str | None] = {}
    for entry, _ in placed:
        assert entry.sidecar is not None
        countries[entry.path] = entry.sidecar.country
    czech = [(e, found) for e, found in placed if countries[e.path] == "CZ"]
    polish = [(e, found) for e, found in placed if countries[e.path] != "CZ"]
    assert czech and polish
    for outline, group in ((CZ_OUTLINE, czech), (PL_OUTLINE, polish)):
        centres = {e.path: shapely.box(*found.wgs84[:4]).centroid for e, found in group}
        assert [path for path, c in centres.items() if not outline.contains(c)] == []


def _first_version(store: StoreManifest, family: Family) -> Path:
    return store.root / next(
        e.path for e in store.by_family(family) if e.kind == "version"
    )


def _laszip_chunk_size(header: Any) -> int:
    """Points per chunk from the LASzip VLR (user ``laszip encoded``, 22204)."""
    [vlr] = [v for v in header.vlrs if v.record_id == 22204]
    size: int = struct.unpack_from("<I", vlr.record_data, 12)[0]
    return size


def test_store_fixture_file_families_have_their_structure(
    store: StoreManifest,
) -> None:
    """Each v0.2 family has the structure its preview path depends on."""
    with rasterio.open(_first_version(store, "tif_classes"), driver="GTiff") as src:
        assert (src.crs.to_string(), src.colorinterp) == (
            "EPSG:3035",
            (ColorInterp.palette,),
        )
        assert set(src.colormap(1)) >= set(CLC_CLASSES)
        assert src.nodata == CLC_NODATA
    with rasterio.open(_first_version(store, "tif_map"), driver="GTiff") as src:
        assert src.crs.to_string() == "EPSG:2180"
        assert src.colorinterp[3] == ColorInterp.alpha
        assert not src.profile["tiled"] and src.overviews(1) == []
        assert min(src.width, src.height) > 4096
    with rasterio.open(_first_version(store, "tif_oblique"), driver="GTiff") as src:
        assert src.crs.to_string() == "EPSG:2177"
        assert src.profile["tiled"] and src.overviews(1) == list(OVERVIEW_FACTORS)
    with rasterio.open(_first_version(store, "tif_wgs84"), driver="GTiff") as src:
        assert src.crs.to_string() == "EPSG:4326" and src.nodata == SOIL_NODATA
    png = _first_version(store, "png_preview").read_bytes()
    assert png.startswith(b"\x89PNG") and b"pHYs" not in png and b"tEXt" not in png
    assert _first_version(store, "pdf_map").read_bytes().startswith(b"%PDF-")
    with zipfile.ZipFile(_first_version(store, "zip_citygml")) as archive:
        assert {Path(n).suffix for n in archive.namelist()} == {".gml", ".pdf"}
    with zipfile.ZipFile(_first_version(store, "zip_ascii_nmt")) as archive:
        assert [Path(n).suffix for n in archive.namelist()] == [".xyz"]
    layers = pyogrio.list_layers(_first_version(store, "gpkg_layers"))
    assert [tuple(row) for row in layers] == [
        ("swrs", "LineString"),
        ("ptwp", "Polygon"),
    ]
    with laspy.open(_first_version(store, "laz_compressed")) as reader:
        header = reader.header
        chunk_size = _laszip_chunk_size(header)
        points = reader.read()
    assert header.are_points_compressed and header.parse_crs() is not None
    assert header.point_count > chunk_size
    assert set(points.classification) == set(LAZ_CLASSES)


def test_store_fixture_two_formats_share_the_variant(store: StoreManifest) -> None:
    """ASC and ASCII-NMT of one sheet: one product, CRS, heights, resolution."""
    links = [e for e in store.by_case("two_formats") if e.kind == "link"]
    metas = [
        e.sidecar
        for e in iter_store(store.root)
        if e.kind == "link" and entry_row(e, store.root)[3] in {x.path for x in links}
    ]

    assert len({link.segment for link in links}) == 2
    assert len({link.unit for link in links}) == 1
    assert None not in metas
    variants = {
        (m.product, m.horizontal_crs, m.vertical_crs, m.resolution)
        for m in metas
        if m is not None
    }
    assert len(variants) == 1


def test_store_fixture_standard_path_file_without_sha256(store: StoreManifest) -> None:
    """The 0.7.x sidecar has no ``sha256``; Kartograf lists it as a link."""
    [wanted] = store.by_case("no_sha256")
    [found] = [e for e in iter_store(store.root) if e.path == store.root / wanted.path]

    assert found.kind == "link" and found.version_path is None
    assert found.sidecar is not None and found.sidecar.sha256 is None


def test_store_fixture_projects_open_as_expected(store: StoreManifest) -> None:
    """Valid project files read with their pins; the invalid one is refused."""
    for project in store.projects:
        directory = store.base / project.path
        if not project.valid:
            with pytest.raises(ProjectFileError):
                read_project_file(directory)
            continue
        opened = read_project_file(directory)
        (root,) = opened.stores
        store_dir = (store.base / project.store).resolve()
        assert (directory / root.root).resolve() == store_dir
        pins = {
            (group.name, pin.version) for group in opened.groups for pin in group.pins
        }
        assert pins == {
            (group.name, pin.version) for group in project.groups for pin in group.pins
        }
    every_pin = [pin for p in store.projects for g in p.groups for pin in g.pins]
    assert all((store.root / pin.version).is_file() == pin.present for pin in every_pin)
    assert any(pin.present and not pin.current for pin in every_pin)
    assert {p.case for p in store.projects} == {
        "regular",
        "missing_version",
        "other_store",
        "invalid_project_file",
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


def test_verify_store_rejects_accepted_invalid_project_file(tmp_path: Path) -> None:
    """An invalid project file that reads stops the generator's verification."""
    manifest = make_store(tmp_path / "store", slots=MIN_SLOTS, seed=2)
    invalid = next(p for p in manifest.projects if not p.valid)
    path = manifest.base / invalid.path / PROJECT_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["groups"][0]["name"] = "teren"
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
    assert re.search(rf"^slots: \d+ \({MIN_SLOTS} regular\)$", out, re.MULTILINE)
    assert (tmp_path / "data").is_dir()
    assert len(list((tmp_path / "projects").iterdir())) == 4


def test_make_store_cli_refuses_repository_directory() -> None:
    """The command line never writes test data into the repository."""
    inside = Path(__file__).resolve().parents[1] / "store-in-repo"

    with pytest.raises(SystemExit) as exit_info:
        main(["--slots", str(MIN_SLOTS), str(inside)])

    assert exit_info.value.code == 2
    assert not inside.exists()
