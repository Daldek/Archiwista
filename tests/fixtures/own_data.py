"""Own-data folders, a QGIS-like GeoPackage editor and snapshots for tests.

Plan v0.2, step 2 (decisions 8 and 9):

- ``make_own_folder(path, families=...)`` writes a project's data folder with
  every own-data family the reader must handle (GeoPackage, Shapefile with
  and without ``.prj``, GeoTIFF with and without georeference, GeoJSON,
  FlatGeobuf, MapInfo TAB, unrecognised CSV and TXT, hidden files, a
  subdirectory, symbolic links leaving the folder, a GeoPackage in EPSG:5514
  with a point on control point 3722) and returns what a scan must find;
- ``project_inside_store(store_root)`` writes a project whose manifest lies
  in a producer directory (its default ``dane/`` would be in the store);
- ``GpkgEditor(path)`` edits a GeoPackage from another process the way QGIS
  does: WAL journal, committed frames left in ``-wal``, an open transaction,
  a crash leaving ``-wal`` without ``-shm`` and an open for update that
  rewrites only derived data (``gpkg_ogr_contents``, ``last_change``);
- ``write_snapshot_fixture(folder, source, ...)`` writes a snapshot directory
  in the ``archiwista-snapshot/1`` layout for scan tests before the snapshot
  procedure exists.

Vector and raster files are written by GDAL (pyogrio, rasterio), as a
desktop GIS would write them; the editor speaks plain SQLite with the
GeoPackage SQL functions GDAL's triggers call.
"""

import hashlib
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Literal, get_args

import numpy as np
import pyogrio.raw
import rasterio
import shapely
from rasterio.transform import from_bounds

from archiwista.projects import ProjectDocument, StoreRoot, change_project_file
from archiwista.sources.registry import APP_DISTRIBUTION
from tests.fixtures.control_points import POINT_3722

OwnFamily = Literal[
    "gpkg_layers",
    "shp_full",
    "shp_no_prj",
    "tif_2180",
    "tif_world_file",
    "geojson_wgs84",
    "fgb",
    "tab_native",
    "csv",
    "txt",
    "hidden",
    "subdir",
    "symlink_outside",
    "gpkg_5514_control",
]
ALL_OWN_FAMILIES: tuple[OwnFamily, ...] = get_args(OwnFamily)

# Kraków, EPSG:2180 (the area of the plan's snapshot example).
_AREA = (566_100.0, 241_050.0, 569_800.0, 246_200.0)
_OUTSIDE_SUFFIX = ".poza"
"""Sibling directory (``<folder>.poza``) the symbolic links lead to."""

SNAPSHOTS_DIR = ".wersje"
SNAPSHOT_FILE = "migawka.json"
SNAPSHOT_SCHEMA = "archiwista-snapshot/1"
ContentMethod = Literal["sqlite", "fileset", "bytes"]


@dataclass(frozen=True)
class OwnLayer:
    """A vector layer of an own-data file."""

    name: str
    geometry_type: str
    """OGR name: ``Point``, ``LineString``, ``Polygon``."""
    feature_count: int


@dataclass(frozen=True)
class OwnFile:
    """One file (or file set) of an own-data folder and what a scan sees."""

    family: OwnFamily
    path: str
    """Main file relative to the folder, ``/`` separated."""
    members: tuple[str, ...]
    """Every file of the set relative to the folder, main file first."""
    indexed: bool
    """The scan lists it (not hidden, not behind a link leaving the folder)."""
    driver: str | None
    """GDAL/OGR driver of a recognised file; ``None``: unrecognised."""
    crs: str | None
    """CRS as GDAL reports it (``EPSG:<code>`` when identified, else WKT);
    ``None``: no CRS of its own."""
    layers: tuple[OwnLayer, ...] = ()
    raster: tuple[int, int, int] | None = None
    """``(width, height, bands)`` of a raster."""

    @property
    def feature_count(self) -> int | None:
        """Sum of the layers' features (``None`` for a raster or no data)."""
        return (
            sum(layer.feature_count for layer in self.layers) if self.layers else None
        )


