"""Area files for the upload tests: valid ones, malformed ones and hostile ones.

Every builder returns the bytes a client would upload. Valid files hold the
same 10 km square in EPSG:2180 (100 km²) unless stated otherwise; archives
are built in memory with ``zipfile``.
"""

import io
import json
import math
import struct
import sys
import zipfile
from collections.abc import Sequence
from pathlib import Path

import httpx
import numpy as np
import pyogrio.raw
import shapely
from pyproj import Transformer
from shapely.geometry import Polygon

from archiwista.security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE
from tests.fixtures import slow_area_reader
from tests.fixtures.api_session import Caller

# The 10 km square (x east, y north) in EPSG:2180, south-west of Kraków.
SQUARE_2180 = (500_000.0, 250_000.0, 510_000.0, 260_000.0)
SQUARE_KM2 = 100.0
SHAPEFILE_PARTS = (".shp", ".shx", ".dbf", ".prj")
SLOW_READER_COMMAND = (sys.executable, str(Path(slow_area_reader.__file__)))


def square(bounds: tuple[float, float, float, float] = SQUARE_2180) -> Polygon:
    """Return a rectangle as a shapely polygon."""
    min_x, min_y, max_x, max_y = bounds
    return Polygon([(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)])


def square_wgs84() -> Polygon:
    """Return the corners of ``SQUARE_2180`` in WGS84 (lon, lat)."""
    to_wgs84 = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)
    return shapely.transform(square(), to_wgs84.transform, interleaved=False)


def circle(
    positions: int, *, centre: tuple[float, float] = (19.5, 51.0)
) -> dict[str, object]:
    """Return a WGS84 GeoJSON polygon with exactly ``positions`` positions.

    The closing position repeats the first one, as GeoJSON requires.
    """
    count = positions - 1
    angles = np.linspace(0.0, 2 * math.pi, count, endpoint=False)
    ring = [
        [centre[0] + 0.1 * math.cos(angle), centre[1] + 0.1 * math.sin(angle)]
        for angle in angles
    ]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def geojson_file(geometry: dict[str, object]) -> bytes:
    """Return an RFC 7946 FeatureCollection (WGS84) holding one geometry."""
    feature = {"type": "Feature", "properties": {}, "geometry": geometry}
    collection = {"type": "FeatureCollection", "features": [feature]}
    return json.dumps(collection).encode("utf-8")


def gdal_file(
    directory: Path,
    name: str,
    *,
    driver: str,
    geometries: Sequence[object] = (),
    crs: str | None = "EPSG:2180",
    layers: Sequence[str] = ("obszar",),
) -> Path:
    """Write layers of polygons (the square by default) with GDAL."""
    path = directory / name
    wkb = np.array([shapely.to_wkb(item) for item in geometries or [square()]])
    for layer in layers:
        pyogrio.raw.write(
            path,
            wkb,
            [],
            [],
            layer=layer,
            driver=driver,
            geometry_type="Polygon",
            crs=crs,
            append=path.exists(),
        )
    return path


def gpkg_file(directory: Path, *, layers: Sequence[str] = ("obszar",)) -> bytes:
    """Return a GeoPackage with the square in each layer."""
    return gdal_file(
        directory, "obszar.gpkg", driver="GPKG", layers=layers
    ).read_bytes()


def shapefile_zip(
    directory: Path,
    *,
    names: Sequence[str] = ("obszar",),
    prefix: str = "",
    without: Sequence[str] = (),
    crs: str | None = "EPSG:2180",
) -> bytes:
    """Return a ZIP archive of Shapefiles with the square (``prefix/name.*``)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            shp = gdal_file(directory, f"{name}.shp", driver="ESRI Shapefile", crs=crs)
            for part in SHAPEFILE_PARTS:
                source = shp.with_suffix(part)
                if part not in without and source.exists():
                    archive.write(source, f"{prefix}{name}{part}")
    return buffer.getvalue()


def escaping_zip(member: str) -> bytes:
    """Return a Shapefile archive with one more member named ``member``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for part in SHAPEFILE_PARTS:
            archive.writestr(f"obszar{part}", b"\x00")
        archive.writestr(zipfile.ZipInfo(member), b"payload")
    return buffer.getvalue()


def declared_size_zip(size: int) -> bytes:
    """Return an archive whose header declares ``size`` bytes for tiny content.

    Unpacking it would fail (the content does not match the header), so
    ``area_too_large`` proves the declared size was checked before.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for part in SHAPEFILE_PARTS:
            archive.writestr(f"obszar{part}", b"x")
    data = bytearray(buffer.getvalue())
    central = data.index(b"PK\x01\x02")
    struct.pack_into("<I", data, central + 24, size)  # uncompressed size
    return bytes(data)


def zip_bomb(megabytes: int) -> bytes:
    """Return a Shapefile archive whose ``.shp`` is ``megabytes`` MiB of zeros."""
    buffer = io.BytesIO()
    zeros = bytes(1024**2)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        with archive.open("obszar.shp", "w") as member:
            for _ in range(megabytes):
                member.write(zeros)
        for part in SHAPEFILE_PARTS[1:]:
            archive.writestr(f"obszar{part}", b"x")
    return buffer.getvalue()


def upload(
    caller: Caller,
    content: bytes,
    *,
    query: str = "",
    content_type: str = "application/octet-stream",
    csrf: bool = True,
) -> httpx.Response:
    """Send a file as the raw body of ``POST /api/v1/areas`` in the session."""
    headers = {
        "cookie": f"{SESSION_COOKIE}={caller.session_id}; {CSRF_COOKIE}={caller.csrf}",
        "content-type": content_type,
    }
    if csrf:
        headers[CSRF_HEADER] = caller.csrf
    response: httpx.Response = caller.client.post(
        f"/api/v1/areas{query}", content=content, headers=headers
    )
    return response
