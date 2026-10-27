"""Catalog, search and file cards over HTTP (SPEC 9.2, 6.6, 6.8).

``GET /slots`` pages the catalog with the filters of the interface, an area
(``area_id`` or ``bbox`` with ``bbox_crs``), ``limit`` up to 200 and an
opaque ``cursor``; ``GET /products`` lists what the index holds; the file
card (``/stores/{store}/slots/{slot}``), a version with its raw sidecar and
copy path (``/stores/{store}/versions/{version}``, ``…/sidecar``) and the
files of one producer request (``/requests/{parent_request}``) answer from the
index too. Routes only translate: ``IndexQueries`` reads and filters, also by
the projects the principal sees; copy paths also go through the principal's
own path aliases (``CopyPath.personal``). ``archiwista search`` and
``archiwista entry`` (step 12) call ``search_slots`` and ``slot_card``.
"""

from collections.abc import Collection
from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends, Path, Query

from archiwista.api.dependencies import (
    index_queries,
    plugin_registry,
    principal_preferences,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import problem_responses
from archiwista.api.models import (
    WGS84,
    CatalogFilters,
    CatalogPage,
    CopyPath,
    Preferences,
    Product,
    ProductList,
    RequestFile,
    RequestFiles,
    SlotCard,
    VersionCard,
    staleness,
)
from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import AppSettings, SettingsService
from archiwista.doctor import REQUIRED_PRODUCERS
from archiwista.errors import (
    IndexQueryError,
    NotFoundError,
    SourceStateError,
    SourceUnavailableError,
)
from archiwista.index import AreaFilter, BBox, IndexQueries, StoreFreshness
from archiwista.index.geometry import box_geometry, require_wgs84_bbox
from archiwista.messages import message
from archiwista.paths import indexed_path
from archiwista.security import current_principal
from archiwista.services import issue_problem
from archiwista.sources import GeoAdapter, SourceState
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["catalog"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Preferences = Annotated[Preferences, Depends(principal_preferences)]
_Store = Annotated[str, Path(description="Store id.", examples=["zespol"])]
# Points per edge when a projected rectangle is turned into WGS84.
_EDGE_POINTS = 16
# Only whether a version exists: no project's pins are needed.
_NO_PROJECTS = ProjectVisibility()


def search_slots(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    filters: CatalogFilters,
    *,
    visible: ProjectVisibility,
) -> CatalogPage:
    """Return a catalog page for the filters, area, page size and cursor.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    settings : AppSettings
        Settings in effect (the configured stores).
    registry : PluginRegistry
        Producer plugins: the pinned operation of a ``bbox`` in another CRS
        and the countries of a ``bbox``.
    filters : CatalogFilters
        Query of ``GET /slots``.
    visible : ProjectVisibility
        Projects the principal sees (pins, ``versions=pinned``, ``project``).

    Raises
    ------
    IndexQueryError
        Unknown store or area, both ``area_id`` and ``bbox``, a reversed
        range, a limit out of range or a cursor of another query.
    SourceStateError
        A ``bbox`` needs a producer plugin that is not available.
    NotFoundError
        ``project`` is unknown or not visible to the principal.
    """
    freshness = queries.freshness()
    stores = checked_store(filters.store, settings, freshness)
    checked_project(queries, filters.project, visible)
    area = None
    if filters.area_id is not None and filters.bbox is not None:
        raise IndexQueryError(message("api.area_and_bbox"))
    if filters.area_id is not None:
        record = queries.area(filters.area_id)
        if record is None:
            text = message("api.area_unknown", area=filters.area_id)
            raise IndexQueryError(text)
        area = AreaFilter(record.geometry, record.countries)
    bbox = filters.bbox_values()
    if bbox is not None:
        area = bbox_area(registry, bbox, filters.bbox_crs)
    page = queries.slots(filters.slot_query(area), visible=visible)
    return CatalogPage.of(page, staleness(freshness, stores))


def read_products(
    queries: IndexQueries, settings: AppSettings, store: str | None
) -> ProductList:
    """Return the indexed products with their segments, of all stores or one."""
    freshness = queries.freshness()
    stores = checked_store(store, settings, freshness)
    products = queries.products(store=store)
    return ProductList(
        items=[Product.of(product) for product in products],
        **staleness(freshness, stores),
    )


def slot_card(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    store: str,
    slot: str,
    *,
    visible: ProjectVisibility,
) -> SlotCard:
    """Return the file card of a slot: versions, links, pins, problems.

    Raises
    ------
    NotFoundError
        The index does not know the slot.
    """
    detail = queries.slot(store, slot, visible=visible)
    if detail is None:
        text = message("api.slot_unknown", slot=slot, store=store)
        raise NotFoundError(text)
    producer = detail.segment.producer
    problems = [issue_problem(issue) for issue in detail.issues]
    paths = copy_path(settings, preferences, store, producer, detail.slot)
    freshness = staleness(queries.freshness(), {store})
    return SlotCard.of(detail, problems, paths, freshness)


def version_card(
    queries: IndexQueries,
    settings: AppSettings,
    preferences: Preferences,
    store: str,
    version: str,
    *,
    visible: ProjectVisibility,
) -> VersionCard:
    """Return every indexed value of a version, its raw sidecar and copy path.

    Raises
    ------
    NotFoundError
        The index does not know the version.
    """
    detail = queries.version(store, version, visible=visible)
    if detail is None:
        text = message("api.version_unknown", version=version, store=store)
        raise NotFoundError(text)
    paths = copy_path(settings, preferences, store, detail.segment.producer, version)
    return VersionCard.of(
        detail,
        queries.sidecar(store, version),
        paths,
        staleness(queries.freshness(), {store}),
    )


def copy_path(
    settings: AppSettings,
    preferences: Preferences,
    store: str,
    producer: str,
    relative: str,
) -> CopyPath | None:
    """Return a file's path on this computer and as aliased elsewhere (SPEC 4.6).

    The store's path aliases give ``aliases``, the person's own the path on
    their computer (``personal``). ``None`` when the store or its producer
    directory is no longer configured. Nothing is read from the disk.

    Raises
    ------
    PathOutsideRootError
        The indexed path would leave the store's directory.
    """
    config = settings.store(store)
    root = None if config is None else config.roots().get(producer)
    if config is None or root is None:
        return None
    local = indexed_path(root, relative)
    return CopyPath(
        local=str(local),
        aliases=list(config.foreign_paths(local)),
        personal=preferences.personal_path(str(local)),
    )


def geo_adapter(registry: PluginRegistry) -> GeoAdapter:
    """Return the first available producer with coordinate operations.

    Raises
    ------
    SourceStateError
        No such producer is available: the error of the first one that
        failed, e.g. Kartograf not installed.
    """
    failure: SourceStateError | None = None
    for producer in sorted({*registry.producers(), *REQUIRED_PRODUCERS}):
        try:
            adapter = registry.adapter(producer)
        except SourceStateError as error:
            failure = failure or error
            continue
        if isinstance(adapter, GeoAdapter):
            return adapter
    if failure is not None:
        raise failure
    producer = min(REQUIRED_PRODUCERS)
    state = SourceState(producer, "error", detail=message("api.no_geo_source"))
    raise SourceUnavailableError(message("api.no_geo_source"), state=state)


def bbox_area(registry: PluginRegistry, bbox: BBox, crs: str) -> AreaFilter:
    """Return a rectangle as an area in WGS84 with the countries it meets.

    A rectangle in another CRS becomes the WGS84 polygon of its densified
    edges, converted with the producer's pinned operation (KA-6).

    Raises
    ------
    IndexQueryError
        A reversed rectangle, or one outside WGS84.
    SourceStateError
        No producer with coordinate operations is available.
    ProducerError
        The producer has no pinned operation for ``crs``.
    """
    min_x, min_y, max_x, max_y = bbox
    if not (min_x < max_x and min_y < max_y):
        raise IndexQueryError(message("api.bbox_invalid"))
    adapter = geo_adapter(registry)
    if crs.upper() == WGS84:
        bounds = require_wgs84_bbox(bbox)
        geometry = box_geometry(bounds)
    else:
        steps = np.linspace(0.0, 1.0, _EDGE_POINTS, endpoint=False)
        width, height = max_x - min_x, max_y - min_y
        xs = np.concatenate(
            [
                min_x + width * steps,
                np.full(_EDGE_POINTS, max_x),
                max_x - width * steps,
                np.full(_EDGE_POINTS, min_x),
            ]
        )
        ys = np.concatenate(
            [
                np.full(_EDGE_POINTS, min_y),
                min_y + height * steps,
                np.full(_EDGE_POINTS, max_y),
                max_y - height * steps,
            ]
        )
        lons, lats = adapter.transformer(crs, WGS84).transform(xs, ys)
        ring = [[float(lon), float(lat)] for lon, lat in zip(lons, lats, strict=True)]
        geometry = {"type": "Polygon", "coordinates": [[*ring, ring[0]]]}
        bounds = (
            float(np.min(lons)),
            float(np.min(lats)),
            float(np.max(lons)),
            float(np.max(lats)),
        )
        require_wgs84_bbox(bounds)
    return AreaFilter(geometry, tuple(adapter.countries(bounds)))


def checked_store(
    store: str | None, settings: AppSettings, freshness: tuple[StoreFreshness, ...]
) -> Collection[str] | None:
    """Return the stores an answer covers (``None``: all of them).

    Raises
    ------
    IndexQueryError
        ``store`` is neither configured nor in the index: a misspelt id must
        not look like an empty store.
    """
    if store is None:
        return None
    known = {config.id for config in settings.stores} | {
        item.store for item in freshness
    }
    if store not in known:
        raise IndexQueryError(message("api.store_unknown", store=store))
    return {store}


def checked_project(
    queries: IndexQueries, project: str | None, visible: ProjectVisibility
) -> None:
    """Refuse a ``project`` filter the principal cannot use.

    Raises
    ------
    NotFoundError
        The project is unknown or not visible: both answer the same, so an
        invisible project's existence is not revealed.
    """
    if project is not None and queries.project(project, visible=visible) is None:
        raise NotFoundError(message("project.not_found", project=project))


@router.get(
    "/slots",
    response_model=CatalogPage,
    responses=problem_responses(404, 400, 503),
)
def list_slots(
    filters: Annotated[CatalogFilters, Query()],
    visible: _Visible,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> CatalogPage:
    """Search and filter the catalog: slots with the version the query chooses.

    Rows sort by file name, slot path and store (and version path); follow
    `next_cursor` for the next page of the same query. `groups` counts the
    location groups over the whole result. Rows of an unavailable store
    stay in the answer, marked by `stale`. With `project`, only versions
    pinned in that project; a project not visible is `404`.
    """
    return search_slots(queries, settings.get(), registry, filters, visible=visible)


@router.get("/products", response_model=ProductList, responses=problem_responses(400))
def list_products(
    principal: _Principal,
    settings: _Settings,
    queries: _Queries,
    store: Annotated[
        str | None, Query(description="Only this store's segments.")
    ] = None,
) -> ProductList:
    """List indexed products with the producer's segment names and counts.

    Only what scans found; a segment the producer does not recognise is
    listed under the product `null`.
    """
    return read_products(queries, settings.get(), store)


@router.get(
    "/stores/{store}/slots/{slot:path}",
    response_model=SlotCard,
    responses=problem_responses(403, 404),
)
def get_slot(
    store: _Store,
    slot: Annotated[
        str,
        Path(
            description="Slot path (the standard path) in the store.",
            examples=["nmt/pl_1992_1m_evrf2007/N-34/130/D/d/2/4/N-34-130-D-d-2-4.asc"],
        ),
    ],
    visible: _Visible,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
) -> SlotCard:
    """Return the file card: all versions, current, `full_sheet`, pins, problems.

    `paths` is the copy path of the standard path on this computer, on
    aliased ones and on the person's own (`personal`); pins name only
    projects the session's principal sees.
    """
    return slot_card(queries, settings.get(), preferences, store, slot, visible=visible)


@router.get(
    "/stores/{store}/versions/{version:path}/sidecar",
    response_model=dict[str, Any],
    responses={
        200: {
            "description": "The producer's sidecar, unchanged.",
            "content": {
                "application/json": {
                    "example": {
                        "schema": "kartograf-meta/1",
                        "dataset": "pl.gugik.nmt_1m",
                        "sha256": (
                            "fdd30535e8085f861a106824ba4401a7"
                            "e96187a6c54abc33511803acd87b4623"
                        ),
                    }
                }
            },
        },
        **problem_responses(404),
    },
)
def get_sidecar(
    store: _Store,
    version: Annotated[str, Path(description="Version path in the store.")],
    principal: _Principal,
    queries: _Queries,
) -> dict[str, Any]:
    """Return the version's raw sidecar as the producer wrote it (from the index)."""
    found = queries.sidecar(store, version)
    if found is None:
        if queries.version(store, version, visible=_NO_PROJECTS) is not None:
            text = message("api.sidecar_missing", version=version, store=store)
        else:
            text = message("api.version_unknown", version=version, store=store)
        raise NotFoundError(text)
    return found


@router.get(
    "/stores/{store}/versions/{version:path}",
    response_model=VersionCard,
    responses=problem_responses(403, 404),
)
def get_version(
    store: _Store,
    version: Annotated[
        str,
        Path(
            description="Version path in the store.",
            examples=[
                "nmt/pl_1992_1m_evrf2007/versions/N-34/130/D/d/2/4/"
                "2025-04-26_82710_fdd30535/N-34-130-D-d-2-4.asc"
            ],
        ),
    ],
    visible: _Visible,
    settings: _Settings,
    preferences: _Preferences,
    queries: _Queries,
) -> VersionCard:
    """Return a version: every indexed value, outline, raw sidecar, copy path."""
    return version_card(
        queries, settings.get(), preferences, store, version, visible=visible
    )


@router.get(
    "/requests/{parent_request:path}",
    response_model=RequestFiles,
    responses=problem_responses(404),
)
def list_request_files(
    parent_request: Annotated[
        str,
        Path(
            description=(
                "Key of a producer request (`parent_request` of a version),"
                " URL-encoded."
            )
        ),
    ],
    principal: _Principal,
    queries: _Queries,
) -> RequestFiles:
    """List the files of one producer request, e.g. both sides of a border."""
    members = queries.group(parent_request)
    if not members:
        text = message("api.request_unknown", parent_request=parent_request)
        raise NotFoundError(text)
    stores = {member.store for member in members}
    return RequestFiles(
        parent_request=parent_request,
        items=[RequestFile.of(member) for member in members],
        **staleness(queries.freshness(), stores),
    )