@dataclass(frozen=True)
class OwnFolderManifest:
    """What ``make_own_folder`` wrote."""

    root: Path
    files: tuple[OwnFile, ...]
    outside: Path | None
    """Directory outside the folder the symbolic links lead to."""

    def file(self, family: OwnFamily) -> OwnFile:
        """Return the file of ``family``."""
        return next(entry for entry in self.files if entry.family == family)

    def path(self, family: OwnFamily) -> Path:
        """Absolute path of the main file of ``family``."""
        return self.root / self.file(family).path

    @property
    def indexed(self) -> tuple[OwnFile, ...]:
        """Files the scan must list."""
        return tuple(entry for entry in self.files if entry.indexed)


def make_own_folder(
    path: Path, *, families: Collection[str] = ALL_OWN_FAMILIES
) -> OwnFolderManifest:
    """Write an own-data folder with the requested families.

    Parameters
    ----------
    path : Path
        Missing or empty directory; becomes the data folder.
    families : collection of OwnFamily, optional
        Families to write (default: all). ``symlink_outside`` also writes
        ``<path>.poza/`` next to the folder.

    Returns
    -------
    OwnFolderManifest
        The files and their expected reading.

    Raises
    ------
    ValueError
        A non-empty ``path`` or an unknown family.
    """
    unknown = set(families) - set(ALL_OWN_FAMILIES)
    if unknown:
        raise ValueError(f"unknown own-data families: {sorted(unknown)}")
    path = path.absolute()
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"own-data folder is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    outside = path.with_name(path.name + _OUTSIDE_SUFFIX)
    files = tuple(
        _WRITERS[family](path, outside)
        for family in ALL_OWN_FAMILIES
        if family in families
    )
    return OwnFolderManifest(
        path, files, outside if "symlink_outside" in families else None
    )


def _at(fx: float, fy: float) -> tuple[float, float]:
    min_x, min_y, max_x, max_y = _AREA
    return (min_x + (max_x - min_x) * fx, min_y + (max_y - min_y) * fy)


def _write_vector(
    path: Path,
    *,
    driver: str,
    layer: str,
    geometry_type: str,
    crs: str | None,
    geometries: Sequence[shapely.Geometry],
    fields: dict[str, Sequence[Any]],
) -> OwnLayer:
    """One layer through GDAL (a new file, or a new layer of a GeoPackage)."""
    arrays = [
        np.array(values, dtype=np.int32 if isinstance(values[0], int) else object)
        for values in fields.values()
    ]
    pyogrio.raw.write(
        path,
        np.array([shapely.to_wkb(geometry) for geometry in geometries], dtype=object),
        arrays,
        list(fields),
        layer=layer,
        driver=driver,
        geometry_type=geometry_type,
        crs=crs,
    )
    return OwnLayer(layer, geometry_type, len(geometries))


def _pipes() -> list[shapely.Geometry]:
    return [
        shapely.LineString([_at(0.1, 0.1), _at(0.5, 0.4), _at(0.9, 0.9)]),
        shapely.LineString([_at(0.2, 0.8), _at(0.6, 0.6)]),
        shapely.LineString([_at(0.7, 0.1), _at(0.8, 0.3)]),
    ]


def _parcels() -> list[shapely.Geometry]:
    return [
        shapely.box(*_at(0.1, 0.1), *_at(0.3, 0.3)),
        shapely.box(*_at(0.5, 0.5), *_at(0.8, 0.7)),
    ]


def _points() -> list[shapely.Geometry]:
    return [shapely.Point(_at(0.25, 0.75)), shapely.Point(_at(0.75, 0.25))]


def _gpkg_layers(root: Path, _outside: Path) -> OwnFile:
    target = root / "kanalizacja.gpkg"
    layers = (
        _write_vector(
            target,
            driver="GPKG",
            layer="przewody",
            geometry_type="LineString",
            crs="EPSG:2180",
            geometries=_pipes(),
            fields={"srednica_mm": [300, 200, 160], "material": ["PVC", "PE", "PE"]},
        ),
        _write_vector(
            target,
            driver="GPKG",
            layer="zlewnie",
            geometry_type="Polygon",
            crs="EPSG:2180",
            geometries=_parcels(),
            fields={"nazwa": ["Zlewnia A", "Zlewnia B"]},
        ),
    )
    return OwnFile(
        "gpkg_layers", target.name, (target.name,), True, "GPKG", "EPSG:2180", layers
    )


