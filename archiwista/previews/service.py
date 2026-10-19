"""Previews of objects for the API and the command line (plan v0.2, step 6).

``PreviewService`` answers the preview routes and ``archiwista preview`` for
an object named by its ``ref`` (``archiwista.refs``), always in this order:

1. the object is found and its visibility decided (``ObjectResolver``);
2. the preview cache answers what it holds — for a version with a
   ``sha256`` without touching its store, so a disconnected store still
   shows what was rendered before;
3. only then is the file resolved inside its root (a link leaving it is
   ``403 path_outside_root``, a store out of reach ``503
   store_unavailable``) and rendered by the ``RenderPool``; the server never
   opens a data file itself.

``info`` gives the object's ``PreviewInfo``: its state, reason, styles,
legend and the addresses of its images. ``thumbnail``, ``tile``,
``features`` and ``members`` give images and data with their ``ETag``, which
names what they hold (the content, the renderer's version, the parameters),
so a client's ``If-None-Match`` is answered before anything is read or
rendered. Parameters are checked against the file: a style of its
``styles`` (``422``), a tile within its zoom range and extent (``404``), map
tiles only after their local COG is built (``409 preview_not_ready``).
``build`` submits the ``preview`` job of what files need built, joining a
job that builds them already.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote

from archiwista.api import API_PREFIX
from archiwista.api.models_previews import (
    PreviewInfo,
    PreviewJob,
    PreviewReasonInfo,
    legend_model,
)
from archiwista.auth import Principal
from archiwista.errors import (
    NotFoundError,
    PreviewBusyError,
    PreviewNotReadyError,
    PreviewParameterError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    SourceUnavailableError,
)
from archiwista.formats import file_format
from archiwista.index import MAX_PAGE_LIMIT
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import MESSAGES
from archiwista.previews.cache import INFO_NAME, CacheKey, cache_key
from archiwista.previews.legends import legend
from archiwista.previews.pool import RETRY_AFTER_S, RenderPool
from archiwista.previews.types import (
    PREVIEW_REASONS,
    JsonObject,
    PreviewKind,
    PreviewProbe,
    PreviewReason,
    PreviewSource,
    PreviewState,
    auto_build,
    build_product,
)
from archiwista.previews.worker import OPERATIONS
from archiwista.refs import (
    ObjectRef,
    ObjectResolver,
    VersionRef,
    format_ref,
    parse_ref,
)

# Reasons after which a file shows nothing but its metadata.
NOTHING_SHOWN: frozenset[PreviewReason] = frozenset(
    {
        "unreadable",
        "unsupported_format",
        "document_no_preview",
        "auxiliary_file",
        "too_large",
        "missing_file",
        "store_unavailable",
        "changed_since_scan",
    }
)
# Reasons of a load or a moment: the preview ``failed`` and may succeed later.
FAILURES: frozenset[PreviewReason] = frozenset({"timeout", "memory_limit"})

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Payload:
    """An image or data with its ``ETag``.

    ``data`` is ``None`` when the client holds it already (its
    ``If-None-Match`` names the ``etag``): answer ``304``.
    """

    data: bytes | None
    etag: str


@dataclass(frozen=True, slots=True)
class _Located:
    """An object as the index knows it: its reference and source."""

    ref: ObjectRef
    text: str
    source: PreviewSource


class PreviewService:
    """Previews of objects by reference (see the module).

    Parameters
    ----------
    pool : RenderPool
        The started render pool; its preview cache is the one used.
    resolver : ObjectResolver
        From references to files.
    jobs : JobSupervisor or None, optional
        The started job supervisor: the ``preview`` jobs building a file
        (``job`` of ``PreviewInfo``) and ``build``. Without one (the
        command line without ``--build``) no job is named, and ``build``
        refuses (``PreviewBusyError``).

    Notes
    -----
    Methods are coroutines: index, cache and file system calls run in
    threads, renders are awaited (``RenderPool.arequest``), so cancelling a
    call (the client went away) gives its render request up.
    """

    def __init__(
        self,
        pool: RenderPool,
        resolver: ObjectResolver,
        jobs: JobSupervisor | None = None,
    ) -> None:
        self._pool = pool
        self._cache = pool.cache
        self._resolver = resolver
        self._jobs = jobs

    async def info(self, ref: str, *, principal: Principal) -> PreviewInfo:
        """Return the preview of an object (``GET …/preview``).

        A file that cannot be reached, or whose probe failed, is described
        with its reason (``store_unavailable``, ``missing_file``,
        ``timeout``…) rather than refused.

        Raises
        ------
        InvalidRefError
            Not a reference (``422 invalid_ref``).
        NotFoundError
            An unknown object, or one the principal does not see.
        PathOutsideRootError
            Its file resolves outside its root.
        PreviewBusyError
            The render queue is full.
        """
        parsed = parse_ref(ref)
        text = format_ref(parsed)
        try:
            located = await self._locate(parsed, principal)
        except SourceUnavailableError:
            return _unavailable(text, _kind(parsed), "store_unavailable")
        except PreviewUnavailableError as error:
            return _unavailable(
                text, _kind(parsed), _reason(error.reason), error.detail
            )
        source = located.source
        try:
            probe, detail = await self._probe(located, principal)
        except SourceUnavailableError:
            return _unavailable(text, source.kind, "store_unavailable", source=source)
        except PreviewTimeoutError:
            return _unavailable(text, source.kind, "timeout", source=source)
        except PreviewUnavailableError as error:
            code = _reason(error.reason)
            return _unavailable(text, source.kind, code, error.detail, source=source)
        return await self._described(located, probe, detail)

    async def thumbnail(
        self,
        ref: str,
        *,
        principal: Principal,
        style: str | None,
        size: int,
        frame: JsonObject | None = None,
        if_none_match: str | None = None,
    ) -> Payload:
        """Return the PNG thumbnail of an object (``GET …/preview.png``).

        Parameters
        ----------
        ref : str
            The object.
        principal : Principal
            Who asks.
        style : str or None
            One of the file's ``styles``; its default style when ``None``.
        size : int
            Longest side in pixels (128, 256, 512, 1024; checked by the
            route).
        frame : dict or None, optional
            ``{"bbox": [min_x, min_y, max_x, max_y], "crs": "EPSG:…"}``.
        if_none_match : str or None, optional
            The client's ``If-None-Match``.

        Raises
        ------
        PreviewParameterError
            A style the file does not have.
        PreviewUnavailableError
            The file has no thumbnail (its reason).
        SourceUnavailableError
            Not in the cache, and the store is out of reach.
        """
        located = await self._locate(parse_ref(ref), principal)
        probe, _ = await self._probe(located, principal)
        _require_shown(probe)
        params: JsonObject = {"style": _style(probe, style), "size": size}
        if frame is not None:
            params["frame"] = frame
        return await self._image("thumbnail", located, params, principal, if_none_match)

    async def tile(
        self,
        ref: str,
        *,
        principal: Principal,
        z: int,
        x: int,
        y: int,
        style: str | None,
        rescale: list[float] | None = None,
        if_none_match: str | None = None,
    ) -> Payload:
        """Return the PNG map tile ``z/x/y`` of an object (EPSG:3857).

        ``x`` and ``y`` are within ``0 … 2^z - 1`` (checked by the route).

        Raises
        ------
        PreviewParameterError
            A style the file does not have.
        PreviewUnavailableError
            The file has no map preview (its reason, e.g. ``no_georeference``).
        NotFoundError
            The tile is outside the file's zoom range or extent.
        PreviewNotReadyError
            The file's local COG is not built yet (the job building it, if
            any).
        SourceUnavailableError
            Not in the cache, and the store is out of reach.
        """
        located = await self._locate(parse_ref(ref), principal)
        probe, _ = await self._probe(located, principal)
        _require_shown(probe)
        if probe.reason is not None:
            raise PreviewUnavailableError(probe.reason)
        params: JsonObject = {"style": _style(probe, style), "z": z, "x": x, "y": y}
        bounds, minzoom, maxzoom = probe.bbox_wgs84, probe.minzoom, probe.maxzoom
        if bounds is None or minzoom is None or maxzoom is None:
            raise PreviewUnavailableError("no_georeference")
        if not (minzoom <= z <= maxzoom and _meets(tile_bounds(z, x, y), bounds)):
            message = MESSAGES["preview_tile_outside"].format(
                z=z, x=x, y=y, minzoom=minzoom, maxzoom=maxzoom
            )
            raise NotFoundError(message)
        await self._require_built(located.source, probe)
        if rescale is not None:
            params["rescale"] = rescale
        return await self._image("tile", located, params, principal, if_none_match)

    async def features(
        self,
        ref: str,
        *,
        principal: Principal,
        bbox: list[float],
        zoom: int,
        layer: str | None = None,
        limit: int,
        if_none_match: str | None = None,
    ) -> Payload:
        """Return the features of a map view as GeoJSON in WGS84 (``…/features``).

        At most ``limit`` features simplified to ``zoom``, with
        ``number_matched``, ``truncated`` and ``simplified`` (decision 4).

        Raises
        ------
        PreviewParameterError
            A layer the file does not have.
        PreviewUnavailableError
            Not a vector file with a map preview (its reason).
        """
        located = await self._locate(parse_ref(ref), principal)
        probe, _ = await self._probe(located, principal)
        _require_shown(probe)
        if probe.kind != "vector" or probe.reason is not None:
            raise PreviewUnavailableError(probe.reason or "unsupported_format")
        if probe.bbox_wgs84 is None:
            raise PreviewUnavailableError("no_crs")
        names = [str(item.get("name")) for item in probe.layers]
        if layer is not None and layer not in names:
            message = MESSAGES["preview_layer_unknown"].format(
                layer=layer, layers=", ".join(names) or MESSAGES["preview_none"]
            )
            raise PreviewParameterError("query.layer", message)
        await self._require_built(located.source, probe)
        params: JsonObject = {
            "layer": layer,
            "bbox": bbox,
            "zoom": zoom,
            "limit": limit,
        }
        return await self._data("features", located, params, principal, if_none_match)

    async def members(
        self, ref: str, *, principal: Principal, if_none_match: str | None = None
    ) -> Payload:
        """Return the members of an archive (``…/members``) as JSON.

        ``total``, ``truncated`` and ``members`` (name, sizes, directory,
        format and kind by the name), read without unpacking.

        Raises
        ------
        PreviewUnavailableError
            Not an archive whose members can be listed (``too_large``…).
        """
        located = await self._locate(parse_ref(ref), principal)
        probe, _ = await self._probe(located, principal)
        if probe.kind != "archive" or probe.reason != "archive_members_only":
            raise PreviewUnavailableError(probe.reason or "unsupported_format")
        return await self._data("members", located, {}, principal, if_none_match)

    async def plan_build(
        self, refs: Sequence[str], *, principal: Principal, force: bool
    ) -> JsonObject | None:
        """Return the ``preview`` job's parameters for what the files need built.

        A file needing nothing (no local COG, built already, nothing to
        show) is left out, and so is one past the auto-build limits without
        ``force``.

        Returns
        -------
        dict or None
            ``refs``, their ``contents`` and ``force``; ``None`` when no
            file needs a build.

        Raises
        ------
        PreviewUnavailableError
            ``too_large``: every file needing a build is past the limits
            and ``force`` is off; or a file that cannot be reached.
        SourceUnavailableError
            A file's store is out of reach.
        """
        chosen: list[str] = []
        contents: list[str] = []
        too_large = False
        for ref in refs:
            located = await self._locate(parse_ref(ref), principal)
            probe, _ = await self._probe(located, principal)
            if probe.reason in NOTHING_SHOWN or await self._built(
                located.source, probe
            ):
                continue
            if not force and not auto_build(located.source, probe):
                too_large = True
                continue
            chosen.append(located.text)
            contents.append(located.source.content_key)
        if not chosen:
            if too_large:
                raise PreviewUnavailableError("too_large")
            return None
        return {"refs": chosen, "contents": contents, "force": force}

    async def build(
        self, refs: Sequence[str], *, principal: Principal, force: bool
    ) -> JobRecord | None:
        """Build what files need (``POST …/preview``) in the ``preview`` job.

        Returns
        -------
        JobRecord or None
            The job (new, or one building the same contents that the
            request joined); ``None`` when no file needs a build.

        Raises
        ------
        PreviewBusyError
            No job supervisor runs (the server is stopping).
        """
        params = await self.plan_build(refs, principal=principal, force=force)
        if params is None:
            return None
        jobs = self._jobs
        if jobs is None:
            raise PreviewBusyError(
                MESSAGES["preview_closed"], retry_after_s=RETRY_AFTER_S
            )
        return await asyncio.to_thread(
            jobs.submit, "preview", params=params, actor=principal
        )

    # Steps of every answer.

    async def _locate(self, ref: ObjectRef, principal: Principal) -> _Located:
        source = await asyncio.to_thread(
            self._resolver.locate, ref, principal=principal
        )
        return _Located(ref, format_ref(ref), source)

    async def _resolve(self, located: _Located, principal: Principal) -> PreviewSource:
        return await asyncio.to_thread(
            self._resolver.resolve, located.ref, principal=principal
        )

    async def _probe(
        self, located: _Located, principal: Principal
    ) -> tuple[PreviewProbe, str | None]:
        """Return the file's probe from the cache, else from a render process.

        The second value is the library's message of a probe that found a
        lasting reason now, else ``None``.
        """
        data = await asyncio.to_thread(
            self._cached, cache_key(located.source), INFO_NAME
        )
        if data is not None:
            with contextlib.suppress(ValueError):  # a damaged object: probe again
                return PreviewProbe.from_bytes(data), None
        source = await self._resolve(located, principal)
        result = await self._pool.arequest("probe", source)
        return result.probe(), result.detail

    async def _image(
        self,
        op: str,
        located: _Located,
        params: JsonObject,
        principal: Principal,
        if_none_match: str | None,
    ) -> Payload:
        """Return a cached image of an operation, or render it from the file."""
        target = OPERATIONS[op].target
        if target is None:  # pragma: no cover - thumbnails and tiles are kept
            raise ValueError(f"{op} is not kept in the preview cache")
        key, name = cast(tuple[CacheKey, str], target(located.source, params))
        etag = _etag(f"{key.directory}/{name}")
        if _matches(if_none_match, etag):
            return Payload(None, etag)
        data = await asyncio.to_thread(self._cached, key, name)
        if data is None:
            source = await self._resolve(located, principal)
            data = (await self._pool.arequest(op, source, params)).data
        return Payload(data, etag)

    async def _data(
        self,
        op: str,
        located: _Located,
        params: JsonObject,
        principal: Principal,
        if_none_match: str | None,
    ) -> Payload:
        """Return the JSON of an operation the cache does not keep."""
        basis = [op, str(cache_key(located.source).directory), params]
        etag = _etag(json.dumps(basis, sort_keys=True, separators=(",", ":")))
        if _matches(if_none_match, etag):
            return Payload(None, etag)
        source = await self._resolve(located, principal)
        result = await self._pool.arequest(op, source, params)
        return Payload(result.data, etag)

    async def _described(
        self, located: _Located, probe: PreviewProbe, detail: str | None
    ) -> PreviewInfo:
        source = located.source
        job: JobRecord | None = None
        built = await self._built(source, probe)
        if not built and probe.reason not in NOTHING_SHOWN:
            job = await asyncio.to_thread(self._active_job, source.content_key)
        state: PreviewState
        if probe.reason in NOTHING_SHOWN:
            state = "unavailable"
        elif built:
            state = "ready"
        else:
            state = "building" if job is not None else "needs_build"
        base = object_url(located.ref)
        shown = state != "unavailable"
        located_on_map = shown and probe.reason is None and probe.bbox_wgs84 is not None
        tiles = (
            located_on_map
            and bool(probe.styles)
            and probe.minzoom is not None
            and probe.maxzoom is not None
        )
        default = probe.default_style
        legends = {
            style: found
            for style in probe.styles
            if (found := legend_model(legend(probe, style))) is not None
        }
        return PreviewInfo(
            ref=located.text,
            state=state,
            kind=probe.kind,
            reason=None
            if probe.reason is None
            else PreviewReasonInfo.of(probe.reason, detail),
            styles=list(probe.styles),
            default_style=default,
            thumbnail_url=f"{base}/preview.png" if shown and probe.styles else None,
            tiles_url=f"{base}/tiles/{{z}}/{{x}}/{{y}}.png" if tiles else None,
            features_url=(
                f"{base}/features?bbox={{bbox}}&zoom={{zoom}}"
                if located_on_map and probe.kind == "vector"
                else None
            ),
            members_url=(
                f"{base}/members"
                if probe.kind == "archive" and probe.reason == "archive_members_only"
                else None
            ),
            bounds=None if probe.bbox_wgs84 is None else list(probe.bbox_wgs84),
            minzoom=probe.minzoom,
            maxzoom=probe.maxzoom,
            legend=None if default is None else legends.get(default),
            legends=legends,
            layers=list(probe.layers),
            points=probe.points,
            size_bytes=source.size_bytes,
            auto_build=auto_build(source, probe),
            job=None if job is None else PreviewJob.of(job),
        )

    async def _built(self, source: PreviewSource, probe: PreviewProbe) -> bool:
        """Whether what the file needs built (its local COG) is in the cache."""
        product = build_product(probe)
        if product is None:
            return True
        return await asyncio.to_thread(self._has, cache_key(source), product)

    async def _require_built(self, source: PreviewSource, probe: PreviewProbe) -> None:
        """Refuse a map preview whose local COG is not built yet."""
        if await self._built(source, probe):
            return
        job = await asyncio.to_thread(self._active_job, source.content_key)
        if job is None:
            raise PreviewNotReadyError(MESSAGES["preview_not_ready_build"])
        raise PreviewNotReadyError(
            MESSAGES["preview_not_ready_job"].format(job=job.id),
            job_id=job.id,
            kind=job.kind,
            state=job.state,
        )

    def _active_job(self, content_key: str) -> JobRecord | None:
        """Return the ``preview`` job building a content, running ones first."""
        if self._jobs is None:
            return None
        for state in ("running", "queued"):
            page = self._jobs.list(kind="preview", state=state, limit=MAX_PAGE_LIMIT)
            for record in page.items:
                if content_key in record.params.get("contents", ()):
                    return record
        return None

    def _cached(self, key: CacheKey, name: str) -> bytes | None:
        """Return a small file of the cache; a broken cache is a miss."""
        try:
            return self._cache.get(key, name)
        except (OSError, sqlite3.Error):
            logger.exception("Reading the preview cache failed")
            return None

    def _has(self, key: CacheKey, name: str) -> bool:
        try:
            return self._cache.has(key, name)
        except (OSError, sqlite3.Error):
            logger.exception("Reading the preview cache failed")
            return False


def object_url(ref: ObjectRef) -> str:
    """Return the address of an object's preview routes (without the route).

    Raises
    ------
    ValueError
        An object without preview routes yet (own data: step 9).
    """
    if isinstance(ref, VersionRef):
        store = quote(ref.store, safe="")
        return f"{API_PREFIX}/stores/{store}/versions/{quote(ref.path)}"
    raise ValueError(f"no preview routes of {format_ref(ref)}")


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return the WGS84 extent (west, south, east, north) of a map tile."""
    count = 2**z

    def latitude(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / count))))

    west = x / count * 360.0 - 180.0
    east = (x + 1) / count * 360.0 - 180.0
    return west, latitude(y + 1), east, latitude(y)


