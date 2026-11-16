r"""Criterion 8 of v0.3: a warmed version's first thumbnail (plan of 2026-10-25, A9).

SPEC 13 v0.3 criterion 8: after pre-building, the first thumbnail of a
prepared current version from an HDD or SMB store is served from the local
preview cache within the target of a preview from the cache (plan v0.2,
decision 12: 100 ms at p95). Run on the reference machine over the preview
fixtures written next to the 50 000-slot store (``tests.fixtures.preview_store``,
as ``tests/perf/test_previews_perf.py``)::

    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_warm_perf.py --no-cov -s
    ARCHIWISTA_SMB_STORE=<udział>/store-50k ARCHIWISTA_SMB_WORK=<katalog-danych> \\
        .venv/bin/python -m pytest -m smb tests/perf/test_warm_perf.py --no-cov -s

The server runs as its own process (``archiwista serve``) with an empty
preview cache in ``perf-warm-<ssd|smb>/`` (rebuilt on each run; on a share in
``ARCHIWISTA_SMB_WORK``: the cache is local whatever the store, SPEC 4.6) and
the setting ``preview_warm_after_scan`` on: its scheduler's full scan at the
start indexes every fixture, and the next tick warms what the scan indexed in
a ``preview_warm`` job of the scheduler. Then each sampled version is looked
at once, as a person's first look: its description (``…/preview``) and the
pane's thumbnail (``preview.png?size=512``). The test prints the warm-up's
time and summary and the p95 of both for the report (A14).

Coverage must be off (``--no-cov``): its tracing would be measured too.
"""

import os
import shutil
import statistics
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from archiwista.config import AppSettings, StoreConfig, StoreKind, detect_store_kind
from tests.fixtures.perf_server import (
    Medium,
    ServerProcess,
    job_seconds,
    load,
    p95,
    refuse_coverage,
    serve_process,
)
from tests.fixtures.preview_store import PreviewStore

STORE = "podglady"
PREVIEW_STORE = "previews-perf"
"""The fixtures' directory, next to the 50 000-slot store."""
SAMPLES = 40
SCAN_TIMEOUT_S = 600.0
WARM_TIMEOUT_S = 3600.0
# The scheduler plans once a minute; its warm-up follows the scan's end.
TICK_WAIT_S = 180.0
# The pane's thumbnail, the one the warm-up prepares.
PANE_SIZE = 512


@dataclass(frozen=True)
class Target:
    """Where the fixtures lie and the limits there (seconds; plan v0.2, decision 12)."""

    name: str
    variable: str
    kind: StoreKind
    description_s: float = 0.2
    cached_s: float = 0.1


SSD = Target("ssd", "ARCHIWISTA_PERF_STORE", "local")
SMB = Target("smb", "ARCHIWISTA_SMB_STORE", "share")


@dataclass
class _Served(ServerProcess):
    """The server over the fixtures with the scheduler's warm-up done."""

    target: Target = SSD
    fixtures: PreviewStore | None = None
    warm_up: dict[str, Any] | None = None

    @property
    def store(self) -> PreviewStore:
        """The fixtures' groups."""
        assert self.fixtures is not None
        return self.fixtures

    def timed(self, url: str) -> tuple[float, Any]:
        """GET an address below or with ``/api/v1``; return seconds and the answer."""
        address = url if url.startswith("/api/") else f"/api/v1{url}"
        started = time.perf_counter()
        response = self.client.get(address)
        seconds = time.perf_counter() - started
        assert response.status_code == 200, (url, response.text[:300])
        return seconds, response


def _fixtures_dir(target: Target) -> Path:
    variable = os.environ.get(target.variable)
    if not variable:
        pytest.skip(f"{target.variable} names the 50 000-slot store")
    directory = Path(variable).parent / PREVIEW_STORE
    if not (directory / "preview-store.json").is_file():
        pytest.skip(
            f"no preview fixtures in {directory}: python -m"
            " tests.fixtures.preview_store --source"
            " <udział>/kartograf/release-0.8.0/data <katalog>/previews-perf"
        )
    medium = Medium.of(directory)
    if target is SMB:
        assert medium.share, medium
    return directory