_SHP_MEMBERS = (".shp", ".shx", ".dbf", ".prj", ".cpg")


def _shapefile(root: Path, family: OwnFamily, stem: str, *, with_prj: bool) -> OwnFile:
    target = root / f"{stem}.shp"
    layer = _write_vector(
        target,
        driver="ESRI Shapefile",
        layer=stem,
        geometry_type="Polygon",
        crs="EPSG:2180",
        geometries=_parcels(),
        fields={"numer": ["12/3", "12/4"], "pow_m2": [812, 640]},
    )
    if not with_prj:
        target.with_suffix(".prj").unlink()
    members = tuple(
        f"{stem}{suffix}" for suffix in _SHP_MEMBERS if with_prj or suffix != ".prj"
    )
    missing = [name for name in members if not (root / name).is_file()]
    if missing:
        raise AssertionError(f"GDAL did not write the Shapefile set: {missing}")
    return OwnFile(
        family,
        target.name,
        members,
        True,
        "ESRI Shapefile",
        "EPSG:2180" if with_prj else None,
        (layer,),
    )


def _shp_full(root: Path, _outside: Path) -> OwnFile:
    return _shapefile(root, "shp_full", "dzialki", with_prj=True)


def _shp_no_prj(root: Path, _outside: Path) -> OwnFile:
    return _shapefile(root, "shp_no_prj", "bez_ukladu", with_prj=False)


_RASTER_SIZE = 64


def _write_raster(target: Path, *, crs: str | None, georeferenced: bool) -> None:
    rows, cols = np.indices((_RASTER_SIZE, _RASTER_SIZE))
    values = (200.0 + rows * 0.5 + cols * 0.25).astype(np.float32)
    profile: dict[str, Any] = {
        "driver": "GTiff",
        "width": _RASTER_SIZE,
        "height": _RASTER_SIZE,
        "count": 1,
        "dtype": "float32",
    }
    if georeferenced:
        profile.update(
            crs=crs, transform=from_bounds(*_AREA, _RASTER_SIZE, _RASTER_SIZE)
        )
    with (
        rasterio.Env(GDAL_PAM_ENABLED="NO"),
        rasterio.open(target, "w", **profile) as dst,
    ):
        dst.write(values, 1)


def _tif_2180(root: Path, _outside: Path) -> OwnFile:
    target = root / "nmt.tif"
    _write_raster(target, crs="EPSG:2180", georeferenced=True)
    return OwnFile(
        "tif_2180",
        target.name,
        (target.name,),
        True,
        "GTiff",
        "EPSG:2180",
        raster=(_RASTER_SIZE, _RASTER_SIZE, 1),
    )


def _tif_world_file(root: Path, _outside: Path) -> OwnFile:
    """Write a TIFF without GeoTIFF tags; only ``skan.tfw`` places it."""
    target = root / "skan.tif"
    _write_raster(target, crs=None, georeferenced=False)
    min_x, min_y, max_x, max_y = _AREA
    dx = (max_x - min_x) / _RASTER_SIZE
    dy = (max_y - min_y) / _RASTER_SIZE
    world = (dx, 0.0, 0.0, -dy, min_x + dx / 2, max_y - dy / 2)
    target.with_suffix(".tfw").write_text(
        "".join(f"{value:.6f}\n" for value in world), encoding="ascii"
    )
    return OwnFile(
        "tif_world_file",
        target.name,
        (target.name,),
        True,
        "GTiff",
        None,
        raster=(_RASTER_SIZE, _RASTER_SIZE, 1),
    )


