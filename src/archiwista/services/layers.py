"""Local layers of a product: its years, campaigns and editions (decision 7).

``read_local_layers`` answers ``GET /local-layers`` and ``archiwista
layers``: the present versions of a store's product — in an area, after the
view refresh shared with ``/local-coverage`` (``refresh_area``), or in the
whole store for counts only — grouped into layers. A layer is a variant and
the data year (``data_year``, never the download's year); a version without
one joins the layer of its edition, else of its label, and
``group="campaign"`` splits a year by campaign. The variant has no file
format (A-ADR-017, SPEC 6.4): its key is ``product``, ``horizontal_crs``,
``resolution`` and ``vertical_crs`` of the version's metadata, so one set of
sheets in two formats (ASC and ASCII-NMT) is one layer with both formats as
badges; a version missing one of them keys by its segment (segment names
are never taken apart). Layers come newest first, each keyed
``<variant>:<year|edition|label>[:<campaign>]``, the variant being 12
characters of the SHA-256 of its key, or the segment.

With an area a layer carries what the views draw: the share of the area
under its versions measured in the area's planar CRS (``frame``: EPSG:2180,
EPSG:5514), its outlines in that CRS, its versions (at most 500) with the
state of their previews, and its own previews' state. The versions still
missing a preview (not probed yet, or a local COG not built) are built by
one ``preview`` job per layer, which the server submits and the next answers
join; the addresses of the layer's thumbnail and map tiles carry ``v``, a
digest of the ready contents, so they change as previews get ready.

``layer_thumbnail`` and ``layer_tile`` draw those images in a render
process (``compose``) from the layer's ready versions — a tile only from the
versions meeting it and only from the layer's ``minzoom``, the zoom at which
a typical sheet of the layer has at least 32 pixels, so that a tile meets at
most about 9 × 9 sheets. The preview cache answers first, so a disconnected
store still shows what was drawn; only a miss resolves the files inside
their root. ``LayerMemo`` keeps the layers of the last answers for a
minute, so the tiles of a map view do not read the index again.

``read_own_file_layers`` answers ``GET
/projects/{project}/files/{file_id}/layers``: an own file's working file,
then its snapshots newest first (SPEC 4.7.1: a file's snapshots are its
versions), each a layer of that one object. Their frame is the union of the
objects' extents in the planar CRS of their country, as an area's (an
extent already in that CRS is taken as it is), so the Wachlarz draws every
``LayerSet`` alike. A layer's state and images are its object's, as the
file routes answer them (``PreviewService.info``; the thumbnail is the
object's ``preview.png`` in the frame, the tiles are the object's): those
routes check the project's visibility and a working file's change since its
scan for every image, and one object needs no composite (``LayerImages``).
"""

import asyncio
import functools
import hashlib
import logging
import math
import sqlite3
import statistics
import threading
import time
from collections import Counter, OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlencode

import shapely
from pydantic import ValidationError
from shapely.geometry import mapping, shape

from archiwista.api import API_PREFIX
from archiwista.api.areas import (
    REFRESH_TIMEOUT_S,
    AreaRefreshes,
    refresh_area,
)
from archiwista.api.models import AreaRef, CountryCoverage, staleness
from archiwista.api.models_layers import (
    Layer,
    LayerCoverage,
    LayerFrame,
    LayerKind,
    LayerPreview,
    LayerSet,
    LayersQuery,
    LayerVariant,
    LayerVersion,
    LayerVersionPreview,
)
from archiwista.api.models_previews import THUMBNAIL_SIZES, PreviewInfo, PreviewJob
from archiwista.api.slots import geo_adapter
from archiwista.areas import area_crs
from archiwista.auth import Principal
from archiwista.config import AppSettings
from archiwista.errors import (
    IndexQueryError,
    NotFoundError,
    OwnFolderInvalidError,
    PathOutsideRootError,
    PreviewParameterError,
    PreviewUnavailableError,
    ProducerError,
    SourceUnavailableError,
)
from archiwista.formats import UNKNOWN_FORMAT, file_format
from archiwista.index import (
    REFRESH_VIEW_MAX_UNITS,
    AreaRecord,
    IndexQueries,
    LocalCoverage,
    OwnFileDetail,
    ProductVersion,
    SnapshotRecord,
)
from archiwista.index.coverage import (
    WGS84,
    CoverageShape,
    PlanarMover,
    measure_planar,
)
from archiwista.index.geometry import box_geometry, polygon_bounds
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message
from archiwista.owndata.document import SnapshotDocument
from archiwista.previews.cache import INFO_NAME, CacheKey, PreviewCache, cache_key
from archiwista.previews.compose import LAYER_THUMBNAIL, LAYER_TILE, tile_wgs84_bounds
from archiwista.previews.pool import RenderPool
from archiwista.previews.service import PreviewService, object_url
from archiwista.previews.types import (
    BBox,
    Extent,
    JsonObject,
    PreviewProbe,
    PreviewSource,
    PreviewState,
    auto_build,
    build_product,
)
from archiwista.previews.worker import OPERATIONS
from archiwista.refs import (
    FileRef,
    ObjectResolver,
    SnapshotRef,
    VersionRef,
    format_ref,
    version_ref,
)
from archiwista.sources import GeoJSONGeometry
from archiwista.sources.registry import PluginRegistry

# Versions a layer lists, and draws, at most (the newest).
MAX_LAYER_VERSIONS = 500
# A typical sheet of a layer has at least this many pixels from its minzoom.
SHEET_MIN_PX = 32
# Seconds and layers ``LayerMemo`` keeps.
LAYER_MEMORY_S = 60.0
LAYER_MEMORY_SIZE = 256
# Kinds of files a layer's images can draw.
_DRAWN_KINDS = frozenset({"raster", "image", "vector", "points"})
_VARIANT_CHARS = 12
_DIGEST_CHARS = 16
# Planar coordinates of the outlines and of an own file's frame: centimetres.
_OUTLINE_DECIMALS = 2
# The shortest side of an own file's frame (a file of one point), in metres.
_FRAME_MIN_M = 1.0
# Pixels a marker on an extent's edge reaches out of it in a thumbnail
# (``archiwista.previews.rasterize.REACH_PX``, a module of the render
# processes only).
_EDGE_REACH_PX = 4
# The style of a layer none of whose versions is ready: nothing is drawn.
_NO_STYLE = "rgb"
_TILE_PX = 256