def _work_dir(target: Target, directory: Path) -> Path:
    if target is not SMB:
        return directory.parent
    variable = os.environ.get("ARCHIWISTA_SMB_WORK")
    if not variable:
        pytest.skip("ARCHIWISTA_SMB_WORK names a local directory for the index")
    work = Path(variable)
    assert detect_store_kind(work) == "local", work
    return work


def _ended(served: _Served, kind: str, timeout_s: float) -> dict[str, Any]:
    """Wait for the first job of a kind of the fixtures' scheduler; return it ended."""
    deadline = time.monotonic() + timeout_s
    while not (jobs := served.jobs(kind=kind)):
        assert time.monotonic() < deadline, f"no {kind} job"
        time.sleep(1.0)
    job: dict[str, Any] = served.wait(jobs[-1]["id"], WARM_TIMEOUT_S, poll_s=1.0)
    return job


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(SSD, marks=pytest.mark.perf, id="ssd"),
        pytest.param(SMB, marks=pytest.mark.smb, id="smb"),
    ],
)
def served(request: pytest.FixtureRequest) -> Iterator[_Served]:
    """Serve the fixtures; wait for the scheduler's scan and its warm-up."""
    target: Target = request.param
    directory = _fixtures_dir(target)
    refuse_coverage()
    work = _work_dir(target, directory) / f"perf-warm-{target.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    config = StoreConfig(
        id=STORE, name="Podglądy", kartograf=directory / "data", kind=target.kind
    )
    settings = AppSettings(
        offline=True,
        stores=(config,),
        project_dirs=(directory / "projects",),
        scan_interval_local_min=1440,
        scan_interval_share_min=1440,
        preview_warm_after_scan=True,
    )
    with serve_process(work, settings) as server:
        served = _Served(
            server.process,
            server.client,
            server.memory,
            server.paths,
            target=target,
            fixtures=PreviewStore.load(directory),
        )
        scan = _ended(served, "scan", SCAN_TIMEOUT_S)
        assert scan["state"] == "succeeded", scan
        served.warm_up = _ended(served, "preview_warm", TICK_WAIT_S)
        print(
            f"\n[{target.name}] fixtures on {Medium.of(directory).describe()}; scan"
            f" {job_seconds(scan):.1f} s; warm-up {job_seconds(served.warm_up):.1f} s,"
            f" {served.warm_up['result']}; preview cache"
            f" {served.previews_bytes() / 10**6:.0f} MB; {load()}"
        )
        yield served


def test_warm_first_thumbnail_of_a_warmed_version_from_the_cache(
    served: _Served,
) -> None:
    """The first thumbnail of each sampled warmed version ≤ 100 ms at p95."""
    warm_up = served.warm_up
    assert warm_up is not None
    assert warm_up["actor_kind"] == "scheduler"
    assert warm_up["params"]["store"] == STORE and warm_up["params"]["since"]
    result = warm_up["result"]
    assert result["failed"] == 0 and result["stopped"] is None, result
    store = served.store
    groups = (
        store.asc_year,
        store.sm5_year,
        store.map_year,
        store.asc_singles,
        store.sm5_singles,
        (store.ortho, store.sm5_sheet),
    )
    candidates = [path for group in groups for path in group[: SAMPLES // 4]]
    descriptions: list[float] = []
    thumbnails: list[float] = []
    for path in candidates:
        if len(thumbnails) == SAMPLES:
            break
        seconds, answer = served.timed(f"/stores/{STORE}/versions/{path}/preview")
        info = answer.json()
        waits = info["state"] == "needs_build" and not info["auto_build"]
        if not info["thumbnail_url"] or waits:
            continue
        descriptions.append(seconds)
        thumbnails.append(served.timed(f"{info['thumbnail_url']}?size={PANE_SIZE}")[0])
    print(
        f"\n[{served.target.name}] {len(thumbnails)} warmed versions, first look"
        f" each: description p95 {p95(descriptions) * 1000:.1f} ms (median"
        f" {statistics.median(descriptions) * 1000:.1f} ms); first thumbnail p95"
        f" {p95(thumbnails) * 1000:.1f} ms (median"
        f" {statistics.median(thumbnails) * 1000:.1f} ms)"
    )

    assert len(thumbnails) >= SAMPLES // 2, len(thumbnails)
    assert p95(descriptions) <= served.target.description_s
    assert p95(thumbnails) <= served.target.cached_s
