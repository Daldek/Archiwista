"""Render pool and its render processes (plan v0.2, step 4; decision 3).

Real render processes under the sandbox (``tests.fixtures.render_worker``:
the real worker with a test renderer doing what each file's JSON says) and
a real preview cache in ``tmp_path``.
"""

import asyncio
import contextlib
import functools
import hashlib
import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from archiwista.errors import (
    PreviewBusyError,
    PreviewTimeoutError,
    PreviewUnavailableError,
    RendererStartError,
)
from archiwista.previews import pool as pool_module
from archiwista.previews.cache import INFO_NAME, PreviewCache, cache_key
from archiwista.previews.pool import RenderPool, RenderResult
from archiwista.previews.types import PreviewProbe, PreviewSource
from tests.fixtures.hostile_files import SECRET_TEXT, SECRET_VALUE, hostile_files
from tests.fixtures.http_listener import listening
from tests.fixtures.jobs import worker_path
from tests.fixtures.refused_start import refuse_starts
from tests.fixtures.render_worker import TEST_RENDER_WORKER

THUMBNAIL = {"style": "gray", "size": 256}
WAIT_S = 30.0


@contextlib.contextmanager
def _pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **options: Any
) -> Iterator[RenderPool]:
    """Yield a started pool of test render processes over a fresh cache."""
    worker_path(monkeypatch)
    options.setdefault("workers", 1)
    with (
        PreviewCache(tmp_path / "previews", limit_bytes=100 * 1024**2) as cache,
        RenderPool(
            cache=cache,
            command=TEST_RENDER_WORKER,
            work_dir=tmp_path / "work",
            **options,
        ) as pool,
    ):
        yield pool


def _source(directory: Path, name: str, **steps: Any) -> PreviewSource:
    """Write a data file of instructions and return it as a source.

    The file names itself, so no two files share a content.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps({"name": name, **steps}), encoding="utf-8")
    content = hashlib.sha256(path.read_bytes()).hexdigest()
    return PreviewSource(ref=f"test:{name}", content_key=content, paths=(path,))


def _log(path: Path) -> list[tuple[int, str]]:
    """Return ``(pid, operation)`` of each line of a render log."""
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [(int(line.split()[0]), line.split()[1]) for line in lines]


def _running(pid: int) -> bool:
    """Whether a process exists and is not a zombie (Linux ``/proc``)."""
    try:
        state = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    return state.rsplit(")", 1)[1].split()[0] != "Z"


def _await(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + WAIT_S
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


def _in_thread(call: Callable[[], RenderResult]) -> tuple[threading.Thread, list[Any]]:
    """Run a request in a thread; the list gets its result or error."""
    outcome: list[Any] = []

    def run() -> None:
        try:
            outcome.append(call())
        except Exception as error:
            outcome.append(error)

    thread = threading.Thread(target=run)
    thread.start()
    return thread, outcome


def test_single_flight_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Equal requests at once are rendered once; later ones come from the cache."""
    # Arrange
    log = tmp_path / "render.log"
    source = _source(
        tmp_path / "data", "a.tif", sleep_s={"thumbnail": 1.0}, log=str(log)
    )

    with _pool(tmp_path, monkeypatch, workers=2) as pool:
        # Act
        asked = [
            _in_thread(lambda: pool.request("thumbnail", source, THUMBNAIL))
            for _ in range(6)
        ]
        for thread, _ in asked:
            thread.join()
        again = pool.request("thumbnail", source, THUMBNAIL)
        stats = pool.stats()

    # Assert
    results = [outcome[0] for _, outcome in asked]
    assert all(isinstance(result, RenderResult) for result in results)
    assert len({result.data for result in results}) == 1
    assert [op for _, op in _log(log)] == ["probe", "thumbnail"]
    assert again.cached and again.data == results[0].data
    assert stats.rendered == 1


