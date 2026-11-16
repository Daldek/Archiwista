"""Contract of the preview libraries in the sandbox (plan v0.2, step 1).

What steps 4-8 stand on, checked before they are built: a tile warped by
``rasterio.warp.reproject`` with Kartograf's pinned operation lands within
2 m of the control point 3722, while ``WarpedVRT`` (and rio-tiler) ignore a
forced operation; a LAZ file is read from a later chunk without the earlier
ones; the three states of a SQLite file read as decision 8 says; and in a
sandboxed process GDAL opens no file but the one named, with no side file
written. Every library call runs in ``tests/fixtures/preview_probes.py``
started by ``run_untrusted``; a control without one sandbox variable shows
a probe is not moot.
"""

import contextlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import kartograf
import laspy
import morecantile
import numpy as np
import pyogrio.raw
import pytest
import rasterio
import shapely
from pyproj import CRS, Geod, Transformer
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from archiwista.owndata.content import SHADOW_SUFFIXES
from archiwista.sandbox import run_untrusted, untrusted_env
from tests.fixtures import preview_probes
from tests.fixtures.control_points import POINT_3722

PROBE_COMMAND = (sys.executable, str(Path(preview_probes.__file__)))
PROBE_TIMEOUT_S = 120.0
TILE_ZOOM = 19
MAX_DEVIATION_M = 2.0
# 50 m east in EPSG:3857 is about 32 m on the ground at 49.76° N.
SHIFT_SEEN_M = 25.0
SECRET_VALUE = 77
OWN_VALUE = 5
# Editor of a GeoPackage, like QGIS: one committed row stays in the WAL,
# a second one in an open transaction, until a line comes on stdin.
EDITOR = """
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], isolation_level=None)
connection.execute("PRAGMA wal_autocheckpoint=0")
add = "INSERT INTO pts (geom, name) SELECT geom, ? FROM pts LIMIT 1"
connection.execute(add, ("committed",))
connection.execute("BEGIN IMMEDIATE")
connection.execute(add, ("open",))
print("ready", flush=True)
sys.stdin.readline()
connection.execute("ROLLBACK")
connection.close()
"""
GPKG_ROWS = ["a", "b", "c"]
_MODULE = re.compile(r"\s*create\s+virtual\s+table\s.*?\busing\s+(\w+)", re.I | re.S)


def _probe(request: dict[str, Any], *, without: str | None = None) -> Any:
    """Run a probe in the sandbox, or with one sandbox variable left out."""
    data = (json.dumps(request) + "\n").encode("utf-8")
    if without is None:
        finished = run_untrusted(PROBE_COMMAND, timeout_s=PROBE_TIMEOUT_S, input=data)
    else:
        env = untrusted_env()
        del env[without]
        finished = subprocess.run(
            PROBE_COMMAND,
            input=data,
            stdout=subprocess.PIPE,
            env=env,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    assert finished.returncode == 0, finished.stdout
    return json.loads(finished.stdout.decode("utf-8").splitlines()[-1])


def _geotiff(path: Path, value: int, *, size: int = 16) -> Path:
    """Single-band GeoTIFF in EPSG:2180 filled with ``value``."""
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="uint8",
        crs="EPSG:2180",
        transform=from_origin(500_000, 300_000, 10, 10),
    ) as dst:
        dst.write(np.full((1, size, size), value, dtype="uint8"))
    return path


def _vrt(source: Path, *, size: int = 16) -> str:
    """VRT XML whose band is the first band of ``source``."""
    return f"""<VRTDataset rasterXSize="{size}" rasterYSize="{size}">
  <VRTRasterBand dataType="Byte" band="1">
    <SimpleSource>
      <SourceFilename relativeToVRT="0">{source}</SourceFilename>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>
"""


def _files(directory: Path) -> dict[str, tuple[int, int]]:
    """Names of a directory's files with their size and modification time."""
    return {
        item.name: (item.stat().st_size, item.stat().st_mtime_ns)
        for item in directory.iterdir()
    }


# GDAL opening (decision 3) -------------------------------------------------