def _meets(
    tile: tuple[float, float, float, float], bounds: tuple[float, float, float, float]
) -> bool:
    """Whether a tile meets an extent (touching counts: MapLibre asks for it)."""
    west, south, east, north = tile
    return (
        west <= bounds[2]
        and east >= bounds[0]
        and south <= bounds[3]
        and north >= bounds[1]
    )


def _style(probe: PreviewProbe, style: str | None) -> str:
    """Return the style asked for, or the default one; refuse another one."""
    if style is None:
        chosen = probe.default_style or (probe.styles[0] if probe.styles else None)
        if chosen is None:
            raise PreviewUnavailableError(probe.reason or "unsupported_format")
        return chosen
    if style not in probe.styles:
        message = MESSAGES["preview_style_unknown"].format(
            style=style, styles=", ".join(probe.styles) or MESSAGES["preview_none"]
        )
        raise PreviewParameterError("query.style", message)
    return style


def _require_shown(probe: PreviewProbe) -> None:
    """Refuse a file whose probe found nothing to show."""
    if probe.reason is not None and probe.reason in NOTHING_SHOWN:
        raise PreviewUnavailableError(probe.reason)


def _reason(code: str) -> PreviewReason:
    """Return a reason code, an unknown one (a broken render) as ``unreadable``."""
    return code if code in PREVIEW_REASONS else "unreadable"