def test_timeout_kills_and_respawns_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past its time limit a process is killed; the next request gets a new one."""
    # Arrange
    log = tmp_path / "render.log"
    data = tmp_path / "data"
    quick = _source(data, "quick.tif", log=str(log))
    slow = _source(data, "slow.tif", sleep_s={"thumbnail": 60}, log=str(log))
    after = _source(data, "after.tif", log=str(log))

    with _pool(tmp_path, monkeypatch, timeouts={"thumbnail": 1.0}) as pool:
        pool.request("probe", quick)
        first_pid = _log(log)[0][0]

        # Act
        started = time.monotonic()
        with pytest.raises(PreviewTimeoutError):
            pool.request("thumbnail", slow, THUMBNAIL)
        waited_s = time.monotonic() - started
        killed = not _running(first_pid)
        result = pool.request("probe", after)

    # Assert
    assert waited_s < 10
    assert killed
    assert result.probe().driver == "test"
    pids = [pid for pid, _ in _log(log)]
    assert pids[-1] != first_pid
    assert [op for _, op in _log(log)] == ["probe", "probe", "probe"]


def test_memory_limit_kills_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process past its address-space limit ends; the failure is remembered."""
    # Arrange
    log = tmp_path / "render.log"
    data = tmp_path / "data"
    quick = _source(data, "quick.tif", log=str(log))
    hog = _source(data, "hog.tif", allocate_bytes=3 * 1024**3)

    with _pool(tmp_path, monkeypatch) as pool:
        pool.request("probe", quick)
        first_pid = _log(log)[0][0]

        # Act
        with pytest.raises(PreviewUnavailableError) as caught:
            pool.request("probe", hog)
        ended = not _running(first_pid)
        rendered = pool.stats().rendered
        with pytest.raises(PreviewUnavailableError) as repeated:
            pool.request("probe", hog)
        stats = pool.stats()
        info = pool.cache.get(cache_key(hog), INFO_NAME)

    # Assert
    assert caught.value.reason == repeated.value.reason == "memory_limit"
    assert ended
    assert stats.rendered == rendered
    assert info is None


def test_abandoned_request_never_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request given up while it waits leaves the queue unrendered."""
    # Arrange
    data = tmp_path / "data"
    blocker = _source(data, "blocker.tif", sleep_s={"thumbnail": 1.5})
    victim_log = tmp_path / "victim.log"
    victim = _source(data, "victim.tif", log=str(victim_log))

    with _pool(tmp_path, monkeypatch) as pool:
        thread, _ = _in_thread(lambda: pool.request("thumbnail", blocker, THUMBNAIL))
        _await(lambda: pool.stats().rendering == 1)

        async def give_up() -> int:
            task = asyncio.create_task(pool.arequest("thumbnail", victim, THUMBNAIL))
            await asyncio.sleep(0.3)
            queued = pool.stats().queued
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            return queued

        # Act
        queued = asyncio.run(give_up())
        thread.join()
        time.sleep(0.5)  # a free process takes anything left in the queue
        stats = pool.stats()

    # Assert
    assert queued == 1
    assert _log(victim_log) == []
    assert (stats.abandoned, stats.queued, stats.rendered) == (1, 0, 1)


def test_queue_full_is_preview_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Past the queue's places a new request is refused; an equal one joins."""
    # Arrange
    data = tmp_path / "data"
    log = tmp_path / "render.log"
    blocker = _source(data, "blocker.tif", sleep_s={"thumbnail": 1.5})
    waiting = [_source(data, f"q{index}.tif", log=str(log)) for index in range(2)]
    extra = _source(data, "extra.tif")

    with _pool(tmp_path, monkeypatch, queue_size=2) as pool:
        blocked, _ = _in_thread(lambda: pool.request("thumbnail", blocker, THUMBNAIL))
        _await(lambda: pool.stats().rendering == 1)
        queued = [
            _in_thread(functools.partial(pool.request, "thumbnail", source, THUMBNAIL))
            for source in waiting
        ]
        _await(lambda: pool.stats().queued == 2)

        # Act
        with pytest.raises(PreviewBusyError) as caught:
            pool.request("thumbnail", extra, THUMBNAIL)
        joined, joined_outcome = _in_thread(
            lambda: pool.request("thumbnail", waiting[0], THUMBNAIL)
        )
        for thread in (blocked, joined, *(thread for thread, _ in queued)):
            thread.join()

    # Assert
    assert caught.value.retry_after_s > 0
    assert all(isinstance(outcome[0], RenderResult) for _, outcome in queued)
    assert joined_outcome[0].data == queued[0][1][0].data
    assert [op for _, op in _log(log)].count("thumbnail") == 2


