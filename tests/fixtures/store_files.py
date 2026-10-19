"""Tiny but well-formed data files for the synthetic Kartograf store.

Every encoder is deterministic: the same arguments give the same bytes, and
``nonce`` makes the content (and so the version identity, the SHA-256 of
the file) differ between versions. The v0.1 encoders are pure Python: the
bulk of a 50 000-slot store only needs genuine headers (Kartograf's
``file_footprint`` reads ASC/GeoTIFF/JPEG + world file/GPKG/LAS headers), so
rasters are 64 x 64 pixels, a GeoPackage holds one point and a point cloud a
few points. The file families of plan v0.2 (decision 5: palette, tiling and
overviews, RGBA strips, a compressed LAZ, two-layer GeoPackages, archives
with members) are written once per store, so they use GDAL (rasterio) and
laspy to get the real structure previews depend on.
"""

import io
import sqlite3
import struct
import zipfile
import zlib
from collections.abc import Sequence
from datetime import date
from functools import cache

import laspy
import numpy as np
import numpy.typing as npt
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.io import MemoryFile
from rasterio.transform import from_bounds

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


_GPKG_TABLES = """
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
"""
_GPKG_SCHEMA = _GPKG_TABLES + (
    "CREATE TABLE objects (fid INTEGER PRIMARY KEY, geom POINT, name TEXT);\n"
)


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


# --- v0.2 file families (plan v0.2, decision 5) --------------------------------

NONCE_TAG = "ARCHIWISTA_NONCE"
"""GDAL metadata item carrying ``nonce`` in the GDAL-written rasters."""

CLC_CLASSES: dict[int, tuple[str, tuple[int, int, int]]] = {
    1: ("111", (230, 0, 77)),
    2: ("112", (255, 0, 0)),
    12: ("211", (255, 255, 168)),
    23: ("311", (128, 255, 0)),
    41: ("512", (128, 242, 230)),
}
"""CORINE raster values written by ``geotiff_classes``: CLC code and colour."""
CLC_NODATA = 48
SOIL_NODATA = -32768
STRIPED_SIZE_PX = 4160
"""Side of the striped RGBA map: above the 4096 px limit of direct tiles."""
OBLIQUE_SIZE_PX = (1024, 640)
"""``(width, height)`` of the tiled oblique orthophoto (a 1:1000 sheet)."""
OVERVIEW_FACTORS = (2, 4)
LAZ_POINTS = 120_000
"""Points of the compressed LAZ: three LASzip chunks of 50 000 points."""
LAZ_CLASSES = (2, 3, 6)
"""ASPRS classes of the compressed LAZ: ground, low vegetation, building."""


def reprojected_bounds(bounds: Bounds, source_epsg: int, target_epsg: int) -> Bounds:
    """Envelope of ``bounds`` in another CRS (fixture geometry, densified).

    Only used to place test rasters whose CRS differs from the slot's
    request (CORINE in EPSG:3035, SoilGrids in EPSG:4326); never the
    reference values of a check.
    """
    transformer = Transformer.from_crs(source_epsg, target_epsg, always_xy=True)
    min_x, min_y, max_x, max_y = transformer.transform_bounds(*bounds, densify_pts=21)
    return (min_x, min_y, max_x, max_y)


