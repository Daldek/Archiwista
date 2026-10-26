"""Stations of the producers' station catalogs over HTTP (SPEC 9.2, 6.7, 6.8).

``GET /stations`` pages the stations of the filters by name, in an area
(``area_id``, or ``bbox`` with ``bbox_crs``) with the stations on its
boundary, each variable of each series labelled (P16), with the counts of
the location groups: the stations without a location are counted after the
attribute and coverage filters and never placed in an area (SPEC 4.3 point
3). ``GET /stations/datasets`` names the datasets with station series (the
dataset chip of the map), ``GET /stations/{code}`` is a station's card,
``GET /stations/{code}/coverage`` its variables year by year (the Timeline)
and ``GET /map/stations`` the located stations of a map view or their grid.
The fixed paths are declared before ``/stations/{code}``, which would else
read them as a code. Without ``year_type`` the labels number the years as the
settings remember for the data's family (``year_types``, P15), a list of both
families as for hydro data. Everything is read from the index, never from a
series file, and only while the source of the stations is available: else
``503`` (SPEC 5.8). ``archiwista stations`` calls the same functions without
HTTP.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models import AreaRef, staleness
from archiwista.api.models_stations import (
    StationCard,
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
)
from archiwista.api.slots import bbox_area, checked_store
from archiwista.auth import Principal
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import IndexQueryError, NotFoundError
from archiwista.index import (
    MAX_PAGE_LIMIT,
    AreaRecord,
    BBox,
    IndexQueries,
    StationQuery,
    StationRow,
)
from archiwista.index.geometry import box_geometry, is_wgs84, require_wgs84_bbox
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.sources import GeoJSONGeometry
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
    )
    page = queries.stations(query)
    reference = None if record is None else AreaRef.of(record)
    return StationList.of(page, reference, staleness(freshness, stores))


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
    """Return a station's card: its catalog entry and its series labelled.

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
    return StationCard(
        station=StationItem.of(row, found), **staleness(freshness, {row.store})
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
    """List stations by name with every variable of their series labelled.

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

    A code that several stations share (two stores, two providers) is `400`
    (reason `ambiguous_station`) until `store` and `provider` name one.
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
