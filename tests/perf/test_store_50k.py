r"""SPEC 4.5 on the 50 000-slot store through ``archiwista serve`` (v0.1 and v0.2).

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
slots (``/local-coverage``) and that area's layers (``/local-layers``, plan
v0.2 decision 12), list, search, card and map answers over HTTP (p95 of 40
after a warm-up), sample the memory of the server, its job workers and its
render processes, pan the map with up to 5000 outlines in Chromium, and count
the sidecars a full and an incremental scan open against the cost table of
the plan (decision 3). Since v0.2 the index has schema 6 with outlines as
polygons (decision 4).

The frame rate counts only with WebGL drawn on the GPU (plan v0.2, decision
1): ``ARCHIWISTA_BROWSER_CDP=http://127.0.0.1:<port>`` names a Chrome started
with ``--remote-debugging-port`` in a graphical session, otherwise
Playwright's Chromium starts with the GPU flags; WebGL in software skips the
assertion, or fails it with ``ARCHIWISTA_REQUIRE_GPU=1`` (the gate). Coverage
must be off (``--no-cov``): its tracing would be measured too.
``test_store_50k_generator_reproduces_store`` regenerates the store next to it
and times the generator.
"""

import os
import re
import shutil
import statistics
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, Response, sync_playwright

from archiwista.config import (
    AppSettings,
    StoreConfig,
    StoreKind,
    detect_store_kind,
)
from archiwista.index import BBox, IndexQueries, IndexWriter, initialize, scan_store
from archiwista.sources import ScanScope, SourceEntry
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import (
    VIEWPORT,
    gpu_browser,
    pan_frames,
    require_hardware_gl,
    webgl_renderer,
)
from tests.fixtures.make_store import make_store
from tests.fixtures.perf_server import (
    JOB_WORKER,
    POOL_FLAG,
    RENDER_WORKER,
    Medium,
    ServerProcess,
    frame_rate,
    job_seconds,
    load,
    memory_status,
    p95,
    refuse_coverage,
    serve_process,
)

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
SIDECAR = ".meta.json"
MANIFEST = "archiwista-project.json"
FRAME_SECONDS = 4.0
FRAMES_PER_S = 30.0
# Every sample of ``/local-layers`` is another area of the same slots: one
# rescanned within a minute is not rescanned again (plan v0.2, step 11).
AREA_SHIFT_DEG = 1e-6
PREVIEW_JOBS_S = 1800.0


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


def _store_dir(target: Target) -> Path:
    variable = os.environ.get(target.variable)
    if not variable:
        pytest.skip(f"{target.variable} names the generated 50 000-slot store")
    store = Path(variable)
    medium = Medium.of(store)
    if target is SMB:
        assert medium.share, medium
    else:
        assert detect_store_kind(store) == "local", medium
        assert medium.rotational is False, f"not an SSD: {medium}"
    return store


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


@dataclass
class _Run(ServerProcess):
    """A server over the 50k store after its full and incremental scans."""

    target: Target = SSD
    store: Path = Path()
    medium: Medium | None = None
    full: dict[str, Any] = field(default_factory=dict)
    incremental: dict[str, Any] = field(default_factory=dict)
    incremental_seen_s: float = 0.0
    scans_before: int = 0
    # The area of at most 500 NMT slots: its box, slots and the area itself.
    area_500: tuple[BBox, int, dict[str, Any]] | None = None


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
    refuse_coverage()
    work = _work_dir(target, store) / f"perf-50k-{target.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    config = StoreConfig(
        id=STORE, name="Magazyn 50 000", kartograf=store / "data", kind=target.kind
    )
    settings = AppSettings(
        offline=True,
        stores=(config,),
        project_dirs=(store / "projects",),
        # Scheduled rescans come after the measurements, not during them.
        scan_interval_local_min=1440,
        scan_interval_share_min=1440,
    )
    with serve_process(work, settings) as server:
        run = _Run(
            server.process,
            server.client,
            server.memory,
            server.paths,
            target=target,
            store=store,
            medium=Medium.of(store),
        )
        print(f"\n[{target.name}] start: {load()}")
        deadline = time.monotonic() + 3 * target.full_s
        while not (jobs := run.get("/jobs", store=STORE, kind="scan")["items"]):
            assert time.monotonic() < deadline, "no scan at start"
            time.sleep(0.5)
        run.full = run.wait(jobs[0]["id"], 3 * target.full_s)
        started = time.perf_counter()
        job = run.post(f"/stores/{STORE}/scan", {"mode": "incremental"})
        run.incremental = run.wait(job["id"], 3 * target.incremental_s)
        run.incremental_seen_s = time.perf_counter() - started
        run.scans_before = len(run.jobs(store=STORE, kind="scan"))
        yield run
        print(f"\n[{target.name}] end: {load()}")


