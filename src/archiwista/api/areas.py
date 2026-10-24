"""Areas and local coverage over HTTP (SPEC 9.2, 6.3, 10.1; plan step 9c).

``POST /areas`` keeps an area: GeoJSON in WGS84 as ``application/json``
(``AreaInput``), or a file as the raw body of any other type — GeoJSON,
GeoPackage, or a Shapefile in a ZIP archive, read in a separate process with
the limits of ``archiwista.areas``. ``GET /areas/{area_id}`` returns a kept
area. ``GET /local-coverage`` first rescans the area's slots of the product
(``refresh_area``, at most 500 slots, units from the outlines in the index;
each rescan is noted in ``AreaRefreshes``, which ``/local-layers`` reuses
for a minute), then measures the
share of the area under the current versions in the planar CRS of each
country (decision 5); an unavailable store, a rescan out of time or too many
slots answer from the index with ``stale_reason``. The functions without
HTTP (``read_area``, ``save_area``, ``save_area_file``,
``read_local_coverage``, ``refresh_area``) take the same models.
"""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi import Path as PathParameter
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models import Area, AreaCoverage, AreaInput, CoverageQuery
from archiwista.api.slots import geo_adapter
from archiwista.areas import (
    AreaFiles,
    area_from_file,
    area_from_geometry,
    check_body_size,
    discard_copy,
    keep_copy,
    read_area_file,
)
from archiwista.auth import Principal
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import IndexQueryError, NotFoundError
from archiwista.index import (
    REFRESH_VIEW_MAX_UNITS,
    AreaRecord,
    IndexQueries,
    IndexWriter,
    refresh_view,
)
from archiwista.index.geometry import polygon_bounds
from archiwista.messages import MESSAGES
from archiwista.security import current_principal
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["areas"])

# Longest rescan of an area's slots before the answer comes from the index:
# twice the target of a view refresh on a share (SPEC 4.5).
REFRESH_TIMEOUT_S = 10.0
# Seconds a rescan of an area's segment stands for the next answers: the
# local coverage and the local layers of one view rescan its slots once
# (plan v0.2, step 11).
REFRESH_MEMORY_S = 60.0

_JSON = "application/json"
_NAME_CHARS = 200


def index_path(request: Request) -> Path:
    """Return the application's local index file (written by these routes)."""
    value: Path = request.app.state.index_path
    return value


def area_files(request: Request) -> AreaFiles:
    """Return where the application keeps area files and how it reads them."""
    value: AreaFiles = request.app.state.area_files
    return value


