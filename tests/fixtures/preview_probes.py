"""Probes of the preview libraries, run in the sandbox (plan v0.2, step 1).

``tests/contract/test_preview_stack.py`` starts this script with
``archiwista.sandbox.run_untrusted`` (a control: with one sandbox variable
left out), writes one JSON request ``{"probe": <name>, ...}`` to its
standard input and reads one JSON answer from its standard output. The
script only reads: the test prepares every file (the SQLite copy probes
write to the work directory they are given). A refusal is answered as
``{"refused": "<exception class>", "layer": "formats" | "library"}``, so
the answer shows which layer refused a file. Libraries are imported here,
after the sandbox environment is in place, as in a render process.
"""

import json
import shutil
import sqlite3
import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

import laspy
import morecantile
import numpy as np
import pyogrio
import pyogrio.raw
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import reproject
from rio_tiler.io import Reader

from archiwista.errors import FormatRefusedError
from archiwista.formats import file_format, open_raster, vector_source

TILE_PX = 256
WEB_MERCATOR = "EPSG:3857"


def _attempt(read: Callable[[], Any]) -> Any:
    """Return what ``read`` returns, or which layer refused and how."""
    try:
        return read()
    except Exception as error:  # the answer names the refusal
        layer = "formats" if isinstance(error, FormatRefusedError) else "library"
        return {"refused": type(error).__name__, "layer": layer}


def _warp(path: Path) -> None:
    """Make a ``WarpedVRT``, as rio-tiler does: GDAL registers VRT again."""
    with (
        rasterio.open(path, driver="GTiff") as src,
        WarpedVRT(src, crs=WEB_MERCATOR) as warped,
    ):
        warped.read(1)


def _raster_max(path: Path, *, explicit: bool) -> Any:
    """Largest value of the first band, opened through the table or plainly."""

    def read() -> dict[str, Any]:
        opened = (
            open_raster(path, file_format(path)) if explicit else rasterio.open(path)
        )
        with opened as src:
            return {"max": int(src.read(1).max()), "driver": src.driver}

    return _attempt(read)


def probe_raster_vrt(request: dict[str, Any]) -> dict[str, Any]:
    """VRT XML named ``.tif``/``.asc``: plain and table opens around a warp."""
    directory = Path(request["dir"])
    evil = directory / "evil.tif"
    answer = {"plain_before_warp": _raster_max(evil, explicit=False)}
    _warp(directory / "a.tif")
    answer["plain_after_warp"] = _raster_max(evil, explicit=False)
    for name in ("evil.tif", "evil.asc"):
        answer[name] = _raster_max(directory / name, explicit=True)
    return answer


