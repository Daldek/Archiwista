"""GeoJSON helpers of the index: bounding boxes, boxes and validation.

Footprints and areas arrive as GeoJSON geometries in WGS84 (longitude,
latitude). The index keeps each footprint's bounding box next to the version
(exact doubles) and in the R*Tree (rounded outwards), and remembers whether
the outline *is* its bounding box: most producers' footprints are boxes, so
area tests can stay in SQL.
"""

import math
from typing import Any

from archiwista.errors import IndexQueryError
from archiwista.messages import MESSAGES
from archiwista.sources import GeoJSONGeometry

type BBox = tuple[float, float, float, float]


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
        raise IndexQueryError(MESSAGES["index_invalid_area"])
    min_x, min_y, max_x, max_y = bounds
    inside = -180.0 <= min_x < max_x <= 180.0 and -90.0 <= min_y < max_y <= 90.0
    if not inside:
        raise IndexQueryError(MESSAGES["index_invalid_area"])
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
        raise IndexQueryError(MESSAGES["index_invalid_bbox"])
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