logger = logging.getLogger(__name__)

type _MemoKey = tuple[str, str, str, str | None, str, str, str | None]


@dataclass(frozen=True, slots=True)
class LayerItem:
    """A ready version of a layer, as its images draw it.

    ``source`` is located from the index (its content key names the objects
    of the preview cache; its path is not resolved and is never read),
    ``bounds`` its WGS84 extent; ``resolve`` returns the source with its
    file resolved inside its root, for a render (``ObjectResolver``).
    """

    source: PreviewSource
    bounds: BBox | None
    resolve: Callable[[], PreviewSource]


@dataclass(frozen=True, slots=True)
class LayerImages:
    """What a layer's thumbnail and map tiles are drawn from.

    ``items`` are its ready versions, oldest first (drawn in that order, the
    newest on top); ``digest`` names their contents (``v`` of the
    addresses); ``styles`` and ``default_style`` are their probes';
    ``frame`` is the area's box in its planar CRS (``None`` outside PL and
    CZ); ``minzoom`` the zoom from which tiles are drawn and ``bounds`` the
    WGS84 extent of all the layer's versions (``None``: none on the map).
    """

    key: str
    digest: str
    items: tuple[LayerItem, ...]
    styles: tuple[str, ...]
    default_style: str | None
    frame: Extent | None
    minzoom: int | None
    bounds: BBox | None


@dataclass(frozen=True, slots=True)
class LayerPayload:
    """A layer's image with its ``ETag``; ``data`` is ``None`` for ``304``.

    ``final``: drawn from exactly the contents its address names (``v``),
    so the client may keep it for good.
    """

    data: bytes | None
    etag: str
    final: bool


class LayerMemo:
    """The layers of the last answers, for their images (one minute).

    ``GET /local-layers`` computes every layer of its answer; the thumbnails
    and tiles of its addresses take theirs from here instead of the index,
    by the query of their ``LayerSet``, the layer's key and ``v``. Safe to
    share between threads.

    Parameters
    ----------
    ttl_s : float, optional
        Seconds a layer is kept.
    size : int, optional
        Layers kept at most (the least recently used go first).
    clock : callable, optional
        Monotonic seconds.
    """

    def __init__(
        self,
        *,
        ttl_s: float = LAYER_MEMORY_S,
        size: int = LAYER_MEMORY_SIZE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._size = size
        self._clock = clock
        self._lock = threading.Lock()
        self._kept: OrderedDict[_MemoKey, tuple[LayerImages, float]] = OrderedDict()

    def get(self, key: _MemoKey) -> LayerImages | None:
        """Return a layer kept under ``key`` within its time, else ``None``."""
        with self._lock:
            found = self._kept.get(key)
            if found is None:
                return None
            images, when = found
            if not 0 <= self._clock() - when < self._ttl_s:
                del self._kept[key]
                return None
            self._kept.move_to_end(key)
            return images

    def put(self, key: _MemoKey, images: LayerImages) -> None:
        """Keep a layer under ``key``."""
        with self._lock:
            self._kept[key] = (images, self._clock())
            self._kept.move_to_end(key)
            while len(self._kept) > self._size:
                self._kept.popitem(last=False)


@dataclass(slots=True)
class _Version:
    """A version of a layer with the state of its preview."""

    item: ProductVersion
    ref: str
    source: PreviewSource | None = None
    probe: PreviewProbe | None = None
    state: PreviewState = "unavailable"


@dataclass(slots=True)
class _Layer:
    """The versions of one layer, newest first."""

    key: str
    variant: str
    kind: LayerKind
    period: LayerKind
    year: int | None
    part: str
    campaign: str | None
    versions: list[_Version] = field(default_factory=list)


def read_local_layers(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    index: Path,
    query: LayersQuery,
    *,
    principal: Principal,
    cache: PreviewCache | None,
    jobs: JobSupervisor | None = None,
    memory: AreaRefreshes | None = None,
    memo: LayerMemo | None = None,
    timeout_s: float = REFRESH_TIMEOUT_S,
    max_units: int = REFRESH_VIEW_MAX_UNITS,
) -> LayerSet:
    """Return the layers of a store's product, in an area or in the whole store.

    Parameters
    ----------
    queries : IndexQueries
        Reader of the local index.
    settings : AppSettings
        Settings in effect (the store's directory and threads).
    registry : PluginRegistry
        Producer plugins: the store's producer and the pinned operations.
    index : Path
        The local index file, written by the area's rescan.
    query : LayersQuery
        Store, product and, optionally, area, segment and grouping.
    principal : Principal
        Who asks: the actor of the layers' ``preview`` jobs.
    cache : PreviewCache or None
        The preview cache: the state of the versions' previews (all of them
        need building without one).
    jobs : JobSupervisor or None, optional
        The server's job supervisor: a ``preview`` job per layer builds its
        missing previews. Without one (the command line) none is submitted
        or named.
    memory : AreaRefreshes or None, optional
        The server's rescans of the last minute (shared with
        ``/local-coverage``).
    memo : LayerMemo or None, optional
        Where the layers are kept for the images of their addresses.
    timeout_s : float, optional
        Longest rescan; after it the answer comes from the index.
    max_units : int, optional
        Most slots rescanned; an area with more answers from the index.

    Raises
    ------
    IndexQueryError
        Unknown area, or a store that is not configured (``422``).
    SourceStateError
        No producer with coordinate operations, or the store's producer, is
        available.
    ProducerError
        The producer refused a unit or has no pinned operation.
    """
    record = _area(queries, query.area_id)
    _require_store(settings, query.store)
    reason = None
    if record is not None:
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
            reuse=True,
        )
    freshness = queries.freshness()
    unavailable = any(item.store == query.store and item.stale for item in freshness)
    if record is not None and reason is None and unavailable:
        reason = "store_unavailable"
    resolver = ObjectResolver(queries, lambda: settings)
    layers = _collect(queries, query, record, cache, resolver)
    frame: Extent | None = None
    mover: PlanarMover | None = None
    region: Any = None
    if record is not None:
        crs = area_crs(record.countries)
        if crs is not None:
            mover = PlanarMover(crs, geo_adapter(registry).transformer)
            region, frame = _frame(mover, record)
    models = []
    for layer in layers:
        job = None
        if record is not None and jobs is not None and not unavailable:
            job = _build_missing(jobs, layer, principal)
        images = None
        if record is not None:
            images = _images(layer, query.store, frame, resolver)
        if images is not None and memo is not None:
            memo.put(_memo_key(query, layer.key, images.digest), images)
        models.append(_model(layer, query, record, mover, region, images, job))
    fields = staleness(freshness, {query.store})
    return LayerSet(
        area=None if record is None else AreaRef.of(record),
        store=query.store,
        product=query.product,
        segment=query.segment,
        group=query.group,
        frame=None
        if frame is None
        else LayerFrame(crs=frame.crs, bbox=list(frame.bbox)),
        layers=models,
        stale=reason is not None or fields["stale"],
        stale_stores=fields["stale_stores"],
        stale_reason=reason,
    )


