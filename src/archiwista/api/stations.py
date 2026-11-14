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
number the years as the person remembers for the data's family (``year_types``
of their preferences, P15), a list of both families as for hydro data; a
series file's copy path also goes through the person's own path aliases.
Everything is read from the index, never from a series file, except the
values of a chart or a comparison, which the producer reads
(``SeriesValuesAdapter``); and only while the source of the stations is
available: else ``503`` (SPEC 5.8).
``archiwista stations`` calls the same functions without HTTP, with the
local owner's preferences.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path as FilePath
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Path, Query

from archiwista import attribution
from archiwista.api.dependencies import (
    index_queries,
    plugin_registry,
    principal_preferences,
    settings_service,
)
from archiwista.api.errors import problem_responses
from archiwista.api.models import AreaRef, CopyPath, Preferences, staleness
from archiwista.api.models_handoff import StationHandoff, StationHandoffQuery
from archiwista.api.models_stations import (
    AnnualPoint,
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
from archiwista.services import series_chart
from archiwista.services import station_handoff as station_handoff_service
from archiwista.sources import GeoJSONGeometry, SeriesValuesAdapter
from archiwista.sources.registry import PluginRegistry

# The producer whose plugin keeps the station catalogs and series (Obserwator,
# for IMGW-PIB and ČHMÚ): without it the stations are not shown (SPEC 5.8).
STATION_PRODUCER = "obserwator"

router = APIRouter(tags=["stations"])

_Preferences = Annotated[Preferences, Depends(principal_preferences)]
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
        ``503``: Obserwator is not installed (``missing_dependency``, reason
        ``source_unavailable``, the fix ``pip install "archiwista[obserwator]"``),
        does not fit or failed to load; the stations the index still holds
        are not shown (SPEC 5.8).
    """
    registry.adapter(STATION_PRODUCER)


def station_list(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
    page, area, freshness = _station_page(
        queries, settings, preferences, registry, filters
    )
    return StationList.of(page, area, freshness)


def station_timeline_page(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
    page, area, freshness = _station_page(
        queries, settings, preferences, registry, filters
    )
    return StationTimelinePage.of(page, filters.variable, area, freshness)


def station_datasets(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
    found = queries.station_datasets(query.store, year_types=preferences.year_types)
    return StationDatasets.of(found, staleness(freshness, stores))


def station_card(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    registry: PluginRegistry,
    code: str,
    lookup: StationLookup,
) -> StationCard:
    """Return a station's card: its catalog entry, its series labelled, their files.

    Each series file is also given on this computer, as mounted on others
    and on the person's own (``paths``), as the file card gives a version's
    (SPEC 4.6); ``charts`` are the charts of ``station_chart`` its series
    give, when the producer reads their values.

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
        year_types=preferences.year_types,
    )
    paths: dict[str, CopyPath] = {}
    for series in found:
        copied = copy_path(
            settings, preferences, row.store, STATION_PRODUCER, series.file
        )
        if copied is not None:
            paths[series.dataset] = copied
    adapter = registry.adapter(STATION_PRODUCER)
    charts = (
        series_chart.chart_choices(found, adapter.statistics_of)
        if isinstance(adapter, SeriesValuesAdapter)
        else []
    )
    lines = attribution.station(
        row.provider, row.catalog_attribution, positions=row.point is not None
    )
    return StationCard(
        station=StationItem.of(row, found),
        paths=paths,
        charts=charts,
        **lines.fields(),
        **staleness(freshness, {row.store}),
    )


def station_timeline(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
        year_types=preferences.year_types,
    )
    return StationTimeline.of(
        row, found, filters.variable, staleness(freshness, {row.store})
    )


