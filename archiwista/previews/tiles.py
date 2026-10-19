"""Map tiles of the previews: the tile grid, pinned operations, warping (decision 4).

Render processes only (pyproj, morecantile, rasterio and rio-tiler): the
server never imports this module.

A preview reaches the map only through an operation Kartograf pins
(``transformer``: the first producer with a ``GeoAdapter``, Kartograf), as
``COORDINATE_OPERATION`` of ``rasterio.warp.reproject`` (``operation``):
GDAL would otherwise choose an operation itself, and ``WarpedVRT`` (thus
rio-tiler's tiles) silently drops that option. CRSs on the WGS84 ellipsoid
without a datum change (EPSG:4326, OGC:CRS84, EPSG:3857: SoilGrids, HSG,
web maps) are converted by GDAL and PROJ themselves: there is nothing to pin,
and Kartograf refuses a conversion without a declared accuracy.

Tiles are the ``WebMercatorQuad`` grid of 256 pixels (EPSG:3857). A file's
place on the map (``map_placement``) is its WGS84 bounding box (the native
rectangle's densified edges moved by the pinned operation) with the zoom
levels a map asks tiles for: up to the native resolution's zoom + 2, at most
22, from the zoom at which the file fits one tile.

``warp`` puts a raster on a grid (a tile with its margin, a thumbnail's
frame): only the part of the grid the raster covers, from the window of the
raster that part needs, read decimated near the grid's resolution (GDAL
takes the nearest overview: ``OVERVIEW_LEVEL`` without opening the file
again), then ``reproject`` with the pinned operation. A ``RasterView`` is an
open raster with the georeference a preview uses: the file's own, else the
index's (an ASC grid's CRS, a JPEG sheet's header outline — decision 5).
"""

import functools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import morecantile
import numpy as np
import pyproj
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject
from rasterio.windows import Window
from rio_tiler.utils import render

from archiwista.errors import PreviewUnavailableError, ProducerError, SourceStateError
from archiwista.index.geometry import is_wgs84, outline_wgs84, polygon_bounds
from archiwista.previews.types import BBox
from archiwista.sources import CoordinateTransformer, FloatArray, GeoAdapter
from archiwista.sources.registry import load_registry

if TYPE_CHECKING:
    from rasterio.crs import CRS
    from rasterio.io import DatasetReader

type Values = np.ma.MaskedArray[Any, np.dtype[np.floating[Any]]]
type Metres = np.ndarray[Any, np.dtype[np.float64]] | float

TILE_SIZE = 256
WEB_MERCATOR = "EPSG:3857"
WGS84 = "EPSG:4326"
MAX_ZOOM = 22
# Zoom levels past the native resolution a map may still ask tiles for.
OVERZOOM = 2
# EPSG:3857 units (metres at the equator) per pixel of a zoom 0 tile.
ZOOM0_RESOLUTION = 2 * math.pi * 6378137.0 / TILE_SIZE
# CRSs on the WGS84 ellipsoid without a datum change (decision 4).
PLAIN_CRS = frozenset({"EPSG:4326", "OGC:CRS84", "EPSG:3857"})

_GRID = morecantile.tms.get("WebMercatorQuad")
_EARTH_RADIUS_M = 6378137.0
# Metres of a degree of longitude at the equator and of latitude.
_METRES_PER_DEGREE_X = 111_320.0
_METRES_PER_DEGREE_Y = 110_574.0
# Positions per edge of a rectangle moved into another CRS.
_EDGE_POINTS = 21
# Source pixels read around the window a grid needs (resampling kernels).
_READ_PAD_PX = 2


@dataclass(frozen=True, slots=True)
class MapPlacement:
    """Where a file lies on the map and the zoom levels of its tiles.

    Attributes
    ----------
    bbox_wgs84 : BBox
        West, south, east, north in degrees.
    minzoom, maxzoom : int
        The zoom at which the file fits one tile, and its native
        resolution's zoom + ``OVERZOOM`` (at most ``MAX_ZOOM``).
    """

    bbox_wgs84: BBox
    minzoom: int
    maxzoom: int


