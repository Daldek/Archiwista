"""WGS84 outlines of native rectangles (decision 4 of the v0.2 plan).

Operations here are pyproj's (``PyprojOperation``): these tests check how an
outline is built and which one a footprint keeps. The producer's pinned
operation on the ground is checked by ``test_cz_control_point.py``.
"""

import itertools
import math
from collections.abc import Sequence
from dataclasses import replace
from typing import cast

import numpy as np
import pyproj
import pytest
import shapely

from archiwista.errors import ProducerError
from archiwista.index.geometry import (
    BBox,
    box_geometry,
    is_box,
    outline_wgs84,
    polygon_bounds,
)
from archiwista.index.scanner import outline_footprints
from archiwista.sources import (
    CoordinateTransformer,
    FloatArray,
    Footprint,
    GeoJSONGeometry,
    SourceAdapter,
    SourceEntry,
)
from tests.fixtures.index_data import (
    CZ_NMT,
    NMT,
    PyprojOperation,
    polygon,
    slot_path,
    version,
)

GEOD = pyproj.Geod(ellps="WGS84")
# A 5 x 5 km sheet in EPSG:2180 at 14.2° E, by Poland's western border.
WEST_SHEET: BBox = (180_000.0, 570_000.0, 185_000.0, 575_000.0)
# A 2.5 x 2 km raster in EPSG:5514 at Český Těšín.
CZ_RASTER: BBox = (-449_334.63, -1_113_919.25, -446_834.63, -1_111_919.25)
# A PL-1992 1:10000 sheet (1.875' x 1.25') in longitude and latitude.
PL1992_SHEET: BBox = (14.25, 52.875, 14.25 + 1.875 / 60, 52.875 + 1.25 / 60)


class _GeoProducer:
    """A producer with pyproj's operations, but none from a CRS to itself."""

    def transformer(self, src_crs: str, dst_crs: str) -> CoordinateTransformer:
        """Return pyproj's operation between two different CRSs."""
        if src_crs == dst_crs:
            raise ProducerError("fixture", "Unavailable", f"no {src_crs} operation")
        return PyprojOperation(src_crs, dst_crs)

    def countries(
        self, bbox_wgs84: tuple[float, float, float, float]
    ) -> tuple[str, ...]:
        """Return no countries."""
        return ()