def layer_images(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    query: LayersQuery,
    layer: str,
    *,
    cache: PreviewCache | None,
    v: str | None = None,
    memo: LayerMemo | None = None,
) -> LayerImages:
    """Return what a layer's images are drawn from: the memo's, else the index's.

    Without the view refresh and without jobs: the layer as the index holds
    it now (``read_local_layers`` rescanned it for its ``LayerSet``).

    Raises
    ------
    IndexQueryError
        Unknown area, or a store that is not configured (``422``).
    NotFoundError
        The product has no such layer in the area (``404``).
    """
    key = _memo_key(query, layer, v)
    if memo is not None:
        found = memo.get(key)
        if found is not None:
            return found
    record = _area(queries, query.area_id)
    if record is None:
        raise IndexQueryError(message("layer.area_required"))
    _require_store(settings, query.store)
    resolver = ObjectResolver(queries, lambda: settings)
    chosen = next(
        (
            item
            for item in _collect(queries, query, record, cache, resolver)
            if item.key == layer
        ),
        None,
    )
    if chosen is None:
        text = message("layer.unknown", layer=layer, product=query.product)
        raise NotFoundError(text)
    frame = None
    crs = area_crs(record.countries)
    if crs is not None:
        _, frame = _frame(PlanarMover(crs, geo_adapter(registry).transformer), record)
    images = _images(chosen, query.store, frame, resolver)
    if memo is not None:
        memo.put(key, images)
        memo.put(_memo_key(query, layer, images.digest), images)
    return images


async def layer_thumbnail(
    pool: RenderPool,
    images: LayerImages,
    *,
    style: str | None,
    size: int,
    v: str | None,
    if_none_match: str | None = None,
) -> LayerPayload:
    """Return the PNG of a layer in its frame (``layer_thumbnail``).

    Parameters
    ----------
    pool : RenderPool
        The started render pool with its preview cache.
    images : LayerImages
        The layer (``layer_images``).
    style : str or None
        A style of its versions; their usual one when ``None``.
    size : int
        Longest side in pixels (128, 256, 512, 1024; checked by the caller).
    v : str or None
        The digest the client's address names.
    if_none_match : str or None, optional
        The client's ``If-None-Match``.

    Raises
    ------
    NotFoundError
        The area has no planar CRS, so the layer has no frame.
    PreviewParameterError
        A style none of the layer's versions has.
    SourceUnavailableError
        Not in the cache, and the store is out of reach.
    """
    frame = images.frame
    if frame is None:
        raise NotFoundError(message("layer.no_frame"))
    params: JsonObject = {
        "frame": {"bbox": list(frame.bbox), "crs": frame.crs},
        "style": _style(images, style),
        "size": size,
    }
    return await _draw(
        pool,
        LAYER_THUMBNAIL,
        images.items,
        params,
        final=v == images.digest,
        if_none_match=if_none_match,
    )


async def layer_tile(
    pool: RenderPool,
    images: LayerImages,
    *,
    z: int,
    x: int,
    y: int,
    style: str | None,
    v: str | None,
    if_none_match: str | None = None,
) -> LayerPayload:
    """Return the PNG map tile ``z/x/y`` of a layer (``layer_tile``, EPSG:3857).

    Drawn from the ready versions meeting the tile, the others transparent.

    Raises
    ------
    NotFoundError
        Below the layer's ``minzoom``, or outside its versions' extent.
    PreviewParameterError
        A style none of the layer's versions has.
    SourceUnavailableError
        Not in the cache, and the store is out of reach.
    """
    minzoom, bounds = images.minzoom, images.bounds
    if minzoom is None or bounds is None or z < minzoom:
        text = message(
            "layer.tile_below_minzoom",
            z=z,
            minzoom=minzoom if minzoom is not None else "–",
        )
        raise NotFoundError(text)
    tile = tile_wgs84_bounds(z, x, y)
    if not _meets(tile, bounds):
        raise NotFoundError(message("layer.tile_outside", z=z, x=x, y=y))
    params: JsonObject = {"z": z, "x": x, "y": y, "style": _style(images, style)}
    items = tuple(
        item
        for item in images.items
        if item.bounds is not None and _overlaps(tile, item.bounds)
    )
    return await _draw(
        pool,
        LAYER_TILE,
        items,
        params,
        final=v == images.digest,
        if_none_match=if_none_match,
    )


