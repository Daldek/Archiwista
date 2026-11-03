"""The own-data reader process (plan v0.2, step 7a; decisions 3 and 8).

Every family of an own-data folder is read as written: drivers, sets of
files, layers, CRS (or none), rasters with or without their own
georeference. Planted files never lead the reader to the file they name, a
file that hangs costs only its time limit, and reading leaves the folder as
it was in each of the three states of a GeoPackage under edit; rows only in
``-wal`` are read from a local copy.
"""

import json
import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import shapely

from archiwista.config import AppPaths
from archiwista.errors import OwnReaderError
from archiwista.owndata import reader as reader_module
from archiwista.owndata.content import content_identity, content_method
from archiwista.owndata.formats import fileset_members
from archiwista.owndata.reader import OwnFileInfo, OwnReader
from tests.fixtures.hostile_files import SECRET_TEXT, hostile_files
from tests.fixtures.own_data import GpkgEditor, OwnFolderManifest, make_own_folder
from tests.fixtures.refused_start import refuse_starts

# make_own_folder writes a TIFF without georeference on purpose.
pytestmark = pytest.mark.filterwarnings(
    "ignore::rasterio.errors.NotGeoreferencedWarning"
)
_HANG_TIMEOUT_S = 3.0
_BASIN = shapely.box(566_200, 241_200, 566_300, 241_300)


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return the local data of the application in this test's directory."""
    return AppPaths(config_file=tmp_path / "config.toml", data_dir=tmp_path / "data")


@pytest.fixture
def reader(paths: AppPaths) -> Iterator[OwnReader]:
    """Yield the reader with its time and memory limits."""
    with OwnReader(paths) as own_reader:
        yield own_reader


def _layers(info: OwnFileInfo) -> list[tuple[str, str | None, int | None]]:
    return [
        (layer.name, layer.geometry_type, layer.feature_count) for layer in info.layers
    ]


def test_reader_reads_each_family_as_written(tmp_path: Path, reader: OwnReader) -> None:
    """Drivers, sets, layers and CRS as written; no CRS and no georeference too.

    A Shapefile is read with its members; one without ``.prj`` has an
    extent but no CRS; a TIFF placed only by its world file has no
    georeference (``EMPTY_DIR``); CSV and TXT have no driver.
    """
    # Arrange
    folder = make_own_folder(tmp_path / "dane")

    # Act
    read = {
        entry.family: reader.read(folder.root / entry.path) for entry in folder.indexed
    }

    # Assert
    for entry in folder.indexed:
        info = read[entry.family]
        assert info.error is None, entry.family
        assert info.driver == entry.driver, entry.family
        assert info.native_crs == entry.crs, entry.family
        assert info.members == tuple(Path(name).name for name in entry.members)
        assert _layers(info) == [
            (layer.name, layer.geometry_type, layer.feature_count)
            for layer in entry.layers
        ], entry.family
        assert info.feature_count == entry.feature_count, entry.family
        raster = info.raster
        dimensions = None if raster is None else (raster.width, raster.height)
        expected = None if entry.raster is None else entry.raster[:2]
        assert dimensions == expected, entry.family
    assert read["shp_no_prj"].native_bbox is not None
    world_file = read["tif_world_file"]
    assert world_file.raster is not None and not world_file.raster.georeferenced
    assert world_file.native_bbox is None
    assert read["tif_2180"].raster is not None and read["tif_2180"].raster.georeferenced


def test_mapinfo_view_and_seamless_table_unsupported(
    tmp_path: Path, reader: OwnReader
) -> None:
    """A view and a seamless table name other tables: refused, nothing read."""
    # Arrange
    planted = hostile_files(tmp_path / "dane")

    # Act
    answers = [
        reader.read(path) for path in (planted.mapinfo_view, planted.mapinfo_seamless)
    ]

    # Assert
    assert [info.error for info in answers] == ["unsupported_format"] * 2
    assert [info.layers for info in answers] == [(), ()]


def test_set_with_a_linked_member_refused(tmp_path: Path, reader: OwnReader) -> None:
    """A member that is a symbolic link would be opened by name: refused."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("shp_full",))
    path = folder.path("shp_full")
    outside = tmp_path / "poza"
    outside.mkdir()
    dbf = path.with_suffix(".dbf")
    dbf.rename(outside / dbf.name)
    dbf.symlink_to(outside / dbf.name)

    # Act
    info = reader.read(path)

    # Assert
    assert (info.error, info.layers) == ("unsupported_format", ())
    assert "dzialki.dbf" in info.members


def test_vrt_content_under_data_names_never_reads_its_target(
    tmp_path: Path, reader: OwnReader
) -> None:
    """VRT XML named ``.tif``/``.asc``, OGR VRT named ``.gpkg``/``.shp``... fail.

    Read with the format's own driver, none of them reports the target's
    raster, layer or attributes.
    """
    # Arrange
    planted = hostile_files(tmp_path / "dane")

    # Act
    answers = {
        path.name: reader.read(path)
        for path in (*planted.vrt_rasters, *planted.ogr_vrt_vectors)
    }

    # Assert
    assert sorted(answers) == [
        "vrt.asc",
        "vrt.fgb",
        "vrt.geojson",
        "vrt.gpkg",
        "vrt.shp",
        "vrt.tif",
    ]
    for name, info in answers.items():
        assert info.error in ("unsupported_format", "unreadable"), name
        assert (info.raster, info.layers, info.native_bbox) == (None, (), None), name
        assert SECRET_TEXT not in json.dumps(info.to_json()), name


def test_hanging_file_killed_and_next_files_read(
    tmp_path: Path, paths: AppPaths
) -> None:
    """A file whose reading blocks is killed at its limit; the next file is read."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("geojson_wgs84", "fgb"))
    hanging = folder.root / "zawieszony.geojson"
    os.mkfifo(hanging)  # opening it for reading blocks: no writer ever comes

    with OwnReader(paths, timeout_s=_HANG_TIMEOUT_S) as reader:
        # Act
        started = time.monotonic()
        stuck = reader.read(hanging)
        waited = time.monotonic() - started
        after = [
            reader.read(folder.path("geojson_wgs84")),
            reader.read(folder.path("fgb")),
        ]

    # Assert
    assert (stuck.error, stuck.driver, stuck.members) == (
        "timeout",
        "GeoJSON",
        ("zawieszony.geojson",),
    )
    assert _HANG_TIMEOUT_S <= waited < _HANG_TIMEOUT_S + 10
    assert [(info.error, info.feature_count) for info in after] == [
        (None, 2),
        (None, 3),
    ]


