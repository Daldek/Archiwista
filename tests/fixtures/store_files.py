"""Tiny but well-formed data files for the synthetic Kartograf store.

Every encoder is pure Python and deterministic: the same arguments give the
same bytes, and ``nonce`` makes the content (and so the version identity,
the SHA-256 of the file) differ between versions. Readers only need the
headers to be genuine (Kartograf's ``file_footprint`` reads ASC/GeoTIFF/JPEG
+ world file/GPKG/LAS headers), so the payloads stay minimal: rasters are
64 x 64 pixels, a GeoPackage holds one point and a point cloud a few points.
"""

import io
import sqlite3
import struct
import zipfile
from functools import cache

from pyproj import CRS

RASTER_SIZE_PX = 64
NODATA = -9999

Bounds = tuple[float, float, float, float]
"""``(min_x, min_y, max_x, max_y)`` in the file's own CRS."""


def asc_grid(bounds: Bounds, nonce: int) -> bytes:
    """ESRI ASCII grid 64 x 64 whose header covers ``bounds`` (west/south).

    Parameters
    ----------
    bounds : Bounds
        Extent in the CRS of the sidecar; the cell size follows its width.
    nonce : int
        Value of the first cell; distinguishes versions.

    Returns
    -------
    bytes
        The grid text in ASCII.
    """
    min_x, min_y, max_x, _ = bounds
    cell_m = (max_x - min_x) / RASTER_SIZE_PX
    header = (
        f"ncols {RASTER_SIZE_PX}\nnrows {RASTER_SIZE_PX}\n"
        f"xllcorner {min_x:.3f}\nyllcorner {min_y:.3f}\n"
        f"cellsize {cell_m:.6f}\nNODATA_value {NODATA}\n"
    )
    return (header + f"{nonce} " + _asc_body()).encode("ascii")


@cache
def _asc_body() -> str:
    """Cells after the first one: a small repeating relief (2-digit values)."""
    rows = [
        [str(10 + (row + col) % 90) for col in range(RASTER_SIZE_PX)]
        for row in range(RASTER_SIZE_PX)
    ]
    rows[0] = rows[0][1:]
    return "\n".join(" ".join(row) for row in rows) + "\n"


def geotiff(
    bounds: Bounds, epsg: int, nonce: int, *, nodata: int | None = None
) -> bytes:
    """Uncompressed single-band 8-bit GeoTIFF of 64 x 64 pixels.

    Parameters
    ----------
    bounds : Bounds
        Extent of the raster in ``epsg``.
    epsg : int
        Code of a projected CRS (``ProjectedCSTypeGeoKey``).
    nonce : int
        Written into the first eight pixels; distinguishes versions.
    nodata : int or None, optional
        GDAL nodata value of the band (``GDAL_NODATA`` tag).

    Returns
    -------
    bytes
        A little-endian TIFF with ``ModelPixelScale``, ``ModelTiepoint`` and
        a ``GeoKeyDirectory``.
    """
    min_x, min_y, max_x, max_y = bounds
    size = RASTER_SIZE_PX
    pixels = (nonce % 2**64).to_bytes(8, "little") + _tiff_pixels()[8:]
    scale = struct.pack("<3d", (max_x - min_x) / size, (max_y - min_y) / size, 0.0)
    tiepoint = struct.pack("<6d", 0.0, 0.0, 0.0, min_x, max_y, 0.0)
    # Version 1.1.0, three keys: projected model, pixel-is-area, EPSG code.
    geokeys = struct.pack(
        "<16H", 1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, epsg
    )
    nodata_text = f"{nodata}\0".encode("ascii") if nodata is not None else b""
    tag_count = 14 + (1 if nodata_text else 0)
    data_offset = 8 + 2 + tag_count * 12 + 4
    scale_offset = data_offset
    tiepoint_offset = scale_offset + len(scale)
    geokeys_offset = tiepoint_offset + len(tiepoint)
    nodata_offset = geokeys_offset + len(geokeys)
    pixels_offset = nodata_offset + len(nodata_text)
    entries = [
        _tag(256, 3, 1, size),
        _tag(257, 3, 1, size),
        _tag(258, 3, 1, 8),
        _tag(259, 3, 1, 1),
        _tag(262, 3, 1, 1),
        _tag(273, 4, 1, pixels_offset),
        _tag(277, 3, 1, 1),
        _tag(278, 3, 1, size),
        _tag(279, 4, 1, len(pixels)),
        _tag(284, 3, 1, 1),
        _tag(339, 3, 1, 1),
        _tag(33550, 12, 3, scale_offset),
        _tag(33922, 12, 6, tiepoint_offset),
        _tag(34735, 3, 16, geokeys_offset),
    ]
    if nodata_text:
        entries.append(_tag(42113, 2, len(nodata_text), nodata_offset))
    ifd = struct.pack("<H", tag_count) + b"".join(entries) + struct.pack("<I", 0)
    header = b"II*\0" + struct.pack("<I", 8)
    return header + ifd + scale + tiepoint + geokeys + nodata_text + pixels