async def read_own_file_layers(
    detail: OwnFileDetail,
    registry: PluginRegistry,
    previews: PreviewService,
    *,
    principal: Principal,
) -> LayerSet:
    """Return the layers of an own file: its working file, then its snapshots.

    The snapshots come newest first, as the index lists them. Each layer is
    one object, keyed ``file`` or ``snapshot:<label>``, with the state and
    addresses of its own ``PreviewInfo``; its thumbnail is drawn in the
    frame of all the objects' extents (``_own_frame``).

    Parameters
    ----------
    detail : OwnFileDetail
        The file, as the principal sees it (``archiwista.api.owndata.own_file``).
    registry : PluginRegistry
        Producer plugins: the countries and pinned operations of the frame.
    previews : PreviewService
        The previews the file routes answer with.
    principal : Principal
        Who asks.

    Raises
    ------
    NotFoundError
        The file or a snapshot left the index meanwhile (``404``).
    PreviewBusyError
        The render queue is full (``503 preview_busy``).
    SourceStateError
        No producer with coordinate operations is available.
    """
    objects = _own_objects(detail)
    frame, footprints = await asyncio.to_thread(_own_frame, registry, objects)
    # One object after another: a first view probes each in the render pool.
    infos = [await _own_info(previews, item.ref, principal) for item in objects]
    path = detail.file.path
    badge = _format(path)
    return LayerSet(
        area=None,
        store=None,
        product=None,
        segment=None,
        group=None,
        frame=None
        if frame is None
        else LayerFrame(crs=frame.crs, bbox=list(frame.bbox)),
        layers=[
            _own_layer(item, info, frame, footprint, path=path, badge=badge)
            for item, info, footprint in zip(objects, infos, footprints, strict=True)
        ],
        stale=False,
        stale_stores=[],
        stale_reason=None,
    )


# Layers from the index.


def _collect(
    queries: IndexQueries,
    query: LayersQuery,
    record: AreaRecord | None,
    cache: PreviewCache | None,
    resolver: ObjectResolver,
) -> list[_Layer]:
    """Return the layers of the query's versions, newest first.

    With an area: the versions whose outline shares interior with it, with
    the state of their previews; without one, every present version.
    """
    bbox = None if record is None else polygon_bounds(record.geometry)
    if record is not None and bbox is None:
        return []
    found = queries.product_versions(
        query.store, query.product, segment=query.segment, bbox=bbox
    )
    if record is not None:
        region = shape(record.geometry)
        shapely.prepare(region)
        found = tuple(
            item
            for item in found
            if item.outline is not None and _shares_interior(region, item.outline)
        )
    layers: dict[str, _Layer] = {}
    for item in found:
        variant = _variant(item)
        period, year, part = _period(item)
        campaign = item.campaign if query.group == "campaign" else None
        key = f"{variant}:{part}"
        kind: LayerKind = period
        if campaign:
            kind, key = "campaign", f"{key}:{campaign}"
        layer = layers.get(key)
        if layer is None:
            layer = _Layer(key, variant, kind, period, year, part, campaign or None)
            layers[key] = layer
        ref = version_ref(query.store, item.path)
        version = _Version(item, ref)
        if record is not None:
            version = _version(query.store, item, ref, cache, resolver)
        layer.versions.append(version)
    for layer in layers.values():
        layer.versions.sort(key=_age, reverse=True)
    ordered = sorted(layers.values(), key=lambda layer: layer.variant)
    return sorted(ordered, key=_newness, reverse=True)


def _version(
    store: str,
    item: ProductVersion,
    ref: str,
    cache: PreviewCache | None,
    resolver: ObjectResolver,
) -> _Version:
    """Return a version with its preview's state, read from the cache only."""
    if file_format(item.path).kind not in _DRAWN_KINDS:
        return _Version(item, ref)
    try:
        source = resolver.version_source(store, item, on_disk=False)
    except (PathOutsideRootError, PreviewUnavailableError, SourceUnavailableError):
        return _Version(item, ref)
    if cache is None:
        return _Version(item, ref, source, None, "needs_build")
    key = cache_key(source)
    probe = _probe(cache, key)
    if probe is None:
        return _Version(item, ref, source, None, "needs_build")
    if probe.reason is not None or not probe.styles or probe.bbox_wgs84 is None:
        return _Version(item, ref, source, probe)
    product = build_product(probe)
    if product is not None and not _has(cache, key, product):
        return _Version(item, ref, source, probe, "needs_build")
    return _Version(item, ref, source, probe, "ready")


def _build_missing(
    jobs: JobSupervisor, layer: _Layer, principal: Principal
) -> JobRecord | None:
    """Submit (or join) the ``preview`` job of a layer's missing previews.

    Its versions in the job are ``building`` from then on; one past the
    auto-build limits waits for ``Zbuduj podgląd`` (decision 6).
    """
    missing = [
        version
        for version in layer.versions[:MAX_LAYER_VERSIONS]
        if version.state == "needs_build"
        and version.source is not None
        and auto_build(version.source, version.probe)
    ]
    if not missing:
        return None
    params = {
        "refs": [version.ref for version in missing],
        "contents": [
            cast(PreviewSource, version.source).content_key for version in missing
        ],
        "force": False,
    }
    try:
        record = jobs.submit("preview", params=params, actor=principal)
    except (ValueError, IndexQueryError, NotFoundError) as error:
        logger.warning("Cannot build the previews of layer %s: %s", layer.key, error)
        return None
    building = set(record.params.get("contents", ()))
    for version in missing:
        if cast(PreviewSource, version.source).content_key in building:
            version.state = "building"
    return record