def is_plain(crs: str) -> bool:
    """Whether ``crs`` is converted to the map's CRS without a pinned operation."""
    return crs.upper() in PLAIN_CRS


@functools.cache
def transformer(src_crs: str, dst_crs: str) -> CoordinateTransformer:
    """Return the operation of a render process from one CRS to another.

    The same CRS is the identity; two CRSs of ``PLAIN_CRS`` are converted by
    PROJ; any other pair takes Kartograf's pinned operation (the first
    available producer with a ``GeoAdapter``). Kept per pair for the life of
    the process.

    Parameters
    ----------
    src_crs, dst_crs : str
        CRSs, e.g. ``EPSG:2180`` and ``EPSG:3857``.

    Returns
    -------
    CoordinateTransformer
        Coordinates in x (east), y (north) order.

    Raises
    ------
    PreviewUnavailableError
        ``transform_unavailable``: no producer pins an operation for the
        pair.
    """
    if src_crs.upper() == dst_crs.upper():
        return _Identity()
    if is_plain(src_crs) and is_plain(dst_crs):
        return _Plain(src_crs, dst_crs)
    try:
        return _geo_adapter().transformer(src_crs, dst_crs)
    except ProducerError as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error


def operation(src_crs: str, dst_crs: str) -> str | None:
    """Return ``COORDINATE_OPERATION`` for warping between two CRSs.

    ``None`` where GDAL converts by itself: the same CRS, or two CRSs of
    ``PLAIN_CRS``. Otherwise the pinned operation's PROJ pipeline.

    Raises
    ------
    PreviewUnavailableError
        ``transform_unavailable``: no pinned operation for the pair.
    """
    if src_crs.upper() == dst_crs.upper() or (is_plain(src_crs) and is_plain(dst_crs)):
        return None
    try:
        return transformer(src_crs, dst_crs).gdal_operation()
    except ProducerError as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error


def wgs84_bounds(bbox: BBox, crs: str) -> BBox:
    """Return the WGS84 bounding box of a rectangle in its CRS.

    The rectangle's edges are densified before the pinned operation moves
    them (``archiwista.index.geometry.outline_wgs84``), so the box holds the
    whole rotated outline.

    Raises
    ------
    PreviewUnavailableError
        ``transform_unavailable``: no pinned operation, or it fails there.
    """
    if is_wgs84(crs):
        return bbox
    try:
        outline = outline_wgs84(bbox, crs, transformer(crs, WGS84))
    except (ProducerError, ValueError) as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error
    bounds = polygon_bounds(outline)
    if bounds is None:
        raise PreviewUnavailableError("transform_unavailable", "no outline")
    return bounds


def map_placement(bbox: BBox, crs: str, width: int, height: int) -> MapPlacement:
    """Return where a raster of ``width`` x ``height`` pixels lies on the map.

    Parameters
    ----------
    bbox : BBox
        Its extent in ``crs``.
    crs : str
        Its CRS.
    width, height : int
        Its size in pixels (a point cloud: its 2D image).

    Raises
    ------
    PreviewUnavailableError
        ``transform_unavailable``: no pinned operation to WGS84.
    """
    bounds = wgs84_bounds(bbox, crs)
    west, south, east, north = mercator_bounds(bounds)
    resolution = min((east - west) / max(1, width), (north - south) / max(1, height))
    if not math.isfinite(resolution) or resolution <= 0:
        native = MAX_ZOOM - OVERZOOM
    else:
        native = math.ceil(math.log2(ZOOM0_RESOLUTION / resolution) - 1e-9)
    native = max(0, min(MAX_ZOOM - OVERZOOM, native))
    across = math.ceil(math.log2(max(1.0, max(width, height) / TILE_SIZE)))
    maxzoom = min(MAX_ZOOM, native + OVERZOOM)
    return MapPlacement(bounds, min(maxzoom, max(0, native - across)), maxzoom)