def test_worker_env_has_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GDAL in a render process asked for URLs sends nothing anywhere."""
    # Arrange
    with listening() as listener:
        source = _source(tmp_path / "data", "net.json", network=listener.url)
        with _pool(tmp_path, monkeypatch) as pool:
            # Act
            answer = pool.request("members", source).json()

    # Assert
    assert listener.received == []
    assert answer["raster"] != "GTiff"
    assert "fields" not in answer["vector"]


def test_vrt_refused_after_warpedvrt_in_same_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a ``WarpedVRT`` the process reads planted files through the table.

    VRT XML named ``.tif``/``.asc``, ``a.tif.ovr`` holding VRT XML and OGR
    VRT XML named as vector files never yield the bytes of their target.
    """
    # Arrange
    planted = hostile_files(tmp_path / "planted")
    source = _source(
        tmp_path / "data",
        "hostile.json",
        hostile={
            "ovr_base": str(planted.ovr_base),
            "vrt_rasters": [str(path) for path in planted.vrt_rasters],
            "ogr_vrt_vectors": [str(path) for path in planted.ogr_vrt_vectors],
        },
    )

    with _pool(tmp_path, monkeypatch) as pool:
        # Act
        answer = pool.request("members", source).json()

    # Assert
    for path in (*planted.vrt_rasters, *planted.ogr_vrt_vectors):
        assert "refused" in answer[path.name], (path.name, answer[path.name])
    genuine = answer[planted.ovr_base.name]
    assert genuine["overviews"] == []
    assert SECRET_VALUE not in (genuine["max"], genuine["overview_max"])
    assert SECRET_TEXT not in json.dumps(answer)


def test_failure_detail_has_no_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A library's message reaches the pool with file names, never with paths.

    A source's paths are real (``PreviewSource``): a render process refuses a
    file reached through a symbolic link (review of v0.4, D2), so the message
    names real paths of a project's data folder only.
    """
    # Arrange
    real = tmp_path / "projekty" / "ola" / "dane"
    sources = [_source(real, name, fail=True) for name in ("plik.tif", "drugi.tif")]

    with _pool(tmp_path, monkeypatch) as pool:
        # Act
        probed = pool.request("probe", sources[0])
        with pytest.raises(PreviewUnavailableError) as caught:
            pool.request("tile", sources[1], {"style": "gray", "z": 1, "x": 0, "y": 0})

    # Assert
    for detail, name in (
        (probed.detail, "plik.tif"),
        (caught.value.detail, "drugi.tif"),
    ):
        assert detail is not None
        assert name in detail and "dane" in detail
        assert "/" not in detail and str(tmp_path) not in detail
    assert probed.probe().reason == caught.value.reason == "unreadable"


def test_unreadable_cached_as_code_and_timeout_not_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``unreadable`` is kept as a bare code; a timeout only in memory, 10 min."""
    # Arrange
    data = tmp_path / "data"
    broken = _source(data, "broken.tif", fail=True)
    slow = _source(data, "slow.tif", sleep_s={"probe": 60})

    with _pool(tmp_path, monkeypatch, timeouts={"probe": 1.0}) as pool:
        # Act
        first = pool.request("probe", broken)
        rendered = pool.stats().rendered
        second = pool.request("probe", broken)
        kept = pool.cache.get(cache_key(broken), INFO_NAME)
        with pytest.raises(PreviewTimeoutError):
            pool.request("probe", slow)
        timed_out = pool.stats().rendered
        started = time.monotonic()
        with pytest.raises(PreviewTimeoutError):
            pool.request("probe", slow)
        repeated_s = time.monotonic() - started
        final = pool.stats().rendered
        slow_kept = pool.cache.get(cache_key(slow), INFO_NAME)

    # Assert
    assert first.probe().reason == "unreadable" and first.detail is not None
    assert second.cached and second.detail is None and second.data == first.data
    assert kept is not None
    assert PreviewProbe.from_bytes(kept) == PreviewProbe(
        kind="raster", reason="unreadable"
    )
    assert pool.stats().rendered == rendered + 1 == timed_out == final
    assert repeated_s < 0.5
    assert slow_kept is None