def _geojson(target: Path, family: OwnFamily, *, indexed: bool, root: Path) -> OwnFile:
    target.parent.mkdir(parents=True, exist_ok=True)
    wgs84 = [shapely.Point(19.94, 50.06), shapely.Point(19.95, 50.07)]
    layer = _write_vector(
        target,
        driver="GeoJSON",
        layer=target.stem,
        geometry_type="Point",
        crs="EPSG:4326",
        geometries=wgs84,
        fields={"opis": ["studnia", "hydrant"]},
    )
    relative = target.relative_to(root).as_posix()
    return OwnFile(
        family, relative, (relative,), indexed, "GeoJSON", "EPSG:4326", (layer,)
    )


def _geojson_wgs84(root: Path, _outside: Path) -> OwnFile:
    return _geojson(
        root / "punkty_wgs84.geojson", "geojson_wgs84", indexed=True, root=root
    )


def _fgb(root: Path, _outside: Path) -> OwnFile:
    target = root / "drogi.fgb"
    layer = _write_vector(
        target,
        driver="FlatGeobuf",
        layer="drogi",
        geometry_type="LineString",
        crs="EPSG:2180",
        geometries=_pipes(),
        fields={"klasa": ["G", "Z", "D"]},
    )
    return OwnFile(
        "fgb", target.name, (target.name,), True, "FlatGeobuf", "EPSG:2180", (layer,)
    )


def _tab_native(root: Path, _outside: Path) -> OwnFile:
    target = root / "budynki.tab"
    layer = _write_vector(
        target,
        driver="MapInfo File",
        layer="budynki",
        geometry_type="Polygon",
        crs="EPSG:2180",
        geometries=_parcels(),
        fields={"funkcja": ["mieszkalny", "gospodarczy"]},
    )
    members = tuple(f"budynki{suffix}" for suffix in (".tab", ".dat", ".map", ".id"))
    missing = [name for name in members if not (root / name).is_file()]
    if missing:
        raise AssertionError(f"GDAL did not write the MapInfo set: {missing}")
    # MapInfo layers may mix geometry kinds: OGR reports the layer type as
    # ``Unknown`` (the features are polygons). A MapInfo CoordSys has no EPSG
    # code: EPSG:2180 comes back as an unnamed Transverse Mercator on WGS84,
    # so the declared CRS is the WKT GDAL reports.
    return OwnFile(
        "tab_native",
        target.name,
        members,
        True,
        "MapInfo File",
        pyogrio.read_info(target)["crs"],
        (OwnLayer(layer.name, "Unknown", layer.feature_count),),
    )


def _csv(root: Path, _outside: Path) -> OwnFile:
    target = root / "pomiary.csv"
    x, y = _at(0.5, 0.5)
    target.write_text(f"x;y;h\n{x:.2f};{y:.2f};212.4\n", encoding="utf-8")
    return OwnFile("csv", target.name, (target.name,), True, None, None)


def _txt(root: Path, _outside: Path) -> OwnFile:
    target = root / "notatki.txt"
    target.write_text("Opis danych projektu.\n", encoding="utf-8")
    return OwnFile("txt", target.name, (target.name,), True, None, None)


def _hidden(root: Path, _outside: Path) -> OwnFile:
    """Write a hidden data file and a hidden directory: never indexed."""
    hidden_dir = root / ".ukryty_katalog" / "dane.geojson"
    _geojson(hidden_dir, "hidden", indexed=False, root=root)
    entry = _geojson(root / ".ukryty.geojson", "hidden", indexed=False, root=root)
    relative = hidden_dir.relative_to(root).as_posix()
    return OwnFile(
        "hidden",
        entry.path,
        (entry.path, relative),
        False,
        "GeoJSON",
        "EPSG:4326",
        entry.layers,
    )


def _subdir(root: Path, _outside: Path) -> OwnFile:
    return _geojson(
        root / "archiwum" / "2025" / "punkty.geojson", "subdir", indexed=True, root=root
    )