def _tag(code: int, kind: int, count: int, value: int) -> bytes:
    """One IFD entry; SHORT values fit left-justified in the value field."""
    if kind == 3 and count == 1:
        return struct.pack("<HHIHH", code, kind, count, value, 0)
    return struct.pack("<HHII", code, kind, count, value)


@cache
def _tiff_pixels() -> bytes:
    size = RASTER_SIZE_PX
    return bytes((row * 4 + col) % 256 for row in range(size) for col in range(size))


def jpeg(nonce: int) -> bytes:
    """Baseline grayscale JPEG of 64 x 64 uniform pixels.

    Every 8 x 8 block is coded as a zero DC difference and an immediate
    end-of-block with one-symbol Huffman tables, so the scan is 16 zero
    bytes. ``nonce`` lives in a comment segment.

    Parameters
    ----------
    nonce : int
        Comment text; distinguishes versions.

    Returns
    -------
    bytes
        A JPEG file readable by libjpeg (GDAL).
    """
    size = RASTER_SIZE_PX
    comment = f"archiwista fixture {nonce}".encode("ascii")
    one_symbol = bytes([1] + [0] * 15) + b"\0"
    blocks = (size // 8) * (size // 8)
    return b"".join(
        (
            b"\xff\xd8",
            _segment(0xDB, b"\0" + bytes([1] * 64)),
            _segment(0xC0, struct.pack(">BHHBBBB", 8, size, size, 1, 1, 0x11, 0)),
            _segment(0xC4, b"\x00" + one_symbol),
            _segment(0xC4, b"\x10" + one_symbol),
            _segment(0xFE, comment),
            _segment(0xDA, bytes([1, 1, 0x00, 0, 63, 0])),
            bytes(blocks * 2 // 8),
            b"\xff\xd9",
        )
    )


def _segment(marker: int, payload: bytes) -> bytes:
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def world_file(bounds: Bounds) -> bytes:
    """ESRI world file (``.jgw``) of a 64 x 64 image covering ``bounds``."""
    min_x, min_y, max_x, max_y = bounds
    dx = (max_x - min_x) / RASTER_SIZE_PX
    dy = (max_y - min_y) / RASTER_SIZE_PX
    lines = (dx, 0.0, 0.0, -dy, min_x + dx / 2, max_y - dy / 2)
    return "".join(f"{value:.6f}\n" for value in lines).encode("ascii")


def geopackage(bounds: Bounds, epsg: int, nonce: int) -> bytes:
    """GeoPackage 1.2 with one point layer whose extent is ``bounds``.

    Parameters
    ----------
    bounds : Bounds
        Extent recorded in ``gpkg_contents``; the point is its centre.
    epsg : int
        CRS of the layer.
    nonce : int
        Name of the point; distinguishes versions.

    Returns
    -------
    bytes
        The serialised SQLite database.
    """
    min_x, min_y, max_x, max_y = bounds
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(_GPKG_SCHEMA)
        conn.execute(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, 'EPSG', ?, ?, NULL)",
            (f"EPSG:{epsg}", epsg, epsg, _wkt(epsg)),
        )
        conn.execute(
            "INSERT INTO gpkg_contents VALUES "
            "('objects', 'features', 'objects', '', '2026-01-01T00:00:00.000Z', "
            "?, ?, ?, ?, ?)",
            (min_x, min_y, max_x, max_y, epsg),
        )
        conn.execute(
            "INSERT INTO gpkg_geometry_columns VALUES "
            "('objects', 'geom', 'POINT', ?, 0, 0)",
            (epsg,),
        )
        point = struct.pack(
            "<2sBBiBIdd",
            b"GP",
            0,
            1,  # little endian, no envelope
            epsg,
            1,
            1,  # WKB point
            (min_x + max_x) / 2,
            (min_y + max_y) / 2,
        )
        conn.execute(
            "INSERT INTO objects (geom, name) VALUES (?, ?)", (point, str(nonce))
        )
        conn.commit()
        return conn.serialize()
    finally:
        conn.close()


_GPKG_SCHEMA = """
PRAGMA application_id = 1196444487;
PRAGMA user_version = 10200;
CREATE TABLE gpkg_spatial_ref_sys (
    srs_name TEXT NOT NULL, srs_id INTEGER PRIMARY KEY,
    organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
    definition TEXT NOT NULL, description TEXT);
INSERT INTO gpkg_spatial_ref_sys VALUES
    ('Undefined cartesian SRS', -1, 'NONE', -1, 'undefined', NULL),
    ('Undefined geographic SRS', 0, 'NONE', 0, 'undefined', NULL);
CREATE TABLE gpkg_contents (
    table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT NULL,
    identifier TEXT UNIQUE, description TEXT DEFAULT '',
    last_change DATETIME NOT NULL, min_x DOUBLE, min_y DOUBLE,
    max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
CREATE TABLE gpkg_geometry_columns (
    table_name TEXT NOT NULL, column_name TEXT NOT NULL,
    geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL,
    z TINYINT NOT NULL, m TINYINT NOT NULL,
    PRIMARY KEY (table_name, column_name));
CREATE TABLE objects (fid INTEGER PRIMARY KEY, geom POINT, name TEXT);
"""


@cache
def _wkt(epsg: int) -> str:
    return str(CRS.from_epsg(epsg).to_wkt())


def zip_archive(member: str, nonce: int) -> bytes:
    """ZIP with one small text member and a fixed timestamp.

    Parameters
    ----------
    member : str
        Name of the archived file.
    nonce : int
        Part of the member text; distinguishes versions.

    Returns
    -------
    bytes
        The archive.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo(member, date_time=(2024, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, f"archiwista fixture {member} {nonce}\n")
    return buffer.getvalue()


def las_points(bounds: Bounds, nonce: int, *, points: int = 5) -> bytes:
    """LAS 1.2 point cloud (format 0) with a few points inside ``bounds``.

    The fixture stores it under the ``.laz`` name Kartograf uses, but the
    points are not LASzip-compressed: readers of the store only use the
    public header (extent, point count), which is the same in both.

    Parameters
    ----------
    bounds : Bounds
        Extent of the points (header min/max).
    nonce : int
        Intensity of the points; distinguishes versions.
    points : int, optional
        Number of points (at least 2: the two corners).

    Returns
    -------
    bytes
        Header (227 bytes) and point records.
    """
    min_x, min_y, max_x, max_y = bounds
    scale = 0.01
    record = struct.Struct("<3iHBBbBH")
    body = b"".join(
        record.pack(
            round((min_x + (max_x - min_x) * k / (points - 1) - min_x) / scale),
            round((min_y + (max_y - min_y) * k / (points - 1) - min_y) / scale),
            round(100.0 / scale),
            nonce % 2**16,
            0b00001001,  # return 1 of 1
            2,  # ground
            0,
            0,
            0,
        )
        for k in range(points)
    )
    header = struct.pack(
        "<4sHH16sBB32s32sHHHIIBHI5I3d3d6d",
        b"LASF",
        0,
        0,
        bytes(16),
        1,
        2,
        b"archiwista fixture",
        b"archiwista make_store",
        1,
        2026,
        227,
        227,
        0,
        0,
        record.size,
        points,
        points,
        0,
        0,
        0,
        0,
        scale,
        scale,
        scale,
        min_x,
        min_y,
        0.0,
        max_x,
        min_x,
        max_y,
        min_y,
        100.0,
        100.0,
    )
    return header + body