def mercator_bounds(bbox_wgs84: BBox) -> BBox:
    """Return a WGS84 box in EPSG:3857 metres (latitudes kept within the grid)."""
    west, south, east, north = bbox_wgs84
    limit = 85.05112878

    def y(lat: float) -> float:
        phi = math.radians(max(-limit, min(limit, lat)))
        return _EARTH_RADIUS_M * math.log(math.tan(math.pi / 4 + phi / 2))

    def x(lon: float) -> float:
        return _EARTH_RADIUS_M * math.radians(lon)

    return x(west), y(south), x(east), y(north)


def tile_bounds(z: int, x: int, y: int) -> BBox:
    """Return the EPSG:3857 bounds of tile ``z/x/y`` (``WebMercatorQuad``)."""
    found = _GRID.xy_bounds(morecantile.Tile(x, y, z))
    return float(found.left), float(found.bottom), float(found.right), float(found.top)


def tile_resolution(z: int) -> float:
    """Return EPSG:3857 units per pixel of a tile of zoom ``z``."""
    return ZOOM0_RESOLUTION / (1 << z)


def tile_grid(z: int, x: int, y: int, *, margin: int = 0) -> tuple[Affine, int]:
    """Return the transform and side in pixels of tile ``z/x/y`` with a margin.

    The margin is ``margin`` pixels of the neighbouring tiles on every side,
    on the same pixel grid, so a style looking at neighbours (hillshade)
    gives the same edge pixels in both tiles.
    """
    west, south, east, north = tile_bounds(z, x, y)
    pad = margin * tile_resolution(z)
    side = TILE_SIZE + 2 * margin
    bounds = (west - pad, south - pad, east + pad, north + pad)
    return from_bounds(*bounds, side, side), side


def frame_shape(bbox: BBox, size: int) -> tuple[int, int]:
    """Return ``(height, width)`` of an image of a frame: its longer side ``size``."""
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    if width <= 0 or height <= 0:
        raise ValueError("a frame has an area")
    if width >= height:
        return max(1, round(size * height / width)), size
    return size, max(1, round(size * width / height))


def grid_transform(bbox: BBox, width: int, height: int) -> Affine:
    """Return the transform of ``width`` x ``height`` pixels covering ``bbox``."""
    return from_bounds(*bbox, width, height)


def encode_png(rgba: np.ndarray[Any, np.dtype[np.uint8]]) -> bytes:
    """Encode ``uint8`` RGBA (4, rows, columns) as a PNG with its alpha."""
    if rgba.ndim != 3 or rgba.shape[0] != 4 or rgba.dtype != np.uint8:
        raise ValueError("an RGBA image is uint8 (4, rows, columns)")
    return render(rgba[:3], mask=rgba[3], img_format="PNG")


@dataclass(frozen=True, slots=True)
class RasterView:
    """An open raster with the georeference its preview uses.

    Attributes
    ----------
    dataset : rasterio.io.DatasetReader
        The open file (the caller closes it).
    transform : Affine or None
        Pixel to CRS coordinates: the file's, else the index's.
    crs : str or None
        The file's CRS (``crs_name``), else the index's.
    data_bands : tuple[int, ...]
        Bands holding values (1-based): all but an alpha band.
    nodata : float or None
        A value masked besides the file's own mask (the index's ``nodata``
        of a file without one).
    """

    dataset: "DatasetReader"
    transform: Affine | None
    crs: str | None
    data_bands: tuple[int, ...]
    nodata: float | None = None


