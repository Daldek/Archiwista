"""The ``preview_warm`` job: the first look at current versions prepared ahead.

``warm_previews`` runs in the job's worker process (``run_preview_warm`` of
``archiwista.jobs.worker``; SPEC 5.7, ADR-041). Its parameters, checked by the
supervisor, are the filters ``WARM_FILTERS``: ``store``, ``product``,
``segment``, ``project``, ``area_id`` and ``since`` (the scheduler's warm-up
after a scan), each ``None`` when not given. The job:

1. selects the current versions the filters admit and, with ``project``, the
   working files of the project's own data
   (``IndexQueries.warm_selection``), as the owner of the installation: the
   request was checked against the person who asked when it was submitted;
2. takes them in order and, for each, finds what a person's first look at
   it asks for (``first_look``: the pane's thumbnail in the default style,
   the map's tiles at the file's smallest zoom) and renders what the preview
   cache does not hold, in a render pool of its own (one render process) at
   the lowest CPU priority (``NICENESS``), so the server's render pool, which
   serves people, goes first. Whether the cache holds an object is no use of
   it (``PreviewCache.peek`` and ``has``), and a version with a ``sha256``
   the cache holds whole is ``cached`` without a read of its store;
3. before rendering, asks the cache how much it may add without evicting an
   object used in the last ``RECENT_S`` (``PreviewCache.room``): with less
   than ``RESERVE_BYTES`` (what the first look at one file takes at most) it
   stops, the versions it did not reach are ``skipped`` and the job says
   why (``stopped``: ``cache_full``) in its summary and a warning notice.

It never builds a local COG or a consistent copy: the ``preview`` job does,
at a person's first view or "Zbuduj podgląd". A file whose map tiles wait for
one gets its thumbnail only and counts in ``needs_build``. The job uses no
network, writes only the preview cache, and its render processes only read
the stores. A file that fails (unreadable, out of time, its store out of
reach, its data folder breaking the rules of a scan now:
``own_folder_invalid``) fails alone. Progress: ``current`` of ``total``
with ``warmed``, ``cached``, ``failed`` and ``skipped``, at most once a
second. The summary:
``versions`` and ``files`` selected, ``warmed`` (something rendered now),
``cached``, ``needs_build``, ``failed`` and its first ``MAX_LISTED_FAILURES``
``failures`` (``ref``, ``code``, Polish ``detail``), ``skipped``,
``stopped``, ``room_bytes`` (what puts may still add) and ``seconds``.
"""

import contextlib
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.config import AppPaths
from archiwista.errors import (
    InvalidRefError,
    NotFoundError,
    OwnFileChangedError,
    OwnFolderInvalidError,
    PathOutsideRootError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    SourceUnavailableError,
)
from archiwista.index import AreaFilter, IndexQueries, WarmQuery
from archiwista.jobs.protocol import JobSpec, JsonObject
from archiwista.messages import lookup, message, with_detail
from archiwista.previews.cache import INFO_NAME, CacheKey, PreviewCache, cache_key
from archiwista.previews.pool import RenderPool
from archiwista.previews.service import NOTHING_SHOWN, first_look
from archiwista.previews.types import PreviewProbe, PreviewSource, build_product
from archiwista.previews.worker import OPERATIONS
from archiwista.refs import FileRef, ObjectResolver, format_ref, version_ref

if TYPE_CHECKING:
    from archiwista.jobs.worker import Emitter

# An object used within this many seconds is never evicted for a warm-up.
RECENT_S = 7 * 24 * 3600.0
# Bytes the first look at one file takes at most: a 512-pixel thumbnail and
# up to nine 256-pixel tiles, each an RGBA PNG of incompressible data, and its
# probe.
RESERVE_BYTES = 4 * 1024**2
# CPU priority of the job's process and its render processes (POSIX ``nice``).
NICENESS = 19
# Failures the summary names; the rest are only counted.
MAX_LISTED_FAILURES = 100
# Seconds between two progress events.
PROGRESS_INTERVAL_S = 1.0

type Stop = Literal["cache_full"]

# What fails one file alone; any other error ends the job.
_FAILURES = (
    InvalidRefError,
    NotFoundError,
    OwnFileChangedError,
    OwnFolderInvalidError,
    PathOutsideRootError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    SourceUnavailableError,
    RuntimeError,
)


@dataclass(frozen=True, slots=True)
class _Look:
    """What the cache holds of a file's first look, and what it lacks.

    ``probe`` is ``None`` while the file was never recognised; ``missing``
    the renders of ``first_look`` the cache lacks; ``needs_build`` whether
    its map tiles (or its thumbnail) wait for a build.
    """

    probe: PreviewProbe | None
    missing: tuple[tuple[str, JsonObject], ...]
    needs_build: bool


