r"""SPEC 4.5 on the 50 000-slot store through ``archiwista serve`` (step 13).

Run explicitly on the reference machine: the local disk targets on the
generated store, the SMB 3 targets on the same store copied to a real share
(hard links kept) — never a local directory standing for a share::

    python -m tests.fixtures.make_store --slots 50000 --seed 1 --projects 30 \\
        <katalog-danych>/store-50k
    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_store_50k.py --no-cov -s
    ARCHIWISTA_SMB_STORE=<udział>/store-50k ARCHIWISTA_SMB_WORK=<katalog-danych> \\
        .venv/bin/python -m pytest -m smb tests/perf/test_store_50k.py --no-cov -s

The server runs as its own process, the way a person starts it, with its
configuration and index in ``<katalog-danych>/perf-50k-<ssd|smb>/`` (rebuilt
on each run, offline, scheduled rescans pushed out of the measurement). Its
scheduler fully scans the never-indexed store at start; the tests then ask
for an unchanged incremental scan, view refreshes of an area of at most 500
slots (``/local-coverage``), list, search, card and map answers over HTTP
(p95 of 40 after a warm-up), sample the memory of the server and its job
workers, pan the map with up to 5000 outlines in Chromium, and count the
sidecars a full and an incremental scan open against the cost table of the
plan (decision 3). Coverage must be off (``--no-cov``): its tracing would be
measured too. ``test_store_50k_generator_reproduces_store`` regenerates the
store next to it and times the generator.
"""

import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Self

import httpx
import pytest
from playwright.sync_api import Page, Response, sync_playwright

from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    StoreConfig,
    StoreKind,
    detect_store_kind,
)
from archiwista.index import BBox, IndexQueries, IndexWriter, initialize, scan_store
from archiwista.security import CSRF_HEADER
from archiwista.sources import ScanScope, SourceEntry
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import VIEWPORT
from tests.fixtures.make_store import make_store

STORE = "perf"
SLOTS = 50_000
SEED = 1
PROJECTS = 30
RUNS = 40
LIST_MS = SEARCH_MS = CARD_MS = 200.0
MAP_MS = 300.0
MEMORY_BYTES = INDEX_BYTES = 500 * 10**6
# Outlines one map view draws; above it the view is a grid (SPEC 4.5).
MAP_LIMIT = 5000
# Grid columns the map view asks for at 1440 px (``src/views/map.js``).
GRID_COLUMNS = 25
POLAND = (14.0, 49.0, 24.2, 54.9)
START_TIMEOUT_S = 60.0
FINAL_STATES = frozenset({"succeeded", "failed", "interrupted", "cancelled"})
SIDECAR = ".meta.json"
MANIFEST = "kartograf-project.json"
FRAME_SECONDS = 4.0
FRAMES_PER_S = 30.0
_SERVE_URL = re.compile(r"http://127\.0\.0\.1:(\d+)/#token=(\S+)")


@dataclass(frozen=True)
class Target:
    """Where the store lies and the SPEC 4.5 limits there."""

    name: str
    variable: str
    kind: StoreKind
    full_s: float
    incremental_s: float
    refresh_s: float


SSD = Target("ssd", "ARCHIWISTA_PERF_STORE", "local", 120.0, 20.0, 1.0)
SMB = Target("smb", "ARCHIWISTA_SMB_STORE", "share", 600.0, 180.0, 5.0)


@dataclass(frozen=True)
class Medium:
    """The mount holding the store, as ``/proc/self/mountinfo`` names it."""

    mount_point: str
    filesystem: str
    source: str
    options: str
    rotational: bool | None

    @classmethod
    def of(cls, path: Path) -> Self:
        """Return the deepest mount containing ``path``."""
        target = Path(os.path.realpath(path))
        best: tuple[int, Self] | None = None
        with open("/proc/self/mountinfo", encoding="utf-8") as table:
            for line in table:
                fields, _, rest = line.rstrip("\n").partition(" - ")
                parts = fields.split(" ")
                mount_point = Path(parts[4].replace("\\040", " "))
                if not target.is_relative_to(mount_point):
                    continue
                filesystem, source, options = (rest.split(" ") + ["", "", ""])[:3]
                depth = len(mount_point.parts)
                if best is None or depth >= best[0]:
                    found = cls(
                        str(mount_point),
                        filesystem,
                        source,
                        f"{parts[5]} {options}",
                        _rotational(source),
                    )
                    best = (depth, found)
        assert best is not None, path
        return best[1]


