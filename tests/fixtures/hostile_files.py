r"""Planted files that try to make a reader open something else (plan v0.2).

``hostile_files(path)`` writes, for the sandbox and format-table tests
(decision 3), files that are not what their names say or that point outside
the folder they are in:

- GDAL VRT XML under raster names (``.tif``, ``.asc``) and OGR VRT XML under
  vector names (``.gpkg``, ``.geojson``, ``.shp``, ``.fgb``), each pointing
  at a target file outside ``path``;
- a genuine ``a.tif`` with ``a.tif.ovr`` holding VRT XML (an "overview" that
  reads the target);
- a MapInfo view and a MapInfo seamless table (``\\IsSeamless``) whose
  tables lie outside ``path`` (GDAL follows both: it reads the seamless
  table's component, and opens the view's tables before refusing the view
  for the join index ``.IND`` OGR cannot write);
- a GeoTIFF declaring 100 000 x 100 000 pixels in well under a megabyte
  (sparse tiles);
- a ZIP whose end records declare 200 000 entries (ZIP64) while holding
  one (``zipfile`` still opens it: only a check of the declared count
  before ``ZipFile`` refuses it).

The targets live in ``<path>-cel/``, next to ``path``; their pixels and
attributes carry ``SECRET_VALUE`` and ``SECRET_TEXT``, so a test sees when a
reader followed a reference.
"""

import io
import os
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyogrio.raw
import rasterio
import shapely
from rasterio.transform import from_bounds

from tests.fixtures import store_files

SECRET_VALUE = 173
"""Every pixel of the raster target."""
SECRET_TEXT = "tajne"
"""The ``opis`` of every feature of the vector targets."""
HUGE_SIZE_PX = 100_000
ZIP_DECLARED_ENTRIES = 200_000

_BOUNDS = (566_100.0, 241_050.0, 569_800.0, 246_200.0)  # EPSG:2180
_SIZE = 64


@dataclass(frozen=True)
class HostileFiles:
    """Paths written by ``hostile_files``."""

    root: Path
    targets: Path
    """Directory outside ``root`` the references lead to."""
    raster_target: Path
    vector_target: Path
    vrt_rasters: tuple[Path, ...]
    """VRT XML named ``.tif`` and ``.asc``."""
    ogr_vrt_vectors: tuple[Path, ...]
    """OGR VRT XML named ``.gpkg``, ``.geojson``, ``.shp``, ``.fgb``."""
    ovr_base: Path
    """A genuine GeoTIFF ``a.tif``."""
    ovr: Path
    """``a.tif.ovr``: VRT XML reading the raster target."""
    mapinfo_view: Path
    mapinfo_seamless: Path
    huge_raster: Path
    zip_many_entries: Path


