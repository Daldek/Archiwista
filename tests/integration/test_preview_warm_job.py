"""The ``preview_warm`` job (plan of 2026-10-25, A9; SPEC 5.7, ADR-041).

A generated store, scanned into a fresh index, with real render processes;
the jobs run in real worker processes (slowed down by
``tests.fixtures.warm_worker`` where a test needs time) and share the preview
cache with the served application.
"""

import hashlib
import sqlite3
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.index import AreaFilter, IndexQueries, SlotQuery, WarmQuery
from archiwista.index.geometry import box_geometry
from archiwista.jobs import JobSupervisor
from archiwista.previews.cache import RENDERER_VERSIONS, CacheKey, PreviewCache
from archiwista.previews.pool import RenderPool
from archiwista.previews.warm import Warmer, WarmTally
from archiwista.refs import ObjectResolver, version_ref
from archiwista.sources.registry import load_registry
from tests.fixtures.api_store import STORE
from tests.fixtures.jobs import worker_path
from tests.fixtures.preview_api import (
    JOB_TIMEOUT_S,
    PreviewApi,
    center_tile_url,
    preview_api,
    scanned_store,
    version_url,
)
from tests.fixtures.warm_worker import DELAY_ENV, WARM_WORKER

# Headers of the synthetic JPEG sheets carry no geotransform (their outline
# comes from the world file); rasterio says so while reading them.
pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")

WAIT_S = 60.0
# A preview cache small enough to fill, and the room one file needs.
LIMIT = 4 * 1024**2
RESERVE = 256 * 1024
FILLER_NAME = "thumb-gray-256.png"


def _catalog_current(queries: IndexQueries, query: SlotQuery | None = None) -> set[str]:
    """Return the refs of the present current versions the catalog lists."""
    given = query or SlotQuery()
    refs: set[str] = set()
    cursor = None
    while True:
        page = queries.slots(
            SlotQuery(
                product=given.product,
                project=given.project,
                area=given.area,
                versions="current",
                limit=200,
                cursor=cursor,
            ),
            visible=ALL_PROJECTS,
        )
        refs |= {
            version_ref(row.store, row.version.path)
            for row in page.items
            if row.version is not None and row.version.state == "present"
        }
        if page.next_cursor is None:
            return refs
        cursor = page.next_cursor


def _selected(queries: IndexQueries, query: WarmQuery) -> set[str]:
    selection = queries.warm_selection(query, visible=ALL_PROJECTS)
    return {version_ref(store, path) for store, path in selection.versions}