def _rotational(source: str) -> bool | None:
    """Whether a block device (or the disk of a partition) spins."""
    device = Path("/sys/class/block") / Path(source).name
    if not source.startswith("/dev/") or not device.exists():
        return None
    for queue in (device / "queue", device.resolve().parent / "queue"):
        flag = queue / "rotational"
        if flag.exists():
            return flag.read_text(encoding="ascii").strip() == "1"
    return None


def _store_dir(target: Target) -> Path:
    variable = os.environ.get(target.variable)
    if not variable:
        pytest.skip(f"{target.variable} names the generated 50 000-slot store")
    store = Path(variable)
    medium = Medium.of(store)
    if target is SMB:
        assert medium.filesystem in ("cifs", "smb3"), medium
    else:
        assert detect_store_kind(store) == "local", medium
        assert medium.rotational is False, f"not an SSD: {medium}"
    return store


def _seconds(job: dict[str, Any]) -> float:
    started = datetime.fromisoformat(job["started_at"])
    finished = datetime.fromisoformat(job["finished_at"])
    return (finished - started).total_seconds()


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


def _status(pid: int) -> dict[str, int] | None:
    """Memory lines of ``/proc/<pid>/status`` in KiB; ``None`` once it is gone."""
    try:
        with open(f"/proc/{pid}/status", encoding="ascii") as status:
            fields = dict(line.split(":", 1) for line in status)
    except (OSError, ValueError):
        return None
    names = ("VmHWM", "VmRSS", "RssAnon", "RssFile")
    if not all(name in fields for name in names):
        return None
    return {name: int(fields[name].split()[0]) for name in names}


def _index_mappings(pid: int) -> dict[str, int]:
    """Return the maps of ``index.sqlite``, their resident KiB and the PSS."""
    found = {"maps": 0, "rss_kib": 0, "pss_kib": 0}
    index = False
    with open(f"/proc/{pid}/smaps", encoding="utf-8", errors="replace") as smaps:
        for line in smaps:
            if re.match(r"[0-9a-f]+-[0-9a-f]+ ", line):
                index = line.rstrip().endswith("index.sqlite")
                found["maps"] += index
            elif index and line.startswith("Rss:"):
                found["rss_kib"] += int(line.split()[1])
    with open(f"/proc/{pid}/smaps_rollup", encoding="ascii") as rollup:
        for line in rollup:
            if line.startswith("Pss:"):
                found["pss_kib"] = int(line.split()[1])
    return found


def _children(pid: int) -> list[int]:
    found: list[int] = []
    try:
        tasks = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return found
    for task in tasks:
        try:
            with open(f"/proc/{pid}/task/{task}/children", encoding="ascii") as text:
                children = [int(item) for item in text.read().split()]
        except OSError:
            continue
        for child in children:
            found += [child, *_children(child)]
    return found


