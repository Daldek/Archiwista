"""Stations of the producers' station catalogs over HTTP (SPEC 9.2, 6.7, 6.8).

``GET /stations`` pages the stations of the filters along rivers or by name
(``sort``), found by a name, river or code (``q``), in an area (``area_id``,
or ``bbox`` with ``bbox_crs``) with the stations on its boundary, each
variable of each series labelled (P16), with the counts of the location
groups: the stations without a location are counted after the attribute and
coverage filters and never placed in an area (SPEC 4.3 point 3).
``GET /stations/datasets`` names the datasets with station series (the
dataset chip of the map), ``GET /stations/timeline`` is a page of the
stations of one dataset with each variable year by year (the Timeline tab of
the Catalog), ``GET /stations/compare`` one variable of 2 to 5 stations over
one range (the comparison), ``GET /stations/{code}`` is a station's card,
``GET /stations/{code}/coverage`` its variables year by year (the Timeline),
``GET /stations/{code}/series`` the values of one or two variables of a
series as a chart and ``GET /map/stations`` the located stations of a map
view or their grid. The fixed paths are declared before ``/stations/{code}``,
which would else read them as a code. Without ``year_type`` the labels
number the years as the settings remember for the data's family
(``year_types``, P15), a list of both families as for hydro data. Everything
is read from the index, never from a series file, except the values of a
chart or a comparison, which the producer reads (``SeriesValuesAdapter``);
and only while the source of the stations is available: else ``503`` (SPEC
5.8).
``archiwista stations`` calls the same functions without HTTP.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path as FilePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models import AreaRef, CopyPath, staleness
from archiwista.api.models_stations import (
    ChartVariable,
    ComparedStation,
    StationCard,
    StationChart,
    StationChartQuery,
    StationCompareQuery,
    StationComparison,
    StationDatasets,
    StationDatasetsQuery,
    StationItem,
    StationList,
    StationListFilters,
    StationLookup,
    StationMapFilters,
    StationMapView,
    StationTimeline,
    StationTimelineFilters,
    StationTimelineListFilters,
    StationTimelinePage,
)
from archiwista.api.slots import bbox_area, checked_store, copy_path
from archiwista.auth import Principal
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import (
    ConflictError,
    IndexQueryError,
    NotFoundError,
    UnsupportedError,
)
from archiwista.index import (
    MAX_PAGE_LIMIT,
    AreaRecord,
    BBox,
    CoverageVariable,
    IndexQueries,
    StationCoverage,
    StationPage,
    StationQuery,
    StationRow,
)
from archiwista.index.geometry import box_geometry, is_wgs84, require_wgs84_bbox
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import series_chart
from archiwista.sources import GeoJSONGeometry, SeriesValuesAdapter
from archiwista.sources.registry import PluginRegistry

# The producer whose plugin keeps the station catalogs and series (IMGWTools,
# for IMGW-PIB and ČHMÚ): without it the stations are not shown (SPEC 5.8).
STATION_PRODUCER = "imgw"

router = APIRouter(tags=["stations"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Code = Annotated[
    str,
    Path(
        description="Station code as its provider gives it (text).",
        examples=["149190310"],
    ),
]


def require_station_source(registry: PluginRegistry) -> None:
    """Refuse while the producer of the station catalogs is not available.

    Raises
    ------
    SourceStateError
        ``503``: IMGWTools is not installed (``missing_dependency``, reason
        ``source_unavailable``, the fix ``pip install "archiwista[imgw]"``),
        does not fit or failed to load; the stations the index still holds
        are not shown (SPEC 5.8).
    """
    registry.adapter(STATION_PRODUCER)


def station_list(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    filters: StationListFilters,
) -> StationList:
    """Return a page of stations of the filters with the coverage of their series.

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    IndexQueryError
        Unknown store or area, both ``area_id`` and ``bbox``, an invalid
        rectangle, a coverage filter without ``dataset``, a reversed range of
        years, a limit out of range or a cursor of another query.
    """
    page, area, freshness = _station_page(queries, settings, registry, filters)
    return StationList.of(page, area, freshness)


def station_timeline_page(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    filters: StationTimelineListFilters,
) -> StationTimelinePage:
    """Return a page of the stations of a dataset, each variable year by year.

    Each item's series is what ``station_timeline`` gives for the station
    with the same dataset, variables, range and year type: the page's
    stations are labelled together, the years of their series read at once.

    Raises
    ------
    SourceStateError, IndexQueryError
        As ``station_list``.
    """
    page, area, freshness = _station_page(queries, settings, registry, filters)
    return StationTimelinePage.of(page, filters.variable, area, freshness)


def station_datasets(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    query: StationDatasetsQuery,
) -> StationDatasets:
    """Return the datasets with station series in the index (the dataset chip).

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    IndexQueryError
        An unknown store.
    """
    require_station_source(registry)
    freshness = queries.freshness()
    stores = checked_store(query.store, settings, freshness)
    found = queries.station_datasets(query.store, year_types=settings.year_types)
    return StationDatasets.of(found, staleness(freshness, stores))


def station_card(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    code: str,
    lookup: StationLookup,
) -> StationCard:
    """Return a station's card: its catalog entry, its series labelled, their files.

    Each series file is also given on this computer and as mounted on others
    (``paths``), as the file card gives a version's (SPEC 4.6).

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    NotFoundError
        No station of the index has the code (in ``store`` and ``provider``).
    IndexQueryError
        An unknown store, a reversed range of years, or a code of several
        stations without ``store`` and ``provider`` (reason
        ``ambiguous_station``, ``details.stations`` names them).
    """
    require_station_source(registry)
    freshness = queries.freshness()
    checked_store(lookup.store, settings, freshness)
    row = find_station(queries, code, store=lookup.store, provider=lookup.provider)
    found = queries.station_coverage(
        row.store,
        row.provider,
        row.code,
        dataset=lookup.dataset,
        year_type=lookup.year_type,
        years=lookup.year_range(),
        year_types=settings.year_types,
    )
    paths: dict[str, CopyPath] = {}
    for series in found:
        copied = copy_path(settings, row.store, STATION_PRODUCER, series.file)
        if copied is not None:
            paths[series.dataset] = copied
    return StationCard(
        station=StationItem.of(row, found),
        paths=paths,
        **staleness(freshness, {row.store}),
    )


def station_timeline(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    code: str,
    filters: StationTimelineFilters,
) -> StationTimeline:
    """Return the coverage of a station's variables by year (the Timeline).

    Raises
    ------
    SourceStateError, NotFoundError, IndexQueryError
        As ``station_card``.
    """
    require_station_source(registry)
    freshness = queries.freshness()
    checked_store(filters.store, settings, freshness)
    row = find_station(queries, code, store=filters.store, provider=filters.provider)
    found = queries.station_coverage(
        row.store,
        row.provider,
        row.code,
        dataset=filters.dataset,
        year_type=filters.year_type,
        years=filters.year_range(),
        year_types=settings.year_types,
    )
    return StationTimeline.of(
        row, found, filters.variable, staleness(freshness, {row.store})
    )


def station_chart(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    code: str,
    query: StationChartQuery,
) -> StationChart:
    """Return one or two variables of a station's series as a chart (SPEC 6.7).

    The series is the station's in ``query.dataset``, or else the one whose
    series has every variable; its current version in the index is read
    through the producer, the version and each variable's label, in the year
    type of ``query.year_type``, come from the index: the label's runs of
    gaps are the bands and its known span the default range (ADR-045
    erratum 1). The extremes come from the station's series of the dataset's
    half-year characteristics when the index holds one.

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    NotFoundError
        No such station, or no series of ``dataset`` of it.
    IndexQueryError
        An unknown store, a code of several stations, a variable the series
        lacks (reason ``unknown_variable``), variables in several series
        without ``dataset`` (``ambiguous_dataset``), half-year
        characteristics (``half_year_chart``) or a reversed range.
    ConflictError
        ``version`` is not the series' current version in the index (reason
        ``series_version_not_current``).
    UnsupportedError
        The producer does not read the values of a series.
    SourceUnavailableError, ProducerError
        The producer could not read the series.
    """
    adapter = _values_adapter(registry)
    _check_range(query.start, query.end)
    freshness = queries.freshness()
    checked_store(query.store, settings, freshness)
    row = find_station(queries, code, store=query.store, provider=query.provider)
    found = queries.station_coverage(
        row.store,
        row.provider,
        row.code,
        dataset=query.dataset,
        year_type=query.year_type,
        year_types=settings.year_types,
    )
    series, variables = _chart_series(row, found, query)
    if query.version is not None and query.version != series.series_version:
        raise ConflictError(
            message(
                "api.chart_version_not_current",
                version=query.version,
                dataset=series.dataset,
                current=series.series_version,
            ),
            reason="series_version_not_current",
            details={"current": series.series_version},
            hint=message("api.chart_version_hint"),
        )
    return _read_chart(
        queries,
        settings,
        adapter,
        series,
        variables,
        span=(query.start, query.end),
        max_points=query.max_points,
        freshness=staleness(freshness, {row.store}),
    )


def station_comparison(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    query: StationCompareQuery,
) -> StationComparison:
    """Return one variable of 2 to 5 stations' series over one range (SPEC 6.7).

    Each station's series of ``query.dataset`` is labelled in one year type,
    so its facts are those of its card, and read over one range: ``from``
    and ``to``, by default the first and last day of the variable's known
    spans at the stations together (``series_chart.known_span``, a chart's
    default range: ADR-045 erratum 1), so that every chart has the same
    interval and its bands are the gaps its label counts. A station without
    the series or the variable stays, without facts and chart ("brak
    danych", P14). A bound asked beyond the other one's default leaves an
    empty comparison, whose series are not read.

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    NotFoundError
        A station the index does not hold, or none of them has a series of
        ``query.dataset``.
    IndexQueryError
        An unknown store, a reversed range, half-year characteristics
        (``half_year_chart``) or a variable no station's series has
        (``unknown_variable``).
    UnsupportedError
        The producer does not read the values of a series.
    SourceUnavailableError, ProducerError
        The producer could not read a series.
    """
    adapter = _values_adapter(registry)
    _check_range(query.start, query.end)
    freshness = queries.freshness()
    found: list[tuple[StationRow, StationCoverage | None]] = []
    for store, provider, code in query.stations():
        checked_store(store, settings, freshness)
        row = find_station(queries, code, store=store, provider=provider)
        held = queries.station_coverage(
            row.store,
            row.provider,
            row.code,
            dataset=query.dataset,
            year_type=query.year_type,
            year_types=settings.year_types,
        )
        found.append((row, held[0] if held else None))
    series = [item for _, item in found if item is not None]
    if not series:
        raise NotFoundError(message("api.compare_series_none", dataset=query.dataset))
    first = series[0]
    if first.time_unit == "half_year":
        raise IndexQueryError(
            message("api.chart_half_year", dataset=first.dataset),
            reason="half_year_chart",
            details={"option": "dataset"},
        )
    compared = [
        (
            row,
            item,
            None
            if item is None
            else next((v for v in item.variables if v.key == query.variable), None),
        )
        for row, item in found
    ]
    variables = [variable for _, _, variable in compared if variable is not None]
    if not variables:
        allowed = list(
            dict.fromkeys(
                variable.key for item in series for variable in item.variables
            )
        )
        raise IndexQueryError(
            message(
                "api.compare_variable_unknown",
                dataset=first.dataset,
                variable=query.variable,
                allowed=", ".join(allowed),
            ),
            reason="unknown_variable",
            details={"option": "variable", "allowed": allowed},
        )
    span = _compared_range(variables, query)
    fresh = staleness(freshness, {row.store for row, _ in found})
    stations: list[ComparedStation] = []
    for row, item, variable in compared:
        chart: ChartVariable | None = None
        if item is not None and variable is not None:
            chart = (
                ChartVariable(
                    key=variable.key,
                    variable=variable.variable,
                    unit=variable.unit,
                    points=[],
                    gaps=[],
                    markers=[],
                )
                if span is None
                else _read_chart(
                    queries,
                    settings,
                    adapter,
                    item,
                    [variable],
                    span=span,
                    max_points=query.max_points,
                    freshness=fresh,
                ).variables[0]
            )
        stations.append(ComparedStation.of(row, item, variable, chart))
    whole = (
        None
        if span is None
        else series_chart.chart_range(first.time_unit, *span, query.max_points)
    )
    return StationComparison.model_validate(
        {
            "dataset": first.dataset,
            "variable": query.variable,
            "kind": first.kind,
            "time_unit": first.time_unit,
            "year_type": first.year_type,
            "from": None if whole is None else whole.start,
            "to": None if whole is None else whole.end,
            "units": 0 if whole is None else whole.units,
            "interval": 1 if whole is None else whole.interval,
            "stations": stations,
            **fresh,
        }
    )


def _values_adapter(registry: PluginRegistry) -> SeriesValuesAdapter:
    """Return the producer that reads the values of the stations' series.

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    UnsupportedError
        It does not read the values of a series.
    """
    require_station_source(registry)
    adapter = registry.adapter(STATION_PRODUCER)
    if not isinstance(adapter, SeriesValuesAdapter):
        raise UnsupportedError(
            message("api.chart_unsupported", producer=STATION_PRODUCER)
        )
    return adapter


def _check_range(start: date | None, end: date | None) -> None:
    """Refuse a range that ends before it starts (``IndexQueryError``)."""
    if start is not None and end is not None and start > end:
        raise IndexQueryError(message("api.chart_range_reversed", start=start, end=end))


def _compared_range(
    variables: Sequence[CoverageVariable], query: StationCompareQuery
) -> tuple[date, date] | None:
    """Return the range of a comparison: ``from`` and ``to``, else the known span.

    A bound left out is the first or last day of the variable's known spans
    at the stations together (``series_chart.known_span``), as a chart's
    default range. ``None`` when a bound is neither asked nor known, or one
    asked lies beyond the other one's default: the comparison is empty.
    """
    known = series_chart.known_span(variables)
    start = query.start if query.start is not None or known is None else known[0]
    end = query.end if query.end is not None or known is None else known[1]
    if start is None or end is None or start > end:
        return None
    return start, end


def _read_chart(
    queries: IndexQueries,
    settings: AppSettings,
    adapter: SeriesValuesAdapter,
    series: StationCoverage,
    variables: Sequence[CoverageVariable],
    *,
    span: tuple[date | None, date | None],
    max_points: int,
    freshness: Mapping[str, Any],
) -> StationChart:
    """Read a station's series through the producer and return its chart.

    The extremes come from the station's series of the dataset's half-year
    characteristics when the index holds one.

    Raises
    ------
    NotFoundError
        The station's store has no IMGWTools directory configured.
    SourceUnavailableError, ProducerError
        The producer could not read the series.
    """
    config = settings.store(series.store)
    root = None if config is None else config.roots().get(STATION_PRODUCER)
    if root is None:
        raise NotFoundError(message("api.store_not_configured", store=series.store))
    characteristics = adapter.characteristics_dataset(series.dataset)
    held = (
        ()
        if characteristics is None
        else queries.station_coverage(
            series.store,
            series.provider,
            series.code,
            dataset=characteristics,
            year_types=settings.year_types,
        )
    )
    start, end = span
    return series_chart.station_chart(
        adapter,
        FilePath(root),
        series,
        variables,
        start=start,
        end=end,
        max_points=max_points,
        characteristics=held[0] if held else None,
        freshness=freshness,
    )


def station_map(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    filters: StationMapFilters,
) -> StationMapView:
    """Return the located stations of a map view, or their grid above the limit.

    With ``dataset`` each point carries the state and label of each variable
    of its series (its colour and tooltip).

    Raises
    ------
    SourceStateError
        The source of the stations is not available.
    IndexQueryError
        An unknown store or area, an invalid view, or the refusals of the
        filters as in ``station_list``.
    """
    require_station_source(registry)
    freshness = queries.freshness()
    stores = checked_store(filters.store, settings, freshness)
    record = _area(queries, filters.area_id)
    query = filters.station_query(
        year_types=settings.year_types,
        area=None if record is None else record.geometry,
        bbox=filters.bbox_values(),
        boundary=filters.boundary,
        labels=filters.dataset is not None,
    )
    found = queries.station_map(
        query, limit=filters.limit, grid_columns=filters.grid_columns
    )
    return StationMapView.of(found, staleness(freshness, stores))


def find_station(
    queries: IndexQueries, code: str, *, store: str | None, provider: str | None
) -> StationRow:
    """Return the one station a code means in ``store`` and ``provider``.

    Raises
    ------
    NotFoundError
        No such station.
    IndexQueryError
        The code means several stations (reason ``ambiguous_station``).
    """
    page = queries.stations(
        StationQuery(store=store, provider=provider, code=code, limit=MAX_PAGE_LIMIT)
    )
    if not page.items:
        raise NotFoundError(message("api.station_unknown", code=code))
    if len(page.items) > 1:
        named = [{"store": row.store, "provider": row.provider} for row in page.items]
        stations = ", ".join(f"{item['store']} {item['provider']}" for item in named)
        raise IndexQueryError(
            message("api.station_ambiguous", code=code, stations=stations),
            reason="ambiguous_station",
            details={"stations": named},
            hint=message("api.station_ambiguous_hint"),
        )
    return page.items[0]


def _chart_series(
    row: StationRow, found: Sequence[StationCoverage], query: StationChartQuery
) -> tuple[StationCoverage, list[CoverageVariable]]:
    """Return the series a chart reads and its variables, in the order asked.

    Raises
    ------
    NotFoundError
        The station has no series of ``query.dataset``.
    IndexQueryError
        As ``station_chart``.
    """
    if query.dataset is not None and not found:
        raise NotFoundError(
            message("api.station_series_none", code=row.code, dataset=query.dataset)
        )
    keyed = [
        (series, {item.key: item for item in series.variables}) for series in found
    ]
    held = [
        (series, variables)
        for series, variables in keyed
        if all(name in variables for name in query.variable)
    ]
    names = ", ".join(query.variable)
    if query.dataset is not None and not held:
        series, variables = keyed[0]
        missing = next(name for name in query.variable if name not in variables)
        raise IndexQueryError(
            message(
                "api.chart_variable_unknown",
                dataset=series.dataset,
                code=row.code,
                variable=missing,
                allowed=", ".join(variables),
            ),
            reason="unknown_variable",
            details={"option": "variable", "allowed": list(variables)},
        )
    if not held:
        raise IndexQueryError(
            message("api.chart_variables_unknown", code=row.code, variables=names),
            reason="unknown_variable",
            details={
                "option": "variable",
                "allowed": sorted({key for _, variables in keyed for key in variables}),
            },
        )
    if len(held) > 1:
        datasets = [series.dataset for series, _ in held]
        raise IndexQueryError(
            message(
                "api.chart_dataset_ambiguous",
                code=row.code,
                variables=names,
                datasets=", ".join(datasets),
            ),
            reason="ambiguous_dataset",
            details={"option": "dataset", "allowed": datasets},
            hint=message("api.chart_dataset_hint"),
        )
    series, variables = held[0]
    if series.time_unit == "half_year":
        raise IndexQueryError(
            message("api.chart_half_year", dataset=series.dataset),
            reason="half_year_chart",
            details={"option": "dataset"},
        )
    return series, [variables[name] for name in query.variable]


def _station_page(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    filters: StationListFilters,
) -> tuple[StationPage, AreaRef | None, dict[str, Any]]:
    """Return a page of stations with their coverage, its area and staleness.

    Raises
    ------
    SourceStateError, IndexQueryError
        As ``station_list``.
    """
    require_station_source(registry)
    freshness = queries.freshness()
    stores = checked_store(filters.store, settings, freshness)
    if filters.area_id is not None and filters.bbox is not None:
        raise IndexQueryError(message("api.area_and_bbox"))
    record = _area(queries, filters.area_id)
    area = None if record is None else record.geometry
    bbox = filters.bbox_values()
    if bbox is not None:
        area = _rectangle(registry, bbox, filters.bbox_crs)
    query = filters.station_query(
        year_types=settings.year_types,
        area=area,
        boundary=filters.boundary,
        location=filters.location,
        limit=filters.limit,
        cursor=filters.cursor,
        q=filters.q,
        sort=filters.sort,
    )
    page = queries.stations(query)
    reference = None if record is None else AreaRef.of(record)
    return page, reference, staleness(freshness, stores)


def _area(queries: IndexQueries, area_id: str | None) -> AreaRecord | None:
    """Return the kept area of ``area_id``.

    Raises
    ------
    IndexQueryError
        No area has the id.
    """
    if area_id is None:
        return None
    record = queries.area(area_id)
    if record is None:
        raise IndexQueryError(message("api.area_unknown", area=area_id))
    return record


def _rectangle(registry: PluginRegistry, bbox: BBox, crs: str) -> GeoJSONGeometry:
    """Return a rectangle as a WGS84 polygon, moved by a producer from another CRS.

    Raises
    ------
    IndexQueryError
        A reversed rectangle, or one outside WGS84.
    SourceStateError
        A rectangle in another CRS and no producer with coordinate operations.
    ProducerError
        The producer has no pinned operation for ``crs``.
    """
    if is_wgs84(crs):
        return box_geometry(require_wgs84_bbox(bbox))
    return bbox_area(registry, bbox, crs).geometry


@router.get(
    "/stations", response_model=StationList, responses=problem_responses(400, 503)
)
def list_stations(
    filters: Annotated[StationListFilters, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationList:
    """List stations along rivers or by name, each variable of their series labelled.

    `sort=river` (the default) follows the rivers as the Catalog does (SPEC
    6.8): the hydrographic code, so a tributary follows its river, then the
    provider's order on the river, then the name; `sort=name` by name. `q`
    finds a station whose name or river contains the text (case-folded; no
    character is a wildcard) or whose code begins with it. Both take part in
    `next_cursor`.

    In an area (`area_id`, or `bbox` with `bbox_crs`) a station is in it, or
    on its boundary when it is closer to it than its location uncertainty
    (`location.on_boundary`; `boundary=false` leaves them out). The stations
    without a location are never placed in an area: `counts.unlocated`
    counts them after the other filters, `location=none` lists them. The
    coverage filters (`coverage`, `min_complete_years`) need `dataset`;
    `counts.hidden` says how many stations they hide. `503` while the source
    of the stations (IMGWTools) is not available.
    """
    return station_list(queries, settings.get(), registry, filters)


@router.get(
    "/stations/datasets",
    response_model=StationDatasets,
    responses=problem_responses(400, 503),
)
def list_station_datasets(
    query: Annotated[StationDatasetsQuery, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationDatasets:
    """List the datasets with station series: their variables and default range.

    Each dataset of each store with the producer's name of its segment, its
    family, time unit and default year type, R by default, the label of its
    current series version and the distinct variables of its stations'
    series (`variables`, the first being the default colour of the map's
    points). `503` while the source of the stations (IMGWTools) is not
    available.
    """
    return station_datasets(queries, settings.get(), registry, query)


@router.get(
    "/stations/timeline",
    response_model=StationTimelinePage,
    responses=problem_responses(400, 503),
)
def list_stations_timeline(
    filters: Annotated[StationTimelineListFilters, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationTimelinePage:
    """Page the stations of a dataset, each variable year by year (the Timeline).

    The filters, order and cursor of `GET /stations`, with `dataset`
    required. Each item is a station with its series as `GET
    /stations/{code}/coverage` gives it for the same `dataset`, `variable`,
    `years` and `year_type`: every year of R with its units, the known ones
    and those with a value, and its cell (`full`, `fraction`, `none`,
    `unknown`). `variable` (repeatable) keeps the stations with a value of
    each variable, and only their years. The years of the whole page are read
    from the index at once, never from a series file. `503` while the source
    of the stations (IMGWTools) is not available.
    """
    return station_timeline_page(queries, settings.get(), registry, filters)


@router.get(
    "/stations/compare",
    response_model=StationComparison,
    responses=problem_responses(400, 404, 503),
)
def compare_stations(
    query: Annotated[StationCompareQuery, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationComparison:
    """Compare 2 to 5 stations: one variable of one dataset over one range.

    Each `station` is `<store>/<provider>/<code>`. The range is `from`–`to`,
    by default the first and last known day of the variable at the stations
    together (as the default range of a chart), the same for every station,
    and so is the interval of a simplified chart (`max_points`). Each station
    gives the label and facts of the variable as its card does in the year
    type (`coverage`) and its points, its label's gaps and markers (`chart`),
    read from its series file through the producer; a station without the
    series or the variable has `null` for both ("brak danych"). `400`
    (reason `unknown_variable`) when no station's series has the variable,
    `404` when none of them has a series of the dataset; `503` while the
    source of the stations (IMGWTools) is not available.
    """
    return station_comparison(queries, settings.get(), registry, query)


@router.get(
    "/stations/{code}",
    response_model=StationCard,
    responses=problem_responses(400, 404, 503),
)
def get_station(
    code: _Code,
    lookup: Annotated[StationLookup, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationCard:
    """Return a station's card: metadata, location and each series labelled.

    `paths` gives each series file on this computer and as mounted on others
    (path aliases). A code that several stations share (two stores, two
    providers) is `400` (reason `ambiguous_station`) until `store` and
    `provider` name one.
    """
    return station_card(queries, settings.get(), registry, code, lookup)


@router.get(
    "/stations/{code}/coverage",
    response_model=StationTimeline,
    responses=problem_responses(400, 404, 503),
)
def get_station_coverage(
    code: _Code,
    filters: Annotated[StationTimelineFilters, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationTimeline:
    """Return every year of R of each variable: units, known, with a value.

    A year that is not wholly known is `unknown`, never a gap. Changing the
    range or the year type reads no series.
    """
    return station_timeline(queries, settings.get(), registry, code, filters)


@router.get(
    "/stations/{code}/series",
    response_model=StationChart,
    responses=problem_responses(400, 404, 409, 503),
)
def get_station_series(
    code: _Code,
    query: Annotated[StationChartQuery, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationChart:
    """Return one or two variables of a station's series as a chart (display only).

    A range (`from`, `to`; by default the variables' known span) of at most
    `max_points` units gives each unit's value; a longer one gives the least,
    mean and greatest value of each interval of `interval` units (`null`
    without a value: never interpolated). `gaps` are the gaps of each
    variable's label (as on the card in the same `year_type`) cut at the
    range's ends; accumulated sums and the extremes the provider published in
    its half-year characteristics are `markers`. The values are read from the
    series file through the producer; `version`, when given, must be the
    current one in the index (`409` otherwise).
    """
    return station_chart(queries, settings.get(), registry, code, query)


@router.get(
    "/map/stations",
    response_model=StationMapView,
    responses=problem_responses(400, 503),
    tags=["map"],
)
def list_map_stations(
    filters: Annotated[StationMapFilters, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationMapView:
    """List the located stations of a map view (WGS84), or their grid.

    Above `limit` the answer is `aggregated`: `cells` count stations.
    Stations without a location are never drawn: `counts.unlocated` counts
    them. With `dataset` each point has the state and label of each variable.
    """
    return station_map(queries, settings.get(), registry, filters)