def raster_view(
    dataset: "DatasetReader",
    *,
    transform: Affine | None = None,
    crs: str | None = None,
    nodata: float | None = None,
) -> RasterView:
    """Return a raster with its georeference: the file's, else the one given.

    Parameters
    ----------
    dataset : rasterio.io.DatasetReader
        The open file.
    transform, crs : optional
        Georeference of a file without its own (from the index).
    nodata : float or None, optional
        Value to mask when the file declares none.
    """
    own = None if dataset.transform.is_identity else dataset.transform
    interpretation = dataset.colorinterp
    data_bands = tuple(
        index
        for index, found in enumerate(interpretation, start=1)
        if found.name != "alpha"
    ) or tuple(range(1, dataset.count + 1))
    return RasterView(
        dataset,
        own if own is not None else transform,
        crs_name(dataset.crs) or crs,
        data_bands,
        nodata if dataset.nodata is None else None,
    )


def crs_name(crs: "CRS | None") -> str | None:
    """Return a CRS as ``EPSG:<code>`` (horizontal part of a compound), else WKT."""
    if crs is None or not crs.to_wkt():
        return None
    found = pyproj.CRS.from_user_input(crs.to_wkt())
    if found.is_compound and found.sub_crs_list:
        found = found.sub_crs_list[0]
    code = found.to_epsg()
    return f"EPSG:{code}" if code is not None else str(found.to_wkt())


def read_values(
    view: RasterView,
    indexes: Sequence[int],
    *,
    shape: tuple[int, int],
    resampling: str,
    window: Window | None = None,
) -> Values:
    """Read bands (or a window of them) decimated to ``shape``, masked.

    GDAL reads the nearest overview at least as fine as ``shape``.

    Returns
    -------
    numpy.ma.MaskedArray
        Floats (bands, rows, columns); nodata, alpha and the index's
        ``nodata`` masked.
    """
    dataset = view.dataset
    data = dataset.read(
        list(indexes),
        window=window,
        out_shape=(len(indexes), *shape),
        resampling=Resampling[resampling],
        masked=True,
    )
    found = np.dtype(dataset.dtypes[indexes[0] - 1])
    wide = found.itemsize > 4 or (found.kind in "iu" and found.itemsize >= 4)
    values = data.astype(np.float64 if wide else np.float32)
    mask = np.ma.getmaskarray(values) | ~np.isfinite(values.filled(0))
    if view.nodata is not None:
        mask |= values.filled(view.nodata) == view.nodata
    return np.ma.MaskedArray(values.filled(np.nan), mask=mask)


def warp(
    view: RasterView,
    indexes: Sequence[int],
    grid: Affine,
    shape: tuple[int, int],
    crs: str,
    *,
    resampling: str,
    decimation: str,
) -> Values:
    """Put bands of a raster on a grid of another CRS with the pinned operation.

    Only the part of the grid the raster covers is warped, from the window
    of the raster that part needs, read decimated near the grid's resolution
    (the nearest overview).

    Parameters
    ----------
    view : RasterView
        The raster, georeferenced.
    indexes : sequence of int
        Bands to warp.
    grid : Affine
        Transform of the grid, in ``crs``.
    shape : tuple[int, int]
        Rows and columns of the grid.
    crs : str
        CRS of the grid.
    resampling, decimation : str
        Resampling of the warp and of the decimated read
        (``rasterio.enums.Resampling`` names).

    Returns
    -------
    numpy.ma.MaskedArray
        Floats (bands, rows, columns); masked where the raster has no value.

    Raises
    ------
    PreviewUnavailableError
        ``no_georeference``: the raster has none; ``transform_unavailable``:
        no pinned operation between the CRSs.
    """
    if view.transform is None or view.crs is None:
        raise PreviewUnavailableError("no_georeference")
    rows, columns = shape
    data = np.full((len(indexes), rows, columns), np.nan, dtype=np.float64)
    mask = np.ones((len(indexes), rows, columns), dtype=bool)
    footprint = raster_bounds(view.transform, view.dataset.width, view.dataset.height)
    covered = _grid_window(_moved_bounds(footprint, view.crs, crs), grid, rows, columns)
    if covered is None:
        return np.ma.MaskedArray(data, mask=mask)
    part = grid @ Affine.translation(covered.col_off, covered.row_off)
    part_rows, part_columns = int(covered.height), int(covered.width)
    needed = _moved_bounds(raster_bounds(part, part_columns, part_rows), crs, view.crs)
    source = _source_window(view, needed)
    if source is None:
        return np.ma.MaskedArray(data, mask=mask)
    grid_pixel = (needed[2] - needed[0]) / part_columns
    source_pixel = math.hypot(view.transform.a, view.transform.d)
    factor = max(1.0, grid_pixel / source_pixel) if source_pixel > 0 else 1.0
    read_shape = (
        max(1, math.ceil(source.height / factor)),
        max(1, math.ceil(source.width / factor)),
    )
    values = read_values(
        view, indexes, shape=read_shape, resampling=decimation, window=source
    )
    read_transform = (
        view.transform
        @ Affine.translation(source.col_off, source.row_off)
        @ Affine.scale(source.width / read_shape[1], source.height / read_shape[0])
    )
    target = np.full((len(indexes), part_rows, part_columns), np.nan, values.dtype)
    pinned = operation(view.crs, crs)
    reproject(
        values.filled(np.nan),
        target,
        src_transform=read_transform,
        src_crs=view.crs,
        dst_transform=part,
        dst_crs=crs,
        resampling=Resampling[resampling],
        src_nodata=np.nan,
        dst_nodata=np.nan,
        **({} if pinned is None else {"COORDINATE_OPERATION": pinned}),
    )
    row, column = int(covered.row_off), int(covered.col_off)
    region = (
        slice(None),
        slice(row, row + part_rows),
        slice(column, column + part_columns),
    )
    data[region] = target
    mask[region] = ~np.isfinite(target)
    return np.ma.MaskedArray(data, mask=mask)