def test_crashed_process_not_kept_and_next_request_renders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process killed by a signal answers ``unreadable`` once; nothing is kept.

    The crash is not the file's verdict: once the cause is gone (here the
    instruction to crash), the next request renders the file.
    """
    # Arrange
    source = _source(tmp_path / "data", "a.tif", signal="SIGSEGV")

    with _pool(tmp_path, monkeypatch) as pool:
        # Act
        with pytest.raises(PreviewUnavailableError) as caught:
            pool.request("probe", source)
        kept = pool.cache.get(cache_key(source), INFO_NAME)
        source.paths[0].write_text(json.dumps({"name": "a.tif"}), encoding="utf-8")
        result = pool.request("probe", source)

    # Assert
    assert caught.value.reason == "unreadable"
    assert "SIGSEGV" in str(caught.value.detail)
    assert kept is None
    assert not result.cached and result.probe().driver == "test"


def test_retry_passes_over_cached_verdict_and_remembered_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``retry`` renders again what the cache or the memory of failures answers.

    The retried probe replaces the verdict, so later requests get the new one.
    """
    # Arrange
    data = tmp_path / "data"
    stale = _source(data, "stale.tif")
    slow = _source(data, "slow.tif", sleep_s={"probe": 60})
    verdict = PreviewProbe(kind="raster", reason="unreadable").to_bytes()

    with _pool(tmp_path, monkeypatch, timeouts={"probe": 1.0}) as pool:
        pool.cache.put(cache_key(stale), INFO_NAME, verdict)
        with pytest.raises(PreviewTimeoutError):
            pool.request("probe", slow)
        slow.paths[0].write_text(json.dumps({"name": "slow.tif"}), encoding="utf-8")

        # Act
        cached = pool.request("probe", stale)
        retried = pool.request("probe", stale, retry=True)
        after = pool.request("probe", stale)
        with pytest.raises(PreviewTimeoutError):
            pool.request("probe", slow)
        recovered = pool.request("probe", slow, retry=True)

    # Assert
    assert cached.cached and cached.data == verdict
    assert not retried.cached and retried.probe().driver == "test"
    assert after.cached and after.data == retried.data
    assert not recovered.cached and recovered.probe().driver == "test"


def test_process_that_cannot_start_is_coded_and_not_remembered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused start is ``renderer_not_started``; the file renders once it starts."""
    # Arrange
    source = _source(tmp_path / "data", "a.tif")
    refused = refuse_starts(monkeypatch, pool_module)

    with _pool(tmp_path, monkeypatch) as pool:
        # Act
        with pytest.raises(RendererStartError) as caught:
            pool.request("probe", source)
        kept = pool.cache.get(cache_key(source), INFO_NAME)
        refused.on = False
        result = pool.request("probe", source)

    # Assert
    assert (caught.value.code, caught.value.details["reason"]) == (
        "missing_dependency",
        "renderer_not_started",
    )
    assert kept is None
    assert not result.cached and result.probe().driver == "test"
