"""Local layers over HTTP (plan v0.2, step 11; decision 7).

- ``GET /local-layers?store&product&area_id&segment&group``: the
  ``LayerSet`` of a store's product, after the view refresh of the area's
  slots, shared with ``/local-coverage`` (an area and segment rescanned in
  the last minute are not rescanned again);
- ``GET /local-layers/thumbnail.png?…&layer&size&style&v``: a layer's image
  in the area's planar frame (the Wachlarz);
- ``GET /local-layers/tiles/{z}/{x}/{y}.png?…&layer&style&v``: a layer's
  map tile, so a year on the map is one raster source, not one per version.

The images carry an ``ETag`` (``If-None-Match`` naming it is ``304``) and,
when drawn from exactly the contents their ``v`` names, ``Cache-Control:
private, max-age=86400, immutable`` (a new ready preview gives a new
address); otherwise ``private, no-cache``. A request whose client goes away
gives its render up. Routes only translate: ``archiwista.services.layers``
does the work, ``archiwista layers`` calls it too.
"""

from collections.abc import Coroutine
from pathlib import Path as FilePath
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError

from archiwista.api.areas import AreaRefreshes, area_refreshes, index_path
from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models_layers import (
    LayerSet,
    LayersQuery,
    LayerThumbnailQuery,
    LayerTileQuery,
)
from archiwista.api.models_previews import MAX_ZOOM
from archiwista.api.previews import (
    CLIENT_GONE,
    PNG,
    VERSION_CACHE_CONTROL,
    ClientGone,
    image_responses,
    while_connected,
)
from archiwista.auth import Principal
from archiwista.config import SettingsService
from archiwista.errors import PreviewBusyError
from archiwista.index import IndexQueries
from archiwista.messages import MESSAGES
from archiwista.previews.pool import RETRY_AFTER_S, RenderPool
from archiwista.security import current_principal
from archiwista.services.layers import (
    LayerMemo,
    LayerPayload,
    layer_images,
    layer_thumbnail,
    layer_tile,
    read_local_layers,
)
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["layers"])

# An image drawn from other contents than its address names: check again.
REVALIDATE_CACHE_CONTROL = "private, no-cache"


def layer_memo(request: Request) -> LayerMemo:
    """Return the layers the application's last answers computed."""
    value: LayerMemo = request.app.state.layer_memo
    return value


def render_pool(request: Request) -> RenderPool:
    """Return the application's render pool.

    Raises
    ------
    PreviewBusyError
        The server runs no render pool (``503 preview_busy``).
    """
    pool: RenderPool | None = request.app.state.previews
    if pool is None:
        raise PreviewBusyError(MESSAGES["preview_closed"], retry_after_s=RETRY_AFTER_S)
    return pool