def _command(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as text:
            return text.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
    except OSError:
        return ""


@dataclass
class _Peak:
    command: str
    hwm_kib: int = 0
    anon_kib: int = 0


class _Memory:
    """Peak memory of the server and of each process it starts, sampled."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.peaks: dict[int, _Peak] = {}
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *details: object) -> None:
        self._stop.set()
        self._thread.join()

    def workers(self) -> list[_Peak]:
        """Peaks of the job workers seen so far."""
        return [
            peak
            for peak in self.peaks.values()
            if "archiwista.jobs.worker" in peak.command
        ]

    def _sample(self) -> None:
        while not self._stop.wait(0.05):
            for pid in [self.pid, *_children(self.pid)]:
                status = _status(pid)
                if status is None:
                    continue
                peak = self.peaks.get(pid)
                if peak is None:
                    peak = self.peaks[pid] = _Peak(_command(pid))
                peak.hwm_kib = max(peak.hwm_kib, status["VmHWM"])
                peak.anon_kib = max(peak.anon_kib, status["RssAnon"])


@dataclass
class _Run:
    """A server over the 50k store after its full and incremental scans."""

    target: Target
    store: Path
    medium: Medium
    paths: AppPaths
    process: subprocess.Popen[bytes]
    client: httpx.Client
    memory: _Memory
    full: dict[str, Any] = field(default_factory=dict)
    incremental: dict[str, Any] = field(default_factory=dict)
    incremental_seen_s: float = 0.0
    jobs_before: int = 0

    @property
    def base(self) -> str:
        """The server's address."""
        return str(self.client.base_url).rstrip("/")

    def get(self, path: str, **params: str | int | float) -> Any:
        """Read ``/api/v1`` with the session; require 200."""
        response = self.client.get(f"/api/v1{path}", params=params or None)
        assert response.status_code == 200, (path, response.text)
        return response.json()

    def post(self, path: str, body: object) -> Any:
        """Change something with the session's CSRF token."""
        response = self.client.post(f"/api/v1{path}", json=body)
        assert response.status_code in (200, 201, 202), (path, response.text)
        return response.json()

    def wait(self, job_id: str, timeout_s: float) -> dict[str, Any]:
        """Wait for a job to end and return it."""
        deadline = time.monotonic() + timeout_s
        while True:
            job: dict[str, Any] = self.get(f"/jobs/{job_id}")
            if job["state"] in FINAL_STATES:
                return job
            assert time.monotonic() < deadline, job
            time.sleep(0.5)

    def index_bytes(self) -> int:
        """Size of the index with its write-ahead log."""
        return sum(
            item.stat().st_size
            for item in self.paths.data_dir.glob("index.sqlite*")
            if item.is_file()
        )


def _serve(
    target: Target, store: Path, work: Path
) -> tuple[subprocess.Popen[bytes], str]:
    """Start ``archiwista serve`` over ``work``; return it and its token."""
    paths = _paths(work)
    config = StoreConfig(
        id=STORE, name="Magazyn 50 000", kartograf=store / "data", kind=target.kind
    )
    ConfigStore(paths.config_file).save(
        AppSettings(
            offline=True,
            stores=(config,),
            project_dirs=(store / "projects",),
            # Scheduled rescans come after the measurements, not during them.
            scan_interval_local_min=1440,
            scan_interval_share_min=1440,
        )
    )
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(work / "config"),
        "XDG_DATA_HOME": str(work / "data"),
    }
    out = work / "serve.out"
    with out.open("wb") as stdout, (work / "serve.err").open("wb") as stderr:
        process = subprocess.Popen(
            [
                str(Path(sys.executable).with_name("archiwista")),
                "serve",
                "--no-browser",
                "--port",
                "0",
            ],
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
    deadline = time.monotonic() + START_TIMEOUT_S
    while (found := _SERVE_URL.search(out.read_text(encoding="utf-8"))) is None:
        assert process.poll() is None, (work / "serve.err").read_text("utf-8")
        assert time.monotonic() < deadline, "the server did not start"
        time.sleep(0.1)
    return process, found[0]


def _work_dir(target: Target, store: Path) -> Path:
    """Return the local directory for the server's configuration and index.

    Next to a store on a local disk; for a share ``ARCHIWISTA_SMB_WORK``
    names one, since the index is never kept on a share (SPEC 4.6).
    """
    if target is not SMB:
        return store.parent
    variable = os.environ.get("ARCHIWISTA_SMB_WORK")
    if not variable:
        pytest.skip("ARCHIWISTA_SMB_WORK names a local directory for the index")
    work = Path(variable)
    assert detect_store_kind(work) == "local", work
    return work


def _paths(work: Path) -> AppPaths:
    """Where ``archiwista serve`` with ``XDG_*_HOME`` in ``work`` keeps its data."""
    return AppPaths(
        config_file=work / "config" / "archiwista" / "config.toml",
        data_dir=work / "data" / "archiwista",
    )


def _session(url: str) -> httpx.Client:
    """Exchange the one-time token of an address for a session (as an agent)."""
    found = _SERVE_URL.search(url)
    assert found is not None, url
    client = httpx.Client(base_url=f"http://127.0.0.1:{found[1]}", timeout=120.0)
    answer = client.post("/api/v1/session", json={"token": found[2]})
    assert answer.status_code == 200, answer.text
    # Every request of the session carries its CSRF token (SPEC 10.1).
    client.headers[CSRF_HEADER] = answer.json()["csrf_token"]
    return client


def _stop(process: subprocess.Popen[bytes]) -> int:
    process.send_signal(signal.SIGINT)
    try:
        return process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        process.kill()
        return process.wait()


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(SSD, marks=pytest.mark.perf, id="ssd"),
        pytest.param(SMB, marks=pytest.mark.smb, id="smb"),
    ],
)
def run(request: pytest.FixtureRequest) -> Iterator[_Run]:
    """Serve the store: the scheduler's full scan, then an incremental one."""
    target: Target = request.param
    store = _store_dir(target)
    coverage = sys.modules.get("coverage")
    if coverage is not None and coverage.Coverage.current() is not None:
        pytest.fail("run with --no-cov: coverage tracing would be measured too")
    work = _work_dir(target, store) / f"perf-50k-{target.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    process, url = _serve(target, store, work)
    try:
        with closing(_session(url)) as client, _Memory(process.pid) as memory:
            run = _Run(
                target, store, Medium.of(store), _paths(work), process, client, memory
            )
            deadline = time.monotonic() + 3 * target.full_s
            while not (jobs := run.get("/jobs", store=STORE, kind="scan")["items"]):
                assert time.monotonic() < deadline, "no scan at start"
                time.sleep(0.5)
            run.full = run.wait(jobs[0]["id"], 3 * target.full_s)
            started = time.perf_counter()
            job = run.post(f"/stores/{STORE}/scan", {"mode": "incremental"})
            run.incremental = run.wait(job["id"], 3 * target.incremental_s)
            run.incremental_seen_s = time.perf_counter() - started
            run.jobs_before = len(run.get("/jobs", store=STORE)["items"])
            yield run
    finally:
        assert _stop(process) == 0, (work / "serve.err").read_text("utf-8")