def _symlink_outside(root: Path, outside: Path) -> OwnFile:
    """Write a file link and a directory link, both leading outside."""
    outside.mkdir(parents=True, exist_ok=True)
    target = outside / "cel.geojson"
    _geojson(target, "symlink_outside", indexed=False, root=outside)
    (outside / "katalog").mkdir(exist_ok=True)
    shutil.copyfile(target, outside / "katalog" / "cel.geojson")
    (root / "poza.geojson").symlink_to(target)
    (root / "katalog_poza").symlink_to(outside / "katalog", target_is_directory=True)
    return OwnFile(
        "symlink_outside",
        "poza.geojson",
        ("poza.geojson", "katalog_poza"),
        False,
        "GeoJSON",
        "EPSG:4326",
    )


def _gpkg_5514_control(root: Path, _outside: Path) -> OwnFile:
    """GeoPackage in EPSG:5514 with one point on control point 3722."""
    target = root / "punkt_3722.gpkg"
    layer = _write_vector(
        target,
        driver="GPKG",
        layer="punkt_kontrolny",
        geometry_type="Point",
        crs="EPSG:5514",
        geometries=[shapely.Point(POINT_3722.epsg5514)],
        fields={"numer": ["3722"]},
    )
    return OwnFile(
        "gpkg_5514_control",
        target.name,
        (target.name,),
        True,
        "GPKG",
        "EPSG:5514",
        (layer,),
    )


_WRITERS = {
    "gpkg_layers": _gpkg_layers,
    "shp_full": _shp_full,
    "shp_no_prj": _shp_no_prj,
    "tif_2180": _tif_2180,
    "tif_world_file": _tif_world_file,
    "geojson_wgs84": _geojson_wgs84,
    "fgb": _fgb,
    "tab_native": _tab_native,
    "csv": _csv,
    "txt": _txt,
    "hidden": _hidden,
    "subdir": _subdir,
    "symlink_outside": _symlink_outside,
    "gpkg_5514_control": _gpkg_5514_control,
}


def project_inside_store(store_root: Path, name: str = "w-magazynie") -> Path:
    """Write a project whose file lies inside the store root.

    Its default data folder (``<project>/dane/``) would be inside the
    producer directory, so Archiwista must report it ``invalid``. The
    project directory adds a directory Kartograf lists as an unknown
    segment: use it on a store the test owns, after ``make_store``.

    Returns
    -------
    Path
        The project directory (``<store_root>/projekty/<name>``).
    """
    directory = store_root / "projekty" / name
    directory.mkdir(parents=True)
    change_project_file(
        directory,
        create=ProjectDocument(
            name=name,
            description="",
            created_at=datetime(2026, 10, 31, tzinfo=UTC),
            created_by="local",
            stores=(StoreRoot("kartograf", os.path.relpath(store_root, directory)),),
        ),
    )
    return directory


# --- GeoPackage editor ------------------------------------------------------------