_Principal = Annotated[Principal, Depends(current_principal)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Index = Annotated[FilePath, Depends(index_path)]
_Refreshes = Annotated[AreaRefreshes, Depends(area_refreshes)]
_Memo = Annotated[LayerMemo, Depends(layer_memo)]
_Pool = Annotated[RenderPool, Depends(render_pool)]
_IfNoneMatch = Annotated[
    str | None,
    Header(description="`ETag` of the image the client holds: `304` when equal."),
]
_IMAGE_PROBLEMS = ("preview_busy", "store_unavailable", "preview_timeout")


@router.get(
    "/local-layers",
    response_model=LayerSet,
    responses=problem_responses(400, 503),
)
def get_local_layers(
    query: Annotated[LayersQuery, Query()],
    request: Request,
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
    index: _Index,
    refreshes: _Refreshes,
    memo: _Memo,
) -> LayerSet:
    """Return the layers of a store's product: years, campaigns, editions.

    A layer is a variant (product, CRSs and resolution, not the file
    format: its formats are badges) and a data year — never the download's
    year; a version without one joins its edition, else its label.
    `group=campaign` splits a year by campaign. With `area_id` the area's
    slots are rescanned first (at most 500, not again within a minute), and
    each layer has its local coverage in the area's planar CRS (`frame`),
    its outlines there, its versions with their previews, and the
    addresses of its thumbnail and map tiles (`v` changes as previews get
    ready; one `preview` job per layer builds the missing ones). Without it,
    only the counts of the whole store. An unavailable store, a rescan out
    of time or too many slots answer from the index, with `stale` and
    `stale_reason`.
    """
    state = request.app.state
    pool: RenderPool | None = state.previews
    return read_local_layers(
        queries,
        settings.get(),
        registry,
        index,
        query,
        principal=principal,
        cache=None if pool is None else pool.cache,
        jobs=None if pool is None else state.jobs,
        memory=refreshes,
        memo=memo,
    )


@router.get(
    "/local-layers/thumbnail.png",
    response_class=Response,
    responses=image_responses(PNG, *_IMAGE_PROBLEMS),
)
async def get_layer_thumbnail(
    query: Annotated[LayerThumbnailQuery, Query()],
    request: Request,
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
    memo: _Memo,
    pool: _Pool,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return a layer's PNG in the area's planar frame, `size` pixels a side.

    Drawn from the layer's ready previews, newest on top; a version still
    without one is left out (its outline is in the `LayerSet`). Use the
    `thumbnail_url` of the `LayerSet`, adding `size` or `style`.
    """
    images = await run_in_threadpool(
        layer_images,
        queries,
        settings.get(),
        registry,
        query,
        query.layer,
        cache=pool.cache,
        v=query.v,
        memo=memo,
    )
    work = layer_thumbnail(
        pool,
        images,
        style=query.style,
        size=query.size,
        v=query.v,
        if_none_match=if_none_match,
    )
    return await _respond(request, work)


@router.get(
    "/local-layers/tiles/{z}/{x}/{y}.png",
    response_class=Response,
    responses=image_responses(PNG, *_IMAGE_PROBLEMS),
)
async def get_layer_tile(
    z: Annotated[int, Path(ge=0, le=MAX_ZOOM, description="Zoom level.")],
    x: Annotated[int, Path(ge=0, description="Column, 0 to 2^z - 1.")],
    y: Annotated[int, Path(ge=0, description="Row, 0 to 2^z - 1.")],
    query: Annotated[LayerTileQuery, Query()],
    request: Request,
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
    memo: _Memo,
    pool: _Pool,
    if_none_match: _IfNoneMatch = None,
) -> Response:
    """Return the map tile `z/x/y` of a layer (EPSG:3857, 256 pixels).

    One raster source per layer on the map: the tile lays the tiles of the
    layer's ready versions over each other, the others transparent. Below
    the layer's `minzoom`, or outside its versions' extent: `404` (show the
    outlines). Use the `tiles_url` of the `LayerSet`.
    """
    last = 2**z - 1
    errors = [
        {
            "loc": ("path", name),
            "msg": MESSAGES["preview_tile_range"].format(z=z, last=last),
            "type": "value_error",
        }
        for name, value in (("x", x), ("y", y))
        if value > last
    ]
    if errors:
        raise RequestValidationError(errors)
    images = await run_in_threadpool(
        layer_images,
        queries,
        settings.get(),
        registry,
        query,
        query.layer,
        cache=pool.cache,
        v=query.v,
        memo=memo,
    )
    work = layer_tile(
        pool,
        images,
        z=z,
        x=x,
        y=y,
        style=query.style,
        v=query.v,
        if_none_match=if_none_match,
    )
    return await _respond(request, work)


async def _respond(
    request: Request, work: Coroutine[Any, Any, LayerPayload]
) -> Response:
    """Answer a layer's image, ``304`` when the client holds it."""
    try:
        payload = await while_connected(request, work)
    except ClientGone:
        return Response(status_code=CLIENT_GONE)
    headers = {
        "Cache-Control": (
            VERSION_CACHE_CONTROL if payload.final else REVALIDATE_CACHE_CONTROL
        ),
        "ETag": payload.etag,
    }
    if payload.data is None:
        return Response(status_code=304, headers=headers)
    return Response(payload.data, media_type=PNG, headers=headers)
