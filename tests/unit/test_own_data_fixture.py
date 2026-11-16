"""The own-data fixtures are what later tests take them for (plan v0.2, step 2)."""

import json
import shutil
import sqlite3
import stat
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyogrio
import pytest
import rasterio
import shapely

from archiwista.projects import read_project_file
from tests.fixtures.own_data import (
    SNAPSHOT_FILE,
    SNAPSHOT_SCHEMA,
    ContentMethod,
    GpkgEditor,
    OwnFamily,
    make_own_folder,
    project_inside_store,
    write_snapshot_fixture,
)

CREATED = datetime(2026, 10, 18, 14, 2, 11, tzinfo=timezone(timedelta(hours=2)))


def _rows(path: Path, table: str, *, uri: str = "mode=ro") -> int:
    connection = sqlite3.connect(f"{path.as_uri()}?{uri}", uri=True)
    try:
        (count,) = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()
        return int(count)
    finally:
        connection.close()


def test_own_folder_shapefile_is_a_complete_set(tmp_path: Path) -> None:
    """The full set has ``.shp .shx .dbf .prj .cpg``; the other lacks ``.prj``."""
    folder = make_own_folder(tmp_path / "dane", families=("shp_full", "shp_no_prj"))

    full, bare = folder.file("shp_full"), folder.file("shp_no_prj")

    assert sorted(p.name for p in folder.root.iterdir()) == sorted(
        full.members + bare.members
    )
    assert {Path(name).suffix for name in full.members} == {
        ".shp",
        ".shx",
        ".dbf",
        ".prj",
        ".cpg",
    }
    assert ".prj" not in {Path(name).suffix for name in bare.members}
    assert pyogrio.read_info(folder.path("shp_full"))["crs"] == "EPSG:2180"
    assert pyogrio.read_info(folder.path("shp_no_prj"))["crs"] is None


@pytest.mark.filterwarnings("ignore::rasterio.errors.NotGeoreferencedWarning")
def test_own_folder_files_read_as_the_manifest_says(tmp_path: Path) -> None:
    """GDAL reads each recognised file with the declared driver, CRS and counts."""
    folder = make_own_folder(tmp_path / "dane")

    for entry in folder.indexed:
        path = folder.root / entry.path
        if entry.driver is None:
            continue
        if entry.raster is not None:
            with (
                rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"),
                rasterio.open(path, driver=entry.driver) as src,
            ):
                crs = src.crs.to_string() if src.crs else None
                assert (crs, (src.width, src.height, src.count)) == (
                    entry.crs,
                    entry.raster,
                ), entry.path
            continue
        layers = [tuple(row) for row in pyogrio.list_layers(path)]
        assert layers == [(x.name, x.geometry_type) for x in entry.layers], entry.path
        for layer in entry.layers:
            info = pyogrio.read_info(path, layer=layer.name)
            assert (info["driver"], info["crs"], info["features"]) == (
                entry.driver,
                entry.crs,
                layer.feature_count,
            ), entry.path
    assert (folder.root / "skan.tfw").is_file()
    hidden = folder.file("hidden")
    assert not hidden.indexed and all(
        any(part.startswith(".") for part in Path(name).parts)
        for name in hidden.members
    )
    outside = folder.outside
    assert outside is not None
    for name in folder.file("symlink_outside").members:
        link = folder.root / name
        assert link.is_symlink() and link.resolve().is_relative_to(outside)
    assert (folder.root / folder.file("subdir").path).is_file()


def _editable(tmp_path: Path) -> Path:
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    return folder.path("gpkg_layers")


def test_gpkg_editor_keeps_committed_frames_in_wal_and_an_open_transaction(
    tmp_path: Path,
) -> None:
    """Committed rows wait in ``-wal``; an open transaction is invisible."""
    path = _editable(tmp_path)
    pipe = shapely.LineString([(566_500, 241_500), (566_600, 241_600)])

    with GpkgEditor(path) as editor:
        editor.begin()
        editor.insert("przewody", pipe, srednica_mm=110, material="PE")
        editor.commit()
        editor.begin()
        editor.insert("przewody", pipe, srednica_mm=90, material="PE")

        assert editor.wal.stat().st_size > 0 and editor.shm.exists()
        assert _rows(path, "przewody") == 4
        assert _rows(path, "przewody", uri="immutable=1") == 3

    assert not editor.wal.exists() and not editor.shm.exists()
    assert _rows(path, "przewody", uri="immutable=1") == 4
    assert pyogrio.read_info(path, layer="przewody")["features"] == 4