def probe_sibling_ovr(request: dict[str, Any]) -> dict[str, Any]:
    """``a.tif`` next to an ``a.tif.ovr`` holding VRT XML, after a warp."""
    path = Path(request["dir"]) / "a.tif"
    _warp(path)
    with open_raster(path, file_format(path)) as src:
        decimated = src.read(1, out_shape=(src.height // 2, src.width // 2))
        return {"overviews": src.overviews(1), "max": int(decimated.max())}


def probe_statistics(request: dict[str, Any]) -> dict[str, Any]:
    """Band statistics of a GeoTIFF; the files of its directory afterwards."""
    path = Path(request["dir"]) / "a.tif"
    with open_raster(path, file_format(path)) as src:
        found = src.stats()[0]
    names = sorted(item.name for item in path.parent.iterdir())
    return {"min": found.min, "max": found.max, "files": names}


def _table_source(path: Path) -> str:
    """Return the name OGR opens a file under, from the format table."""
    return vector_source(path, file_format(path))


def _values(source: Callable[[], str]) -> Any:
    """Attribute values of a vector source, or its refusal."""

    def read() -> dict[str, Any]:
        _, _, _, fields = pyogrio.raw.read(source(), read_geometry=False)
        return {"values": [str(value) for column in fields for value in column]}

    return _attempt(read)


def probe_vector_vrt(request: dict[str, Any]) -> dict[str, Any]:
    """OGR VRT XML under vector names: through the table, and one plain open."""
    directory = Path(request["dir"])
    _warp(directory / "a.tif")
    answer = {}
    for name in request["names"]:
        answer[name] = _values(partial(_table_source, directory / name))
    plain = directory / request["plain"]
    answer["plain"] = _values(lambda: str(plain))
    return answer


def probe_fileset(request: dict[str, Any]) -> dict[str, Any]:
    """Files with members (Shapefile, MapInfo table) read through the table."""

    def read(path: Path) -> dict[str, Any]:
        source = vector_source(path, file_format(path))
        info = pyogrio.read_info(source)
        _, _, wkb, fields = pyogrio.raw.read(source)
        return {
            "crs": info["crs"],
            "values": [str(value) for value in fields[0]],
            "geometries": sum(item is not None for item in wkb),
        }

    return {name: _attempt(partial(read, Path(name))) for name in request["files"]}


def probe_gpkg_colon(request: dict[str, Any]) -> dict[str, Any]:
    """Count a GeoPackage with ``:`` in its name, through the table and unquoted."""
    path = Path(request["path"])

    def count(source: str) -> dict[str, Any]:
        return {"features": int(pyogrio.read_info(source)["features"])}

    return {
        "table": _attempt(lambda: count(_table_source(path))),
        "unquoted": _attempt(lambda: count(f"GPKG:{path}")),
    }


def _spot(image: Any, transform: Any) -> list[float] | None:
    """Centre of the bright pixels of a tile, in EPSG:3857."""
    rows, cols = np.nonzero(np.asarray(image) > 127)
    if rows.size == 0:
        return None
    x, y = transform * (cols.mean() + 0.5, rows.mean() + 0.5)
    return [float(x), float(y)]


def probe_warp(request: dict[str, Any]) -> dict[str, Any]:
    """Bright spot of a tile: forced operation, default one, WarpedVRT, rio-tiler."""
    sjtsk, wgs84 = Path(request["sjtsk"]), Path(request["wgs84"])
    x, y, z = request["tile"]
    tms = morecantile.tms.get("WebMercatorQuad")
    transform = from_bounds(*tms.xy_bounds(x, y, z), TILE_PX, TILE_PX)

    def reprojected(path: Path, *, overview: int | None = None, **warp: Any) -> Any:
        def read() -> Any:
            opening = {} if overview is None else {"OVERVIEW_LEVEL": overview}
            with open_raster(path, file_format(path), **opening) as src:
                tile = np.zeros((TILE_PX, TILE_PX), dtype="uint8")
                reproject(
                    rasterio.band(src, 1),
                    tile,
                    dst_transform=transform,
                    dst_crs=WEB_MERCATOR,
                    resampling=Resampling.nearest,
                    **warp,
                )
                return _spot(tile, transform)

        return _attempt(read)

    def warped(**options: Any) -> Any:
        def read() -> Any:
            with (
                open_raster(sjtsk, file_format(sjtsk)) as src,
                WarpedVRT(
                    src,
                    crs=WEB_MERCATOR,
                    transform=transform,
                    width=TILE_PX,
                    height=TILE_PX,
                    resampling=Resampling.nearest,
                    **options,
                ) as vrt,
            ):
                return _spot(vrt.read(1), transform)

        return _attempt(read)

    def tiled(**vrt_options: Any) -> Any:
        def read() -> Any:
            with (
                open_raster(sjtsk, file_format(sjtsk)) as src,
                Reader(str(sjtsk), dataset=src) as reader,
            ):
                image = reader.tile(
                    x,
                    y,
                    z,
                    tilesize=TILE_PX,
                    resampling_method="nearest",
                    reproject_method="nearest",
                    vrt_options=vrt_options or None,
                )
            return _spot(image.data[0], transform)

        return _attempt(read)

    forced, shifted = request["operation"], request["shifted"]
    return {
        "forced": reprojected(sjtsk, COORDINATE_OPERATION=forced),
        "forced_overview": reprojected(sjtsk, overview=0, COORDINATE_OPERATION=forced),
        "shifted": reprojected(sjtsk, COORDINATE_OPERATION=shifted),
        "upper_case": reprojected(sjtsk, COORDINATE_OPERATION=forced.upper()),
        "default": reprojected(sjtsk),
        "warped_vrt_default": warped(),
        "warped_vrt_shifted": warped(COORDINATE_OPERATION=shifted),
        "rio_tiler_default": tiled(),
        "rio_tiler_shifted": tiled(COORDINATE_OPERATION=shifted),
        "wgs84_default": reprojected(wgs84),
    }


def probe_laz(request: dict[str, Any]) -> dict[str, Any]:
    """Header, CRS from the VLRs and a seek into a later chunk of a LAZ file."""
    path, broken, index = (
        Path(request["path"]),
        Path(request["broken"]),
        request["seek"],
    )
    with laspy.open(path) as reader:
        header = reader.header
        crs = header.parse_crs()
        answer: dict[str, Any] = {
            "points": int(header.point_count),
            "format": int(header.point_format.id),
            "compressed": bool(header.are_points_compressed),
            "epsg": crs.to_epsg() if crs is not None else None,
        }

    def seek() -> dict[str, Any]:
        with laspy.open(broken) as reader:
            reader.seek(index)
            points = reader.read_points(3)
        return {
            "z": [float(value) for value in points.z],
            "classes": [int(value) for value in points.classification],
        }

    def from_start() -> dict[str, Any]:
        with laspy.open(broken) as reader:
            points = reader.read_points(3)
        return {"z": [float(value) for value in points.z]}

    answer["seek_in_broken"] = _attempt(seek)
    answer["start_of_broken"] = _attempt(from_start)
    return answer


def _rows(connection: sqlite3.Connection, table: str) -> list[str]:
    query = f'SELECT name FROM "{table}" ORDER BY fid'
    return [str(row[0]) for row in connection.execute(query)]


def probe_sqlite(request: dict[str, Any]) -> dict[str, Any]:
    """Read a SQLite file one way of decision 8; the rows that way sees."""
    path, way, table = Path(request["path"]), request["way"], request["table"]
    if way in ("immutable", "read_only"):
        mode = "immutable=1" if way == "immutable" else "mode=ro"
        connection = sqlite3.connect(f"{path.as_uri()}?{mode}", uri=True)
        try:
            return {"rows": _rows(connection, table)}
        finally:
            connection.close()
    if way in ("gdal_immutable", "gdal"):
        options = {"IMMUTABLE": "YES"} if way == "gdal_immutable" else {}
        _, _, _, fields = pyogrio.raw.read(
            str(path), layer=table, read_geometry=False, columns=["name"], **options
        )
        return {"rows": [str(value) for value in fields[0]]}
    copy = Path(request["work"]) / path.name
    if way == "backup":
        source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
    elif way == "copy_with_wal":
        shutil.copyfile(path, copy)
        shutil.copyfile(f"{path}-wal", f"{copy}-wal")
    else:
        raise ValueError(way)
    connection = sqlite3.connect(copy)
    try:
        check = connection.execute("PRAGMA integrity_check").fetchone()[0]
        return {"rows": _rows(connection, table), "integrity": check}
    finally:
        connection.close()


PROBES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "raster_vrt": probe_raster_vrt,
    "sibling_ovr": probe_sibling_ovr,
    "statistics": probe_statistics,
    "vector_vrt": probe_vector_vrt,
    "fileset": probe_fileset,
    "gpkg_colon": probe_gpkg_colon,
    "warp": probe_warp,
    "laz": probe_laz,
    "sqlite": probe_sqlite,
}


def main() -> int:
    """Answer the probe asked for on the standard input."""
    request = json.loads(sys.stdin.readline())
    answer = PROBES[request["probe"]](request)
    sys.stdout.write(json.dumps(answer) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
