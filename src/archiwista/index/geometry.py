"""GeoJSON helpers of the index: bounding boxes, boxes, outlines and validation.

Footprints and areas arrive as GeoJSON geometries in WGS84 (longitude,
latitude). The index keeps each footprint's bounding box next to the version
(exact doubles) and in the R*Tree (rounded outwards), and remembers whether
the outline *is* its bounding box: such outlines let area tests stay in SQL.

A rectangle in a projected CRS (a PL-1992 or S-JTSK sheet, a raster's
extent) is a rotated quadrilateral with slightly curved edges in WGS84
(meridian convergence), so its WGS84 bounding box misses its corners by up
to hundreds of metres at the edges of a country. ``outline_wgs84`` moves the
rectangle with the producer's pinned operation instead (decision 4 of the
v0.2 plan, KA-6), its edges densified first.
"""

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import shapely
from shapely.geometry import shape

from archiwista.errors import IndexQueryError
from archiwista.messages import message
from archiwista.sources import CoordinateTransformer, FloatArray, GeoJSONGeometry

type BBox = tuple[float, float, float, float]

WGS84 = "EPSG:4326"
# Longest edge of a native rectangle before it moves to WGS84.
MAX_SEGMENT_M = 5000.0
# Coordinates in these CRSs already are WGS84 longitude, latitude.
_WGS84_NAMES = frozenset({WGS84, "OGC:CRS84"})
# Geographic CRSs: a rectangle's edges are densified in degrees.
_GEOGRAPHIC = frozenset({WGS84, "EPSG:4258", "OGC:CRS84"})
_METRES_PER_DEGREE = 111_320.0
# How far (degrees, about 1 m) a box may stick out of a polygon it lies in.
# The polygon's edges are chords of curved edges (at most MAX_SEGMENT_M
# long), which a box touching the curve crosses by centimetres to decimetres.
_WITHIN_DEGREES = 1e-5


def polygon_bounds(geometry: GeoJSONGeometry | None) -> BBox | None:
    """Return ``(min_x, min_y, max_x, max_y)`` of a polygonal geometry.

    Parameters
    ----------
    geometry : GeoJSONGeometry or None
        A GeoJSON ``Polygon`` or ``MultiPolygon``.

    Returns
    -------
    BBox or None
        ``None`` for anything else: another type, no coordinates, or a
        coordinate that is not a finite number.
    """
    if geometry is None:
        return None
    rings = _rings(geometry)
    if rings is None:
        return None
    try:
        xs = [float(position[0]) for ring in rings for position in ring]
        ys = [float(position[1]) for ring in rings for position in ring]
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    bounds = (min(xs), min(ys), max(xs), max(ys))
    if not all(math.isfinite(value) for value in bounds):
        return None
    return bounds


def is_box(geometry: GeoJSONGeometry, bounds: BBox) -> bool:
    """Whether a polygon is exactly its axis-aligned bounding box.

    Parameters
    ----------
    geometry : GeoJSONGeometry
        A polygonal geometry whose bounds are ``bounds``.
    bounds : BBox
        Its bounding box (``polygon_bounds``).

    Returns
    -------
    bool
        True for a single-ring polygon whose corners are the four corners of
        ``bounds`` (repeated or closing positions allowed).
    """
    rings = _rings(geometry) if geometry.get("type") == "Polygon" else None
    if rings is None or len(rings) != 1:
        return False
    min_x, min_y, max_x, max_y = bounds
    if not (min_x < max_x and min_y < max_y):
        return False
    corners = {(min_x, min_y), (min_x, max_y), (max_x, min_y), (max_x, max_y)}
    try:
        positions = {(float(p[0]), float(p[1])) for p in rings[0]}
    except (TypeError, ValueError, IndexError, KeyError):
        return False
    return positions == corners


def box_geometry(bounds: BBox) -> GeoJSONGeometry:
    """Return the counter-clockwise GeoJSON polygon of a bounding box."""
    min_x, min_y, max_x, max_y = bounds
    ring = [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]
    return {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}


def is_wgs84(crs: str) -> bool:
    """Whether coordinates in ``crs`` already are WGS84 longitude, latitude."""
    return crs.upper() in _WGS84_NAMES


def outline_wgs84(
    native: BBox,
    native_crs: str,
    transformer: CoordinateTransformer | None,
    *,
    max_segment_m: float = MAX_SEGMENT_M,
) -> GeoJSONGeometry:
    """Return the WGS84 polygon of a rectangle given in its native CRS.

    The rectangle's edges are densified to at most ``max_segment_m`` and
    moved by ``transformer``; a rectangle already in WGS84 (``is_wgs84``)
    is its box, not transformed.

    Parameters
    ----------
    native : BBox
        ``(min_x, min_y, max_x, max_y)`` in ``native_crs``, x east.
    native_crs : str
        CRS of ``native``, e.g. ``"EPSG:5514"``.
    transformer : CoordinateTransformer or None
        The producer's pinned operation from ``native_crs`` to WGS84
        (``GeoAdapter.transformer``); ``None`` only for WGS84 itself.
    max_segment_m : float, default MAX_SEGMENT_M
        Longest edge before the transformation, in metres; in a geographic
        CRS as degrees of latitude (``max_segment_m / 111 320``).

    Returns
    -------
    GeoJSONGeometry
        A counter-clockwise ``Polygon`` starting at the south-west corner.

    Raises
    ------
    ValueError
        No rectangle, no transformer for another CRS, or a transformed
        position that is not finite.
    ProducerError
        The producer's operation failed.
    """
    return outlines_wgs84(
        (native,), native_crs, transformer, max_segment_m=max_segment_m
    )[0]