def hostile_files(path: Path) -> HostileFiles:
    """Write the planted files into ``path`` and their targets next to it.

    Parameters
    ----------
    path : Path
        Missing or empty directory.

    Returns
    -------
    HostileFiles
        Every planted file and target.

    Raises
    ------
    ValueError
        ``path`` is not empty.
    """
    path = path.absolute()
    if path.exists() and any(path.iterdir()):
        raise ValueError(f"directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)
    targets = path.with_name(path.name + "-cel")
    targets.mkdir(exist_ok=True)
    raster_target = targets / "tajny.tif"
    _secret_raster(raster_target)
    vector_target = targets / "tajny.geojson"
    _secret_vector(vector_target, "GeoJSON")

    vrt_rasters = tuple(path / name for name in ("vrt.tif", "vrt.asc"))
    for planted in vrt_rasters:
        planted.write_text(_raster_vrt(raster_target, _SIZE), encoding="utf-8")
    ogr_vrt_vectors = tuple(
        path / f"vrt{suffix}" for suffix in (".gpkg", ".geojson", ".shp", ".fgb")
    )
    for planted in ogr_vrt_vectors:
        planted.write_text(_ogr_vrt(vector_target), encoding="utf-8")

    ovr_base = path / "a.tif"
    ovr_base.write_bytes(store_files.geotiff(_BOUNDS, 2180, 1))
    ovr = path / "a.tif.ovr"
    ovr.write_text(_raster_vrt(raster_target, _SIZE // 2), encoding="utf-8")

    huge_raster = path / "ogromny.tif"
    _huge_raster(huge_raster)
    zip_many_entries = path / "wpisy.zip"
    zip_many_entries.write_bytes(_zip_declaring(ZIP_DECLARED_ENTRIES))

    return HostileFiles(
        root=path,
        targets=targets,
        raster_target=raster_target,
        vector_target=vector_target,
        vrt_rasters=vrt_rasters,
        ogr_vrt_vectors=ogr_vrt_vectors,
        ovr_base=ovr_base,
        ovr=ovr,
        mapinfo_view=_mapinfo_view(path, targets),
        mapinfo_seamless=_mapinfo_seamless(path, targets),
        huge_raster=huge_raster,
        zip_many_entries=zip_many_entries,
    )


def _secret_raster(target: Path) -> None:
    with (
        rasterio.Env(GDAL_PAM_ENABLED="NO"),
        rasterio.open(
            target,
            "w",
            driver="GTiff",
            width=_SIZE,
            height=_SIZE,
            count=1,
            dtype="uint8",
            crs="EPSG:2180",
            transform=from_bounds(*_BOUNDS, _SIZE, _SIZE),
        ) as dst,
    ):
        dst.write(np.full((_SIZE, _SIZE), SECRET_VALUE, dtype=np.uint8), 1)


def _polygons() -> list[shapely.Geometry]:
    min_x, min_y, max_x, max_y = _BOUNDS
    return [shapely.box(min_x, min_y, (min_x + max_x) / 2, (min_y + max_y) / 2)]


def _secret_vector(
    target: Path, driver: str, *, fields: dict[str, list[object]] | None = None
) -> None:
    values = fields or {"opis": [SECRET_TEXT]}
    pyogrio.raw.write(
        target,
        np.array([shapely.to_wkb(g) for g in _polygons()], dtype=object),
        [
            np.array(column, dtype=np.int32 if isinstance(column[0], int) else object)
            for column in values.values()
        ],
        list(values),
        layer=target.stem,
        driver=driver,
        geometry_type="Polygon",
        crs="EPSG:2180",
    )


def _raster_vrt(target: Path, size: int) -> str:
    """GDAL VRT of ``size`` x ``size`` pixels reading band 1 of ``target``."""
    min_x, _, max_x, max_y = _BOUNDS
    cell = (max_x - min_x) / size
    return (
        f'<VRTDataset rasterXSize="{size}" rasterYSize="{size}">\n'
        "  <SRS>EPSG:2180</SRS>\n"
        f"  <GeoTransform>{min_x}, {cell}, 0, {max_y}, 0, {-cell}</GeoTransform>\n"
        '  <VRTRasterBand dataType="Byte" band="1">\n'
        "    <SimpleSource>\n"
        f'      <SourceFilename relativeToVRT="0">{target}</SourceFilename>\n'
        "      <SourceBand>1</SourceBand>\n"
        "    </SimpleSource>\n"
        "  </VRTRasterBand>\n"
        "</VRTDataset>\n"
    )


def _ogr_vrt(target: Path) -> str:
    """OGR VRT with one layer reading ``target``."""
    return (
        "<OGRVRTDataSource>\n"
        f'  <OGRVRTLayer name="{target.stem}">\n'
        f'    <SrcDataSource relativeToVRT="0">{target}</SrcDataSource>\n'
        "  </OGRVRTLayer>\n"
        "</OGRVRTDataSource>\n"
    )


def _mapinfo_view(root: Path, targets: Path) -> Path:
    """Write a MapInfo view joining two native tables that lie in ``targets``.

    The join field has no ``.IND`` index (OGR's MapInfo driver does not
    write one), so GDAL opens both tables and then refuses the view.
    """
    _secret_vector(
        targets / "dzialki_cel.tab",
        "MapInfo File",
        fields={"klucz": [1], "opis": [SECRET_TEXT]},
    )
    _secret_vector(
        targets / "wlasciciele_cel.tab",
        "MapInfo File",
        fields={"klucz": [1], "nazwisko": [SECRET_TEXT]},
    )
    relative = os.path.relpath(targets, root)
    view = root / "widok.tab"
    view.write_text(
        "!Table\n"
        "!Version 100\n"
        "!charset Neutral\n"
        "\n"
        f'Open Table "{relative}/wlasciciele_cel" Hide\n'
        f'Open Table "{relative}/dzialki_cel" Hide\n'
        "\n"
        "Create View widok As\n"
        "Select *\n"
        "From wlasciciele_cel, dzialki_cel\n"
        "Where wlasciciele_cel.klucz=dzialki_cel.klucz\n",
        encoding="ascii",
    )
    return view


def _mapinfo_seamless(root: Path, targets: Path) -> Path:
    """Write a MapInfo seamless table whose one component lies in ``targets``."""
    component = targets / "kafel_cel.tab"
    _secret_vector(component, "MapInfo File")
    seamless = root / "mozaika.tab"
    _secret_vector(
        seamless,
        "MapInfo File",
        fields={
            "Table": [os.path.relpath(component, root)],
            "Description": ["kafel"],
        },
    )
    text = seamless.read_text(encoding="latin-1")
    marker = "Definition Table"
    if marker not in text:
        raise AssertionError(f"unexpected MapInfo header in {seamless}")
    seamless.write_text(
        text.replace(
            marker,
            'begin_metadata\n"\\IsSeamless" = "TRUE"\n"\\IsReadOnly" = "FALSE"\n'
            f"end_metadata\n{marker}",
            1,
        ),
        encoding="latin-1",
    )
    return seamless


def _huge_raster(target: Path) -> None:
    """Write a GeoTIFF declaring ``HUGE_SIZE_PX`` square (1 cm pixels).

    Sparse tiles: no block is written, the file holds only the tile tables.
    """
    min_x, min_y = _BOUNDS[:2]
    side_m = HUGE_SIZE_PX / 100
    with (
        rasterio.Env(GDAL_PAM_ENABLED="NO"),
        rasterio.open(
            target,
            "w",
            driver="GTiff",
            width=HUGE_SIZE_PX,
            height=HUGE_SIZE_PX,
            count=1,
            dtype="uint8",
            crs="EPSG:2180",
            transform=from_bounds(
                min_x, min_y, min_x + side_m, min_y + side_m, HUGE_SIZE_PX, HUGE_SIZE_PX
            ),
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress="deflate",
            sparse_ok=True,
        ),
    ):
        pass


def _zip_declaring(entries: int) -> bytes:
    """Return one stored member, then ZIP64 end records declaring ``entries``."""
    buffer = bytearray()
    member = io.BytesIO()
    with zipfile.ZipFile(member, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr(zipfile.ZipInfo("a.txt", (2024, 1, 1, 0, 0, 0)), b"a\n")
    data = member.getvalue()
    (cd_offset,) = struct.unpack_from("<I", data, len(data) - 6)
    (cd_size,) = struct.unpack_from("<I", data, len(data) - 10)
    buffer += data[: cd_offset + cd_size]
    zip64_offset = len(buffer)
    buffer += struct.pack(
        "<IQHHIIQQQQ",
        0x06064B50,
        44,
        45,
        45,
        0,
        0,
        entries,
        entries,
        cd_size,
        cd_offset,
    )
    buffer += struct.pack("<IIQI", 0x07064B50, 0, zip64_offset, 1)
    buffer += struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, 0xFFFF, 0xFFFF, cd_size, cd_offset, 0
    )
    return bytes(buffer)