def station_chart(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    registry: PluginRegistry,
    code: str,
    query: StationChartQuery,
) -> StationChart:
    """Return one or two variables of a station's series as a chart (SPEC 6.7).

    The series is the station's in ``query.dataset``, or else the one whose
    series has every variable (a series of days before one of monthly
    statistics); its current version in the index is read through the
    producer, the version and each variable's label, in the year type of
    ``query.year_type``, come from the index: the label's runs of gaps are
    the bands and its known span the default range (ADR-045 erratum 1). A
    variable of monthly statistics is drawn from its minimum, mean and
    maximum. The extremes come from the station's series of the dataset's
    half-year characteristics when the index holds one. An annual chart
    (``resolution=annual``) reads the station's half-year characteristics
    and gives each hydrological year's maximum and minimum found in them
    (A-ADR-051).

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
        characteristics at their units (``half_year_chart``), an annual chart
        of a station without them (``no_annual_source``) or in calendar years
        (``annual_year_type``), or a reversed range.
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
    annual = query.resolution == "annual"
    if annual and query.year_type == "calendar":
        raise IndexQueryError(
            message("api.chart_annual_year_type"),
            reason="annual_year_type",
            details={"option": "year_type", "allowed": ["hydrological"]},
        )
    freshness = queries.freshness()
    checked_store(query.store, settings, freshness)
    row = find_station(queries, code, store=query.store, provider=query.provider)
    found = queries.station_coverage(
        row.store,
        row.provider,
        row.code,
        dataset=query.dataset,
        year_type=query.year_type,
        year_types=preferences.year_types,
    )
    fresh = staleness(freshness, {row.store})
    if annual:
        halves, sources = _annual_series(row, found, query, adapter)
        _check_version(query.version, halves)
        return series_chart.annual_chart(
            adapter,
            _producer_root(settings, halves),
            halves,
            sources,
            start=query.start,
            end=query.end,
            freshness=fresh,
        )
    series, variables = _chart_series(row, found, query, adapter)
    _check_version(query.version, series)
    return _read_chart(
        queries,
        settings,
        preferences,
        adapter,
        series,
        variables,
        span=(query.start, query.end),
        max_points=query.max_points,
        freshness=fresh,
    )


def station_handoff(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    registry: PluginRegistry,
    code: str,
    query: StationHandoffQuery,
) -> StationHandoff:
    """Return a variable of a station's series as a hand-off to Hydrolog (A-ADR-052).

    ``resolution=annual``: the annual maxima of the station's annual chart
    (A-ADR-051), a year missing one of its halves left out. Otherwise every
    day of the variable's series of days over the range (by default its known
    span), read through the producer as the chart reads it, without the
    chart's simplification.

    Raises
    ------
    IndexQueryError
        As ``station_chart``, and a series that is not of days
        (``no_daily_series``).
    NotFoundError, ConflictError, UnsupportedError, SourceStateError
        As ``station_chart``.
    SourceUnavailableError, ProducerError
        The producer could not read the series.
    """
    chart_query = query.chart_query()
    if query.resolution == "annual":
        chart = station_chart(
            queries, settings, preferences, registry, code, chart_query
        )
        row = find_station(queries, code, store=query.store, provider=query.provider)
        (variable,) = chart.variables
        payload, left_out = station_handoff_service.annual_payload(
            row, query.variable, variable.unit, cast(list[AnnualPoint], variable.points)
        )
        halves = queries.station_coverage(
            row.store, row.provider, row.code, dataset=chart.dataset
        )
        return station_handoff_service.handoff(
            row, halves[0], payload, annual=True, left_out=left_out
        )
    adapter = _values_adapter(registry)
    _check_range(query.start, query.end)
    checked_store(query.store, settings, queries.freshness())
    row = find_station(queries, code, store=query.store, provider=query.provider)
    found = queries.station_coverage(
        row.store,
        row.provider,
        row.code,
        dataset=query.dataset,
        year_types=preferences.year_types,
    )
    series, (source,) = _chart_series(row, found, chart_query, adapter)
    if series.time_unit != "day":
        raise IndexQueryError(
            message(
                "api.handoff_no_daily_series", dataset=series.dataset, code=row.code
            ),
            reason="no_daily_series",
            details={"option": "resolution", "allowed": ["unit", "annual"]},
        )
    known = series_chart.known_span([source.line])
    start = query.start or (known[0] if known else None)
    end = query.end or (known[1] if known else None)
    if start is None or end is None:
        raise NotFoundError(
            message("api.station_series_none", code=row.code, dataset=series.dataset)
        )
    values = adapter.read_values(
        _producer_root(settings, series),
        FilePath(series.series_version),
        station=series.code,
        variables=[source.line.variable],
        start=start,
        end=end,
    )
    payload = station_handoff_service.daily_payload(
        row, source.line.variable, source.line.unit, values, start, end
    )
    return station_handoff_service.handoff(row, series, payload, annual=False)


def station_comparison(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
            year_types=preferences.year_types,
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
                    preferences,
                    adapter,
                    item,
                    [series_chart.ChartSource.own(variable)],
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
    lines = attribution.merge(
        attribution.station(
            row.provider, row.catalog_attribution, positions=row.point is not None
        )
        for row, _ in found
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
            **lines.fields(),
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


def _check_version(version: str | None, series: StationCoverage) -> None:
    """Refuse a chart of another version than the series' current one.

    Raises
    ------
    ConflictError
        ``version`` is not the series' current version in the index (reason
        ``series_version_not_current``).
    """
    if version is not None and version != series.series_version:
        raise ConflictError(
            message(
                "api.chart_version_not_current",
                version=version,
                dataset=series.dataset,
                current=series.series_version,
            ),
            reason="series_version_not_current",
            details={"current": series.series_version},
            hint=message("api.chart_version_hint"),
        )


def _producer_root(settings: AppSettings, series: StationCoverage) -> FilePath:
    """Return the Obserwator directory of a series' store.

    Raises
    ------
    NotFoundError
        The station's store has no Obserwator directory configured.
    """
    config = settings.store(series.store)
    root = None if config is None else config.roots().get(STATION_PRODUCER)
    if root is None:
        raise NotFoundError(message("api.store_not_configured", store=series.store))
    return FilePath(root)


def _read_chart(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    adapter: SeriesValuesAdapter,
    series: StationCoverage,
    variables: Sequence[series_chart.ChartSource],
    *,
    span: tuple[date | None, date | None],
    max_points: int,
    freshness: Mapping[str, Any],
) -> StationChart:
    """Read a station's series through the producer and return its chart.

    The extremes of a variable of days come from the station's series of the
    dataset's half-year characteristics when the index holds one.

    Raises
    ------
    NotFoundError
        The station's store has no Obserwator directory configured.
    SourceUnavailableError, ProducerError
        The producer could not read the series.
    """
    root = _producer_root(settings, series)
    characteristics = (
        adapter.characteristics_dataset(series.dataset)
        if any(item.own_value for item in variables)
        else None
    )
    held = (
        ()
        if characteristics is None
        else queries.station_coverage(
            series.store,
            series.provider,
            series.code,
            dataset=characteristics,
            year_types=preferences.year_types,
        )
    )
    start, end = span
    return series_chart.station_chart(
        adapter,
        root,
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
    preferences: Preferences,
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
        year_types=preferences.year_types,
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
    row: StationRow,
    found: Sequence[StationCoverage],
    query: StationChartQuery,
    adapter: SeriesValuesAdapter,
) -> tuple[StationCoverage, list[series_chart.ChartSource]]:
    """Return the series a chart reads and its variables, in the order asked.

    A series offers its variables as a chart takes them: a series of days
    its own, one of monthly statistics the variables they describe;
    half-year characteristics offer both their keys and the variables they
    describe, only to be refused. Without ``dataset`` a series of days with
    every variable comes before one of monthly statistics.

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
    offered = [_offered(series, adapter) for series in found]
    held = [item for item in offered if all(name in item[2] for name in query.variable)]
    names = ", ".join(query.variable)
    if query.dataset is not None and not held:
        series, _, allowed = offered[0]
        missing = next(name for name in query.variable if name not in allowed)
        raise IndexQueryError(
            message(
                "api.chart_variable_unknown",
                dataset=series.dataset,
                code=row.code,
                variable=missing,
                allowed=", ".join(allowed),
            ),
            reason="unknown_variable",
            details={"option": "variable", "allowed": allowed},
        )
    if not held:
        raise IndexQueryError(
            message("api.chart_variables_unknown", code=row.code, variables=names),
            reason="unknown_variable",
            details={
                "option": "variable",
                "allowed": sorted(
                    {name for _, _, allowed in offered for name in allowed}
                ),
            },
        )
    first = min(series_chart.CHART_ORDER[series.time_unit] for series, _, _ in held)
    held = [
        item for item in held if series_chart.CHART_ORDER[item[0].time_unit] == first
    ]
    if len(held) > 1:
        datasets = [series.dataset for series, _, _ in held]
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
    series, sources, _ = held[0]
    if series.time_unit == "half_year":
        raise IndexQueryError(
            message("api.chart_half_year", dataset=series.dataset),
            reason="half_year_chart",
            details={"option": "dataset"},
            hint=message("api.chart_half_year_hint"),
        )
    return series, [sources[name] for name in query.variable]