def outlines_wgs84(
    natives: Sequence[BBox],
    native_crs: str,
    transformer: CoordinateTransformer | None,
    *,
    max_segment_m: float = MAX_SEGMENT_M,
) -> list[GeoJSONGeometry]:
    """``outline_wgs84`` of rectangles in one CRS, with one ``transform`` call."""
    for min_x, min_y, max_x, max_y in natives:
        finite = all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y))
        if not (finite and min_x < max_x and min_y < max_y):
            raise ValueError(f"not a rectangle: {(min_x, min_y, max_x, max_y)}")
    if not max_segment_m > 0:
        raise ValueError(f"max_segment_m must be positive, not {max_segment_m}")
    if is_wgs84(native_crs):
        return [box_geometry(native) for native in natives]
    if transformer is None:
        raise ValueError(f"a transformer from {native_crs} to WGS84 is required")
    if not natives:
        return []
    step = max_segment_m
    if native_crs.upper() in _GEOGRAPHIC:
        step /= _METRES_PER_DEGREE
    rings = [_ring(native, step) for native in natives]
    lons, lats = transformer.transform(
        np.concatenate([xs for xs, _ in rings]),
        np.concatenate([ys for _, ys in rings]),
    )
    if not (np.isfinite(lons).all() and np.isfinite(lats).all()):
        raise ValueError(message("index.outline_not_finite", crs=native_crs))
    outlines: list[GeoJSONGeometry] = []
    start = 0
    for xs, _ in rings:
        end = start + len(xs)
        ring = np.column_stack((lons[start:end], lats[start:end])).tolist()
        outlines.append({"type": "Polygon", "coordinates": [[*ring, list(ring[0])]]})
        start = end
    return outlines


def box_within(bounds: BBox, polygon: GeoJSONGeometry) -> bool:
    """Whether a box lies within a polygon, give or take a metre.

    A corner of the box on (or just across) the polygon's edge counts as
    inside: the box is shrunk by about 1 m (``_WITHIN_DEGREES``) first.
    """
    min_x, min_y, max_x, max_y = bounds
    margin = min(_WITHIN_DEGREES, (max_x - min_x) / 4, (max_y - min_y) / 4)
    inner = shapely.box(min_x + margin, min_y + margin, max_x - margin, max_y - margin)
    return bool(shapely.covers(shape(polygon), inner))


def require_wgs84_area(geometry: GeoJSONGeometry) -> BBox:
    """Validate an area polygon in WGS84 and return its bounding box.

    Parameters
    ----------
    geometry : GeoJSONGeometry
        A GeoJSON ``Polygon`` or ``MultiPolygon`` in longitude, latitude.

    Returns
    -------
    BBox
        ``(min_lon, min_lat, max_lon, max_lat)``.

    Raises
    ------
    IndexQueryError
        Not a polygonal geometry, no area, or coordinates outside WGS84.
    """
    bounds = polygon_bounds(geometry)
    if bounds is None:
        raise IndexQueryError(message("index.invalid_area"))
    min_x, min_y, max_x, max_y = bounds
    inside = -180.0 <= min_x < max_x <= 180.0 and -90.0 <= min_y < max_y <= 90.0
    if not inside:
        raise IndexQueryError(message("index.invalid_area"))
    return bounds


def require_wgs84_bbox(bbox: BBox) -> BBox:
    """Validate ``(min_lon, min_lat, max_lon, max_lat)`` of a map view.

    Raises
    ------
    IndexQueryError
        Reversed, empty or outside WGS84.
    """
    min_x, min_y, max_x, max_y = (float(value) for value in bbox)
    finite = all(math.isfinite(value) for value in (min_x, min_y, max_x, max_y))
    if not (
        finite and -180.0 <= min_x < max_x <= 180.0 and -90.0 <= min_y < max_y <= 90.0
    ):
        raise IndexQueryError(message("index.invalid_bbox"))
    return (min_x, min_y, max_x, max_y)


def _rings(geometry: GeoJSONGeometry) -> list[list[Any]] | None:
    """Rings of a ``Polygon`` or ``MultiPolygon``; ``None`` if malformed."""
    kind = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        return None
    if kind == "Polygon":
        polygons: list[Any] = [coordinates]
    elif kind == "MultiPolygon":
        polygons = coordinates
    else:
        return None
    rings: list[list[Any]] = []
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            return None
        for ring in polygon:
            if not isinstance(ring, list) or not ring:
                return None
            rings.append(ring)
    return rings


def _ring(bounds: BBox, step: float) -> tuple[FloatArray, FloatArray]:
    """Positions on a rectangle's edges at most ``step`` apart, unclosed.

    Counter-clockwise from the south-west corner; every corner is a position.
    """
    min_x, min_y, max_x, max_y = bounds
    width, height = max_x - min_x, max_y - min_y
    columns = max(1, math.ceil(width / step))
    rows = max(1, math.ceil(height / step))
    # Fractions of an edge: 0 (its first corner) up to, not including, 1.
    across = np.arange(columns) / columns
    up = np.arange(rows) / rows
    xs = np.concatenate(
        (
            min_x + width * across,
            np.full(up.size, max_x),
            max_x - width * across,
            np.full(up.size, min_x),
        )
    )
    ys = np.concatenate(
        (
            np.full(across.size, min_y),
            min_y + height * up,
            np.full(across.size, max_y),
            max_y - height * up,
        )
    )
    return xs, ys