def test_store_50k_full_and_unchanged_incremental_scan(run: _Run) -> None:
    """The scheduler's full scan and an unchanged incremental one meet SPEC 4.5."""
    full, incremental = run.full, run.incremental
    medium = run.medium
    print(
        f"\n[{run.target.name}] store on {medium.filesystem} {medium.source}"
        f" at {medium.mount_point} ({medium.options}; rotational {medium.rotational})"
    )
    for job in (full, incremental):
        result = job["result"]
        print(
            f"{job['params']['mode']} scan (job {job['id']}): {_seconds(job):.1f} s"
            f" in the worker process, scan itself {result['seconds']:.1f} s;"
            f" {result['entries']} entries, {result['versions_written']} versions"
            f" written, {result['footprints_written']} footprints"
            f" ({result['footprints_failed']} failed), projects {result['projects']}"
        )
    print(f"incremental scan seen over HTTP: {run.incremental_seen_s:.1f} s")
    print(f"{'segment':42} {'entries':>8} {'full s':>8} {'incr s':>8}")
    again = {item["segment"]: item for item in incremental["result"]["segments"]}
    for item in full["result"]["segments"]:
        print(
            f"{item['segment'] or '-':42} {item['entries']:8} {item['seconds']:8.2f}"
            f" {again[item['segment']]['seconds']:8.2f}"
        )

    assert (full["state"], full["params"]["mode"]) == ("succeeded", "full")
    assert (incremental["state"], incremental["params"]["mode"]) == (
        "succeeded",
        "incremental",
    )
    assert full["result"]["versions_written"] > 75_000
    result = incremental["result"]
    assert (result["versions_written"], result["links_changed"]) == (0, 0)
    assert (result["missing"], result["removed"]) == (0, 0)
    # Unchanged manifests are not read again; those still to be checked are
    # (an invalid manifest, one naming no configured store).
    projects = result["projects"]
    assert projects["read"] == projects["invalid"] + projects["unknown_store"]
    assert _seconds(full) <= run.target.full_s
    assert _seconds(incremental) <= run.target.incremental_s