def test_vrt_refused_after_warpedvrt_in_same_process(tmp_path: Path) -> None:
    """After a ``WarpedVRT`` only the explicit driver keeps VRT XML out.

    ``GDAL_SKIP`` refuses VRT XML named ``.tif`` until the first warp; then
    a plain open reads the file it names. Opened through the format table,
    ``.tif`` and ``.asc`` with VRT XML are refused before and after.
    """
    # Arrange
    secret = _geotiff(tmp_path / "secret.tif", SECRET_VALUE)
    _geotiff(tmp_path / "a.tif", OWN_VALUE)
    for name in ("evil.tif", "evil.asc"):
        (tmp_path / name).write_text(_vrt(secret), encoding="utf-8")

    # Act
    answer = _probe({"probe": "raster_vrt", "dir": str(tmp_path)})

    # Assert
    assert answer["plain_before_warp"]["refused"] == "RasterioIOError"
    assert answer["plain_after_warp"] == {"max": SECRET_VALUE, "driver": "VRT"}
    assert answer["evil.tif"] == {"refused": "RasterioIOError", "layer": "library"}
    assert answer["evil.asc"] == {"refused": "RasterioIOError", "layer": "library"}


def test_sibling_ovr_ignored(tmp_path: Path) -> None:
    """An ``a.tif.ovr`` with VRT XML is no overview of ``a.tif`` (``EMPTY_DIR``).

    Without ``EMPTY_DIR`` the same process, after a warp, reads the secret
    file through the overview.
    """
    # Arrange
    secret = _geotiff(tmp_path / "secret.tif", SECRET_VALUE)
    _geotiff(tmp_path / "a.tif", OWN_VALUE)
    (tmp_path / "a.tif.ovr").write_text(_vrt(secret, size=8), encoding="utf-8")
    request = {"probe": "sibling_ovr", "dir": str(tmp_path)}

    # Act
    sandboxed = _probe(request)
    seeing_siblings = _probe(request, without="GDAL_DISABLE_READDIR_ON_OPEN")

    # Assert
    assert sandboxed == {"overviews": [], "max": OWN_VALUE}
    assert seeing_siblings == {"overviews": [2], "max": SECRET_VALUE}


def test_statistics_write_no_aux_xml(tmp_path: Path) -> None:
    """Band statistics leave no ``a.tif.aux.xml`` next to the file (PAM off)."""
    # Arrange
    _geotiff(tmp_path / "a.tif", OWN_VALUE)
    request = {"probe": "statistics", "dir": str(tmp_path)}

    # Act
    sandboxed = _probe(request)
    with_pam = _probe(request, without="GDAL_PAM_ENABLED")

    # Assert
    assert sandboxed["files"] == ["a.tif"]
    assert sandboxed["max"] == OWN_VALUE
    assert with_pam["files"] == ["a.tif", "a.tif.aux.xml"]


def test_ogr_vrt_refused_under_vector_names(tmp_path: Path) -> None:
    """OGR VRT XML named as a vector file never reaches the file it names.

    The prefixes of GeoPackage and GeoJSON make GDAL refuse it; a Shapefile
    and a FlatGeobuf fail their signature, a MapInfo table its header,
    before GDAL opens anything. Without ``GDAL_SKIP`` a plain open reads
    the secret.
    """
    # Arrange
    _geotiff(tmp_path / "a.tif", OWN_VALUE)
    secret = tmp_path / "secret.geojson"
    secret.write_text(
        '{"type": "FeatureCollection", "features": [{"type": "Feature",'
        ' "properties": {"name": "SECRET"},'
        ' "geometry": {"type": "Point", "coordinates": [19, 50]}}]}',
        encoding="utf-8",
    )
    vrt = (
        f"<OGRVRTDataSource><OGRVRTLayer name='stolen'>"
        f"<SrcDataSource>{secret}</SrcDataSource><SrcLayer>secret</SrcLayer>"
        f"</OGRVRTLayer></OGRVRTDataSource>"
    )
    names = ["evil.gpkg", "evil.geojson", "evil.shp", "evil.fgb", "evil.tab"]
    for name in names:
        (tmp_path / name).write_text(vrt, encoding="utf-8")
    request = {
        "probe": "vector_vrt",
        "dir": str(tmp_path),
        "names": names,
        "plain": "evil.geojson",
    }

    # Act
    sandboxed = _probe(request)
    without_skip = _probe(request, without="GDAL_SKIP")

    # Assert
    layers = {name: sandboxed[name].get("layer") for name in names}
    assert layers == {
        "evil.gpkg": "library",
        "evil.geojson": "library",
        "evil.shp": "formats",
        "evil.fgb": "formats",
        "evil.tab": "formats",
    }
    assert sandboxed["plain"]["layer"] == "library"
    assert without_skip["plain"] == {"values": ["SECRET"]}
    assert without_skip["evil.geojson"]["layer"] == "library"


