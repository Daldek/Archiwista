"""Local coverage measured in the planar CRS of the product's country (decision 5)."""

from dataclasses import dataclass, field
from typing import Any

import pyproj
import pytest
import shapely
from shapely.geometry import mapping, shape

from archiwista.index import IndexQueries, IndexWriter
from archiwista.sources import CoordinateTransformer, FloatArray, SourceSegment
from tests.fixtures.index_data import STORE, box, link, polygon, slot_path, version
from tests.fixtures.index_data import write_pass as run_pass

Index = tuple[IndexWriter, IndexQueries]
TOLERANCE = 0.005  # 0.5 percentage point


class _Operation:
    """A coordinate operation of pyproj in x (east), y (north) order."""

    def __init__(self, source: str, target: str) -> None:
        self._transformer = pyproj.Transformer.from_crs(source, target, always_xy=True)
        self.description = str(self._transformer.description)
        self.accuracy_m = float(self._transformer.accuracy or 0.0)

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Transform coordinates."""
        x, y = self._transformer.transform(xs, ys)
        return x, y


def _operation(source: str, target: str) -> CoordinateTransformer:
    return _Operation(source, target)


def _rectangle(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return polygon((west, south), (east, south), (east, north), (west, north))


def _planar(geometry: dict[str, Any], crs: str) -> Any:
    """Return a WGS84 geometry in ``crs``, densified finer than the index does."""
    transformer = pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    return shapely.transform(
        shapely.segmentize(shape(geometry), 0.0005),
        transformer.transform,
        interleaved=False,
    )


@dataclass(frozen=True)
class _Scenario:
    product: str
    country: str | None
    area: dict[str, Any]
    boxes: tuple[tuple[float, float, float, float], ...]
    native_crs: str | None = None
    planar: str | None = None
    degree_ratio: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


SCENARIOS = {
    # 5.5° north–south: in degrees the northern half is 50%, in EPSG:2180 ~48.5%.
    "north_south": _Scenario(
        "ns",
        "PL",
        _rectangle(19.0, 49.0, 19.2, 54.5),
        ((19.0, 51.75, 19.2, 54.5),),
        planar="EPSG:2180",
        degree_ratio=0.5,
    ),
    "west_east": _Scenario(
        "we",
        "PL",
        _rectangle(15.0, 50.0, 24.0, 50.2),
        ((15.0, 50.0, 18.0, 50.2),),
        planar="EPSG:2180",
    ),
    "overlap_once": _Scenario(
        "overlap",
        "PL",
        _rectangle(20.0, 50.0, 20.2, 50.2),
        ((20.0, 50.0, 20.15, 50.2), (20.05, 50.0, 20.2, 50.1)),
        planar="EPSG:2180",
    ),
    "cz_krovak": _Scenario(
        "dmr",
        "CZ",
        _rectangle(15.0, 49.8, 15.2, 50.0),
        ((15.0, 49.8, 15.1, 50.0),),
        native_crs="EPSG:5514",
        planar="EPSG:5514",
    ),
    "no_country": _Scenario(
        "x",
        None,
        _rectangle(18.0, 50.0, 18.2, 50.2),
        ((18.0, 50.0, 18.1, 50.1),),
    ),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_local_coverage_in_planar_crs(index: Index, name: str) -> None:
    """The share of the area is the planar one, overlaps counted once."""
    # Arrange
    writer, queries = index
    scenario = SCENARIOS[name]
    segment = f"{scenario.product}/test"
    entries = []
    footprints = {}
    planar_footprints = []
    for number, bounds in enumerate(scenario.boxes):
        slot = slot_path(segment, f"F-{number}")
        item = version(slot, "2024", number + 1, country=scenario.country)
        entries += [item, link(slot, item)]
        native = None
        if scenario.native_crs is not None:
            native = mapping(_planar(_rectangle(*bounds), scenario.native_crs))
        footprints[item.relative_path.as_posix()] = box(
            *bounds, native=native, native_crs=scenario.native_crs
        )
        if scenario.planar is not None:
            planar_footprints.append(_planar(_rectangle(*bounds), scenario.planar))
    run_pass(
        writer,
        entries,
        footprints=footprints,
        segments=[
            SourceSegment(
                segment, scenario.product, scenario.country, None, segment, True
            )
        ],
    )

    # Act
    report = queries.local_coverage(
        scenario.area,
        store=STORE,
        product=scenario.product,
        transformer=_operation,
        countries=("PL", "CZ"),
    )

    # Assert
    assert len(report.results) == 1
    result = report.results[0]
    assert result.country == scenario.country
    assert result.versions_count == len(scenario.boxes)
    if scenario.planar is None:
        assert (result.crs, result.ratio, result.reason) == (
            None,
            None,
            "no_planar_crs",
        )
        return
    region = _planar(scenario.area, scenario.planar)
    covered = shapely.union_all(planar_footprints).intersection(region).area
    expected = covered / region.area
    assert result.crs == scenario.planar
    assert result.ratio is not None and result.area_km2 is not None
    assert abs(result.ratio - expected) < TOLERANCE
    assert abs(result.area_km2 - region.area / 1e6) < region.area / 1e6 * TOLERANCE
    if scenario.degree_ratio is not None:
        # Measured in degrees the answer would be off by more than the tolerance.
        assert abs(scenario.degree_ratio - expected) > TOLERANCE
    if len(planar_footprints) > 1:
        separately = sum(item.intersection(region).area for item in planar_footprints)
        assert result.covered_km2 is not None
        assert result.covered_km2 < separately / 1e6


def test_local_coverage_only_current_versions_of_the_store(index: Index) -> None:
    """Older versions do not add to the local share; an empty product gives none."""
    # Arrange
    writer, queries = index
    segment = "nmt/test"
    slot = slot_path(segment, "F-0")
    current = version(slot, "2024", 1)
    older = version(slot, "2019", 2)
    run_pass(
        writer,
        [link(slot, current), current, older],
        footprints={
            current.relative_path.as_posix(): box(19.0, 50.0, 19.05, 50.1),
            older.relative_path.as_posix(): box(19.0, 50.0, 19.1, 50.1),
        },
        segments=[SourceSegment(segment, "nmt", "PL", None, segment, True)],
    )
    area = _rectangle(19.0, 50.0, 19.1, 50.1)

    # Act
    report = queries.local_coverage(
        area, store=STORE, product="nmt", transformer=_operation
    )
    missing = queries.local_coverage(
        area, store=STORE, product="orto", transformer=_operation
    )
    elsewhere = queries.local_coverage(
        _rectangle(21.0, 52.0, 21.1, 52.1),
        store=STORE,
        product="nmt",
        transformer=_operation,
        countries=("PL",),
    )

    # Assert
    assert [result.versions_count for result in report.results] == [1]
    assert report.results[0].ratio == pytest.approx(0.5, abs=TOLERANCE)
    assert missing.results == ()
    assert [(item.country, item.ratio) for item in elsewhere.results] == [("PL", 0.0)]