def _densest_cell(run: _Run, **filters: str) -> tuple[float, float]:
    """Return the centre of the grid cell with most outlines in Poland."""
    view = run.get(
        "/map/footprints",
        bbox=",".join(map(str, POLAND)),
        grid_columns=GRID_COLUMNS,
        **filters,
    )
    assert view["aggregated"], view["total"]
    cell = max(view["cells"], key=lambda item: item["count"])
    return (
        (cell["min_lon"] + cell["max_lon"]) / 2,
        (cell["min_lat"] + cell["max_lat"]) / 2,
    )


def _box(centre: tuple[float, float], half: float) -> BBox:
    """Return a box ``2 * half`` degrees of longitude wide, square on the ground."""
    lon, lat = centre
    tall = half * 0.65  # cos(50°): the same kilometres north and east
    return (lon - half, lat - tall, lon + half, lat + tall)


def _fit(
    count: Callable[[float], int], low_count: int, high_count: int
) -> tuple[float, int]:
    """Bisect a box's half side until ``count`` lies within the bounds."""
    low, high = 0.0, 4.0
    for _ in range(40):
        half = (low + high) / 2
        found = count(half)
        if found > high_count:
            high = half
        elif found < low_count:
            low = half
        else:
            return half, found
    raise AssertionError(f"no box with {low_count}–{high_count} items")


def test_store_50k_view_refresh_of_500_slots(run: _Run) -> None:
    """``/local-coverage`` rescans an area of up to 500 slots within SPEC 4.5."""
    centre = _densest_cell(run, product="nmt")
    with IndexQueries(run.paths.index_file) as queries:

        def slots(half: float) -> int:
            found = queries.slots_in_bbox(STORE, _box(centre, half), product="nmt")
            return sum(1 for item in found if item.unit is not None)

        half, count = _fit(slots, 450, 500)
    lon0, lat0, lon1, lat1 = _box(centre, half)
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    area = run.post(
        "/areas",
        {
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "name": "500 slotów",
            "source": "drawn",
        },
    )
    params = {"area_id": area["id"], "product": "nmt", "store": STORE}
    run.get("/local-coverage", **params)
    samples = []
    answers = []
    for _ in range(RUNS):
        started = time.perf_counter()
        answers.append(run.get("/local-coverage", **params))
        samples.append(time.perf_counter() - started)
    p95 = _p95(samples)
    print(
        f"\n[{run.target.name}] view refresh of {count} slots"
        f" ({area['area_km2']:.0f} km²): p95 {p95 * 1000:.0f} ms,"
        f" median {statistics.median(samples) * 1000:.0f} ms,"
        f" max {max(samples) * 1000:.0f} ms"
    )

    assert {(item["stale"], item["stale_reason"]) for item in answers} == {
        (False, None)
    }
    assert p95 <= run.target.refresh_s


