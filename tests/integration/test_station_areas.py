"""Stations in an area and the coverage filters of the index (plan I6, SPEC 6.7, 4.8.4).

The stations and their series are written the way a scan writes a provider's
catalog and a dataset's series index (``IndexWriter.replace_stations``,
``replace_series``), from synthetic lists placed around one kept area, so
each rule is shown on the stations it is about: a station closer to the
area's boundary than its location uncertainty is on the boundary, on either
side; the stations without a location are counted after the attribute and
coverage filters and never placed in an area (SPEC 4.3 point 3); a coverage
filter labels the variables of one dataset in a range of years, before any
page is cut, and the stations it hides are counted.
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from archiwista.errors import IndexQueryError
from archiwista.index import (
    AreaRecord,
    IndexQueries,
    IndexWriter,
    SeriesState,
    StationCounts,
    StationPage,
    StationQuery,
)
from archiwista.sources import (
    DateRange,
    SeriesListing,
    Station,
    StationSeries,
    TimeUnit,
    VariableCoverage,
)

STORE = "dane"
PL = "IMGW-PIB"
DAILY = "pl.imgw.hydro_daily"
HALF_YEAR = "pl.imgw.hydro_semiannual"
# The hydrological years 2001 to 2004 (1 XI 2000 to 31 X 2004).
KNOWN: DateRange = (date(2000, 11, 1), date(2004, 10, 31))
# The area: 20.0-20.2 E, 50.0-50.2 N (a degree of longitude is about 71.5 km there).
AREA = AreaRecord(
    id="zlewnia",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[20.0, 50.0], [20.2, 50.0], [20.2, 50.2], [20.0, 50.2], [20.0, 50.0]]
        ],
    },
    created_at=datetime(2026, 10, 26, tzinfo=UTC),
)
# Stations by name: (point, location uncertainty in metres).
INSIDE = "149200001"  # far from every edge
ON_EDGE = "149200002"  # on the eastern edge, no uncertainty: inside
NEAR_INSIDE = "149200003"  # 500 m inside the eastern edge, uncertain to 1 km
NEAR_OUTSIDE = "149200004"  # 500 m outside the eastern edge, uncertain to 1 km
WIDE = "149200005"  # 21 km outside, uncertain to 30 km
OUTSIDE = "149200006"  # 3.6 km outside, uncertain to 1 km
BESIDE = "149200007"  # 36 m outside, no uncertainty
NOWHERE = "149200008"  # no location (`none`)
ZERO = "149200009"  # no location (`zero`), a meteo station
PLACES: dict[str, tuple[tuple[float, float], float | None]] = {
    INSIDE: ((20.1, 50.1), 150.0),
    ON_EDGE: ((20.2, 50.1), None),
    NEAR_INSIDE: ((20.193, 50.1), 1000.0),
    NEAR_OUTSIDE: ((20.207, 50.1), 1000.0),
    WIDE: ((20.5, 50.1), 30_000.0),
    OUTSIDE: ((20.25, 50.1), 1000.0),
    BESIDE: ((20.2005, 50.1), None),
}
IN_AREA = {INSIDE, ON_EDGE, NEAR_INSIDE, NEAR_OUTSIDE, WIDE}
ON_BOUNDARY = {NEAR_INSIDE, NEAR_OUTSIDE, WIDE}


@pytest.fixture
def index(tmp_path: Path) -> Iterator[IndexQueries]:
    """Return the queries of an index with the stations, the area and the series."""
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores({STORE: {"imgw": tmp_path / "dane" / "imgw"}})
        writer.write_area(AREA)
        stations = [
            Station(
                PL,
                code,
                name=f"Stacja {code[-1]}",
                kind="hydro",
                point=point,
                location_source="api_hydro",
                location_uncertainty_m=uncertainty,
            )
            for code, (point, uncertainty) in PLACES.items()
        ]
        stations += [
            Station(PL, NOWHERE, name="Stacja 8", kind="hydro", location_reason="none"),
            Station(PL, ZERO, name="Stacja 9", kind="meteo", location_reason="zero"),
        ]
        writer.replace_stations(
            STORE,
            "imgw",
            PL,
            slot="stations/versions",
            version="stations/versions/2026-10-26_00000000/stations.geojson",
            stations=stations,
        )
        _write_daily(writer)
        _write_half_years(writer)
        yield queries


def _variable(
    key: str,
    *gaps: DateRange,
    first: date = KNOWN[0],
    last: date = KNOWN[1],
) -> VariableCoverage:
    variable, _, period = key.partition("@")
    return VariableCoverage(
        key=key,
        variable=variable,
        unit="m3/s",
        period=period or None,
        first=first,
        last=last,
        with_value=0,
        accumulated=0,
        gaps=gaps,
    )


def _series(dataset: str, code: str, *variables: VariableCoverage) -> StationSeries:
    slug = dataset.rsplit(".", 1)[1]
    return StationSeries(
        code=code,
        file=f"series/versions/{slug}/2026-10-26_00000000/stations/{code}.parquet",
        sha256="0" * 64,
        rows=1461,
        variables=variables,
    )


def _write_listing(
    writer: IndexWriter, dataset: str, unit: TimeUnit, stations: list[StationSeries]
) -> None:
    slug = dataset.rsplit(".", 1)[1]
    writer.replace_series(
        STORE,
        "imgw",
        slot=f"series/versions/{slug}",
        version=f"series/versions/{slug}/2026-10-26_00000000/series.json",
        listing=SeriesListing(
            dataset=dataset,
            provider=PL,
            kind="hydro",
            time_unit=unit,
            year_type="hydrological",
            first_year=2001,
            periods=(KNOWN,),
            stations=tuple(stations),
        ),
    )


def _write_daily(writer: IndexWriter) -> None:
    """Write Q and H by day, each station as it is described here.

    In 2001-2004 Q is, by station (complete years): continuous (4) at INSIDE,
    WIDE, OUTSIDE, BESIDE and NOWHERE; with gaps in March 2002 (3) at
    NEAR_OUTSIDE; partial from 2003 (2) at NEAR_INSIDE; absent at ON_EDGE (H
    only). H is continuous at INSIDE, ON_EDGE and NOWHERE and has gaps at WIDE.
    ZERO has no series of the dataset.
    """
    march = (date(2002, 3, 1), date(2002, 3, 31))
    _write_listing(
        writer,
        DAILY,
        "day",
        [
            _series(DAILY, INSIDE, _variable("Q"), _variable("H")),
            _series(DAILY, ON_EDGE, _variable("H")),
            _series(DAILY, NEAR_INSIDE, _variable("Q", first=date(2002, 11, 1))),
            _series(DAILY, NEAR_OUTSIDE, _variable("Q", march)),
            _series(DAILY, WIDE, _variable("Q"), _variable("H", march)),
            _series(DAILY, OUTSIDE, _variable("Q")),
            _series(DAILY, BESIDE, _variable("Q")),
            _series(DAILY, NOWHERE, _variable("Q"), _variable("H")),
        ],
    )


def _write_half_years(writer: IndexWriter) -> None:
    """Write Q_max of the winter and summer half-years, 2001-2004 (a unit a year).

    INSIDE: both continuous; NEAR_INSIDE: the summer without 2003; ON_EDGE:
    only H_max of the winter.
    """
    summer_2003 = (date(2003, 6, 1), date(2003, 6, 1))
    _write_listing(
        writer,
        HALF_YEAR,
        "half_year",
        [
            _series(
                HALF_YEAR, INSIDE, _variable("Q_max@winter"), _variable("Q_max@summer")
            ),
            _series(
                HALF_YEAR,
                NEAR_INSIDE,
                _variable("Q_max@winter"),
                _variable("Q_max@summer", summer_2003),
            ),
            _series(HALF_YEAR, ON_EDGE, _variable("H_max@winter")),
        ],
    )


def _codes(page: StationPage) -> set[str]:
    return {row.code for row in page.items}


def _all(queries: IndexQueries, query: StationQuery) -> list[str]:
    """Return the codes of every row, page after page."""
    codes: list[str] = []
    cursor = None
    while True:
        page = queries.stations(replace(query, cursor=cursor))
        codes += [row.code for row in page.items]
        cursor = page.next_cursor
        if cursor is None:
            return codes


def test_an_area_takes_the_stations_in_it_and_on_its_boundary(
    index: IndexQueries,
) -> None:
    """Closer to the boundary than the uncertainty, on either side, is the boundary.

    A station without an uncertainty is inside when the area covers its point
    (edges included) and never on the boundary; one far outside whose
    uncertainty reaches the area is still found among the candidates.
    """
    # Arrange
    area = AREA.geometry

    # Act
    found = index.stations(StationQuery(area=area))
    inside = index.stations(StationQuery(area=area, boundary=False))

    # Assert
    assert _codes(found) == IN_AREA
    assert {row.code for row in found.items if row.on_boundary} == ON_BOUNDARY
    assert all(row.location == "point" for row in found.items)
    assert found.counts == StationCounts(located=5, boundary=3, unlocated=2)
    assert _codes(inside) == {INSIDE, ON_EDGE}
    assert not any(row.on_boundary for row in inside.items)
    assert inside.counts == StationCounts(located=2, boundary=3, unlocated=2)


def test_the_stations_without_a_location_are_counted_never_placed_by_an_area(
    index: IndexQueries,
) -> None:
    """SPEC 4.3 point 3: the attribute filters narrow them, an area never does."""
    # Act
    everywhere = index.stations(StationQuery())
    unlocated = index.stations(StationQuery(area=AREA.geometry, location="none"))
    hydro = index.stations(StationQuery(area=AREA.geometry, kind="hydro"))
    hydro_unlocated = index.stations(
        StationQuery(area=AREA.geometry, kind="hydro", location="none")
    )

    # Assert
    assert everywhere.counts == StationCounts(located=7, unlocated=2)
    assert _codes(unlocated) == {NOWHERE, ZERO}
    assert {(row.point, row.on_boundary) for row in unlocated.items} == {(None, False)}
    assert unlocated.counts == StationCounts(located=5, boundary=3, unlocated=2)
    assert hydro.counts == StationCounts(located=5, boundary=3, unlocated=1)
    assert _codes(hydro_unlocated) == {NOWHERE}


@pytest.mark.parametrize(
    ("coverage", "least", "located", "unlocated", "counts"),
    [
        pytest.param(
            (("Q", "continuous"),),
            (),
            {INSIDE, WIDE},
            {NOWHERE},
            StationCounts(located=2, boundary=1, unlocated=1, hidden=3),
            id="one-state",
        ),
        pytest.param(
            (("Q", "continuous"), ("Q", "gaps")),
            (),
            {INSIDE, WIDE, NEAR_OUTSIDE},
            {NOWHERE},
            StationCounts(located=3, boundary=2, unlocated=1, hidden=2),
            id="alternative-states",
        ),
        pytest.param(
            (("Q", "continuous"), ("H", "continuous")),
            (),
            {INSIDE},
            {NOWHERE},
            StationCounts(located=1, boundary=0, unlocated=1, hidden=4),
            id="two-variables-must-both-match",
        ),
        pytest.param(
            (("H", "continuous"),),
            (),
            {INSIDE, ON_EDGE},
            {NOWHERE},
            StationCounts(located=2, boundary=0, unlocated=1, hidden=3),
            id="without-the-variable-hidden",
        ),
        pytest.param(
            (),
            (("Q", 3),),
            {INSIDE, WIDE, NEAR_OUTSIDE},
            {NOWHERE},
            StationCounts(located=3, boundary=2, unlocated=1, hidden=2),
            id="min-complete-years",
        ),
        pytest.param(
            (("Q", "gaps"), ("Q", "partial")),
            (("Q", 3),),
            {NEAR_OUTSIDE},
            set(),
            StationCounts(located=1, boundary=1, unlocated=0, hidden=5),
            id="states-and-years-together",
        ),
    ],
)
def test_coverage_filters_label_one_dataset_before_the_page(
    index: IndexQueries,
    coverage: tuple[tuple[str, SeriesState], ...],
    least: tuple[tuple[str, int], ...],
    located: set[str],
    unlocated: set[str],
    counts: StationCounts,
) -> None:
    """The stations a filter hides are counted; a station without the variable fails.

    In the area: INSIDE and WIDE have a continuous Q, NEAR_OUTSIDE gaps,
    NEAR_INSIDE a partial one and ON_EDGE no Q; NOWHERE (no location) a
    continuous Q. ZERO has no series of the dataset, so the dataset leaves
    it out before any label: it is not hidden.
    """
    # Arrange
    query = StationQuery(
        area=AREA.geometry,
        dataset=DAILY,
        coverage=coverage,
        min_complete_years=least,
        limit=1,
    )

    # Act
    rows = _all(index, query)
    without = _all(index, replace(query, location="none"))
    page = index.stations(query)

    # Assert
    assert len(rows) == len(set(rows))
    assert set(rows) == located
    assert set(without) == unlocated
    assert page.counts == counts


def test_the_range_and_the_boundary_choice_decide_what_a_filter_hides(
    index: IndexQueries,
) -> None:
    """A label is that of R; the boundary left out is not hidden, still counted."""
    # Arrange
    continuous = StationQuery(
        area=AREA.geometry, dataset=DAILY, coverage=(("Q", "continuous"),)
    )

    # Act
    later = index.stations(replace(continuous, years=(2003, 2004)))
    inside = index.stations(replace(continuous, boundary=False))

    # Assert
    assert _codes(later) == {INSIDE, WIDE, NEAR_INSIDE, NEAR_OUTSIDE}
    assert later.counts == StationCounts(located=4, boundary=3, unlocated=1, hidden=1)
    assert _codes(inside) == {INSIDE}
    assert inside.counts == StationCounts(located=1, boundary=1, unlocated=1, hidden=1)


def test_a_variable_of_half_years_passes_when_each_period_does(
    index: IndexQueries,
) -> None:
    """``Q_max`` is the winter and the summer; a key names one period only."""
    # Arrange
    query = StationQuery(dataset=HALF_YEAR)

    # Act
    both = index.stations(replace(query, coverage=(("Q_max", "continuous"),)))
    either = index.stations(
        replace(query, coverage=(("Q_max", "continuous"), ("Q_max", "gaps")))
    )
    winter = index.stations(replace(query, coverage=(("Q_max@winter", "continuous"),)))
    calendar = index.stations(
        replace(query, coverage=(("Q_max", "continuous"),), year_type="calendar")
    )
    four = index.stations(replace(query, min_complete_years=(("Q_max", 4),)))
    having = index.stations(replace(query, variables=("Q_max@summer",)))

    # Assert
    assert _codes(both) == {INSIDE}
    assert both.counts == StationCounts(located=1, unlocated=0, hidden=2)
    assert _codes(either) == {INSIDE, NEAR_INSIDE}
    assert _codes(winter) == {INSIDE, NEAR_INSIDE}
    assert _codes(calendar) == {INSIDE}  # half-years stay hydrological
    assert _codes(four) == {INSIDE}
    assert _codes(having) == {INSIDE, NEAR_INSIDE}
    assert having.counts.hidden == 0


def test_labels_of_a_page_are_those_of_its_stations_in_the_dataset(
    index: IndexQueries,
) -> None:
    """``labels`` labels the page's stations only, in the query's range."""
    # Act
    page = index.stations(
        StationQuery(
            area=AREA.geometry, dataset=DAILY, labels=True, years=(2002, 2004), limit=2
        )
    )
    unlabelled = index.stations(StationQuery(area=AREA.geometry, limit=2))

    # Assert
    assert {found.code for found in page.coverage} == _codes(page)
    assert {found.dataset for found in page.coverage} == {DAILY}
    assert {found.span for found in page.coverage} == {(2002, 2004)}
    assert unlabelled.coverage == ()


def test_pages_with_filters_follow_one_query(index: IndexQueries) -> None:
    """Every station once by name; a cursor of other coverage filters is refused."""
    # Arrange
    query = StationQuery(
        area=AREA.geometry,
        dataset=DAILY,
        coverage=(("Q", "continuous"), ("Q", "gaps"), ("Q", "partial")),
        limit=1,
    )
    first = index.stations(query)
    other = replace(query, coverage=(("Q", "continuous"),), cursor=first.next_cursor)

    # Act
    rows = _all(index, query)

    # Assert
    assert rows == [row.code for row in index.stations(replace(query, limit=50)).items]
    assert set(rows) == IN_AREA - {ON_EDGE}
    assert first.next_cursor is not None
    with pytest.raises(IndexQueryError):
        index.stations(other)
    with pytest.raises(IndexQueryError):
        index.stations(replace(query, boundary=False, cursor=first.next_cursor))


@pytest.mark.parametrize(
    "query",
    [
        pytest.param(StationQuery(coverage=(("Q", "continuous"),)), id="no-dataset"),
        pytest.param(
            StationQuery(min_complete_years=(("Q", 3),)), id="years-without-dataset"
        ),
        pytest.param(StationQuery(dataset=DAILY, years=(2004, 2001)), id="reversed"),
        pytest.param(
            StationQuery(area={"type": "Point", "coordinates": [20.1, 50.1]}),
            id="no-polygon",
        ),
    ],
)
def test_a_filter_that_cannot_apply_is_refused(
    index: IndexQueries, query: StationQuery
) -> None:
    """A label belongs to one dataset and R runs forward; an area is a polygon."""
    with pytest.raises(IndexQueryError):
        index.stations(query)


def test_the_map_draws_the_located_stations_of_the_view_or_their_grid(
    index: IndexQueries,
) -> None:
    """The counts are those of the list; the unlocated are counted, never drawn."""
    # Arrange
    view = (19.0, 49.0, 21.0, 51.0)
    query = StationQuery(bbox=view, area=AREA.geometry, dataset=DAILY, labels=True)

    # Act
    drawn = index.station_map(query, limit=10, grid_columns=4)
    grid = index.station_map(query, limit=4, grid_columns=4)
    plain = index.station_map(StationQuery(bbox=view), limit=10, grid_columns=4)
    listed = index.stations(replace(query, bbox=None))

    # Assert
    assert (drawn.total, drawn.aggregated, drawn.cells) == (5, False, ())
    assert {row.code for row in drawn.items} == IN_AREA
    assert {row.code for row in drawn.items if row.on_boundary} == ON_BOUNDARY
    assert {found.code for found in drawn.coverage} == IN_AREA
    assert drawn.counts == listed.counts
    assert (grid.total, grid.aggregated, grid.items, grid.coverage) == (5, True, (), ())
    assert [(cell.min_lon, cell.count) for cell in grid.cells] == [(20.0, 4), (20.5, 1)]
    assert grid.counts == listed.counts
    assert {row.code for row in plain.items} == set(PLACES)
    assert plain.counts == StationCounts(located=7, unlocated=2)
    assert plain.coverage == ()
    with pytest.raises(IndexQueryError):
        index.station_map(StationQuery(), limit=10, grid_columns=4)