@dataclass(slots=True)
class WarmTally:
    """How a warm-up went so far (the job's summary without its selection)."""

    total: int
    warmed: int = 0
    cached: int = 0
    needs_build: int = 0
    failed: int = 0
    failures: list[JsonObject] = field(default_factory=list)
    skipped: int = 0
    stopped: Stop | None = None

    def counts(self) -> JsonObject:
        """Return the counts of a progress event."""
        return {
            "warmed": self.warmed,
            "cached": self.cached,
            "failed": self.failed,
            "skipped": self.skipped,
        }


class Warmer:
    """Prepares the first look at files, one after another (see the module).

    Parameters
    ----------
    cache : PreviewCache
        The preview cache the pool keeps its renders in.
    pool : RenderPool
        A started render pool over ``cache``.
    resolver : ObjectResolver
        From refs to files, seeing every project.
    clock : Callable[[], float], optional
        Seconds since the epoch: what counts as used lately.
    recent_s : float, default RECENT_S
        An object used within this many seconds is never evicted for it.
    reserve_bytes : int, default RESERVE_BYTES
        Room the cache must have before a file is rendered.
    """

    def __init__(
        self,
        cache: PreviewCache,
        pool: RenderPool,
        resolver: ObjectResolver,
        *,
        clock: Callable[[], float] = time.time,
        recent_s: float = RECENT_S,
        reserve_bytes: int = RESERVE_BYTES,
    ) -> None:
        self._cache = cache
        self._pool = pool
        self._resolver = resolver
        self._clock = clock
        self._recent_s = recent_s
        self._reserve = reserve_bytes

    def run(
        self, refs: Sequence[str], report: Callable[[int, WarmTally], None]
    ) -> WarmTally:
        """Prepare the first look at each ref in order, within the room.

        Parameters
        ----------
        refs : Sequence[str]
            The objects (``version:``, ``file:`` refs).
        report : Callable[[int, WarmTally], None]
            Called after each ref with how many were taken so far.

        Returns
        -------
        WarmTally
            The counts; when the room ran out, ``stopped`` and ``skipped``.
        """
        tally = WarmTally(total=len(refs))
        for index, ref in enumerate(refs):
            try:
                look = self._look(ref, self._resolver.locate)
                rendered = False
                if look.probe is None or look.missing:
                    if self.room() < self._reserve:
                        tally.skipped = len(refs) - index
                        tally.stopped = "cache_full"
                        break
                    look, rendered = self._render(ref)
            except _FAILURES as error:
                _fail(tally, ref, error)
            else:
                if rendered:
                    tally.warmed += 1
                else:
                    tally.cached += 1
                if look.needs_build:
                    tally.needs_build += 1
            report(index + 1, tally)
        return tally

    def room(self) -> int:
        """Return the bytes puts may add without evicting an object used lately."""
        return self._cache.room(used_before=self._clock() - self._recent_s)

    def _look(self, ref: str, find: Callable[..., PreviewSource]) -> _Look:
        """Return what the cache holds of a ref's first look, by ``find``'s file."""
        source = find(ref, principal=LOCAL_OWNER)
        key = cache_key(source)
        probe = _probe_of(self._cache.peek(key, INFO_NAME))
        if probe is None:
            return _Look(None, (), needs_build=False)
        return self._lacking(source, key, probe)

    def _lacking(
        self, source: PreviewSource, key: CacheKey, probe: PreviewProbe
    ) -> _Look:
        """Return the renders of a file's first look that the cache lacks."""
        product = build_product(probe)
        built = product is None or self._cache.has(key, product)
        missing = tuple(
            (op, params)
            for op, params in first_look(source, probe, built=built)
            if not self._cache.has(*_target(op, source, params))
        )
        waits = not built and probe.reason not in NOTHING_SHOWN
        return _Look(probe, missing, needs_build=waits)

    def _render(self, ref: str) -> tuple[_Look, bool]:
        """Render what a ref's first look lacks from its file; whether anything was."""
        source = self._resolver.resolve(ref, principal=LOCAL_OWNER)
        key = cache_key(source)
        rendered = False
        probe = _probe_of(self._cache.peek(key, INFO_NAME))
        if probe is None:
            found = self._pool.request("probe", source)
            probe, rendered = found.probe(), not found.cached
        look = self._lacking(source, key, probe)
        for op, params in look.missing:
            rendered = not self._pool.request(op, source, params).cached or rendered
        return _Look(probe, (), look.needs_build), rendered