def _images(
    layer: _Layer, store: str, frame: Extent | None, resolver: ObjectResolver
) -> LayerImages:
    """Return what a layer's images are drawn from: its ready versions."""
    listed = layer.versions[:MAX_LAYER_VERSIONS]
    ready = [version for version in reversed(listed) if version.state == "ready"]
    items = tuple(
        LayerItem(
            source=cast(PreviewSource, version.source),
            bounds=version.item.bounds,
            resolve=functools.partial(
                resolver.version_source, store, version.item, on_disk=True
            ),
        )
        for version in ready
    )
    probes = [cast(PreviewProbe, version.probe) for version in ready]
    styles = sorted({style for probe in probes for style in probe.styles})
    defaults = Counter(probe.default_style for probe in probes if probe.default_style)
    default = min(defaults, key=lambda style: (-defaults[style], style), default=None)
    bounds = [version.item.bounds for version in listed if version.item.bounds]
    return LayerImages(
        key=layer.key,
        digest=_digest(item.source.content_key for item in items),
        items=items,
        styles=tuple(styles),
        default_style=default,
        frame=frame,
        minzoom=_minzoom(bounds),
        bounds=_union(bounds),
    )


def _model(
    layer: _Layer,
    query: LayersQuery,
    record: AreaRecord | None,
    mover: PlanarMover | None,
    region: Any,
    images: LayerImages | None,
    job: JobRecord | None,
) -> Layer:
    """Return the model of a layer (with an area: coverage, outlines, previews)."""
    versions = layer.versions
    listed = versions[:MAX_LAYER_VERSIONS]
    items = [version.item for version in versions]
    segments = Counter(item.segment or "" for item in items)
    names = {item.segment or "": item.segment_name for item in items}
    main = min(segments, key=lambda name: (-segments[name], name))
    coverage = None
    outlines = None
    if mover is not None and region is not None:
        footprints = [mover.footprint(_shape(item)) for item in items]
        coverage = _coverage(region, footprints, mover.crs)
        refs = [version.ref for version in listed]
        outlines = _outlines(footprints[: len(listed)], refs)
    preview = None
    versions_out = None
    if record is not None and images is not None:
        preview = _preview(layer, query, images, job)
        versions_out = [_version_model(version) for version in listed]
    return Layer(
        key=layer.key,
        variant=LayerVariant(
            product=_common(item.product for item in items),
            horizontal_crs=_common(item.horizontal_crs for item in items),
            resolution=_common(item.resolution for item in items),
            vertical_crs=_common(item.vertical_crs for item in items),
            segments=sorted(name for name in segments if name),
            formats=sorted({_format(item.path) for item in items}),
        ),
        kind=layer.kind,
        year=layer.year,
        title=_title(layer),
        subtitle=names[main],
        versions_count=len(items),
        units_count=len({item.unit or item.slot for item in items}),
        campaigns=sorted({item.campaign for item in items if item.campaign}),
        data_dates=sorted({item.data_date for item in items if item.data_date}),
        coverage=coverage,
        outlines=outlines,
        preview=preview,
        versions=versions_out,
    )


def _preview(
    layer: _Layer, query: LayersQuery, images: LayerImages, job: JobRecord | None
) -> LayerPreview:
    listed = layer.versions[:MAX_LAYER_VERSIONS]
    ready = sum(version.state == "ready" for version in listed)
    total = sum(version.state != "unavailable" for version in listed)
    state: PreviewState
    if total == 0:
        state = "unavailable"
    elif ready == total:
        state = "ready"
    elif any(version.state == "building" for version in listed):
        state = "building"
    else:
        state = "needs_build"
    address = urlencode(_address(query, layer.key, images.digest))
    base = f"{API_PREFIX}/local-layers"
    return LayerPreview(
        state=state,
        ready=ready,
        total=total,
        job=None if job is None else PreviewJob.of(job),
        thumbnail_url=None
        if images.frame is None
        else f"{base}/thumbnail.png?{address}",
        tiles_url=(
            None
            if images.minzoom is None
            else f"{base}/tiles/{{z}}/{{x}}/{{y}}.png?{address}"
        ),
        minzoom=images.minzoom,
    )


def _version_model(version: _Version) -> LayerVersion:
    probe = version.probe
    tiles = (
        version.state == "ready"
        and probe is not None
        and probe.minzoom is not None
        and probe.maxzoom is not None
    )
    item = version.item
    return LayerVersion(
        ref=version.ref,
        slot=item.slot,
        unit=item.unit,
        preview=LayerVersionPreview(
            state=version.state,
            tiles_url=(
                f"{object_url(VersionRef(_store(version.ref), item.path))}"
                "/tiles/{z}/{x}/{y}.png"
                if tiles
                else None
            ),
        ),
        bounds=None if item.bounds is None else list(item.bounds),
    )


# Own-data layers.


@dataclass(frozen=True, slots=True)
class _OwnObject:
    """A working file or one of its snapshots, with its extent from the index.

    ``native`` is its extent in ``crs`` (the scan's, or the snapshot
    document's), ``wgs84`` its WGS84 outline; ``note`` a snapshot's.
    """

    ref: FileRef | SnapshotRef
    crs: str | None
    native: BBox | None
    wgs84: GeoJSONGeometry | None
    note: str = ""


def _own_objects(detail: OwnFileDetail) -> list[_OwnObject]:
    """Return the working file, then its snapshots newest first (the index's)."""
    project, path = detail.folder.project, detail.file.path
    found = [
        _OwnObject(
            FileRef(project, path), detail.native_crs, detail.native_bbox, detail.wgs84
        )
    ]
    for record in detail.snapshots:
        document = _snapshot_document(record)
        extent = None if document is None else document.extent
        wgs84 = None if extent is None else extent.wgs84
        found.append(
            _OwnObject(
                SnapshotRef(project, record.label, path),
                None if extent is None else extent.crs,
                None if extent is None else extent.bbox,
                None if wgs84 is None else box_geometry(wgs84),
                "" if document is None else document.note,
            )
        )
    return found