def _await(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        assert time.monotonic() < deadline, "condition not met in time"
        time.sleep(0.05)


def _first_looks(served: PreviewApi, versions: list[str]) -> dict[str, list[int]]:
    """Ask for what a person's first look at each version asks: answer codes.

    The description, the pane's thumbnail (unless it waits for a build) and
    the map's tile at the file's smallest zoom (when the map shows tiles).
    """
    answers: dict[str, list[int]] = {}
    for path in versions:
        info = served.get(version_url(path)).json()
        codes = [200]
        awaited = info["state"] == "needs_build" and not info["auto_build"]
        if info["thumbnail_url"] and not awaited:
            codes.append(served.get(f"{info['thumbnail_url']}?size=512").status_code)
        if info["state"] == "ready" and info["tiles_url"] and not info["features_url"]:
            codes.append(served.get(center_tile_url(info)).status_code)
        answers[path] = codes
    return answers


def test_warm_prepares_the_first_look_the_server_then_serves_from_the_cache(
    tmp_path: Path,
) -> None:
    """Every current version's first look comes from the cache, nothing rendered.

    A second warm-up finds everything ready and renders nothing either.
    """
    with preview_api(tmp_path) as served:
        # Arrange
        with IndexQueries(served.api.paths.index_file) as queries:
            current = sorted(_catalog_current(queries))
        paths = [ref.split(":", 2)[2] for ref in current]

        # Act
        first = served.wait(served.jobs.submit("preview_warm", actor=LOCAL_OWNER).id)
        again = served.wait(served.jobs.submit("preview_warm", actor=LOCAL_OWNER).id)
        rendered = served.pool.stats().rendered
        looks = _first_looks(served, paths)
        after = served.pool.stats().rendered

    # Assert
    assert (first.state, again.state) == ("succeeded", "succeeded")
    assert first.result is not None and again.result is not None
    total = len(current)
    assert (first.result["versions"], first.result["files"]) == (total, 0)
    assert (first.result["warmed"], first.result["cached"]) == (total, 0)
    assert (again.result["warmed"], again.result["cached"]) == (0, total)
    assert again.result["needs_build"] == first.result["needs_build"] > 0
    for result in (first.result, again.result):
        assert (result["failed"], result["skipped"], result["stopped"]) == (0, 0, None)
    assert {path: codes for path, codes in looks.items() if set(codes) != {200}} == {}
    assert after == rendered


def test_warm_selects_the_current_versions_the_filters_admit(tmp_path: Path) -> None:
    """Store, product, segment, project and area narrow it as the catalog does.

    ``since`` admits only the versions indexed since then.
    """
    # Arrange
    _, paths = scanned_store(tmp_path)
    with IndexQueries(paths.index_file) as queries:
        everything = _catalog_current(queries)
        rows = queries.slots(SlotQuery(limit=200), visible=ALL_PROJECTS).items
        segment = sorted(
            row.segment.segment
            for row in rows
            if row.version is not None and row.segment.segment is not None
        )[0]
        projects = [project.key for project in queries.projects(visible=ALL_PROJECTS)]
    area = AreaFilter(box_geometry((19.0, 49.0, 22.0, 51.0)), ("PL",))
    late = sorted(everything)[0]
    index = sqlite3.connect(paths.index_file)
    with index:
        index.execute(
            "UPDATE versions SET indexed_at = '2099-01-01T00:00:00+00:00'"
            " WHERE path = ?",
            (late.split(":", 2)[2],),
        )
    index.close()

    with IndexQueries(paths.index_file) as queries:
        # Act
        chosen = {
            "all": _selected(queries, WarmQuery()),
            "store": _selected(queries, WarmQuery(store=STORE)),
            "other_store": _selected(queries, WarmQuery(store="inny")),
            "product": _selected(queries, WarmQuery(product="nmt")),
            "segment": _selected(queries, WarmQuery(segment=segment)),
            "area": _selected(queries, WarmQuery(area=area)),
            "since": _selected(
                queries, WarmQuery(since=datetime(2098, 1, 1, tzinfo=UTC))
            ),
            **{
                f"project {key}": _selected(queries, WarmQuery(project=key))
                for key in projects
            },
        }
        expected = {
            "all": everything,
            "store": everything,
            "other_store": set(),
            "product": _catalog_current(queries, SlotQuery(product="nmt")),
            "segment": {
                version_ref(row.store, row.version.path)
                for row in rows
                if row.version is not None
                and row.version.state == "present"
                and row.segment.segment == segment
            },
            "area": _catalog_current(queries, SlotQuery(area=area)),
            "since": {late},
            **{
                f"project {key}": _catalog_current(queries, SlotQuery(project=key))
                for key in projects
            },
        }

    # Assert
    assert chosen == expected
    assert expected["product"] and expected["segment"] and expected["area"]
    assert set().union(*(chosen[f"project {key}"] for key in projects))


def _fill(
    root: Path, sizes: Sequence[int], used_at: float, name: str
) -> list[CacheKey]:
    """Put objects of these sizes into a cache, each last used at ``used_at``."""
    keys = []
    with PreviewCache(root, limit_bytes=LIMIT, clock=lambda: used_at) as cache:
        for number, size in enumerate(sizes):
            content = hashlib.sha256(f"{name}-{number}".encode()).hexdigest()
            key = CacheKey(content, "raster", RENDERER_VERSIONS["raster"])
            cache.put(key, FILLER_NAME, b"\0" * size)
            keys.append(key)
    return keys


def _warm_in(
    paths: AppPaths, previews: Path, *, recent: Sequence[int], cold: Sequence[int]
) -> tuple[WarmTally, list[bool], list[bool], int, int]:
    """Warm every current version into a cache of ``LIMIT`` bytes filled first.

    Objects of the sizes ``recent`` were used an hour ago, those of ``cold``
    a month ago. Returns the tally, whether each recent and each cold object
    is still there, the version count and the bytes the cache holds.
    """
    settings = ConfigStore(paths.config_file).load()
    now = time.time()
    recents = _fill(previews, recent, now - 3600, "recent")
    colds = _fill(previews, cold, now - 30 * 24 * 3600, "cold")
    with (
        IndexQueries(paths.index_file) as queries,
        PreviewCache(previews, limit_bytes=LIMIT) as cache,
        RenderPool(workers=1, cache=cache, work_dir=paths.work_dir) as pool,
    ):
        selection = queries.warm_selection(WarmQuery(), visible=ALL_PROJECTS)
        refs = [version_ref(store, path) for store, path in selection.versions]
        resolver = ObjectResolver(
            queries, lambda: settings, visible=lambda _: ALL_PROJECTS
        )
        warmer = Warmer(cache, pool, resolver, reserve_bytes=RESERVE)
        tally = warmer.run(refs, lambda current, tally: None)
        kept = [cache.has(key, FILLER_NAME) for key in recents]
        left = [cache.has(key, FILLER_NAME) for key in colds]
        used = cache.usage().used_bytes
    return tally, kept, left, len(refs), used


def test_warm_never_evicts_previews_used_lately_and_stops_when_out_of_room(
    tmp_path: Path,
) -> None:
    """Old previews make room; recent ones never go; the rest is ``skipped``.

    In an empty cache every version is prepared. A cache whose room is less
    than one file needs takes nothing: every version is skipped at once.
    Previews used a month ago are evicted for the warm-up. A cache with room
    for a quarter of the warm-up takes some versions, then stops.
    """
    # Arrange
    _, paths = scanned_store(tmp_path)

    # Act
    empty = _warm_in(paths, tmp_path / "empty", recent=(), cold=())
    warm_bytes = empty[4]
    stuck = _warm_in(paths, tmp_path / "full", recent=(LIMIT - RESERVE // 2,), cold=())
    evicting = _warm_in(
        paths,
        tmp_path / "cold",
        recent=(RESERVE,) * 4,
        cold=(LIMIT - 4 * RESERVE - 16 * 1024,),
    )
    stopped = _warm_in(
        paths,
        tmp_path / "some",
        recent=(LIMIT - RESERVE - warm_bytes // 4,),
        cold=(),
    )

    # Assert
    tally, _, _, total, _ = empty
    assert (tally.warmed, tally.failed, tally.skipped, tally.stopped) == (
        total,
        0,
        0,
        None,
    )
    tally, kept, _, total, _ = stuck
    assert (tally.stopped, tally.skipped, tally.warmed) == ("cache_full", total, 0)
    assert all(kept)
    tally, kept, left, total, _ = evicting
    assert (tally.stopped, tally.skipped, tally.warmed) == (None, 0, total)
    assert all(kept) and not any(left)
    tally, kept, _, total, _ = stopped
    assert tally.stopped == "cache_full"
    assert tally.warmed > 0 and tally.skipped > 0
    assert tally.warmed + tally.cached + tally.failed + tally.skipped == total
    assert all(kept)


def test_warm_cancelled_midway_then_run_again_keeps_what_it_prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancelled warm-up ends ``cancelled``; the next one finds its work ready."""
    # Arrange
    worker_path(monkeypatch)
    monkeypatch.setenv(DELAY_ENV, "1")
    _, paths = scanned_store(tmp_path)
    settings = SettingsService(
        ConfigStore(paths.config_file), load_registry(cache_dir=paths.cache_dir)
    )

    with JobSupervisor(paths, settings, worker_command=WARM_WORKER) as jobs:
        job = jobs.submit("preview_warm", actor=LOCAL_OWNER)

        def started() -> bool:
            record = jobs.get(job.id)
            progress: dict[str, Any] = (record.progress if record else None) or {}
            return int(progress.get("warmed", 0)) >= 1

        # Act
        _await(started)
        jobs.cancel(job.id)
        cancelled = jobs.wait(job.id, timeout=JOB_TIMEOUT_S)
        monkeypatch.delenv(DELAY_ENV)
        again = jobs.wait(
            jobs.submit("preview_warm", actor=LOCAL_OWNER).id, timeout=JOB_TIMEOUT_S
        )

    # Assert
    assert (cancelled.state, cancelled.result) == ("cancelled", None)
    assert again.state == "succeeded" and again.result is not None
    assert again.result["cached"] >= 1
    assert again.result["warmed"] + again.result["cached"] == again.result["versions"]


def test_warm_job_refuses_parameters_it_does_not_know(tmp_path: Path) -> None:
    """A filter that is not text, an unknown one or a time without offset: refused.

    A request of the filters of a waiting warm-up joins it.
    """
    # Arrange
    _, paths = scanned_store(tmp_path)
    settings = SettingsService(
        ConfigStore(paths.config_file), load_registry(cache_dir=paths.cache_dir)
    )
    bad: list[dict[str, Any]] = [
        {"product": 7},
        {"product": ""},
        {"sheet": "N-34"},
        {"since": "2026-10-26T10:00:00"},
    ]
    since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

    with JobSupervisor(paths, settings, max_jobs=0) as jobs:
        # Act
        refused = 0
        for params in bad:
            with pytest.raises(ValueError):
                jobs.submit("preview_warm", params=params, actor=LOCAL_OWNER)
            refused += 1
        listed = jobs.list(kind="preview_warm").items
        queued = jobs.submit("preview_warm", params={"since": since}, actor=LOCAL_OWNER)
        joined = jobs.submit("preview_warm", params={"since": since}, actor=LOCAL_OWNER)

    # Assert
    assert (refused, listed) == (len(bad), ())
    assert joined.id == queued.id
    assert queued.params == {
        "store": None,
        "product": None,
        "segment": None,
        "project": None,
        "area_id": None,
        "since": since,
    }
