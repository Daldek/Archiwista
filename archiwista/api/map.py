"""Map layers: footprints in a view and sheet grids (SPEC 9.2, 5.4).

``GET /map/footprints`` answers from the index: up to ``limit`` (5000)
outlines in the view, above that a grid of counts, and always the catalog's
location groups (``groups.none`` is the "files without outline" counter that
leads to the catalog). ``GET /map/sheets`` asks a producer for the sheets of
a sheet system and scale in the view (Kartograf: PL-1992 and PL-2000); a
view with far more sheets than ``MAP_FOOTPRINT_LIMIT`` is refused before the
grid is drawn.
"""

import math
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from archiwista.api.dependencies import (
    index_queries,
    plugin_registry,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import ApiError, problem_responses
from archiwista.api.models import (
    MapFilters,
    MapView,
    Sheet,
    SheetFilters,
    SheetList,
    staleness,
)
from archiwista.api.slots import checked_store
from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import AppSettings, SettingsService
from archiwista.index import MAP_FOOTPRINT_LIMIT, BBox, IndexQueries
from archiwista.index.geometry import polygon_bounds, require_wgs84_bbox
from archiwista.messages import MESSAGES
from archiwista.security import current_principal
from archiwista.sources import SheetGridAdapter
from archiwista.sources.registry import PluginRegistry

router = APIRouter(prefix="/map", tags=["map"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
# Side of the box at the view's centre whose sheet gives the sheet size, °.
_PROBE_DEG = 1e-6


def map_view(
    queries: IndexQueries,
    settings: AppSettings,
    filters: MapFilters,
    *,
    visible: ProjectVisibility,
) -> MapView:
    """Return the footprints of a map view, or their grid above the limit.

    Raises
    ------
    IndexQueryError
        An unknown store, a view outside WGS84, a reversed range or a limit
        out of range.
    """
    freshness = queries.freshness()
    stores = checked_store(filters.store, settings, freshness)
    page = queries.footprints(filters.map_query(), visible=visible)
    return MapView.of(page, staleness(freshness, stores))


def sheet_list(registry: PluginRegistry, filters: SheetFilters) -> SheetList:
    """Return the producer's sheets of a system and scale in a WGS84 view.

    Raises
    ------
    IndexQueryError
        The view is reversed or outside WGS84.
    ApiError
        ``422 validation_error``: the view holds more than
        ``MAP_FOOTPRINT_LIMIT`` sheets.
    SourceStateError
        The producer's plugin is not available.
    ProducerError
        The producer does not know the system or the scale.
    """
    bbox = require_wgs84_bbox(filters.bbox_values())
    adapter = registry.adapter(filters.producer)
    found = SheetList(
        producer=filters.producer,
        system=filters.system,
        scale=filters.scale,
        status="unsupported",
        items=[],
    )
    if not isinstance(adapter, SheetGridAdapter):
        return found
    estimate = _estimated_sheets(adapter, bbox, filters.system, filters.scale)
    if estimate is not None and estimate > 2 * MAP_FOOTPRINT_LIMIT:
        raise _too_many(estimate, filters.scale)
    grid = adapter.sheet_grid(bbox, filters.system, filters.scale)
    if len(grid.sheets) > MAP_FOOTPRINT_LIMIT:
        raise _too_many(len(grid.sheets), filters.scale)
    return found.model_copy(
        update={
            "status": grid.status,
            "items": [
                Sheet(sheet=sheet, geometry=outline)
                for sheet, outline in zip(grid.sheets, grid.outlines, strict=True)
            ],
        }
    )


def _estimated_sheets(
    adapter: SheetGridAdapter, bbox: BBox, system: str, scale: str
) -> int | None:
    """Estimate the sheets of a view from the size of the sheet at its centre.

    ``None`` when no sheet lies at the centre (outside the grid's extent).
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    lon = (min_lon + max_lon) / 2
    lat = (min_lat + max_lat) / 2
    probe = adapter.sheet_grid(
        (lon, lat, lon + _PROBE_DEG, lat + _PROBE_DEG), system, scale
    )
    bounds = polygon_bounds(probe.outlines[0]) if probe.outlines else None
    if bounds is None:
        return None
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    if width <= 0 or height <= 0:
        return None
    columns = math.ceil((max_lon - min_lon) / width)
    rows = math.ceil((max_lat - min_lat) / height)
    return columns * rows


def _too_many(count: int, scale: str) -> ApiError:
    message = MESSAGES["api_too_many_sheets"].format(
        count=count, scale=scale, limit=MAP_FOOTPRINT_LIMIT
    )
    return ApiError(422, "validation_error", message)


@router.get("/footprints", response_model=MapView, responses=problem_responses(422))
def list_footprints(
    filters: Annotated[MapFilters, Query()],
    visible: _Visible,
    settings: _Settings,
    queries: _Queries,
) -> MapView:
    """List outlines in a map view (WGS84) with the catalog filters, or a grid.

    Above `limit` the answer is `aggregated`: `cells` count outline centres.
    Files without outline are never drawn: `groups.none` counts them.
    """
    return map_view(queries, settings.get(), filters, visible=visible)


@router.get("/sheets", response_model=SheetList, responses=problem_responses(422, 503))
def list_sheets(
    filters: Annotated[SheetFilters, Query()],
    principal: _Principal,
    registry: _Registry,
) -> SheetList:
    """List sheets (godła) of a sheet system and scale in a view, with outlines.

    A producer without sheet grids answers `unsupported`; a system or scale
    the producer does not know is `422 kartograf_error` with its message.
    """
    return sheet_list(registry, filters)