def test_store_50k_list_search_card_map_p95(run: _Run) -> None:
    """Lists, search and cards ≤ 200 ms, map views ≤ 300 ms at p95 over HTTP."""
    sample = run.get("/slots", product="nmt", limit=1)["items"][0]
    deep = run.get("/slots", limit=50)
    for _ in range(100):
        deep = run.get("/slots", limit=50, cursor=deep["next_cursor"])
    centre = _densest_cell(run)

    def outlines(half: float) -> int:
        bbox = ",".join(f"{value:.5f}" for value in _box(centre, half))
        total: int = run.get("/map/footprints", bbox=bbox, limit=MAP_LIMIT)["total"]
        return total

    half, total = _fit(outlines, MAP_LIMIT - 500, MAP_LIMIT)
    view = ",".join(f"{value:.5f}" for value in _box(centre, half))
    sha8 = sample["version"]["sha256"][:8]
    grid = f"limit={MAP_LIMIT}&grid_columns={GRID_COLUMNS}"
    cases = {
        "list: first page": (LIST_MS, "/slots?limit=50"),
        "list: page 101 (cursor)": (
            LIST_MS,
            f"/slots?limit=50&cursor={deep['next_cursor']}",
        ),
        "list: product + years": (
            LIST_MS,
            "/slots?product=orto&years=2020-2022&limit=50",
        ),
        "list: all versions": (LIST_MS, "/slots?versions=all&limit=50"),
        "list: pinned": (LIST_MS, "/slots?versions=pinned&limit=50"),
        "list: without location": (LIST_MS, "/slots?location=none&limit=50"),
        "list: area bbox": (LIST_MS, "/slots?bbox=19.0,49.5,19.5,50.0&limit=50"),
        "search: sheet code": (SEARCH_MS, f"/slots?q={sample['unit']}&limit=50"),
        "search: SHA-256 prefix": (SEARCH_MS, f"/slots?q={sha8}&limit=50"),
        "search: common word '2023'": (SEARCH_MS, "/slots?q=2023&limit=50"),
        "search: product name": (SEARCH_MS, "/slots?q=ortofotomapa&limit=50"),
        "card: slot": (CARD_MS, f"/stores/{STORE}/slots/{sample['slot']}"),
        "card: version": (
            CARD_MS,
            f"/stores/{STORE}/versions/{sample['version']['path']}",
        ),
        f"map: {total} outlines": (MAP_MS, f"/map/footprints?bbox={view}&{grid}"),
        "map: whole Poland (grid)": (
            MAP_MS,
            f"/map/footprints?bbox={','.join(map(str, POLAND))}&{grid}",
        ),
        "health": (CARD_MS, "/health"),
    }
    measured = {}
    for name, (_, path) in cases.items():
        assert run.client.get(f"/api/v1{path}").status_code == 200, path
        samples = []
        for _ in range(RUNS):
            started = time.perf_counter()
            response = run.client.get(f"/api/v1{path}")
            samples.append((time.perf_counter() - started) * 1000)
            assert response.status_code == 200, path
        measured[name] = (_p95(samples), statistics.median(samples))
    print(f"\n[{run.target.name}] over HTTP, {RUNS} requests each:")
    for name, (p95, median) in measured.items():
        print(f"{name:32} p95 {p95:7.1f} ms   median {median:7.1f} ms")

    assert run.get("/map/footprints", bbox=view, limit=MAP_LIMIT)["aggregated"] is False
    over = {
        name: round(measured[name][0], 1)
        for name, (limit, _) in cases.items()
        if measured[name][0] > limit
    }
    assert over == {}


# Collects the times of animation frames for ``duration`` ms; the page reads
# ``window.__frames`` when they are over.
_COUNT_FRAMES = """
(duration) => {
  window.__frames = new Promise((resolve) => {
    const times = [];
    const step = (now) => {
      times.push(now);
      if (now - times[0] < duration) requestAnimationFrame(step);
      else resolve(times);
    };
    requestAnimationFrame(step);
  });
}
"""
_RENDERER = """
() => {
  const gl = document.createElement("canvas").getContext("webgl2");
  const info = gl.getExtension("WEBGL_debug_renderer_info");
  return gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER);
}
"""
# WebGL drawn by the processor: frame rates say nothing of a computer's GPU.
_SOFTWARE_GL = ("SwiftShader", "llvmpipe", "softpipe")


def _frames_while_panning(page: Page) -> tuple[float, float]:
    """Drag the map in a slow circle; return frames per second and frame p95 (ms)."""
    page.wait_for_timeout(2000)
    box = page.locator(".maplibregl-canvas").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.evaluate(_COUNT_FRAMES, FRAME_SECONDS * 1000)
    started = time.monotonic()
    while (moving := time.monotonic() - started) < FRAME_SECONDS + 0.2:
        # The map follows the pointer at every frame.
        page.mouse.move(x + 150 * math.sin(moving * 2), y + 90 * math.cos(moving * 2))
        time.sleep(1 / 120)
    times: list[float] = page.evaluate("() => window.__frames")
    page.mouse.up()
    intervals = [
        later - earlier for earlier, later in zip(times, times[1:], strict=False)
    ]
    return 1000 * len(intervals) / (times[-1] - times[0]), _p95(intervals)