def test_fileset_members_read_with_empty_dir(tmp_path: Path) -> None:
    """``EMPTY_DIR`` keeps the members of a Shapefile and a MapInfo table.

    The Shapefile's text decodes from Windows-1250 only by its ``.cpg`` (the
    ``.dbf`` names no code page), its CRS comes from ``.prj``; the MapInfo
    table reads its ``.dat``, ``.map`` and ``.id``.
    """
    # Arrange
    geometries = shapely.to_wkb(
        np.array([shapely.Point(500_000, 300_000), shapely.Point(500_010, 300_010)])
    )
    values = np.array(["zażółć", "gęślą"], dtype=object)
    shp, tab = tmp_path / "rivers.shp", tmp_path / "lakes.tab"
    pyogrio.raw.write(
        shp,
        geometries,
        [values],
        ["name"],
        driver="ESRI Shapefile",
        geometry_type="Point",
        crs="EPSG:2180",
        encoding="cp1250",
    )
    pyogrio.raw.write(
        tab,
        geometries,
        [np.array(["x", "y"], dtype=object)],
        ["name"],
        driver="MapInfo File",
        geometry_type="Point",
        crs="EPSG:2180",
    )
    no_cpg = tmp_path / "no_cpg"
    no_cpg.mkdir()
    for member in tmp_path.glob("rivers.*"):
        if member.suffix != ".cpg":
            shutil.copy(member, no_cpg / member.name)
    files = [str(shp), str(tab), str(no_cpg / shp.name)]

    # Act
    answer = _probe({"probe": "fileset", "files": files})

    # Assert
    rivers, lakes, undecoded = (answer[name] for name in files)
    assert rivers["values"] == ["zażółć", "gęślą"]
    assert rivers["geometries"] == 2
    assert CRS.from_user_input(rivers["crs"]).to_epsg() == 2180
    assert (lakes["values"], lakes["geometries"]) == (["x", "y"], 2)
    assert undecoded["values"] != rivers["values"]


def test_gpkg_path_with_colon_opened_quoted(tmp_path: Path) -> None:
    """GDAL splits ``GPKG:<path>`` at ``:``; the quoted name opens the file."""
    # Arrange
    path = tmp_path / "plan:2026.gpkg"
    geometries = shapely.to_wkb(np.array([shapely.Point(500_000, 300_000)]))
    pyogrio.raw.write(
        path,
        geometries,
        [np.array(["a"], dtype=object)],
        ["name"],
        driver="GPKG",
        geometry_type="Point",
        crs="EPSG:2180",
    )

    # Act
    answer = _probe({"probe": "gpkg_colon", "path": str(path)})

    # Assert
    assert answer["table"] == {"features": 1}
    assert answer["unquoted"]["layer"] == "library"


# Warp with the pinned operation (decision 4) ---------------------------------