def _snapshot_document(record: SnapshotRecord) -> SnapshotDocument | None:
    """Return a snapshot's ``migawka.json`` as indexed; ``None`` if not valid."""
    if record.document is None:
        return None
    try:
        return SnapshotDocument.model_validate(record.document)
    except ValidationError:
        return None


def _own_frame(
    registry: PluginRegistry, objects: Sequence[_OwnObject]
) -> tuple[Extent | None, list[Any]]:
    """Return the frame of an own file's layers and each object's extent in it.

    The CRS is the planar one of the objects' country, as an area's (PL:
    EPSG:2180, CZ: EPSG:5514); the frame holds every extent moved there
    (``_framed``). An object whose extent cannot be moved there has none
    (``None``) and no thumbnail: its render could not be framed either.
    """
    outlines = [polygon_bounds(item.wgs84) for item in objects if item.wgs84]
    bounds = _union([box for box in outlines if box is not None])
    if bounds is None:
        return None, [None] * len(objects)
    adapter = geo_adapter(registry)
    try:
        crs = area_crs(adapter.countries(bounds))
    except ProducerError as error:
        logger.info("No country of the own data at %s: %s", bounds, error)
        crs = None
    if crs is None:
        return None, [None] * len(objects)
    mover = PlanarMover(crs, adapter.transformer)
    footprints = [_own_footprint(mover, item) for item in objects]
    placed = _union([found.bounds for found in footprints if found is not None])
    if placed is None:
        return None, footprints
    return Extent(_framed(placed), crs), footprints


def _own_footprint(mover: PlanarMover, item: _OwnObject) -> Any:
    """Return an object's extent in the frame's CRS, from its native one if known."""
    try:
        if item.native is not None and item.crs is not None:
            return mover.move(box_geometry(item.native), item.crs)
        if item.wgs84 is not None:
            return mover.move(item.wgs84, WGS84)
    except (ProducerError, ValueError) as error:
        logger.info("No extent of %s in %s: %s", format_ref(item.ref), mover.crs, error)
    return None


def _framed(bounds: BBox) -> BBox:
    """Return the frame around extents, rounded outward to centimetres.

    Each side is at least a tenth of the longer one and ``_FRAME_MIN_M`` (no
    ribbon of one pixel for a straight pipe, a square for one point), with
    room for a marker on an extent's edge (``_EDGE_REACH_PX``) in the
    smallest thumbnail.
    """
    min_x, min_y, max_x, max_y = bounds
    side = max(max(max_x - min_x, max_y - min_y) / 10.0, _FRAME_MIN_M)
    width, height = max(max_x - min_x, side), max(max_y - min_y, side)
    pad = max(width, height) * _EDGE_REACH_PX / min(THUMBNAIL_SIZES)
    half_width, half_height = width / 2.0 + pad, height / 2.0 + pad
    centre_x, centre_y = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0
    scale = 10**_OUTLINE_DECIMALS
    # Float noise (``…0000001``) is no centimetre more.
    return (
        math.floor(round((centre_x - half_width) * scale, 6)) / scale,
        math.floor(round((centre_y - half_height) * scale, 6)) / scale,
        math.ceil(round((centre_x + half_width) * scale, 6)) / scale,
        math.ceil(round((centre_y + half_height) * scale, 6)) / scale,
    )


async def _own_info(
    previews: PreviewService, ref: FileRef | SnapshotRef, principal: Principal
) -> PreviewInfo | None:
    """Return an object's preview as its route does; ``None``: not to be read.

    A file linked out of its root, or of a data folder that breaks the rules
    of a scan now: its own routes refuse it (``403``, ``409``).
    """
    try:
        return await previews.info(format_ref(ref), principal=principal)
    except (PathOutsideRootError, OwnFolderInvalidError):
        return None


def _own_layer(
    item: _OwnObject,
    info: PreviewInfo | None,
    frame: Extent | None,
    footprint: Any,
    *,
    path: str,
    badge: str,
) -> Layer:
    """Return the layer of one object of an own file."""
    ref = format_ref(item.ref)
    kind: LayerKind = "file"
    key, title = "file", message("layer.title_working")
    if isinstance(item.ref, SnapshotRef):
        kind, key = "snapshot", f"snapshot:{item.ref.label}"
        title = message("layer.title_snapshot", label=item.ref.label)
    subtitle = path
    if item.note:
        subtitle = message("layer.subtitle_note", path=path, note=item.note)
    preview = _own_preview(info, None if footprint is None else frame)
    placed = [] if footprint is None else [footprint]
    bounds = None if item.wgs84 is None else polygon_bounds(item.wgs84)
    return Layer(
        key=key,
        variant=LayerVariant(
            product=None,
            horizontal_crs=item.crs,
            resolution=None,
            vertical_crs=None,
            segments=[],
            formats=[badge],
        ),
        kind=kind,
        year=None,
        title=title,
        subtitle=subtitle,
        versions_count=1,
        units_count=1,
        campaigns=[],
        data_dates=[],
        coverage=None,
        outlines=None if frame is None else _outlines(placed, [ref] * len(placed)),
        preview=preview,
        versions=[
            LayerVersion(
                ref=ref,
                slot=path,
                unit=None,
                preview=LayerVersionPreview(
                    state=preview.state, tiles_url=preview.tiles_url
                ),
                bounds=None if bounds is None else list(bounds),
            )
        ],
    )