class _Refusing(PyprojOperation):
    """pyproj's operation that cannot move a position east of ``limit``."""

    def __init__(self, source: str, target: str, limit: float) -> None:
        super().__init__(source, target)
        self._limit = limit

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Transform coordinates west of the limit; refuse the rest."""
        if float(np.max(xs)) > self._limit:
            raise ProducerError("fixture", "TransformError", "outside the operation")
        return super().transform(xs, ys)


class _RefusingProducer(_GeoProducer):
    def __init__(self, limit: float) -> None:
        self._limit = limit

    def transformer(self, src_crs: str, dst_crs: str) -> CoordinateTransformer:
        """Return an operation refusing positions east of the limit."""
        return _Refusing(src_crs, dst_crs, self._limit)


def _corners(bounds: BBox) -> list[tuple[float, float]]:
    min_x, min_y, max_x, max_y = bounds
    return [(min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)]


def _moved(
    points: Sequence[tuple[float, float]], operation: CoordinateTransformer
) -> FloatArray:
    """Positions moved by an operation, one ``[x, y]`` row each."""
    xs, ys = operation.transform(
        np.array([x for x, _ in points]), np.array([y for _, y in points])
    )
    return np.column_stack((xs, ys))


def _envelope(bounds: BBox, operation: CoordinateTransformer) -> BBox:
    """Bounding box of a moved rectangle, 21 positions per edge (as Kartograf)."""
    min_x, min_y, max_x, max_y = bounds
    steps = np.linspace(0.0, 1.0, 21)
    across = min_x + (max_x - min_x) * steps
    up = min_y + (max_y - min_y) * steps
    xs, ys = operation.transform(
        np.concatenate((across, np.full(21, max_x), across, np.full(21, min_x))),
        np.concatenate((np.full(21, min_y), up, np.full(21, max_y), up)),
    )
    return (float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))


def _ring(outline: GeoJSONGeometry) -> list[list[float]]:
    return cast(list[list[list[float]]], outline["coordinates"])[0]


def _distance_m(first: Sequence[float], second: Sequence[float]) -> float:
    return float(GEOD.inv(first[0], first[1], second[0], second[1])[2])


def _entry(seed: int) -> SourceEntry:
    return version(slot_path(CZ_NMT if seed % 2 else NMT, f"u{seed}"), "2025", seed)


def test_outline_wgs84_pl_west_sheet_is_rotated() -> None:
    """A PL-1992 sheet at 14° E is a quadrilateral in WGS84, not its box.

    The box misses every corner of the sheet by about 300 m (decision 4).
    """
    # Arrange
    operation = PyprojOperation("EPSG:2180", "EPSG:4326")
    corners = _moved(_corners(WEST_SHEET), operation)

    # Act
    outline = outline_wgs84(WEST_SHEET, "EPSG:2180", operation)

    # Assert
    ring = _ring(outline)
    bounds = polygon_bounds(outline)
    assert bounds is not None and not is_box(outline, bounds)
    np.testing.assert_allclose(ring, [*corners, corners[0]], rtol=0, atol=1e-12)
    misses = [
        min(_distance_m(corner, vertex) for vertex in ring)
        for corner in _corners(bounds)
    ]
    assert min(misses) > 250.0


@pytest.mark.parametrize(("max_segment_m", "positions"), [(5000.0, 9), (1000.0, 31)])
def test_outline_wgs84_densifies_edges_counter_clockwise(
    max_segment_m: float, positions: int
) -> None:
    """Edges are cut into equal parts of at most ``max_segment_m``.

    The ring starts at the south-west corner and keeps every corner.
    """
    # Arrange
    native: BBox = (400_000.0, 400_000.0, 412_000.0, 403_000.0)  # 12 x 3 km
    operation = PyprojOperation("EPSG:2180", "EPSG:4326")
    corners = _moved(_corners(native), operation)
    across = math.ceil(12_000 / max_segment_m)
    up = math.ceil(3_000 / max_segment_m)

    # Act
    outline = outline_wgs84(native, "EPSG:2180", operation, max_segment_m=max_segment_m)

    # Assert
    ring = _ring(outline)
    assert len(ring) == positions and ring[0] == ring[-1]
    np.testing.assert_allclose(
        [ring[0], ring[across], ring[across + up], ring[2 * across + up]],
        corners,
        rtol=0,
        atol=1e-12,
    )
    # The 2180 scale is below 1, so a part is a little longer on the ground.
    assert max(_distance_m(a, b) for a, b in itertools.pairwise(ring)) <= (
        max_segment_m * 1.001
    )
    assert shapely.LinearRing(ring).is_ccw


@pytest.mark.parametrize("crs", ["EPSG:4326", "epsg:4326", "OGC:CRS84"])
def test_outline_wgs84_of_wgs84_rectangle_is_its_box(crs: str) -> None:
    """A rectangle already in WGS84 is its box, without any operation."""
    native: BBox = (19.0, 50.0, 19.1, 50.1)

    assert outline_wgs84(native, crs, None) == box_geometry(native)


def test_outline_footprints_moves_rectangles_and_keeps_tighter_outlines() -> None:
    """A native rectangle becomes the polygon; a tighter own outline stays.

    A PL-1992 sheet is a longitude/latitude rectangle whose native outline
    is its EPSG:2180 envelope: that envelope's polygon would only widen it.
    A producer's own polygon and a WGS84 rectangle need no operation.
    """
    # Arrange
    cz = PyprojOperation("EPSG:5514", "EPSG:4326")
    raster = Footprint(
        location="footprint",
        wgs84=box_geometry(_envelope(CZ_RASTER, cz)),
        native=box_geometry(CZ_RASTER),
        source="header",
        native_crs="EPSG:5514",
    )
    envelope = _envelope(PL1992_SHEET, PyprojOperation("EPSG:4326", "EPSG:2180"))
    sheet = Footprint(
        location="footprint",
        wgs84=box_geometry(PL1992_SHEET),
        native=box_geometry(envelope),
        source="sheet",
        native_crs="EPSG:2180",
    )
    unit = Footprint(
        location="footprint",
        wgs84=polygon((19.0, 50.0), (19.1, 50.0), (19.0, 50.1)),
        native=box_geometry(WEST_SHEET),
        source="unit",
        native_crs="EPSG:2180",
    )
    request = Footprint(
        location="footprint",
        wgs84=box_geometry((19.0, 50.0, 19.1, 50.1)),
        native=box_geometry((19.0, 50.0, 19.1, 50.1)),
        source="request",
        native_crs="EPSG:4326",
    )
    country = Footprint(location="country", source="country")
    items = [
        (_entry(seed), found)
        for seed, found in enumerate((raster, sheet, unit, request, country))
    ]

    # Act
    outlined, failures = outline_footprints(cast(SourceAdapter, _GeoProducer()), items)

    # Assert
    polygon_of_raster = outline_wgs84(CZ_RASTER, "EPSG:5514", cz)
    assert failures == []
    assert outlined == [
        (items[0][0], replace(raster, wgs84=polygon_of_raster)),
        *items[1:],
    ]


def test_outline_footprints_leaves_out_only_the_rectangle_that_fails() -> None:
    """A rectangle the operation cannot move stays pending with the message.

    The others of its CRS are outlined all the same.
    """
    # Arrange
    east: BBox = (300_000.0, 400_000.0, 305_000.0, 405_000.0)
    items = [
        (
            _entry(seed),
            Footprint("footprint", native=box_geometry(bounds), native_crs="EPSG:2180"),
        )
        for seed, bounds in enumerate((WEST_SHEET, east))
    ]

    # Act
    outlined, failures = outline_footprints(
        cast(SourceAdapter, _RefusingProducer(limit=250_000.0)), items
    )

    # Assert
    operation = PyprojOperation("EPSG:2180", "EPSG:4326")
    assert failures == ["outside the operation"]
    assert outlined == [
        (
            items[0][0],
            replace(
                items[0][1], wgs84=outline_wgs84(WEST_SHEET, "EPSG:2180", operation)
            ),
        )
    ]


def test_outline_footprints_without_operations_keeps_producer_outlines() -> None:
    """A producer without coordinate operations keeps its own outlines."""
    found = Footprint(
        location="footprint",
        wgs84=box_geometry((19.0, 50.0, 19.1, 50.1)),
        native=box_geometry(WEST_SHEET),
        native_crs="EPSG:2180",
    )
    items = [(_entry(1), found)]

    assert outline_footprints(cast(SourceAdapter, object()), items) == (items, [])