class GpkgEditor:
    """Edit a GeoPackage like QGIS: another process, WAL, open transactions.

    The editor process opens ``path`` with ``journal_mode=WAL`` and
    ``wal_autocheckpoint=0``, so committed frames stay in ``<path>-wal``
    until ``close``. Use as a context manager; leaving it closes the
    process (rolling back an open transaction).
    """

    def __init__(self, path: Path) -> None:
        self.path = path.absolute()
        self._process: subprocess.Popen[str] | None = subprocess.Popen(
            [sys.executable, "-m", "tests.fixtures.own_data", "edit", str(self.path)],
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self._call("open")

    @property
    def wal(self) -> Path:
        """The ``-wal`` file of the database."""
        return Path(f"{self.path}-wal")

    @property
    def shm(self) -> Path:
        """The ``-shm`` file of the database."""
        return Path(f"{self.path}-shm")

    def begin(self) -> None:
        """Start a write transaction (``BEGIN IMMEDIATE``)."""
        self._call("begin")

    def insert(self, layer: str, geometry: shapely.Geometry, **values: object) -> int:
        """Insert one feature; GDAL's R*Tree and count triggers run.

        Returns
        -------
        int
            The new ``fid``.
        """
        reply = self._call(
            "insert", layer=layer, wkb=shapely.to_wkb(geometry, hex=True), values=values
        )
        fid: int = reply["fid"]
        return fid

    def commit(self) -> None:
        """Commit the transaction: its frames stay in ``-wal``."""
        self._call("commit")

    def reopen_for_update_unchanged(self) -> None:
        """Write what OGR and QGIS write on an open for update without edits.

        Rewrites ``gpkg_ogr_contents`` (feature counts) and the write
        timestamps ``gpkg_contents.last_change`` (and
        ``gpkg_metadata_reference.timestamp`` when present) in one committed
        transaction; no feature, schema or other column changes.
        """
        self._call("touch")

    def close(self) -> None:
        """Close cleanly: SQLite checkpoints and removes ``-wal``, ``-shm``."""
        if self._process is None:
            return
        self._call("close")
        self._wait()

    def crash_without_shm(self) -> None:
        """Die without closing, then lose ``-shm`` (crash, copied folder).

        Leaves ``-wal`` with the committed frames and no ``-shm``.
        """
        self._call("crash")
        self._wait()
        self.shm.unlink(missing_ok=True)
        if not self.wal.exists():
            raise AssertionError(f"the crash left no WAL: {self.wal}")

    def _call(self, op: str, **arguments: object) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise RuntimeError("the editor is closed")
        process.stdin.write(json.dumps({"op": op, **arguments}) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"the editor process died during {op!r}")
        reply: dict[str, Any] = json.loads(line)
        if "error" in reply:
            raise sqlite3.OperationalError(reply["error"])
        return reply

    def _wait(self) -> None:
        process = self._process
        self._process = None
        if process is not None:
            process.wait(timeout=30)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def __enter__(self) -> "GpkgEditor":
        """Return the editor."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Close the editor; kill its process if closing fails."""
        process = self._process
        if process is None:
            return
        try:
            self.close()
        except (OSError, RuntimeError, sqlite3.Error):
            process.kill()
            self._wait()


def _gpkg_envelope(blob: bytes | None) -> tuple[float, float, float, float] | None:
    """Bounds of a GeoPackage geometry blob (``None``: NULL or empty)."""
    if blob is None:
        return None
    flags = blob[3]
    envelope = (0, 32, 48, 48, 64)[(flags >> 1) & 0b111]
    geometry = shapely.from_wkb(bytes(blob[8 + envelope :]))
    if geometry.is_empty:
        return None
    min_x, min_y, max_x, max_y = geometry.bounds
    return (min_x, min_y, max_x, max_y)


def _register_gpkg_functions(connection: sqlite3.Connection) -> None:
    """Register the SQL functions GDAL's GeoPackage triggers call."""
    connection.create_function(
        "ST_IsEmpty",
        1,
        lambda blob: int(_gpkg_envelope(blob) is None),
        deterministic=True,
    )
    for index, name in enumerate(("ST_MinX", "ST_MinY", "ST_MaxX", "ST_MaxY")):

        def bound(blob: bytes | None, index: int = index) -> float | None:
            envelope = _gpkg_envelope(blob)
            return None if envelope is None else envelope[index]

        connection.create_function(name, 1, bound, deterministic=True)


def _gpkg_geometry(srs_id: int, wkb: bytes) -> bytes:
    """GeoPackage blob with an XY envelope, as GDAL writes it."""
    min_x, min_y, max_x, max_y = shapely.from_wkb(wkb).bounds
    header = struct.pack(
        "<2sBBi4d", b"GP", 0, 0b011, srs_id, min_x, max_x, min_y, max_y
    )
    return header + wkb


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _editor_insert(
    connection: sqlite3.Connection, layer: str, wkb: bytes, values: dict[str, Any]
) -> int:
    row = connection.execute(
        "SELECT column_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
        (layer,),
    ).fetchone()
    if row is None:
        raise sqlite3.OperationalError(f"no feature layer {layer!r}")
    column, srs_id = row
    names = [column, *values]
    cursor = connection.execute(
        f"INSERT INTO {_quoted(layer)} ({', '.join(map(_quoted, names))})"
        f" VALUES ({', '.join('?' * len(names))})",
        (_gpkg_geometry(srs_id, wkb), *values.values()),
    )
    fid = cursor.lastrowid
    assert fid is not None
    return fid


def _editor_touch(connection: sqlite3.Connection) -> None:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    tables = {
        name
        for (name,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    connection.execute("BEGIN IMMEDIATE")
    if "gpkg_ogr_contents" in tables:
        for (table,) in connection.execute(
            "SELECT table_name FROM gpkg_ogr_contents"
        ).fetchall():
            connection.execute(
                "UPDATE gpkg_ogr_contents SET feature_count ="
                f" (SELECT count(*) FROM {_quoted(table)}) WHERE table_name = ?",
                (table,),
            )
    connection.execute("UPDATE gpkg_contents SET last_change = ?", (stamp,))
    if "gpkg_metadata_reference" in tables:
        connection.execute("UPDATE gpkg_metadata_reference SET timestamp = ?", (stamp,))
    connection.execute("COMMIT")


def _editor_main(path: str) -> int:
    """Editor process: one JSON command per stdin line, one reply per line."""
    connection: sqlite3.Connection | None = None

    def reply(message: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        command = json.loads(line)
        op = command["op"]
        try:
            if op == "open":
                connection = sqlite3.connect(path, isolation_level=None)
                _register_gpkg_functions(connection)
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute("PRAGMA wal_autocheckpoint=0")
                reply({})
                continue
            assert connection is not None
            if op == "begin":
                connection.execute("BEGIN IMMEDIATE")
                reply({})
            elif op == "insert":
                fid = _editor_insert(
                    connection,
                    command["layer"],
                    bytes.fromhex(command["wkb"]),
                    command["values"],
                )
                reply({"fid": fid})
            elif op == "commit":
                connection.execute("COMMIT")
                reply({})
            elif op == "touch":
                _editor_touch(connection)
                reply({})
            elif op == "close":
                connection.close()
                reply({})
                return 0
            elif op == "crash":
                reply({})
                os._exit(0)  # no close: -wal and -shm stay as a crash leaves them
            else:
                reply({"error": f"unknown op {op!r}"})
        except sqlite3.Error as exc:
            reply({"error": str(exc)})
    return 0


# --- snapshots -------------------------------------------------------------------

_FORMATS = {
    ".gpkg": "GPKG",
    ".shp": "ESRI Shapefile",
    ".tif": "GTiff",
    ".tiff": "GTiff",
    ".geojson": "GeoJSON",
    ".fgb": "FlatGeobuf",
    ".tab": "MapInfo File",
}
_SET_SUFFIXES = {
    ".shp": (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".sbn", ".sbx"),
    ".tab": (".tab", ".dat", ".map", ".id", ".ind"),
}


@dataclass(frozen=True)
class SnapshotFixture:
    """A snapshot directory written by ``write_snapshot_fixture``."""

    directory: Path
    label: str
    document: dict[str, Any]
    """The ``migawka.json`` content."""


def _set_members(source: Path) -> list[Path]:
    """Return the file set of ``source`` (main file first) or the file alone."""
    suffixes = _SET_SUFFIXES.get(source.suffix.lower())
    if suffixes is None:
        return [source]
    found = [source.with_suffix(suffix) for suffix in suffixes]
    return [path for path in found if path.is_file()]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sqlite(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(16) == b"SQLite format 3\x00"


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds")


def _free_label(parent: Path, base: str) -> str:
    if not (parent / base).exists():
        return base
    return next(
        f"{base}_{n}" for n in _count(2) if not (parent / f"{base}_{n}").exists()
    )


def _count(start: int) -> Iterator[int]:
    value = start
    while True:
        yield value
        value += 1


def write_snapshot_fixture(
    folder: Path,
    source: str,
    *,
    created_at: datetime,
    content: tuple[ContentMethod, str] | None = None,
    note: str = "",
    author: dict[str, Any] | None = None,
    layers: list[dict[str, Any]] | None = None,
    raster: dict[str, Any] | None = None,
    extent: dict[str, Any] | None = None,
) -> SnapshotFixture:
    """Write ``<folder>/.wersje/<source>/<label>/`` as a finished snapshot.

    The copy of a SQLite file is a ``Connection.backup`` (``immutable=1``
    without ``-wal``, ``mode=ro`` with it), of anything else a byte copy of
    the file set (Shapefile, MapInfo TAB) or the file. Files end ``0444``
    and the snapshot directory ``0555``, like a published snapshot.

    Parameters
    ----------
    folder : Path
        The data folder.
    source : str
        Working file relative to ``folder`` (``/`` separated).
    created_at : datetime
        Publication moment, with an offset; its date starts the label.
    content : (method, sha256), optional
        Content identity of decision 8. Required for SQLite files and file
        sets (the identity code computes them); a single other file
        defaults to ``("bytes", sha256 of the file)``.
    note, author, layers, raster, extent : optional
        Fields of ``archiwista-snapshot/1``; ``author`` defaults to the
        local owner, the others to empty values.

    Returns
    -------
    SnapshotFixture
        The directory, label and document.

    Raises
    ------
    ValueError
        ``created_at`` without an offset, or ``content`` missing where it
        cannot be derived.
    """
    if created_at.utcoffset() is None:
        raise ValueError("created_at needs an offset")
    working = folder / source
    members = _set_members(working)
    sqlite = _is_sqlite(working)
    if content is None and (sqlite or len(members) > 1):
        raise ValueError(f"pass content= for {source} (sqlite or file set)")
    identity: tuple[ContentMethod, str] = (
        content if content is not None else ("bytes", _sha256(working))
    )
    parent = folder / SNAPSHOTS_DIR / source
    parent.mkdir(parents=True, exist_ok=True)
    label = _free_label(parent, f"{created_at:%Y-%m-%d}_{identity[1][:8]}")
    directory = parent / label
    directory.mkdir()
    if sqlite:
        _sqlite_backup(working, directory / working.name)
    else:
        for member in members:
            shutil.copyfile(member, directory / member.name)
    copies = [directory / member.name for member in members]
    files: list[dict[str, Any]] = [
        {"name": copy.name, "size_bytes": copy.stat().st_size, "sha256": _sha256(copy)}
        for copy in copies
    ]
    stat = working.stat()
    feature_count = (
        sum(int(layer["feature_count"]) for layer in layers) if layers else None
    )
    document: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "label": label,
        "created_at": _iso(created_at),
        "author": author
        or {"id": "local", "kind": "local_owner", "name": None, "session": None},
        "note": note,
        "source": {
            "path": source,
            "format": _FORMATS.get(working.suffix.lower()),
            "size_bytes": stat.st_size,
            "modified_at": _iso(
                datetime.fromtimestamp(stat.st_mtime, created_at.tzinfo)
            ),
        },
        "content": {"method": identity[0], "sha256": identity[1]},
        "copy": {"method": "sqlite_backup" if sqlite else "files"},
        "files": files,
        "size_bytes": sum(int(item["size_bytes"]) for item in files),
        "layers": layers,
        "raster": raster,
        "feature_count": feature_count,
        "extent": extent,
        "archiwista": version(APP_DISTRIBUTION),
    }
    (directory / SNAPSHOT_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for copy in [*copies, directory / SNAPSHOT_FILE]:
        copy.chmod(0o444)
    directory.chmod(0o555)
    return SnapshotFixture(directory, label, document)


def _sqlite_backup(source: Path, target: Path) -> None:
    """Copy a SQLite database consistently without writing next to it."""
    wal = Path(f"{source}-wal")
    mode = "mode=ro" if wal.exists() else "immutable=1"
    reader = sqlite3.connect(f"{source.as_uri()}?{mode}", uri=True)
    writer = sqlite3.connect(target)
    try:
        reader.backup(writer)
    finally:
        writer.close()
        reader.close()


if __name__ == "__main__":
    if sys.argv[1:2] != ["edit"] or len(sys.argv) != 3:
        sys.exit("usage: python -m tests.fixtures.own_data edit PATH")
    sys.exit(_editor_main(sys.argv[2]))