def _own_preview(info: PreviewInfo | None, frame: Extent | None) -> LayerPreview:
    """Return an object's preview as a layer's: its thumbnail in ``frame``.

    Its tiles only once ready: before its build they would be ``409``.
    """
    if info is None:
        return LayerPreview(
            state="unavailable",
            ready=0,
            total=0,
            job=None,
            thumbnail_url=None,
            tiles_url=None,
            minzoom=None,
        )
    thumbnail = None
    if frame is not None and info.thumbnail_url is not None:
        box = ",".join(str(value) for value in frame.bbox)
        thumbnail = (
            f"{info.thumbnail_url}?{urlencode({'bbox': box, 'bbox_crs': frame.crs})}"
        )
    tiles = info.tiles_url if info.state == "ready" else None
    return LayerPreview(
        state=info.state,
        ready=int(info.state == "ready"),
        total=int(info.state != "unavailable"),
        job=info.job,
        thumbnail_url=thumbnail,
        tiles_url=tiles,
        minzoom=None if tiles is None else info.minzoom,
    )


# Drawing.


async def _draw(
    pool: RenderPool,
    op: str,
    items: Sequence[LayerItem],
    params: JsonObject,
    *,
    final: bool,
    if_none_match: str | None,
) -> LayerPayload:
    """Return a composite from the cache, else drawn from the resolved files."""
    target = OPERATIONS[op].target
    if target is None:  # pragma: no cover - both layer operations are kept
        raise ValueError(f"{op} is not kept in the preview cache")
    located = {**params, "versions": _versions(items, [item.source for item in items])}
    key, name = cast(tuple[CacheKey, str], target(None, located))
    etag = _etag(f"{key.directory}/{name}")
    if _matches(if_none_match, etag):
        return LayerPayload(None, etag, final)
    data = await asyncio.to_thread(_cached, pool.cache, key, name)
    if data is not None:
        return LayerPayload(data, etag, final)
    drawn, sources = await asyncio.to_thread(_resolved, items)
    request = {**params, "versions": _versions(drawn, sources)}
    result = await pool.arequest(op, None, request)
    if len(drawn) != len(items):
        key, name = cast(tuple[CacheKey, str], target(None, request))
        etag, final = _etag(f"{key.directory}/{name}"), False
    return LayerPayload(result.data, etag, final)


def _resolved(
    items: Sequence[LayerItem],
) -> tuple[list[LayerItem], list[PreviewSource]]:
    """Resolve the versions' files; one gone or leaving its root is left out.

    Raises
    ------
    SourceUnavailableError
        The store is out of reach: nothing can be drawn now.
    """
    drawn: list[LayerItem] = []
    sources: list[PreviewSource] = []
    for item in items:
        try:
            source = item.resolve()
        except (PathOutsideRootError, PreviewUnavailableError, NotFoundError):
            continue
        drawn.append(item)
        sources.append(source)
    return drawn, sources


def _versions(
    items: Sequence[LayerItem], sources: Sequence[PreviewSource]
) -> list[JsonObject]:
    return [
        {
            "source": source.to_json(),
            "bounds": None if item.bounds is None else list(item.bounds),
        }
        for item, source in zip(items, sources, strict=True)
    ]


def _style(images: LayerImages, style: str | None) -> str:
    """Return the style asked for, else the versions' usual one."""
    if style is None:
        return images.default_style or (
            images.styles[0] if images.styles else _NO_STYLE
        )
    if images.styles and style not in images.styles:
        text = message(
            "layer.style_unknown", style=style, styles=", ".join(images.styles)
        )
        raise PreviewParameterError("query.style", text)
    return style


# Helpers.


def _area(queries: IndexQueries, area_id: str | None) -> AreaRecord | None:
    if area_id is None:
        return None
    record = queries.area(area_id)
    if record is None:
        raise IndexQueryError(message("api.area_unknown", area=area_id))
    return record


def _require_store(settings: AppSettings, store: str) -> None:
    if settings.store(store) is None:
        text = message("api.store_not_configured", store=store)
        raise IndexQueryError(text)


def _frame(mover: PlanarMover, record: AreaRecord) -> tuple[Any, Extent]:
    """Return the area in its planar CRS and its box there."""
    region = shapely.make_valid(mover.move(record.geometry, WGS84))
    min_x, min_y, max_x, max_y = (
        round(value, _OUTLINE_DECIMALS) for value in region.bounds
    )
    return region, Extent((min_x, min_y, max_x, max_y), mover.crs)


def _variant(item: ProductVersion) -> str:
    """Return a version's variant: a digest of its key, else its segment."""
    fields = (item.product, item.horizontal_crs, item.resolution, item.vertical_crs)
    if all(fields):
        text = "\n".join(cast(tuple[str, str, str, str], fields))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_VARIANT_CHARS]
    return item.segment or ""


def _period(item: ProductVersion) -> tuple[LayerKind, int | None, str]:
    """Return a version's layer kind, data year and key part."""
    if item.data_year is not None:
        return "year", item.data_year, str(item.data_year)
    if item.edition:
        return "edition", None, item.edition
    return "label", None, item.label or ""


def _age(version: _Version) -> tuple[date, float, str]:
    """Order versions by their data, then by download, then by path."""
    item = version.item
    downloaded = item.downloaded_at
    return (
        item.data_date or date.min,
        -math.inf if downloaded is None else downloaded.timestamp(),
        item.path,
    )


def _newness(layer: _Layer) -> tuple[int, str, str]:
    """Order layers newest first: data year, edition or label, campaign."""
    if layer.year is not None:
        year = layer.year
    else:
        dates = [version.item.data_date for version in layer.versions]
        year = max((found.year for found in dates if found), default=-1)
    return year, layer.part, layer.campaign or ""


def _title(layer: _Layer) -> str:
    if layer.period == "year":
        title = message("layer.title_year", year=layer.year)
    elif layer.period == "edition":
        title = message("layer.title_edition", edition=layer.part)
    elif layer.part:
        title = message("layer.title_label", label=layer.part)
    else:
        title = message("layer.title_undated")
    if layer.campaign:
        return message("layer.title_campaign", title=title, campaign=layer.campaign)
    return title