@pytest.fixture(scope="module")
def warped(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Tiles at z = 19 over point 3722 from two rasters with a bright block.

    One raster in EPSG:5514 (0.5 m pixels, internal overviews), one in
    EPSG:4326; each has a 4 x 4 pixel bright block centred on the point.
    """
    directory = tmp_path_factory.mktemp("warp")
    x, y = POINT_3722.epsg5514
    lon, lat = POINT_3722.etrs89
    sjtsk = _bright_block(directory / "sjtsk.tif", "EPSG:5514", x, y, 0.5)
    wgs84 = _bright_block(directory / "wgs84.tif", "EPSG:4326", lon, lat, 2e-6)
    tile = morecantile.tms.get("WebMercatorQuad").tile(lon, lat, TILE_ZOOM)
    operation = kartograf.pinned_transform("EPSG:5514", "EPSG:3857").gdal_operation()
    answer: dict[str, Any] = _probe(
        {
            "probe": "warp",
            "sjtsk": str(sjtsk),
            "wgs84": str(wgs84),
            "tile": [tile.x, tile.y, tile.z],
            "operation": operation,
            # The same operation moved 50 m east: shows whether it is used.
            "shifted": f"{operation} step proj=affine xoff=50",
        }
    )
    return answer


def _bright_block(path: Path, crs: str, x: float, y: float, pixel: float) -> Path:
    size = 400
    data = np.zeros((1, size, size), dtype="uint8")
    middle = size // 2
    data[0, middle - 2 : middle + 2, middle - 2 : middle + 2] = 255
    transform = from_origin(x - middle * pixel, y + middle * pixel, pixel, pixel)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=size,
        height=size,
        count=1,
        dtype="uint8",
        crs=crs,
        transform=transform,
        tiled=True,
        blockxsize=128,
        blockysize=128,
    ) as dst:
        dst.write(data)
        dst.build_overviews([2, 4], Resampling.nearest)
    return path


def _deviation_m(spot: list[float]) -> float:
    """Distance of a tile's bright spot from the ETRS89 position of 3722."""
    to_lonlat = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    lon, lat = to_lonlat.transform(spot[0], spot[1])
    reference_lon, reference_lat = POINT_3722.etrs89
    _, _, distance = Geod(ellps="WGS84").inv(reference_lon, reference_lat, lon, lat)
    return float(distance)


def test_forced_operation_tile_within_2_m(warped: dict[str, Any]) -> None:
    """``reproject`` with the pinned operation puts 3722 within 2 m, overview too.

    The operation is really used: moved 50 m east, the spot moves with it.
    In capitals (what ``WarpedVRT`` makes of option values) it is refused.
    """
    assert _deviation_m(warped["forced"]) <= MAX_DEVIATION_M
    assert _deviation_m(warped["forced_overview"]) <= MAX_DEVIATION_M
    assert _deviation_m(warped["shifted"]) > SHIFT_SEEN_M
    assert warped["upper_case"]["layer"] == "library"


def test_warpedvrt_and_rio_tiler_ignore_forced_operation(
    warped: dict[str, Any],
) -> None:
    """A forced operation changes nothing in ``WarpedVRT`` or a rio-tiler tile."""
    assert warped["warped_vrt_shifted"] == warped["warped_vrt_default"]
    assert warped["rio_tiler_shifted"] == warped["rio_tiler_default"]


def test_wgs84_raster_tile_without_forced_operation(warped: dict[str, Any]) -> None:
    """EPSG:4326 to EPSG:3857 is a plain conversion; Kartograf pins none."""
    assert _deviation_m(warped["wgs84_default"]) <= MAX_DEVIATION_M
    with pytest.raises(kartograf.KartografError):
        kartograf.pinned_transform("EPSG:4326", "EPSG:3857")


# LAZ ------------------------------------------------------------------------


def test_laz_seek_reads_later_chunk_without_earlier_ones(tmp_path: Path) -> None:
    """A seek jumps over chunks: it works with the first chunk destroyed.

    The header gives the count and format, the CRS comes from the VLR, and
    reading the same broken file from its start fails.
    """
    # Arrange
    count, seek = 180_000, 150_000  # lazrs chunks of 50 000 points
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.offsets = [500_000.0, 300_000.0, 0.0]
    header.scales = [0.01, 0.01, 0.01]
    header.add_crs(CRS.from_epsg(2180))
    cloud = laspy.LasData(header)
    index = np.arange(count)
    cloud.x = 500_000 + (index % 1000) * 0.5
    cloud.y = 300_000 + (index // 1000) * 0.5
    cloud.z = index * 0.01
    cloud.classification = np.where(index < 100_000, 2, 6).astype(np.uint8)
    path, broken = tmp_path / "cloud.laz", tmp_path / "broken.laz"
    cloud.write(path, laz_backend=laspy.LazBackend.Lazrs)
    data = bytearray(path.read_bytes())
    with laspy.open(path) as reader:
        start = reader.header.offset_to_point_data
    for position in range(start + 64, start + 2064):
        data[position] ^= 0x5A
    broken.write_bytes(bytes(data))

    # Act
    answer = _probe(
        {"probe": "laz", "path": str(path), "broken": str(broken), "seek": seek}
    )

    # Assert
    assert (answer["points"], answer["format"]) == (count, 6)
    assert answer["compressed"] is True
    assert answer["epsg"] == 2180
    assert answer["seek_in_broken"] == {
        "z": pytest.approx([1500.0, 1500.01, 1500.02]),
        "classes": [6, 6, 6],
    }
    assert answer["start_of_broken"]["layer"] == "library"


# SQLite states (decision 8) ---------------------------------------------------


def _wal_geopackage(directory: Path) -> Path:
    """Write a GeoPackage switched to WAL and closed: no ``-wal`` next to it."""
    directory.mkdir()
    path = directory / "data.gpkg"
    points = [shapely.Point(500_000 + step, 300_000) for step in range(3)]
    pyogrio.raw.write(
        path,
        shapely.to_wkb(np.array(points)),
        [np.array(GPKG_ROWS, dtype=object)],
        ["name"],
        driver="GPKG",
        geometry_type="Point",
        crs="EPSG:2180",
        layer="pts",
        SPATIAL_INDEX="NO",
    )
    with contextlib.closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
    return path


@contextlib.contextmanager
def _editing(path: Path) -> Iterator[None]:
    """Keep an editor process writing ``path`` until the block ends."""
    with subprocess.Popen(
        [sys.executable, "-c", EDITOR, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as editor:
        assert editor.stdin is not None and editor.stdout is not None
        try:
            assert editor.stdout.readline().strip() == "ready"
            yield
        finally:
            editor.stdin.write("\n")
            editor.stdin.flush()
            editor.wait(timeout=30)


def _read(path: Path, way: str, *, work: Path | None = None) -> Any:
    request = {"probe": "sqlite", "path": str(path), "way": way, "table": "pts"}
    if work is not None:
        work.mkdir(exist_ok=True)
        request["work"] = str(work)
    return _probe(request)


def test_sqlite_wal_database_without_wal_file_read_in_place(tmp_path: Path) -> None:
    """State (a): ``immutable=1`` and GDAL ``IMMUTABLE=YES`` add no file.

    ``mode=ro`` would: it creates ``-wal`` and ``-shm`` next to the file.
    """
    # Arrange
    path = _wal_geopackage(tmp_path / "a")
    assert path.read_bytes()[18:20] == b"\x02\x02"  # WAL mode in the header
    before = _files(path.parent)

    # Act
    immutable = _read(path, "immutable")
    after_immutable = _files(path.parent)
    gdal = _read(path, "gdal_immutable")
    after_gdal = _files(path.parent)
    read_only = _read(path, "read_only")

    # Assert
    assert immutable == gdal == read_only == {"rows": GPKG_ROWS}
    assert after_immutable == after_gdal == before
    assert sorted(_files(path.parent)) == [
        "data.gpkg",
        "data.gpkg-shm",
        "data.gpkg-wal",
    ]


def test_sqlite_open_writer_backup_copies_committed_rows_only(tmp_path: Path) -> None:
    """State (b): ``mode=ro`` and ``backup`` copy the committed rows, add nothing.

    The editor's open transaction stays out; the file and its ``-wal`` keep
    their size and time (the ``-shm`` is the editor's shared memory).
    """
    # Arrange
    path = _wal_geopackage(tmp_path / "b")

    # Act
    with _editing(path):
        before = _files(path.parent)
        answer = _read(path, "backup", work=tmp_path / "work")
        after = _files(path.parent)

    # Assert
    assert answer == {"rows": [*GPKG_ROWS, "committed"], "integrity": "ok"}
    assert sorted(before) == ["data.gpkg", "data.gpkg-shm", "data.gpkg-wal"]
    assert sorted(after) == sorted(before)
    assert {name: after[name] for name in ("data.gpkg", "data.gpkg-wal")} == {
        name: before[name] for name in ("data.gpkg", "data.gpkg-wal")
    }


def test_sqlite_wal_without_shm_read_only_from_copy(tmp_path: Path) -> None:
    """State (c): every reading in place changes the folder; a copy does not.

    ``immutable=1`` misses the rows in the WAL, ``mode=ro`` creates
    ``-shm``, GDAL (also with ``IMMUTABLE=YES``) writes the WAL into the file
    and removes it. A copy of the file and its ``-wal`` in the work
    directory has every committed row and passes ``integrity_check``.
    """
    # Arrange
    edited = _wal_geopackage(tmp_path / "b")
    state = tmp_path / "c"
    state.mkdir()
    with _editing(edited):
        for name in ("data.gpkg", "data.gpkg-wal"):
            shutil.copy2(edited.parent / name, state / name)
    pristine = _files(state)
    original = (state / "data.gpkg").read_bytes()
    rows = [*GPKG_ROWS, "committed"]

    def fresh(name: str) -> Path:
        copy = tmp_path / name
        shutil.copytree(state, copy)
        return copy / "data.gpkg"

    # Act
    immutable = _read(state / "data.gpkg", "immutable")
    after_immutable = _files(state)
    copied = _read(state / "data.gpkg", "copy_with_wal", work=tmp_path / "work")
    after_copy = _files(state)
    read_only_path = fresh("read_only")
    read_only = _read(read_only_path, "read_only")
    outcomes = {}
    for way in ("gdal", "gdal_immutable"):
        gdal_path = fresh(way)
        answer = _read(gdal_path, way)
        outcomes[way] = (
            answer["rows"],
            sorted(_files(gdal_path.parent)),
            gdal_path.read_bytes() != original,
        )

    # Assert
    assert immutable == {"rows": GPKG_ROWS}
    assert after_immutable == pristine
    assert copied == {"rows": rows, "integrity": "ok"}
    assert after_copy == pristine
    assert read_only == {"rows": rows}
    assert sorted(_files(read_only_path.parent)) == [
        "data.gpkg",
        "data.gpkg-shm",
        "data.gpkg-wal",
    ]
    assert outcomes == {
        "gdal": (rows, ["data.gpkg"], True),
        "gdal_immutable": (GPKG_ROWS, ["data.gpkg"], True),
    }


def test_sqlite_virtual_and_shadow_tables_known_from_master(tmp_path: Path) -> None:
    """Virtual tables and their shadows from ``sqlite_master`` = ``table_list``.

    ``PRAGMA table_list`` (SQLite 3.37) is the reference; the index allows
    SQLite 3.35, so decision 8 classifies from ``sqlite_master``: ``CREATE
    VIRTUAL TABLE`` and the module's shadow suffixes.
    """
    # Arrange
    statements = [
        "CREATE TABLE plain (id INTEGER PRIMARY KEY, body TEXT)",
        "CREATE TABLE rt_extra (id INTEGER PRIMARY KEY)",
        "CREATE VIRTUAL TABLE rt USING rtree(id, min_x, max_x, min_y, max_y)",
        "CREATE VIRTUAL TABLE f3 USING fts3(body)",
        "CREATE VIRTUAL TABLE f4 USING fts4(body)",
        "CREATE VIRTUAL TABLE f5 USING fts5(body)",
    ]
    with contextlib.closing(sqlite3.connect(tmp_path / "virtual.sqlite")) as db:
        for statement in statements:
            db.execute(statement)
        db.commit()

        # Act
        master = db.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        listed = db.execute(
            "SELECT name, type FROM pragma_table_list WHERE schema = 'main'"
            " AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

    # Assert
    assert _classify(master) == dict(listed)


def _classify(master: list[tuple[str, str]]) -> dict[str, str]:
    """Kind of each table by decision 8: ``virtual``, ``shadow`` or ``table``."""
    modules = {
        name: found[1].lower()
        for name, sql in master
        if (found := _MODULE.match(sql or "")) is not None
    }
    shadows = {
        f"{name}{suffix}"
        for name, module in modules.items()
        for suffix in SHADOW_SUFFIXES.get(module, ())
    }
    return {
        name: "virtual" if name in modules else "shadow" if name in shadows else "table"
        for name, _ in master
    }