def _offered(
    series: StationCoverage, adapter: SeriesValuesAdapter
) -> tuple[StationCoverage, dict[str, series_chart.ChartSource], list[str]]:
    """Return a series, the variables a chart of its units draws and their names.

    The names of half-year characteristics are their keys and the variables
    they describe, none of which a chart of their units draws.
    """
    statistics = adapter.statistics_of(series.dataset)
    sources = series_chart.unit_sources(series, statistics)
    names = list(sources)
    if series.time_unit == "half_year":
        described = series_chart.annual_sources(series, statistics)
        names = list(
            dict.fromkeys([*described, *(item.key for item in series.variables)])
        )
    return series, sources, names


def _annual_series(
    row: StationRow,
    found: Sequence[StationCoverage],
    query: StationChartQuery,
    adapter: SeriesValuesAdapter,
) -> tuple[StationCoverage, list[series_chart.AnnualSource]]:
    """Return the half-year characteristics of an annual chart and its variables.

    The station's series of half-year characteristics (of ``query.dataset``)
    with every variable asked; by default each variable with a value, in
    the order of the series index.

    Raises
    ------
    IndexQueryError
        The station has no half-year characteristics (of ``query.dataset``;
        reason ``no_annual_source``), they do not describe a variable
        (``unknown_variable``) or several series of them do
        (``ambiguous_dataset``).
    """
    offered = [
        (
            series,
            series_chart.annual_sources(series, adapter.statistics_of(series.dataset)),
        )
        for series in found
        if series.time_unit == "half_year"
    ]
    if not offered:
        raise IndexQueryError(
            message(
                "api.chart_no_annual_source",
                code=row.code,
                datasets=", ".join(series.dataset for series in found) or "—",
            ),
            reason="no_annual_source",
            details={
                "option": "resolution" if query.dataset is None else "dataset",
                "allowed": [series.dataset for series in found],
            },
        )
    held = [item for item in offered if all(name in item[1] for name in query.variable)]
    if not held:
        series, sources = offered[0]
        missing = next(name for name in query.variable if name not in sources)
        raise IndexQueryError(
            message(
                "api.chart_variable_unknown",
                dataset=series.dataset,
                code=row.code,
                variable=missing,
                allowed=", ".join(sources),
            ),
            reason="unknown_variable",
            details={"option": "variable", "allowed": list(sources)},
        )
    if len(held) > 1:
        datasets = [series.dataset for series, _ in held]
        raise IndexQueryError(
            message(
                "api.chart_dataset_ambiguous",
                code=row.code,
                variables=", ".join(query.variable or held[0][1]),
                datasets=", ".join(datasets),
            ),
            reason="ambiguous_dataset",
            details={"option": "dataset", "allowed": datasets},
            hint=message("api.chart_dataset_hint"),
        )
    series, sources = held[0]
    names = query.variable or [
        name
        for name, source in sources.items()
        if any(label.first is not None for label in source.labels)
    ]
    return series, [sources[name] for name in names]