def _shape(item: ProductVersion) -> CoverageShape:
    native = item.native
    return CoverageShape(
        cast(dict[str, Any], item.outline),
        native,
        item.native_crs if native is not None else None,
    )


def _coverage(region: Any, footprints: Sequence[Any], crs: str) -> LayerCoverage:
    """Return the share of the area under the footprints (like ``/local-coverage``)."""
    measure = measure_planar(region, footprints)
    empty = measure.area_km2 <= 0
    item = LocalCoverage(
        country=None,
        crs=crs,
        ratio=None if empty else min(1.0, measure.covered_km2 / measure.area_km2),
        area_km2=measure.area_km2,
        covered_km2=None if empty else measure.covered_km2,
        versions_count=measure.footprints,
        reason="empty_area" if empty else None,
    )
    return LayerCoverage.of(CountryCoverage.of(item))


def _outlines(footprints: Sequence[Any], refs: Sequence[str]) -> dict[str, Any]:
    """Return outlines in the frame's CRS as a GeoJSON collection, by ``ref``."""
    features = []
    for footprint, ref in zip(footprints, refs, strict=True):
        rounded = shapely.transform(
            footprint, lambda points: points.round(_OUTLINE_DECIMALS)
        )
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(rounded),
                "properties": {"ref": ref},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _minzoom(bounds: Sequence[BBox]) -> int | None:
    """Return the zoom from which a typical sheet has ``SHEET_MIN_PX`` pixels."""
    sizes = [size for size in (_pixels(box) for box in bounds) if size > 0]
    if not sizes:
        return None
    typical = statistics.median(sizes)
    return max(0, min(22, math.ceil(math.log2(SHEET_MIN_PX / typical) - 1e-9)))


def _pixels(bounds: BBox) -> float:
    """Return the shorter side of an extent in pixels of a zoom 0 tile."""
    west, south, east, north = bounds
    across = (east - west) / 360.0 * _TILE_PX
    down = (_mercator(north) - _mercator(south)) / (2 * math.pi) * _TILE_PX
    return min(across, down)


def _mercator(latitude: float) -> float:
    clamped = max(-85.05112878, min(85.05112878, latitude))
    return math.log(math.tan(math.pi / 4 + math.radians(clamped) / 2))


def _union(bounds: Sequence[BBox]) -> BBox | None:
    if not bounds:
        return None
    return (
        min(box[0] for box in bounds),
        min(box[1] for box in bounds),
        max(box[2] for box in bounds),
        max(box[3] for box in bounds),
    )


def _meets(tile: BBox, bounds: BBox) -> bool:
    """Whether a tile meets an extent (touching counts: MapLibre asks for it)."""
    west, south, east, north = tile
    return (
        west <= bounds[2]
        and east >= bounds[0]
        and south <= bounds[3]
        and north >= bounds[1]
    )


def _overlaps(tile: BBox, bounds: BBox) -> bool:
    """Whether an extent shares interior with a tile (``compose``'s choice)."""
    west, south, east, north = tile
    return (
        bounds[0] < east
        and bounds[2] > west
        and bounds[1] < north
        and bounds[3] > south
    )


def _shares_interior(region: Any, outline: dict[str, Any]) -> bool:
    geometry = shape(outline)
    return bool(
        shapely.intersects(region, geometry) and not shapely.touches(region, geometry)
    )


def _common(values: Any) -> str | None:
    """Return the one value all versions share, else ``None``."""
    found = set(values)
    return found.pop() if len(found) == 1 else None


def _format(path: str) -> str:
    """Return the name of a file's format, a badge of its layer."""
    found = file_format(path)
    if found is UNKNOWN_FORMAT:
        return Path(path).suffix.lstrip(".").upper() or found.name
    return found.name


def _digest(contents: Any) -> str:
    text = "\n".join(sorted(contents))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_DIGEST_CHARS]


def _address(query: LayersQuery, layer: str, digest: str) -> list[tuple[str, str]]:
    """Return the query of a layer's images: its ``LayerSet``'s, the key, ``v``."""
    params = [("store", query.store), ("product", query.product)]
    if query.area_id is not None:
        params.append(("area_id", query.area_id))
    if query.segment is not None:
        params.append(("segment", query.segment))
    params += [("group", query.group), ("layer", layer), ("v", digest)]
    return params


def _memo_key(query: LayersQuery, layer: str, v: str | None) -> _MemoKey:
    return (
        query.store,
        query.product,
        query.area_id or "",
        query.segment,
        query.group,
        layer,
        v,
    )


def _store(ref: str) -> str:
    return ref.split(":", 2)[1]


def _probe(cache: PreviewCache, key: CacheKey) -> PreviewProbe | None:
    data = _cached(cache, key, INFO_NAME)
    if data is None:
        return None
    try:
        return PreviewProbe.from_bytes(data)
    except ValueError:  # a damaged object: probed again by the job
        return None


def _cached(cache: PreviewCache, key: CacheKey, name: str) -> bytes | None:
    """Return a small file of the cache; a broken cache is a miss."""
    try:
        return cache.get(key, name)
    except (OSError, sqlite3.Error):
        logger.exception("Reading the preview cache failed")
        return None


def _has(cache: PreviewCache, key: CacheKey, name: str) -> bool:
    try:
        return cache.has(key, name)
    except (OSError, sqlite3.Error):
        logger.exception("Reading the preview cache failed")
        return False


def _etag(basis: str) -> str:
    """Return a strong ``ETag`` naming what an image holds (as the version routes)."""
    return '"' + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32] + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    """Whether ``If-None-Match`` names ``etag`` (weak tags and ``*`` too)."""
    if if_none_match is None:
        return False
    return any(
        tag == "*" or tag.removeprefix("W/") == etag
        for tag in (item.strip() for item in if_none_match.split(","))
    )