def pixel_metres(
    transform: Affine, rows: int, crs: str | None
) -> tuple[Metres, Metres]:
    """Return the ground size of a grid's pixels in metres, across and down.

    One number in a projected CRS; one per row (rows, 1) in EPSG:3857 and
    in a geographic CRS, where it changes with the latitude. A grid without
    a CRS counts its units as metres.
    """
    across = math.hypot(transform.a, transform.d)
    down = math.hypot(transform.b, transform.e)
    if crs is None:
        return across, down
    centres = transform.f + (np.arange(rows, dtype=np.float64) + 0.5) * transform.e
    if crs.upper() == WEB_MERCATOR:
        scale = np.cos(np.arctan(np.sinh(centres / _EARTH_RADIUS_M)))[:, np.newaxis]
        return across * scale, down * scale
    found = _crs(crs)
    if found.is_geographic:
        latitude = np.cos(np.radians(np.clip(centres, -90.0, 90.0)))[:, np.newaxis]
        return (
            across * _METRES_PER_DEGREE_X * latitude,
            down * _METRES_PER_DEGREE_Y * np.ones_like(latitude),
        )
    factor = found.axis_info[0].unit_conversion_factor if found.axis_info else 1.0
    return across * factor, down * factor


def raster_bounds(transform: Affine, width: int, height: int) -> BBox:
    """Return the box of a grid's corners in its CRS (rotation included)."""
    xs, ys = zip(
        *(
            transform @ corner
            for corner in ((0, 0), (width, 0), (0, height), (width, height))
        ),
        strict=True,
    )
    return min(xs), min(ys), max(xs), max(ys)