def _station_page(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
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
        year_types=preferences.year_types,
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
    preferences: _Preferences,
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
    of the stations (Obserwator) is not available.
    """
    return station_list(queries, settings.get(), preferences, registry, filters)


@router.get(
    "/stations/datasets",
    response_model=StationDatasets,
    responses=problem_responses(400, 503),
)
def list_station_datasets(
    query: Annotated[StationDatasetsQuery, Query()],
    preferences: _Preferences,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationDatasets:
    """List the datasets with station series: their variables and default range.

    Each dataset of each store with the producer's name of its segment, its
    family, time unit and year type (the session's own for its family), R by
    default, the label of its current series version and the distinct
    variables of its stations' series (`variables`, the first being the
    default colour of the map's points). `503` while the source of the
    stations (Obserwator) is not available.
    """
    return station_datasets(queries, settings.get(), preferences, registry, query)


@router.get(
    "/stations/timeline",
    response_model=StationTimelinePage,
    responses=problem_responses(400, 503),
)
def list_stations_timeline(
    filters: Annotated[StationTimelineListFilters, Query()],
    preferences: _Preferences,
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
    of the stations (Obserwator) is not available.
    """
    return station_timeline_page(
        queries, settings.get(), preferences, registry, filters
    )


@router.get(
    "/stations/compare",
    response_model=StationComparison,
    responses=problem_responses(400, 404, 503),
)
def compare_stations(
    query: Annotated[StationCompareQuery, Query()],
    preferences: _Preferences,
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
    source of the stations (Obserwator) is not available.
    """
    return station_comparison(queries, settings.get(), preferences, registry, query)


@router.get(
    "/stations/{code}",
    response_model=StationCard,
    responses=problem_responses(400, 404, 503),
)
def get_station(
    code: _Code,
    lookup: Annotated[StationLookup, Query()],
    preferences: _Preferences,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationCard:
    """Return a station's card: metadata, location and each series labelled.

    `paths` gives each series file on this computer, as mounted on others
    (path aliases) and on the person's own computer (`personal`). A code
    that several stations share (two stores, two providers) is `400`
    (reason `ambiguous_station`) until `store` and `provider` name one.
    """
    return station_card(queries, settings.get(), preferences, registry, code, lookup)


@router.get(
    "/stations/{code}/coverage",
    response_model=StationTimeline,
    responses=problem_responses(400, 404, 503),
)
def get_station_coverage(
    code: _Code,
    filters: Annotated[StationTimelineFilters, Query()],
    preferences: _Preferences,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationTimeline:
    """Return every year of R of each variable: units, known, with a value.

    A year that is not wholly known is `unknown`, never a gap. Changing the
    range or the year type reads no series.
    """
    return station_timeline(
        queries, settings.get(), preferences, registry, code, filters
    )


@router.get(
    "/stations/{code}/series",
    response_model=StationChart,
    responses=problem_responses(400, 404, 409, 503),
)
def get_station_series(
    code: _Code,
    query: Annotated[StationChartQuery, Query()],
    preferences: _Preferences,
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
    return station_chart(queries, settings.get(), preferences, registry, code, query)


@router.get(
    "/stations/{code}/handoff",
    response_model=StationHandoff,
    responses=problem_responses(400, 404, 409, 503),
)
def get_station_handoff(
    code: _Code,
    query: Annotated[StationHandoffQuery, Query()],
    preferences: _Preferences,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationHandoff:
    """Return a variable of a station's series as a hand-off to Hydrolog (A-ADR-052).

    A `nogat-handoff/1` document around a `hydrolog-series/1` payload, which
    Hydrolog's „Statystyka przepływów” opens with „Wczytaj z Archiwisty”: every
    day of the variable's series of days over the range (`null` for a day
    without a value), or with `resolution=annual` the annual maxima Archiwista
    finds in the half-year characteristics, the years missing a half left out
    and named in `provenance.series.left_out`.
    """
    return station_handoff(queries, settings.get(), preferences, registry, code, query)


@router.get(
    "/map/stations",
    response_model=StationMapView,
    responses=problem_responses(400, 503),
    tags=["map"],
)
def list_map_stations(
    filters: Annotated[StationMapFilters, Query()],
    preferences: _Preferences,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> StationMapView:
    """List the located stations of a map view (WGS84), or their grid.

    Above `limit` the answer is `aggregated`: `cells` count stations.
    Stations without a location are never drawn: `counts.unlocated` counts
    them. With `dataset` each point has the state and label of each variable;
    a station without a series of it is drawn too, with no data of it, so a
    station catalog downloaded alone shows its stations.
    """
    return station_map(queries, settings.get(), preferences, registry, filters)