def _kind(ref: ObjectRef) -> PreviewKind:
    """Return the kind of an object's file by its name."""
    return file_format(ref.path).kind


def _unavailable(
    ref: str,
    kind: PreviewKind,
    code: PreviewReason,
    detail: str | None = None,
    *,
    source: PreviewSource | None = None,
) -> PreviewInfo:
    """Return the preview of an object that shows nothing now, with the reason."""
    return PreviewInfo(
        ref=ref,
        state="failed" if code in FAILURES else "unavailable",
        kind=kind,
        reason=PreviewReasonInfo.of(code, detail),
        styles=[],
        default_style=None,
        thumbnail_url=None,
        tiles_url=None,
        features_url=None,
        members_url=None,
        bounds=None,
        minzoom=None,
        maxzoom=None,
        legend=None,
        legends={},
        layers=[],
        points=None,
        size_bytes=None if source is None else source.size_bytes,
        auto_build=False,
        job=None,
    )


def _etag(basis: str) -> str:
    """Return a strong ``ETag`` naming what an answer holds."""
    return '"' + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32] + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    """Whether ``If-None-Match`` names ``etag`` (weak tags and ``*`` too)."""
    if if_none_match is None:
        return False
    for item in if_none_match.split(","):
        tag = item.strip()
        if tag == "*" or tag.removeprefix("W/") == etag:
            return True
    return False