def _moved_bounds(bounds: Sequence[float], src_crs: str, dst_crs: str) -> BBox:
    """Return the box in ``dst_crs`` of a box's densified edges (pinned operation).

    Raises
    ------
    PreviewUnavailableError
        ``transform_unavailable``.
    """
    min_x, min_y, max_x, max_y = bounds
    if src_crs.upper() == dst_crs.upper():
        return min_x, min_y, max_x, max_y
    steps = np.linspace(0.0, 1.0, _EDGE_POINTS)
    xs = np.concatenate(
        (
            min_x + (max_x - min_x) * steps,
            np.full(steps.size, max_x),
            max_x - (max_x - min_x) * steps,
            np.full(steps.size, min_x),
        )
    )
    ys = np.concatenate(
        (
            np.full(steps.size, min_y),
            min_y + (max_y - min_y) * steps,
            np.full(steps.size, max_y),
            max_y - (max_y - min_y) * steps,
        )
    )
    try:
        moved_x, moved_y = transformer(src_crs, dst_crs).transform(xs, ys)
    except ProducerError as error:
        raise PreviewUnavailableError("transform_unavailable", str(error)) from error
    finite = np.isfinite(moved_x) & np.isfinite(moved_y)
    if not finite.any():
        raise PreviewUnavailableError("transform_unavailable", "no finite position")
    return (
        float(np.min(moved_x[finite])),
        float(np.min(moved_y[finite])),
        float(np.max(moved_x[finite])),
        float(np.max(moved_y[finite])),
    )


def _grid_window(bounds: BBox, grid: Affine, rows: int, columns: int) -> Window | None:
    """Return the window of a grid covering a box (a pixel more around), if any."""
    inverse = ~grid
    corners = [
        inverse @ (x, y) for x in (bounds[0], bounds[2]) for y in (bounds[1], bounds[3])
    ]
    first_column = max(0, math.floor(min(c for c, _ in corners)) - 1)
    last_column = min(columns, math.ceil(max(c for c, _ in corners)) + 1)
    first_row = max(0, math.floor(min(r for _, r in corners)) - 1)
    last_row = min(rows, math.ceil(max(r for _, r in corners)) + 1)
    if first_column >= last_column or first_row >= last_row:
        return None
    return Window(
        first_column, first_row, last_column - first_column, last_row - first_row
    )


def _source_window(view: RasterView, bounds: BBox) -> Window | None:
    """Return the window of a raster a box needs, padded, within the raster."""
    assert view.transform is not None
    dataset = view.dataset
    window = _grid_window(bounds, view.transform, dataset.height, dataset.width)
    if window is None:
        return None
    first_column = max(0, int(window.col_off) - _READ_PAD_PX)
    first_row = max(0, int(window.row_off) - _READ_PAD_PX)
    last_column = min(dataset.width, int(window.col_off + window.width) + _READ_PAD_PX)
    last_row = min(dataset.height, int(window.row_off + window.height) + _READ_PAD_PX)
    return Window(
        first_column, first_row, last_column - first_column, last_row - first_row
    )


@functools.cache
def _crs(crs: str) -> pyproj.CRS:
    return pyproj.CRS.from_user_input(crs)


@functools.cache
def _geo_adapter() -> GeoAdapter:
    """Return the first available producer with pinned coordinate operations."""
    registry = load_registry()
    for producer in registry.producers():
        try:
            adapter = registry.adapter(producer)
        except SourceStateError:
            continue
        if isinstance(adapter, GeoAdapter):
            return adapter
    raise PreviewUnavailableError(
        "transform_unavailable", "no producer with pinned coordinate operations"
    )


class _Identity:
    """The same CRS on both sides."""

    description = "identity"
    accuracy_m = 0.0

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Return the coordinates as they are."""
        return np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)

    def gdal_operation(self) -> str:
        """Return PROJ's operation that changes nothing."""
        return "+proj=noop"


class _Plain:
    """A conversion between two CRSs on the WGS84 ellipsoid (no datum change)."""

    accuracy_m = 0.0

    def __init__(self, src_crs: str, dst_crs: str) -> None:
        self._forward = pyproj.Transformer.from_crs(src_crs, dst_crs, always_xy=True)
        # GDAL hands coordinates over in the CRSs' authority axis order.
        self._gdal = pyproj.Transformer.from_crs(src_crs, dst_crs).to_proj4()
        self.description = str(self._forward.description)

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Convert coordinates in x (east), y (north) order."""
        x, y = self._forward.transform(xs, ys)
        return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)

    def gdal_operation(self) -> str:
        """Return the conversion as a PROJ pipeline for GDAL."""
        return self._gdal