def warm_previews(spec: JobSpec, emit: "Emitter") -> JsonObject:
    """Prepare the first look at what the job's filters select; return its summary.

    Raises
    ------
    NotFoundError
        The job's area is no longer kept in the index.
    """
    started = time.perf_counter()
    params = spec.params
    settings = spec.settings
    with IndexQueries(spec.index_path) as queries:
        query = _query(params, queries)
        selection = queries.warm_selection(query, visible=ALL_PROJECTS)
        project = params.get("project")
        refs = [version_ref(store, path) for store, path in selection.versions]
        refs += [
            format_ref(FileRef(str(project), path)) for path in selection.own_files
        ]
        emit.progress(0, len(refs), warmed=0, cached=0, failed=0, skipped=0)
        _lower_priority()
        limit = settings.preview_cache_limit_bytes
        with (
            PreviewCache(spec.previews_dir, limit_bytes=limit) as cache,
            RenderPool(workers=1, cache=cache, work_dir=spec.work_dir) as pool,
        ):
            data_dir = spec.index_path.parent
            resolver = ObjectResolver(
                queries,
                lambda: settings,
                visible=lambda _: ALL_PROJECTS,
                paths=AppPaths(config_file=Path(os.devnull), data_dir=data_dir),
            )
            warmer = Warmer(cache, pool, resolver)
            tally = warmer.run(refs, _reporter(emit))
            room = warmer.room()
    if tally.stopped is not None:
        text = message(
            "job.warm_cache_full",
            skipped=tally.skipped,
            limit=settings.preview_cache_limit_gb,
        )
        emit.notice("warning", "cache_full", text)
    return {
        "versions": len(selection.versions),
        "files": len(selection.own_files),
        "warmed": tally.warmed,
        "cached": tally.cached,
        "needs_build": tally.needs_build,
        "failed": tally.failed,
        "failures": tally.failures,
        "skipped": tally.skipped,
        "stopped": tally.stopped,
        "room_bytes": room,
        "seconds": round(time.perf_counter() - started, 3),
    }


def _query(params: JsonObject, queries: IndexQueries) -> WarmQuery:
    """Return the filters of a job's parameters, its area read from the index."""
    area = None
    area_id = params.get("area_id")
    if area_id is not None:
        record = queries.area(str(area_id))
        if record is None:
            raise NotFoundError(message("api.area_unknown", area=area_id))
        area = AreaFilter(record.geometry, record.countries)
    since = params.get("since")
    return WarmQuery(
        store=params.get("store"),
        product=params.get("product"),
        segment=params.get("segment"),
        project=params.get("project"),
        area=area,
        since=None if since is None else datetime.fromisoformat(str(since)),
    )


def _reporter(emit: "Emitter") -> Callable[[int, WarmTally], None]:
    """Return a progress report sent at most every ``PROGRESS_INTERVAL_S``."""
    last = time.monotonic()

    def report(current: int, tally: WarmTally) -> None:
        nonlocal last
        now = time.monotonic()
        if current < tally.total and now - last < PROGRESS_INTERVAL_S:
            return
        last = now
        emit.progress(current, tally.total, **tally.counts())

    return report


def _lower_priority() -> None:
    """Give this process and the render processes it starts the lowest priority."""
    if not hasattr(os, "nice"):  # pragma: no cover - Windows
        return
    with contextlib.suppress(OSError):
        os.nice(max(0, NICENESS - os.nice(0)))


def _fail(tally: WarmTally, ref: str, error: Exception) -> None:
    """Count a file that failed; name it while the summary names failures."""
    tally.failed += 1
    if len(tally.failures) < MAX_LISTED_FAILURES:
        code, detail = _failure(error)
        tally.failures.append({"ref": ref, "code": code, "detail": detail})


def _failure(error: Exception) -> tuple[str, str]:
    """Return the code and the Polish detail of a file's failure."""
    match error:
        case PreviewUnavailableError():
            reason = error.reason
            text = lookup(f"preview.reason_{reason}", reason)
            return reason, with_detail(text, error.detail)
        case PreviewTimeoutError():
            return "timeout", str(error)
        case SourceUnavailableError():
            return "store_unavailable", str(error)
        case OwnFileChangedError():
            return "changed_since_scan", str(error)
        case OwnFolderInvalidError():
            return "own_folder_invalid", str(error)
        case NotFoundError():
            return "not_found", str(error)
        case PathOutsideRootError():
            return "path_outside_root", str(error)
        case InvalidRefError():
            return "invalid_ref", str(error)
    return "unreadable", with_detail(message("preview.reason_unreadable"), str(error))


def _probe_of(info: bytes | None) -> PreviewProbe | None:
    """Return a cached probe; a damaged one is none (the file is probed again)."""
    if info is None:
        return None
    try:
        return PreviewProbe.from_bytes(info)
    except ValueError:
        return None


def _target(op: str, source: PreviewSource, params: JsonObject) -> tuple[CacheKey, str]:
    """Return the object and file a render of the first look is kept as."""
    target = OPERATIONS[op].target
    if target is None:  # pragma: no cover - thumbnails and tiles are kept
        raise ValueError(f"{op} is not kept in the preview cache")
    return cast(tuple[CacheKey, str], target(source, params))