def test_gpkg_editor_crash_leaves_wal_without_shm(tmp_path: Path) -> None:
    """After the crash the committed row lives only in ``-wal``."""
    path = _editable(tmp_path)
    work = tmp_path / "kopia"
    work.mkdir()

    editor = GpkgEditor(path)
    editor.begin()
    editor.insert("zlewnie", shapely.box(566_200, 241_200, 566_300, 241_300), nazwa="C")
    editor.commit()
    editor.crash_without_shm()

    assert editor.wal.stat().st_size > 0 and not editor.shm.exists()
    assert _rows(path, "zlewnie", uri="immutable=1") == 2
    shutil.copyfile(path, work / path.name)
    shutil.copyfile(editor.wal, work / editor.wal.name)
    copy = sqlite3.connect(work / path.name)
    try:
        assert copy.execute('SELECT count(*) FROM "zlewnie"').fetchone() == (3,)
        assert copy.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        copy.close()


def test_gpkg_editor_open_for_update_rewrites_only_derived_data(
    tmp_path: Path,
) -> None:
    """Counts and timestamps are rewritten; features and schema stay."""
    path = _editable(tmp_path)

    def state() -> tuple[list[object], list[object], list[object]]:
        connection = sqlite3.connect(f"{path.as_uri()}?immutable=1", uri=True)
        try:
            features = connection.execute(
                "SELECT * FROM przewody UNION ALL SELECT fid, geom, nazwa, NULL"
                " FROM zlewnie"
            ).fetchall()
            schema = connection.execute("SELECT sql FROM sqlite_master").fetchall()
            stamps = connection.execute(
                "SELECT last_change FROM gpkg_contents"
            ).fetchall()
            return features, schema, stamps
        finally:
            connection.close()

    before = state()
    with GpkgEditor(path) as editor:
        editor.reopen_for_update_unchanged()
    after = state()

    assert after[:2] == before[:2]
    assert after[2] != before[2]


@pytest.mark.parametrize(
    ("family", "content", "method"),
    [
        ("tif_2180", None, "files"),
        ("gpkg_layers", ("sqlite", "471d37c0" + "0" * 56), "sqlite_backup"),
        ("shp_full", ("fileset", "9c1e" + "0" * 60), "files"),
    ],
)
def test_snapshot_fixture_is_a_published_snapshot(
    tmp_path: Path,
    family: OwnFamily,
    content: tuple[ContentMethod, str] | None,
    method: str,
) -> None:
    """``.wersje/<file>/<date>_<sha8>/``: copies, ``migawka.json``, read-only."""
    folder = make_own_folder(tmp_path / "dane", families=(family,))
    entry = folder.file(family)

    first = write_snapshot_fixture(
        folder.root, entry.path, created_at=CREATED, content=content
    )
    again = write_snapshot_fixture(
        folder.root, entry.path, created_at=CREATED, content=content
    )

    document = json.loads((first.directory / SNAPSHOT_FILE).read_text("utf-8"))
    sha8 = document["content"]["sha256"][:8]
    assert (
        first.directory == folder.root / ".wersje" / entry.path / f"2026-10-18_{sha8}"
    )
    assert again.label == f"{first.label}_2"
    assert document == first.document
    assert (document["schema"], document["copy"]["method"]) == (SNAPSHOT_SCHEMA, method)
    assert sorted(f["name"] for f in document["files"]) == sorted(
        Path(name).name for name in entry.members
    )
    assert document["size_bytes"] == sum(f["size_bytes"] for f in document["files"])
    assert stat.S_IMODE(first.directory.stat().st_mode) == 0o555
    assert all(
        stat.S_IMODE(p.stat().st_mode) == 0o444 for p in first.directory.iterdir()
    )


def test_snapshot_fixture_needs_content_for_sqlite(tmp_path: Path) -> None:
    """The fixture never invents the logical SQLite identity."""
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))

    with pytest.raises(ValueError, match="content"):
        write_snapshot_fixture(
            folder.root, folder.file("gpkg_layers").path, created_at=CREATED
        )


def test_project_inside_store_names_the_store_as_root(tmp_path: Path) -> None:
    """The project file lies in the producer directory it names as its store."""
    store = tmp_path / "data"
    store.mkdir()

    directory = project_inside_store(store)

    assert directory.is_relative_to(store)
    (named,) = read_project_file(directory).stores
    assert (directory / named.root).resolve() == store.resolve()