def test_store_50k_map_5000_outlines_frame_rate(run: _Run) -> None:
    """Panning a map of 4500–5000 outlines keeps ≥ 30 frames per second (v0.2)."""
    lon, lat = _densest_cell(run)
    token = run.post("/session/tokens", None)["token"]
    answers: list[Response] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_context(viewport=VIEWPORT, locale="pl-PL").new_page()
        page.on("response", lambda response: answers.append(response))
        page.goto(f"{run.base}/#token={token}")
        renderer: str = page.evaluate(_RENDERER)
        zoom, view = 9.0, dict[str, Any]()
        for _ in range(16):
            answers.clear()
            page.goto(
                f"{run.base}/?view=map&center={lon:.5f},{lat:.5f}&zoom={zoom:.2f}"
            )
            page.wait_for_load_state("networkidle")
            views = [item for item in answers if "/api/v1/map/footprints" in item.url]
            assert views, "the map asked for no footprints"
            view = views[-1].json()
            if view["aggregated"]:
                zoom += 0.25
            elif view["total"] < MAP_LIMIT - 500:
                zoom -= 0.25
            else:
                break
        loaded, loaded_p95 = _frames_while_panning(page)
        # The same view and basemap without outlines: a product nobody has.
        page.goto(
            f"{run.base}/?view=map&center={lon:.5f},{lat:.5f}&zoom={zoom:.2f}"
            "&product=brak"
        )
        page.wait_for_load_state("networkidle")
        empty, empty_p95 = _frames_while_panning(page)
        browser.close()
    summary = (
        f"{loaded:.1f} frames/s (frame p95 {loaded_p95:.0f} ms) with"
        f" {view['total']} outlines at zoom {zoom:.2f}, {empty:.1f} frames/s"
        f" (p95 {empty_p95:.0f} ms) without outlines; WebGL: {renderer}"
    )
    print(f"\n[{run.target.name}] panning the map: {summary}")

    assert view["aggregated"] is False
    assert MAP_LIMIT - 500 <= view["total"] <= MAP_LIMIT
    if any(name in renderer for name in _SOFTWARE_GL):
        pytest.skip(f"no GPU for the browser, WebGL in software: {summary}")
    assert loaded >= FRAMES_PER_S