def test_reader_that_cannot_start_is_own_reader_failed(
    tmp_path: Path, paths: AppPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused start is ``own_reader_failed``; the next start reads the file."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("geojson_wgs84",))
    refused = refuse_starts(monkeypatch, reader_module)

    with OwnReader(paths) as reader:
        # Act
        with pytest.raises(OwnReaderError) as caught:
            reader.read(folder.path("geojson_wgs84"))
        refused.on = False
        info = reader.read(folder.path("geojson_wgs84"))

    # Assert
    assert (caught.value.code, caught.value.details["reason"]) == (
        "missing_dependency",
        "own_reader_failed",
    )
    assert (info.error, info.feature_count) == (None, 2)


def _listing(root: Path) -> dict[str, tuple[int, int] | None]:
    """Every file and directory under ``root`` with its size and time (lstat).

    A ``-shm`` keeps only its name: it is the editor's shared memory.
    """
    found: dict[str, tuple[int, int] | None] = {}
    for directory, names, files in os.walk(root):
        for name in [*names, *files, "."]:
            path = Path(directory, name)
            stat = path.lstat()
            relative = path.relative_to(root).as_posix()
            found[relative] = (
                None if name.endswith("-shm") else (stat.st_size, stat.st_mtime_ns)
            )
    return found


def _read_everything(
    folder: OwnFolderManifest, reader: OwnReader, work: Path
) -> dict[str, OwnFileInfo]:
    """Read and identify every file a scan would, as a scan would."""
    answers: dict[str, OwnFileInfo] = {}
    for entry in folder.indexed:
        path = folder.root / entry.path
        answers[entry.family] = reader.read(path)
        method = content_method(path)
        files = fileset_members(path) if method == "fileset" else (path,)
        content_identity(files, method=method, work_dir=work)
    return answers


@pytest.mark.parametrize("state", ["closed_wal", "open_in_editor", "crashed_editor"])
def test_data_folder_unchanged_after_reads(
    tmp_path: Path, reader: OwnReader, state: str
) -> None:
    """Names, sizes, times of files and directories stay; no file is added.

    The GeoPackage is a WAL database without ``-wal`` (a), open in an
    editor with committed frames and an open transaction (b), or left with
    ``-wal`` and no ``-shm`` by a crash (c); its committed rows are read.
    """
    # Arrange
    folder = make_own_folder(tmp_path / "dane")
    work = tmp_path / "work"
    work.mkdir()
    editor = GpkgEditor(folder.path("gpkg_layers"))
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
    editor.commit()
    if state == "closed_wal":
        editor.close()
    elif state == "open_in_editor":
        editor.begin()
        editor.insert("zlewnie", _BASIN, nazwa="Zlewnia D")
    else:
        editor.crash_without_shm()
    before = _listing(folder.root)

    # Act
    try:
        answers = _read_everything(folder, reader, work)
        after = _listing(folder.root)
    finally:
        editor.close()

    # Assert
    assert [info.error for info in answers.values()] == [None] * len(answers)
    assert _layers(answers["gpkg_layers"])[1] == ("zlewnie", "Polygon", 3)
    assert after == before
    assert ("kanalizacja.gpkg-wal" in before) == (state != "closed_wal")


def test_wal_without_shm_read_from_local_copy(
    tmp_path: Path, reader: OwnReader
) -> None:
    """A row committed only in ``-wal`` is read; the folder gets no ``-shm``."""
    # Arrange
    folder = make_own_folder(tmp_path / "dane", families=("gpkg_layers",))
    path = folder.path("gpkg_layers")
    editor = GpkgEditor(path)
    editor.begin()
    editor.insert("zlewnie", _BASIN, nazwa="Zlewnia C")
    editor.commit()
    editor.crash_without_shm()
    before = _listing(folder.root)

    # Act
    info = reader.read(path)

    # Assert
    assert _layers(info) == [("przewody", "LineString", 3), ("zlewnie", "Polygon", 3)]
    assert _listing(folder.root) == before
    assert sorted(before) == [".", "kanalizacja.gpkg", "kanalizacja.gpkg-wal"]
