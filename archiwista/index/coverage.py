"""Local coverage of an area, measured in the planar CRS of a country.

"Lokalnie 83% obszaru" (decision 5) is the area of the union of the current
versions' footprints within the area divided by the area — measured in the
country's planar CRS (PL → EPSG:2180, CZ → EPSG:5514), never in WGS84
degrees, where north–south and west–east distances differ by about a third
at Polish latitudes. The area and the footprints are densified
(``shapely.segmentize``) and then moved by the producer's pinned coordinate
operation (``GeoAdapter.transformer``, KA-6), which the caller injects: the
index never imports an adapter. A native outline already in the target CRS
is used as it is. Overlapping footprints count once.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import shapely
from shapely.geometry import shape

from archiwista.index.types import TransformerFactory
from archiwista.sources import CoordinateTransformer, GeoJSONGeometry

PLANAR_CRS: Mapping[str, str] = MappingProxyType({"PL": "EPSG:2180", "CZ": "EPSG:5514"})
WGS84 = "EPSG:4326"
# Longest edge before a transformation: ~0.5 km in degrees or metres.
SEGMENT_DEGREES = 0.005
SEGMENT_METRES = 500.0
_GEOGRAPHIC = frozenset({"EPSG:4326", "EPSG:4258", "OGC:CRS84"})
_SQUARE_METRES_PER_KM2 = 1_000_000.0


@dataclass(frozen=True, slots=True)
class CoverageShape:
    """A footprint to measure: its WGS84 outline and native outline, if any.

    Parameters
    ----------
    wgs84 : GeoJSONGeometry
        Outline in WGS84 (longitude, latitude).
    native : GeoJSONGeometry or None
        The same outline in ``native_crs``; preferred when present.
    native_crs : str or None
        CRS of ``native``, e.g. ``"EPSG:2180"``.
    """

    wgs84: GeoJSONGeometry
    native: GeoJSONGeometry | None = None
    native_crs: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageMeasure:
    """An area and the part of it covered by footprints, in square kilometres.

    ``footprints`` counts the footprints sharing interior with the area.
    """

    area_km2: float
    covered_km2: float
    footprints: int


def planar_crs(country: str | None) -> str | None:
    """Return the planar CRS of a country code, or ``None`` without one."""
    return None if country is None else PLANAR_CRS.get(country.upper())


class PlanarMover:
    """Moves outlines into one planar CRS with the producer's pinned operations.

    The area and footprints of ``measure_coverage``, and the outlines of the
    local layers in their frame (plan v0.2, decision 7): densified first
    (``shapely.segmentize``), each pair of CRSs' operation taken once.

    Parameters
    ----------
    crs : str
        The planar CRS (``planar_crs``).
    transformer : TransformerFactory
        The producer's pinned operations (``GeoAdapter.transformer``).
    """

    def __init__(self, crs: str, transformer: TransformerFactory) -> None:
        self.crs = crs
        self._transformer = transformer
        self._operations: dict[tuple[str, str], CoordinateTransformer] = {}

    def move(self, geometry: GeoJSONGeometry, source: str) -> Any:
        """Return a GeoJSON geometry in ``source`` as a shapely one in ``crs``.

        Raises
        ------
        ProducerError
            The producer has no pinned operation from ``source`` to ``crs``.
        """
        geom = shape(geometry)
        if source == self.crs:
            return geom
        operation = self._operations.get((source, self.crs))
        if operation is None:
            operation = self._transformer(source, self.crs)
            self._operations[(source, self.crs)] = operation
        step = SEGMENT_DEGREES if source in _GEOGRAPHIC else SEGMENT_METRES
        return shapely.transform(
            shapely.segmentize(geom, step), operation.transform, interleaved=False
        )

    def footprint(self, item: CoverageShape) -> Any:
        """Return a footprint in ``crs``, from its native outline when it has one."""
        if item.native is not None and item.native_crs is not None:
            return shapely.make_valid(self.move(item.native, item.native_crs))
        return shapely.make_valid(self.move(item.wgs84, WGS84))


def measure_coverage(
    area: GeoJSONGeometry,
    shapes: Sequence[CoverageShape],
    *,
    crs: str,
    transformer: TransformerFactory,
) -> CoverageMeasure:
    """Measure an area and its part covered by footprints in a planar CRS.

    Parameters
    ----------
    area : GeoJSONGeometry
        ``Polygon`` or ``MultiPolygon`` in WGS84.
    shapes : Sequence[CoverageShape]
        Candidate footprints; ones only touching the area add nothing.
    crs : str
        Planar CRS of the measurement (``planar_crs``).
    transformer : TransformerFactory
        The producer's pinned operations (``GeoAdapter.transformer``).

    Returns
    -------
    CoverageMeasure
        Areas in km²; overlapping footprints count once.

    Raises
    ------
    ProducerError
        The producer has no pinned operation for a needed pair of CRSs.
    """
    mover = PlanarMover(crs, transformer)
    region = shapely.make_valid(mover.move(area, WGS84))
    return measure_planar(region, [mover.footprint(item) for item in shapes])


def measure_planar(region: Any, footprints: Sequence[Any]) -> CoverageMeasure:
    """Measure a planar area and its part covered by planar footprints.

    Parameters
    ----------
    region : shapely geometry
        The area, valid, in a planar CRS (``PlanarMover.move``).
    footprints : Sequence of shapely geometries
        Valid footprints in the same CRS (``PlanarMover.footprint``); ones
        only touching the area add nothing, overlaps count once.
    """
    shapely.prepare(region)
    inside = [
        footprint
        for footprint in footprints
        if shapely.intersects(region, footprint)
        and not shapely.touches(region, footprint)
    ]
    covered = 0.0
    if inside:
        covered = float(shapely.union_all(inside).intersection(region).area)
    return CoverageMeasure(
        area_km2=float(region.area) / _SQUARE_METRES_PER_KM2,
        covered_km2=covered / _SQUARE_METRES_PER_KM2,
        footprints=len(inside),
    )