class AreaRefreshes:
    """Areas whose slots were rescanned lately, per store and segment.

    Every rescan of ``/local-coverage`` and ``/local-layers`` (``refresh_area``)
    is noted here; ``/local-layers`` does not rescan an area's slots of a
    segment again within ``ttl_s`` while the store's directory is there, so
    the coverage and the layers of one view read the files once. Safe to
    share between threads.

    Parameters
    ----------
    ttl_s : float, optional
        Seconds a rescan stands for the next answers.
    clock : callable, optional
        Monotonic seconds.
    """

    def __init__(
        self,
        *,
        ttl_s: float = REFRESH_MEMORY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._done: dict[tuple[str, str, str | None], float] = {}

    def fresh(self, store: str, area: str, segment: str | None) -> bool:
        """Whether the area's slots of the segment were rescanned lately."""
        with self._lock:
            when = self._done.get((store, area, segment))
            return when is not None and 0 <= self._clock() - when < self._ttl_s

    def remember(self, store: str, area: str, segment: str | None) -> None:
        """Note a finished rescan of the area's slots of the segment."""
        with self._lock:
            now = self._clock()
            self._done = {
                key: when
                for key, when in self._done.items()
                if 0 <= now - when < self._ttl_s
            }
            self._done[(store, area, segment)] = now


def area_refreshes(request: Request) -> AreaRefreshes:
    """Return the application's memory of areas rescanned lately."""
    value: AreaRefreshes = request.app.state.area_refreshes
    return value


_Principal = Annotated[Principal, Depends(current_principal)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Index = Annotated[Path, Depends(index_path)]
_Files = Annotated[AreaFiles, Depends(area_files)]
_Refreshes = Annotated[AreaRefreshes, Depends(area_refreshes)]


def read_area(queries: IndexQueries, area_id: str) -> Area:
    """Return a kept area with its geometry, area and countries.

    Raises
    ------
    NotFoundError
        No area has this id.
    """
    record = queries.area(area_id)
    if record is None:
        raise NotFoundError(MESSAGES["api_area_unknown"].format(area=area_id))
    return Area.of(record)


def save_area(
    queries: IndexQueries, index: Path, registry: PluginRegistry, body: AreaInput
) -> Area:
    """Keep an area drawn, from the map view or a sheet (GeoJSON in WGS84).

    The same geometry keeps its id and creation time; its name and source
    become those of the latest request.

    Raises
    ------
    IndexQueryError
        Not a polygon in WGS84, or without area.
    AreaTooComplexError
        More than 100 000 vertices.
    SourceStateError
        No producer with coordinate operations is available.
    ProducerError
        The producer has no pinned operation to the planar CRS.
    """
    adapter = geo_adapter(registry)
    record = area_from_geometry(
        body.geometry, adapter=adapter, source=body.source, name=body.name
    )
    return Area.of(_save(queries, index, record))


def save_area_file(
    queries: IndexQueries,
    index: Path,
    registry: PluginRegistry,
    files: AreaFiles,
    content: bytes,
    *,
    name: str | None = None,
    layer: str | None = None,
) -> Area:
    """Keep the area of an uploaded file, and the file's copy (see ``save_area``).

    Raises
    ------
    AreaTooLargeError
        An archive declares more than 200 MB unpacked.
    AreaUnreadableError
        The file cannot be read (format, archive, layer, CRS, polygons,
        time limit).
    AreaTooComplexError
        More than 100 000 vertices.
    SourceStateError
        No producer with coordinate operations is available.
    ProducerError
        The producer has no pinned operation from the file's CRS.
    """
    adapter = geo_adapter(registry)
    found = read_area_file(files, content, layer=layer)
    try:
        record = area_from_file(found, adapter=adapter, name=name)
        kept = _save(queries, index, record)
    except BaseException:
        discard_copy(found)
        raise
    keep_copy(files, found, kept.id)
    return Area.of(kept)


def read_local_coverage(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    index: Path,
    query: CoverageQuery,
    *,
    timeout_s: float = REFRESH_TIMEOUT_S,
    max_units: int = REFRESH_VIEW_MAX_UNITS,
    memory: AreaRefreshes | None = None,
) -> AreaCoverage:
    """Rescan an area's slots of a product, then measure its local coverage.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    settings : AppSettings
        Settings in effect (the store's directory and threads).
    registry : PluginRegistry
        Producer plugins: the store's producer and the pinned operations.
    index : Path
        The local index file, written by the rescan.
    query : CoverageQuery
        Area, product, store and, optionally, segment.
    timeout_s : float, optional
        Longest rescan; after it the answer comes from the index.
    max_units : int, optional
        Most slots rescanned; an area with more answers from the index.
    memory : AreaRefreshes or None, optional
        The server's rescans of the last minute: this one is noted there for
        ``/local-layers``; the coverage itself always rescans (its
        "Odśwież" reads the files again).

    Raises
    ------
    IndexQueryError
        Unknown area, or a store that is not configured.
    SourceStateError
        No producer with coordinate operations, or the store's producer, is
        available.
    ProducerError
        The producer refused a unit or has no pinned operation.
    """
    record = queries.area(query.area_id)
    if record is None:
        raise IndexQueryError(MESSAGES["api_area_unknown"].format(area=query.area_id))
    if settings.store(query.store) is None:
        message = MESSAGES["api_store_not_configured"].format(store=query.store)
        raise IndexQueryError(message)
    adapter = geo_adapter(registry)
    reason = refresh_area(
        queries,
        settings,
        registry,
        index,
        record,
        store=query.store,
        product=query.product,
        segment=query.segment,
        timeout_s=timeout_s,
        max_units=max_units,
        memory=memory,
    )
    freshness = queries.freshness()
    if reason is None and any(
        item.store == query.store and item.stale for item in freshness
    ):
        reason = "store_unavailable"
    report = queries.local_coverage(
        record.geometry,
        store=query.store,
        product=query.product,
        transformer=adapter.transformer,
        countries=record.countries,
        segment=query.segment,
    )
    report = replace(report, stale=reason is not None, stale_reason=reason)
    return AreaCoverage.of(record, report, segment=query.segment, freshness=freshness)


def refresh_area(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    index: Path,
    record: AreaRecord,
    *,
    store: str,
    product: str,
    segment: str | None,
    timeout_s: float = REFRESH_TIMEOUT_S,
    max_units: int = REFRESH_VIEW_MAX_UNITS,
    memory: AreaRefreshes | None = None,
    reuse: bool = False,
) -> str | None:
    """Rescan an area's slots of a product before an answer; return why not.

    The view refresh of ``/local-coverage`` and ``/local-layers``. Units are
    those of the slots whose current outline meets the area's box
    (``slots_in_bbox``), of ``segment`` or of every segment of the product,
    each segment rescanned by itself; slots without a unit wait for the next
    scan. A finished rescan of a segment is noted in ``memory``; with
    ``reuse``, a segment of the area noted there within its time is not
    rescanned again while the store's directory is there (not a
    disconnected share or an empty mount point).

    Returns
    -------
    str or None
        ``None`` after a rescan (or with nothing to rescan), else
        ``too_many_slots``, ``refresh_timeout`` or ``store_unavailable``.
    """
    bounds = polygon_bounds(record.geometry)
    if bounds is None:
        return None
    producers = {
        item.segment.segment: item.segment.producer
        for summary in queries.products(store=store)
        if summary.product == product
        for item in summary.segments
    }
    units: dict[str | None, list[tuple[str, str]]] = {}
    for slot in queries.slots_in_bbox(store, bounds, segment=segment, product=product):
        if slot.unit is not None and slot.segment in producers:
            units.setdefault(slot.segment, []).append((slot.slot, slot.unit))
    total = sum(len(items) for items in units.values())
    if total == 0:
        return None
    if total > max_units:
        return "too_many_slots"
    config = settings.store(store)
    roots = {} if config is None else config.roots()
    if memory is not None and reuse:
        units = {
            name: items
            for name, items in units.items()
            if not memory.fresh(store, record.id, name)
            or not _present(roots.get(producers[name]))
        }
    if not units:
        return None
    deadline = time.monotonic() + timeout_s
    with IndexWriter(index) as writer:
        for name, items in units.items():
            adapter = registry.adapter(producers[name])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "refresh_timeout"
            try:
                status = refresh_view(
                    adapter,
                    writer,
                    queries,
                    settings,
                    store,
                    name,
                    [unit for _, unit in items],
                    known_slots=[slot for slot, _ in items],
                    timeout_s=remaining,
                )
            except TimeoutError:
                return "refresh_timeout"
            if any(item.store == store and item.stale for item in status.stores):
                return "store_unavailable"
            if memory is not None:
                memory.remember(store, record.id, name)
    return None


def _present(root: Path | None) -> bool:
    """Whether a store's directory is there with entries (not an empty mount)."""
    if root is None:
        return False
    try:
        with os.scandir(root) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


def _save(queries: IndexQueries, index: Path, record: AreaRecord) -> AreaRecord:
    """Write an area and return it as the index keeps it (first creation time)."""
    with IndexWriter(index) as writer:
        writer.write_area(record)
    return queries.area(record.id) or record


async def _body(request: Request) -> bytes:
    """Read the body, refusing it as soon as it is over the limit."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit():
        check_body_size(int(declared))
    content = bytearray()
    async for chunk in request.stream():
        content += chunk
        check_body_size(len(content))
    return bytes(content)


def _area_input(content: bytes) -> AreaInput:
    """Validate a JSON body like FastAPI does (``400 validation_error``)."""
    try:
        return AreaInput.model_validate_json(content)
    except ValidationError as error:
        errors = [
            {**item, "loc": ("body", *item["loc"])}
            for item in error.errors(include_url=False)
        ]
        raise RequestValidationError(errors) from error


def _with_400(description: str, *statuses: int) -> dict[int | str, dict[str, Any]]:
    responses = problem_responses(400, 500, *statuses)
    responses[400] = {**responses[400], "description": description}
    return responses


_REQUEST_BODY = {
    "required": True,
    "description": (
        "GeoJSON in WGS84 as `application/json` (`AreaInput`), or a file as the"
        " raw body of any other type, e.g. `application/octet-stream`: GeoJSON,"
        " GeoPackage or a ZIP archive with one Shapefile (`.shp`, `.shx`, `.dbf`,"
        " `.prj`). At most 50 MB; an archive at most 200 MB unpacked."
    ),
    "content": {
        _JSON: {"schema": AreaInput.model_json_schema()},
        "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
    },
}


@router.post(
    "/areas",
    status_code=201,
    response_model=Area,
    responses=_with_400(
        "Invalid GeoJSON (`errors`), a file over 50 MB or 200 MB unpacked"
        " (`details.reason` `area_too_large`) or an area of more than 100 000"
        " vertices (`area_too_complex`).",
        503,
    ),
    openapi_extra={"requestBody": _REQUEST_BODY},
)
async def create_area(
    request: Request,
    response: Response,
    principal: _Principal,
    registry: _Registry,
    queries: _Queries,
    index: _Index,
    files: _Files,
    name: Annotated[
        str | None,
        Query(
            max_length=_NAME_CHARS,
            description="Name shown with a file's area, e.g. the file name.",
        ),
    ] = None,
    layer: Annotated[
        str | None,
        Query(
            max_length=_NAME_CHARS,
            description="Layer of a GeoPackage, or Shapefile name in a ZIP archive.",
        ),
    ] = None,
) -> Area:
    """Keep an area: GeoJSON in WGS84, or a GeoJSON, GeoPackage or zipped Shapefile.

    A file is read in a separate process killed after 30 s, converted from
    its CRS with the producer's pinned operation and never simplified; its
    copy is kept for 7 days. The id comes from the geometry: the same area
    always gets the same id. `Location` names the new resource.
    """
    content = await _body(request)
    media_type = request.headers.get("content-type", "").split(";")[0].strip()
    if media_type.lower() == _JSON:
        body = _area_input(content)
        area = await run_in_threadpool(save_area, queries, index, registry, body)
    else:
        area = await run_in_threadpool(
            save_area_file,
            queries,
            index,
            registry,
            files,
            content,
            name=name,
            layer=layer,
        )
    response.headers["Location"] = f"{API_PREFIX}/areas/{area.id}"
    return area


@router.get("/areas/{area_id}", response_model=Area, responses=problem_responses(404))
def get_area(
    area_id: Annotated[
        str, PathParameter(description="Area id.", examples=["5f2b9c0e7d41a3b6"])
    ],
    principal: _Principal,
    queries: _Queries,
) -> Area:
    """Return an area: geometry (WGS84), area in km² (planar CRS), countries."""
    return read_area(queries, area_id)


@router.get(
    "/local-coverage",
    response_model=AreaCoverage,
    responses=_with_400(
        "Unknown parameter, area or store (`errors`, or `details.reason`"
        " `invalid_ref`).",
        503,
    ),
)
def get_local_coverage(
    query: Annotated[CoverageQuery, Query()],
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
    index: _Index,
    refreshes: _Refreshes,
) -> AreaCoverage:
    """Return how much of an area the store's current versions of a product cover.

    The area's slots are rescanned first (at most 500); the share is measured
    in the planar CRS of each country (EPSG:2180 for PL, EPSG:5514 for CZ).
    An unavailable store, a rescan out of time or too many slots answer from
    the index, with `stale` and `stale_reason`.
    """
    return read_local_coverage(
        queries,
        settings.get(),
        registry,
        index,
        query,
        timeout_s=REFRESH_TIMEOUT_S,
        memory=refreshes,
    )