def _counted_scans(store: str, kind: StoreKind, work: str) -> dict[str, dict[str, int]]:
    """Scan fully, then incrementally, in this process; count what each opened.

    Runs in a fresh process: the audit hook counting ``open`` and
    ``os.scandir`` calls cannot be removed once added.
    """
    root = Path(store) / "data"
    prefix = f"{root}{os.sep}"
    lock = threading.Lock()
    counts: dict[str, Counter[str]] = {}
    current: list[Counter[str]] = []

    def hook(event: str, args: tuple[Any, ...]) -> None:
        if not current or event not in ("open", "os.scandir", "os.listdir"):
            return
        path = args[0] if args else None
        if not isinstance(path, str | bytes | os.PathLike):
            return
        text = os.fsdecode(path)
        if event != "open":
            name = "scandir" if text.startswith(prefix) or text == str(root) else ""
        elif text.endswith(SIDECAR):
            part = text.removeprefix(prefix).split("/")
            name = (
                "sidecar: version"
                if "versions" in part
                else "sidecar: full_sheet"
                if "full_sheet" in part
                else "sidecar: link"
            )
        elif text.endswith(MANIFEST):
            name = "manifest"
        elif text.startswith(prefix):
            name = "data file"
        else:
            name = ""
        if name:
            with lock:
                current[0][name] += 1

    sys.addaudithook(hook)
    config = StoreConfig(id=STORE, name=STORE, kartograf=root, kind=kind)
    settings = AppSettings(stores=(config,), project_dirs=(Path(store) / "projects",))
    adapter = load_registry(cache_dir=Path(work) / "cache").adapter("kartograf")
    original = type(adapter).iter_entries

    def counted(
        self: Any, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        for entry in original(self, root, scope=scope):
            inside = "versions" in entry.relative_path.parts
            name = f"entry: {entry.kind}"
            if entry.kind == "problem":
                name += f" {entry.problem}{' (versions/)' if inside else ''}"
            elif entry.skipped:
                name += " (skipped)"
            with lock:
                current[0][name] += 1
            yield entry

    setattr(type(adapter), "iter_entries", counted)  # noqa: B010
    index = Path(work) / "index.sqlite"
    initialize(index)
    with IndexWriter(index) as writer:
        writer.sync_stores({STORE: config.roots()})
        for mode in ("full", "incremental"):
            current.append(counts.setdefault(mode, Counter()))
            scan_store(adapter, writer, settings, STORE, mode=mode)
            current.clear()
    return {mode: dict(found) for mode, found in counts.items()}


def test_store_50k_sidecar_opens_match_cost_table(run: _Run) -> None:
    """A full scan opens each sidecar once; an incremental one only the links'."""
    work = _work_dir(run.target, run.store) / f"perf-50k-{run.target.name}-opens"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    with ProcessPoolExecutor(1, mp_context=get_context("spawn")) as pool:
        counts = pool.submit(
            _counted_scans, str(run.store), run.target.kind, str(work)
        ).result()
    shutil.rmtree(work)
    print(f"\n[{run.target.name}] opened during a scan (audit hook of the process):")
    for mode, found in counts.items():
        for name, value in sorted(found.items()):
            print(f"{mode:12} {name:46} {value:8}")

    for mode, found in counts.items():
        links = found.get("entry: link", 0) + found.get("entry: full_sheet", 0)
        versions = found.get("entry: version", 0)
        invalid = found.get("entry: problem invalid_sidecar", 0)
        invalid_versions = found.get("entry: problem invalid_sidecar (versions/)", 0)
        opened = {
            "versions/": found.get("sidecar: version", 0),
            "links": found.get("sidecar: link", 0)
            + found.get("sidecar: full_sheet", 0),
        }
        expected = {"versions/": versions + invalid_versions, "links": links + invalid}
        assert opened == expected, mode
    # Known versions are listed, never read (only an invalid sidecar is, again).
    assert counts["incremental"].get("entry: version", 0) == 0


def test_store_50k_server_memory_and_index_size(run: _Run) -> None:
    """The server stays ≤ 500 MB resident; the index ≤ 500 MB."""
    status = _status(run.process.pid)
    assert status is not None
    server = run.memory.peaks[run.process.pid]
    workers = run.memory.workers()
    size = run.index_bytes()
    jobs = run.get("/jobs", store=STORE)["items"]
    mapped = _index_mappings(run.process.pid)
    print(
        f"\n[{run.target.name}] server: peak resident {status['VmHWM'] / 1024:.0f} MiB"
        f" (heap at most {server.anon_kib / 1024:.0f} MiB); now resident"
        f" {status['VmRSS'] / 1024:.0f} MiB, proportional"
        f" {mapped['pss_kib'] / 1024:.0f} MiB, {mapped['maps']} maps of the index"
        f" holding {mapped['rss_kib'] / 1024:.0f} MiB"
    )
    for peak in workers:
        print(
            f"job worker: peak resident {peak.hwm_kib / 1024:.0f} MiB,"
            f" heap {peak.anon_kib / 1024:.0f} MiB"
        )
    print(f"index {size / 10**6:.0f} MB ({size / 2**20:.0f} MiB); jobs {len(jobs)}")

    assert len(jobs) == run.jobs_before == 2
    assert status["VmHWM"] * 1024 <= MEMORY_BYTES
    assert size <= INDEX_BYTES


def _tree(directory: Path) -> dict[str, tuple[int, int] | None]:
    """Return each file's size and link count, ``None`` for each directory."""
    found: dict[str, tuple[int, int] | None] = {}
    for top, dirnames, filenames in os.walk(directory):
        relative = os.path.relpath(top, directory)
        for name in dirnames:
            found[os.path.join(relative, name)] = None
        for name in filenames:
            info = os.lstat(os.path.join(top, name))
            found[os.path.join(relative, name)] = (info.st_size, info.st_nlink)
    return found


@pytest.mark.perf
def test_store_50k_generator_reproduces_store() -> None:
    """The seed alone gives the measured store again; the generator is timed."""
    store = _store_dir(SSD)
    again = store.with_name(f"{store.name}-regenerated")
    shutil.rmtree(again, ignore_errors=True)
    started = time.perf_counter()
    manifest = make_store(again, slots=SLOTS, seed=SEED, projects=PROJECTS)
    seconds = time.perf_counter() - started
    try:
        regenerated = _tree(again)
        measured = _tree(store)
    finally:
        shutil.rmtree(again)
    print(
        f"\ngenerator: {seconds:.0f} s for {len(manifest.entries)} entries,"
        f" {sum(1 for item in measured.values() if item is not None)} files,"
        f" {sum(1 for item in measured.values() if item is None)} directories"
        " (generation and verification with Kartograf's readers)"
    )

    assert regenerated == measured