def test_store_50k_full_and_unchanged_incremental_scan(run: _Run) -> None:
    """The scheduler's full scan and an unchanged incremental one meet SPEC 4.5."""
    full, incremental = run.full, run.incremental
    assert run.medium is not None
    print(f"\n[{run.target.name}] store on {run.medium.describe()}")
    for job in (full, incremental):
        result = job["result"]
        print(
            f"{job['params']['mode']} scan (job {job['id']}): {job_seconds(job):.1f} s"
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
    assert job_seconds(full) <= run.target.full_s
    assert job_seconds(incremental) <= run.target.incremental_s


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


def _post_area(run: _Run, box: BBox, name: str) -> dict[str, Any]:
    """Keep a drawn area of a box (WGS84)."""
    lon0, lat0, lon1, lat1 = box
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    area: dict[str, Any] = run.post(
        "/areas",
        {
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "name": name,
            "source": "drawn",
        },
    )
    return area


def _area_500(run: _Run) -> tuple[BBox, int, dict[str, Any]]:
    """Return the area of 450–500 NMT slots in the densest cell (made once)."""
    if run.area_500 is None:
        centre = _densest_cell(run, product="nmt")
        with IndexQueries(run.paths.index_file) as queries:

            def slots(half: float) -> int:
                found = queries.slots_in_bbox(STORE, _box(centre, half), product="nmt")
                return sum(1 for item in found if item.unit is not None)

            half, count = _fit(slots, 450, 500)
        box = _box(centre, half)
        run.area_500 = (box, count, _post_area(run, box, "500 slotów"))
    return run.area_500


def test_store_50k_view_refresh_of_500_slots(run: _Run) -> None:
    """``/local-coverage`` rescans an area of up to 500 slots within SPEC 4.5."""
    _, count, area = _area_500(run)
    params = {"area_id": area["id"], "product": "nmt", "store": STORE}
    run.get("/local-coverage", **params)
    samples = []
    answers = []
    for _ in range(RUNS):
        started = time.perf_counter()
        answers.append(run.get("/local-coverage", **params))
        samples.append(time.perf_counter() - started)
    found = p95(samples)
    print(
        f"\n[{run.target.name}] view refresh of {count} slots"
        f" ({area['area_km2']:.0f} km²): p95 {found * 1000:.0f} ms,"
        f" median {statistics.median(samples) * 1000:.0f} ms,"
        f" max {max(samples) * 1000:.0f} ms"
    )

    assert {(item["stale"], item["stale_reason"]) for item in answers} == {
        (False, None)
    }
    assert found <= run.target.refresh_s


def _layers_round(
    run: _Run, box: BBox, first: int
) -> tuple[list[float], list[dict[str, Any]]]:
    """Ask ``/local-layers`` of ``RUNS`` new areas of the same slots once each.

    The area ``first + n`` is the box moved by ``n`` × ``AREA_SHIFT_DEG``
    (11 cm), so each answer comes after a view refresh of its own.
    """
    samples = []
    answers = []
    for number in range(first, first + RUNS):
        shift = number * AREA_SHIFT_DEG
        moved = (box[0] + shift, box[1] + shift, box[2] + shift, box[3] + shift)
        area = _post_area(run, moved, f"warstwy {number}")
        started = time.perf_counter()
        answers.append(
            run.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
        )
        samples.append(time.perf_counter() - started)
    return samples, answers


def test_store_50k_local_layers_of_500_slots(run: _Run) -> None:
    """``/local-layers`` of an area of up to 500 slots, refreshed first (v0.2)."""
    box, count, area = _area_500(run)
    run.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
    building, answers = _layers_round(run, box, 1)
    started = time.perf_counter()
    jobs = run.wait_previews(PREVIEW_JOBS_S)
    waited = time.perf_counter() - started
    built, after = _layers_round(run, box, 1 + RUNS)
    layers = answers[0]["layers"]
    versions = sum(len(layer["versions"] or []) for layer in layers)
    summary = {
        name: sum(job["result"][name] for job in jobs if job["result"])
        for name in ("built", "cached")
    }
    print(
        f"\n[{run.target.name}] /local-layers of {count} NMT slots"
        f" ({area['area_km2']:.0f} km², {len(layers)} layers, {versions} versions),"
        f" {RUNS} new areas each:"
        f" while the layers' previews were built p95 {p95(building) * 1000:.0f} ms"
        f" (median {statistics.median(building) * 1000:.0f} ms, max"
        f" {max(building) * 1000:.0f} ms); after p95 {p95(built) * 1000:.0f} ms"
        f" (median {statistics.median(built) * 1000:.0f} ms, max"
        f" {max(built) * 1000:.0f} ms)"
    )
    print(
        f"preview jobs: {len(jobs)} ({Counter(job['state'] for job in jobs)}),"
        f" {summary['built']} built, {summary['cached']} cached; the last ended"
        f" {waited:.0f} s after the first round"
    )

    assert {item["stale_reason"] for item in answers + after} == {None}
    assert layers and versions
    assert {job["state"] for job in jobs} == {"succeeded"}
    assert p95(building) <= run.target.refresh_s
    assert p95(built) <= run.target.refresh_s


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
        measured[name] = (p95(samples), statistics.median(samples))
    print(f"\n[{run.target.name}] over HTTP, {RUNS} requests each:")
    for name, (found, median) in measured.items():
        print(f"{name:32} p95 {found:7.1f} ms   median {median:7.1f} ms")

    assert run.get("/map/footprints", bbox=view, limit=MAP_LIMIT)["aggregated"] is False
    over = {
        name: round(measured[name][0], 1)
        for name, (limit, _) in cases.items()
        if measured[name][0] > limit
    }
    assert over == {}


def _vertices(view: dict[str, Any]) -> int:
    """Count the outline vertices of a map view's footprints."""

    def count(coordinates: Any) -> int:
        if coordinates and isinstance(coordinates[0], int | float):
            return 1
        return sum(count(item) for item in coordinates)

    return sum(count(item["geometry"]["coordinates"]) for item in view["items"])


def _open_map(
    page: Page, url: str, answers: list[Response], *, required: bool = True
) -> dict[str, Any]:
    """Open a map address; return the last ``/map/footprints`` answer it asked.

    ``required`` false: an address that asked for none gives an empty view.
    """
    answers.clear()
    if required:
        # The map asks once WebGL and the view are set up, maybe after a
        # moment without requests: wait for the answer itself.
        with page.expect_response(
            lambda answer: "/api/v1/map/footprints" in answer.url, timeout=120_000
        ):
            page.goto(url)
    else:
        page.goto(url)
    page.wait_for_load_state("networkidle")
    views = [item for item in answers if "/api/v1/map/footprints" in item.url]
    if not views and not required:
        return {"total": 0, "items": []}
    assert views, "the map asked for no footprints"
    view: dict[str, Any] = views[-1].json()
    return view


def test_store_50k_map_5000_outlines_frame_rate(run: _Run) -> None:
    """Panning a map of 4500–5000 outlines keeps ≥ 30 frames per second (v0.2).

    The same view without outlines, and with the year layer of most versions
    of the 500-slot area chosen (its outlines and raster tiles), are panned
    too, for information.
    """
    lon, lat = _densest_cell(run)
    _, _, area = _area_500(run)
    layers = run.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
    layer = max(layers["layers"], key=lambda item: item["versions_count"])
    token = run.post("/session/tokens", None)["token"]
    answers: list[Response] = []
    with sync_playwright() as playwright:
        browser = gpu_browser(playwright)
        context = browser.new_context(viewport=VIEWPORT, locale="pl-PL")
        page = context.new_page()
        page.on("response", lambda response: answers.append(response))
        page.goto(f"{run.base}/#token={token}")
        renderer = webgl_renderer(page)
        zoom, view = 9.0, dict[str, Any]()
        for _ in range(16):
            position = f"center={lon:.5f},{lat:.5f}&zoom={zoom:.2f}"
            view = _open_map(page, f"{run.base}/?view=map&{position}", answers)
            if view["aggregated"]:
                zoom += 0.25
            elif view["total"] < MAP_LIMIT - 500:
                zoom -= 0.25
            else:
                break
        loaded, loaded_p95 = frame_rate(pan_frames(page, FRAME_SECONDS))
        # The same view and basemap without outlines: a product nobody has.
        _open_map(page, f"{run.base}/?view=map&{position}&product=brak", answers)
        empty, empty_p95 = frame_rate(pan_frames(page, FRAME_SECONDS))
        chosen = f"product=nmt&area_id={area['id']}&layer={layer['key']}"
        year = _open_map(
            page, f"{run.base}/?view=map&{position}&{chosen}", answers, required=False
        )
        year_tiles = sum("/local-layers/tiles/" in item.url for item in answers)
        with_year, with_year_p95 = frame_rate(pan_frames(page, FRAME_SECONDS))
        minzoom = layer["preview"]["minzoom"] if layer["preview"] else None
        zoomed = ""
        if minzoom is not None:
            box = area["bbox"]
            centre = f"center={(box[0] + box[2]) / 2:.5f},{(box[1] + box[3]) / 2:.5f}"
            # MapLibre's zoom asks for tiles one zoom higher (256 px tiles).
            at = f"{centre}&zoom={minzoom - 1:.2f}&{chosen}"
            _open_map(page, f"{run.base}/?view=map&{at}", answers, required=False)
            shown = sum("/local-layers/tiles/" in item.url for item in answers)
            tiles, tiles_p95 = frame_rate(pan_frames(page, FRAME_SECONDS))
            zoomed = (
                f"; at the layer's zoom {minzoom - 1}: {tiles:.1f} frames/s"
                f" (p95 {tiles_p95:.0f} ms), {shown} layer tiles"
            )
        context.close()
        browser.close()
    summary = (
        f"{loaded:.1f} frames/s (frame p95 {loaded_p95:.0f} ms) with"
        f" {view['total']} outlines ({_vertices(view)} vertices) at zoom"
        f" {zoom:.2f}, {empty:.1f} frames/s (p95 {empty_p95:.0f} ms) without"
        f" outlines; WebGL: {renderer}"
    )
    year_summary = (
        f"year layer {layer['title']} ({layer['versions_count']} versions, minzoom"
        f" {minzoom}) chosen: {with_year:.1f} frames/s (p95 {with_year_p95:.0f} ms)"
        f" with {year['total']} outlines of its year asked for, {year_tiles} layer"
        f" tiles{zoomed}"
    )
    print(f"\n[{run.target.name}] panning the map: {summary}; {year_summary}")

    assert view["aggregated"] is False
    assert MAP_LIMIT - 500 <= view["total"] <= MAP_LIMIT
    require_hardware_gl(renderer, summary)
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
    status = memory_status(run.process.pid)
    assert status is not None
    server = run.memory.peaks[run.process.pid]
    size = run.index_bytes()
    scans = run.jobs(store=STORE, kind="scan")
    mapped = _index_mappings(run.process.pid)
    print(
        f"\n[{run.target.name}] server: peak resident {status['VmHWM'] / 1024:.0f} MiB"
        f" (heap at most {server.anon_kib / 1024:.0f} MiB); now resident"
        f" {status['VmRSS'] / 1024:.0f} MiB, proportional"
        f" {mapped['pss_kib'] / 1024:.0f} MiB, {mapped['maps']} maps of the index"
        f" holding {mapped['rss_kib'] / 1024:.0f} MiB"
    )
    groups = {
        "job worker": run.memory.matching(JOB_WORKER),
        "render process": run.memory.matching(RENDER_WORKER, POOL_FLAG),
        "build process": run.memory.matching(RENDER_WORKER, without=POOL_FLAG),
    }
    for name, peaks in groups.items():
        if peaks:
            highest = max(peaks, key=lambda peak: peak.hwm_kib)
            print(
                f"{name}: {len(peaks)}, peak resident at most"
                f" {highest.hwm_kib / 1024:.0f} MiB (heap {highest.anon_kib / 1024:.0f}"
                " MiB)"
            )
    print(
        f"index {size / 10**6:.0f} MB ({size / 2**20:.0f} MiB); preview cache"
        f" {run.previews_bytes() / 10**6:.1f} MB; scans {len(scans)}"
    )

    assert len(scans) == run.scans_before == 2
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