def png_image(nonce: int, *, size: int = RASTER_SIZE_PX) -> bytes:
    """RGB PNG without georeference, like a WMS ``GetMap`` answer.

    Parameters
    ----------
    nonce : int
        Colour of the first pixel; distinguishes versions.
    size : int, optional
        Side in pixels.

    Returns
    -------
    bytes
        An 8-bit RGB PNG (no ancillary chunks).
    """
    rows = bytearray()
    for row in range(size):
        rows.append(0)  # filter: none
        for col in range(size):
            rows += bytes(((row * 4) % 256, (col * 4) % 256, 128))
    rows[1:4] = (nonce % 2**24).to_bytes(3, "big")

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data)
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def geotiff_classes(bounds: Bounds, epsg: int, nonce: int) -> bytes:
    """CORINE-like class raster: 512 x 512 ``uint8`` with a colour table.

    Values are the keys of ``CLC_CLASSES`` in bands, ``CLC_NODATA`` in the
    south-east corner (nodata); 256-pixel tiles, DEFLATE.
    """
    size = 512
    codes = np.array(list(CLC_CLASSES), dtype=np.uint8)
    rows, cols = np.indices((size, size))
    pixels = codes[(rows // 32 + cols // 64) % len(codes)]
    pixels[-16:, -16:] = CLC_NODATA
    colormap = {code: (*rgb, 255) for code, (_, rgb) in CLC_CLASSES.items()}
    colormap[CLC_NODATA] = (255, 255, 255, 0)
    return _gdal_tiff(
        pixels[np.newaxis],
        nonce,
        crs=f"EPSG:{epsg}",
        bounds=bounds,
        nodata=CLC_NODATA,
        colormap=colormap,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
    )


def geotiff_rgba_strips(
    bounds: Bounds, epsg: int, nonce: int, *, size: int = STRIPED_SIZE_PX
) -> bytes:
    """RGBA map sheet in strips, without overviews (BDOT10k map TIFF).

    ``size`` x ``size`` pixels (default above 4096, so previews build a
    local COG), DEFLATE; the alpha band is transparent in the north-west
    eighth.
    """
    axis = np.arange(size, dtype=np.uint32)
    red = np.broadcast_to(((axis // 64) % 256).astype(np.uint8), (size, size))
    blue = ((np.add.outer(axis, axis) // 128) % 256).astype(np.uint8)
    alpha = np.full((size, size), 255, dtype=np.uint8)
    alpha[: size // 8, : size // 8] = 0
    return _gdal_tiff(
        np.stack([red, red.T, blue, alpha]),
        nonce,
        crs=f"EPSG:{epsg}",
        bounds=bounds,
        tiled=False,
        compress="deflate",
        photometric="RGB",
        alpha="YES",
    )


def geotiff_tiled_overviews(bounds: Bounds, epsg: int, nonce: int) -> bytes:
    """RGB orthophoto tiled 256 x 256 with internal overviews 2 and 4.

    ``OBLIQUE_SIZE_PX`` pixels, DEFLATE (the oblique orthophotomap).
    """
    width, height = OBLIQUE_SIZE_PX
    rows, cols = np.indices((height, width))
    bands = np.stack(
        [(cols // 16) % 256, (rows // 16) % 256, ((rows + cols) // 8) % 256]
    ).astype(np.uint8)
    return _gdal_tiff(
        bands,
        nonce,
        crs=f"EPSG:{epsg}",
        bounds=bounds,
        overviews=OVERVIEW_FACTORS,
        tiled=True,
        blockxsize=256,
        blockysize=256,
        compress="deflate",
        photometric="RGB",
    )


def geotiff_wgs84(bounds: Bounds, nonce: int) -> bytes:
    """SoilGrids-like ``int16`` raster in EPSG:4326 (values 150-349).

    ``bounds`` are degrees; 64 x 64 pixels; ``SOIL_NODATA`` in the
    south-east corner.
    """
    size = RASTER_SIZE_PX
    rows, cols = np.indices((size, size))
    values = (150 + (rows + cols) % 200).astype(np.int16)
    values[-8:, -8:] = SOIL_NODATA
    return _gdal_tiff(
        values[np.newaxis],
        nonce,
        crs="EPSG:4326",
        bounds=bounds,
        nodata=SOIL_NODATA,
        compress="deflate",
    )


def _gdal_tiff(
    bands: npt.NDArray[np.generic],
    nonce: int,
    *,
    crs: str,
    bounds: Bounds,
    nodata: float | None = None,
    colormap: dict[int, tuple[int, int, int, int]] | None = None,
    overviews: Sequence[int] = (),
    **options: object,
) -> bytes:
    """GeoTIFF written by GDAL in memory (no ``.aux.xml``, no timestamps)."""
    count, height, width = bands.shape
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=width,
            height=height,
            count=count,
            dtype=bands.dtype.name,
            crs=crs,
            transform=from_bounds(*bounds, width, height),
            nodata=nodata,
            **options,
        ) as dataset:
            dataset.write(bands)
            dataset.update_tags(**{NONCE_TAG: str(nonce)})
            if colormap is not None:
                dataset.write_colormap(1, colormap)
            if overviews:
                dataset.build_overviews(list(overviews), Resampling.average)
        return bytes(memory.read())


def xyz_grid(bounds: Bounds, nonce: int, *, size: int = 32) -> bytes:
    """Regular ASCII XYZ grid (``x y z`` of cell centres, north row first).

    The order GDAL's XYZ driver reads: rows by falling Y, X rising in a row.
    The first Z is ``nonce``; it distinguishes versions.
    """
    min_x, min_y, max_x, max_y = bounds
    dx = (max_x - min_x) / size
    dy = (max_y - min_y) / size
    lines = []
    for row in range(size):
        y = max_y - (row + 0.5) * dy
        for col in range(size):
            z = nonce if row == col == 0 else 100 + (row + col) % 50
            lines.append(f"{min_x + (col + 0.5) * dx:.2f} {y:.2f} {z:.2f}")
    return ("\n".join(lines) + "\n").encode("ascii")


def zip_members(members: Sequence[tuple[str, bytes]]) -> bytes:
    """ZIP of named members (DEFLATE, fixed timestamp, order kept)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members:
            info = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def citygml(bounds: Bounds, epsg: int, nonce: int) -> bytes:
    """CityGML 2.0 document with one LoD2 building envelope in ``bounds``."""
    min_x, min_y, max_x, max_y = bounds
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<core:CityModel xmlns:core="http://www.opengis.net/citygml/2.0"'
        ' xmlns:bldg="http://www.opengis.net/citygml/building/2.0"'
        ' xmlns:gml="http://www.opengis.net/gml">\n'
        f'  <gml:boundedBy><gml:Envelope srsName="EPSG:{epsg}" srsDimension="3">\n'
        f"    <gml:lowerCorner>{min_x:.2f} {min_y:.2f} 100.0</gml:lowerCorner>\n"
        f"    <gml:upperCorner>{max_x:.2f} {max_y:.2f} 130.0</gml:upperCorner>\n"
        "  </gml:Envelope></gml:boundedBy>\n"
        "  <core:cityObjectMember>\n"
        f'    <bldg:Building gml:id="fixture_{nonce}">\n'
        '      <bldg:measuredHeight uom="m">12.5</bldg:measuredHeight>\n'
        "    </bldg:Building>\n"
        "  </core:cityObjectMember>\n"
        "</core:CityModel>\n"
    ).encode()


def pdf_document(title: str) -> bytes:
    """One-page PDF 1.4 (a line, ``title`` in the document information)."""
    content = b"0 0 m 595 842 l S"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content),
        b"<< /Title (%s) /Producer (archiwista fixture) >>" % title.encode("ascii"),
    ]
    body = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, text in enumerate(objects, start=1):
        offsets.append(len(body))
        body += b"%d 0 obj\n%s\nendobj\n" % (number, text)
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    body += b"trailer\n<< /Size %d /Root 1 0 R /Info 5 0 R >>\n" % (len(objects) + 1)
    body += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(body)


GPKG_LAYERS = (("swrs", "LINESTRING"), ("ptwp", "POLYGON"))
"""Layers of ``geopackage_layers`` (BDOT10k classes): name and geometry type."""


def geopackage_layers(bounds: Bounds, epsg: int, nonce: int) -> bytes:
    """GeoPackage 1.2 with a line layer and a polygon layer inside ``bounds``.

    ``swrs`` (watercourses): three lines (``nazwa``, ``szerokosc_m``);
    ``ptwp`` (water surfaces): two squares (``nazwa``). The first line is
    named after ``nonce``.
    """
    min_x, min_y, max_x, max_y = bounds
    width, height = max_x - min_x, max_y - min_y

    def at(fx: float, fy: float) -> tuple[float, float]:
        return (min_x + width * fx, min_y + height * fy)

    lines = [
        (str(nonce), 12, [at(0.0, 0.1), at(0.5, 0.5), at(1.0, 0.9)]),
        ("Potok", 3, [at(0.1, 0.0), at(0.1, 1.0)]),
        ("Rów", 1, [at(0.6, 0.2), at(0.9, 0.3)]),
    ]
    squares = [
        ("Staw", [at(0.2, 0.2), at(0.4, 0.2), at(0.4, 0.4), at(0.2, 0.4)]),
        ("Jezioro", [at(0.6, 0.6), at(0.8, 0.6), at(0.8, 0.8), at(0.6, 0.8)]),
    ]
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            _GPKG_TABLES
            + "CREATE TABLE swrs (fid INTEGER PRIMARY KEY, geom LINESTRING,"
            " nazwa TEXT, szerokosc_m INTEGER);\n"
            "CREATE TABLE ptwp (fid INTEGER PRIMARY KEY, geom POLYGON,"
            " nazwa TEXT);\n"
        )
        conn.execute(
            "INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, 'EPSG', ?, ?, NULL)",
            (f"EPSG:{epsg}", epsg, epsg, _wkt(epsg)),
        )
        for (table, kind), points in zip(
            GPKG_LAYERS,
            (
                [p for _, _, line in lines for p in line],
                [p for _, s in squares for p in s],
            ),
            strict=True,
        ):
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            conn.execute(
                "INSERT INTO gpkg_contents VALUES (?, 'features', ?, '', "
                "'2026-01-01T00:00:00.000Z', ?, ?, ?, ?, ?)",
                (table, table, min(xs), min(ys), max(xs), max(ys), epsg),
            )
            conn.execute(
                "INSERT INTO gpkg_geometry_columns VALUES (?, 'geom', ?, ?, 0, 0)",
                (table, kind, epsg),
            )
        conn.executemany(
            "INSERT INTO swrs (geom, nazwa, szerokosc_m) VALUES (?, ?, ?)",
            [
                (_gpkg_blob(epsg, _wkb_linestring(line)), name, size)
                for name, size, line in lines
            ],
        )
        conn.executemany(
            "INSERT INTO ptwp (geom, nazwa) VALUES (?, ?)",
            [(_gpkg_blob(epsg, _wkb_polygon(ring)), name) for name, ring in squares],
        )
        conn.commit()
        return conn.serialize()
    finally:
        conn.close()


def _gpkg_blob(epsg: int, wkb: bytes) -> bytes:
    """GeoPackage geometry: header (little endian, no envelope) + WKB."""
    return struct.pack("<2sBBi", b"GP", 0, 1, epsg) + wkb


def _wkb_linestring(points: Sequence[tuple[float, float]]) -> bytes:
    coords = b"".join(struct.pack("<2d", x, y) for x, y in points)
    return struct.pack("<BII", 1, 2, len(points)) + coords


def _wkb_polygon(ring: Sequence[tuple[float, float]]) -> bytes:
    closed = [*ring, ring[0]]
    coords = b"".join(struct.pack("<2d", x, y) for x, y in closed)
    return struct.pack("<BIII", 1, 3, 1, len(closed)) + coords


def laz_points(bounds: Bounds, nonce: int, *, epsg: int = 2180) -> bytes:
    """LASzip-compressed LAS 1.4 (point format 6) with classes 2, 3 and 6.

    ``LAZ_POINTS`` points on a regular grid over ``bounds`` (so several
    LASzip chunks with a chunk table), ASPRS classes ``LAZ_CLASSES`` in
    40-point bands, the CRS of ``epsg`` as a WKT VLR and a fixed creation
    date.

    Parameters
    ----------
    bounds : Bounds
        Extent of the points in ``epsg``.
    nonce : int
        Intensity of every point; distinguishes versions.
    epsg : int, optional
        Horizontal CRS written into the WKT VLR.

    Returns
    -------
    bytes
        The ``.laz`` file.
    """
    min_x, min_y, max_x, max_y = bounds
    side = int(np.ceil(np.sqrt(LAZ_POINTS)))
    index = np.arange(LAZ_POINTS)
    col, row = index % side, index // side
    band = (col // 40 + row // 40) % 5
    classes = np.full(LAZ_POINTS, LAZ_CLASSES[0], dtype=np.uint8)
    classes[band == 1] = LAZ_CLASSES[1]
    classes[band == 3] = LAZ_CLASSES[2]
    header = laspy.LasHeader(point_format=6, version="1.4")
    header.offsets = np.array([min_x, min_y, 0.0])
    header.scales = np.array([0.01, 0.01, 0.01])
    header.add_crs(CRS.from_epsg(epsg))
    header.date = date(2026, 1, 1)
    header.system_identifier = "archiwista fixture"
    header.generating_software = "archiwista make_store"
    las = laspy.LasData(header)
    las.x = min_x + (col + 0.5) * (max_x - min_x) / side
    las.y = min_y + (row + 0.5) * (max_y - min_y) / side
    las.z = 200.0 + (col % 50) * 0.1 + np.where(classes == 6, 12.0, 0.0)
    las.classification = classes
    las.intensity = np.full(LAZ_POINTS, nonce % 2**16, dtype=np.uint16)
    las.return_number = np.ones(LAZ_POINTS, dtype=np.uint8)
    las.number_of_returns = np.ones(LAZ_POINTS, dtype=np.uint8)
    buffer = io.BytesIO()
    las.write(buffer, do_compress=True, laz_backend=laspy.LazBackend.Lazrs)
    return buffer.getvalue()
