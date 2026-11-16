r"""Preview targets of plan v0.2 (decision 12) through ``archiwista serve`` (step 16).

Run on the reference machine with the preview fixtures of real sizes written
next to the 50 000-slot store (``tests.fixtures.preview_store``); for the SMB
targets the same directory copied to the share with its hard links::

    python -m tests.fixtures.preview_store \\
        --source <udział>/kartograf/release-0.8.0/data <katalog-danych>/previews-perf
    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_previews_perf.py --no-cov -s
    ARCHIWISTA_SMB_STORE=<udział>/store-50k ARCHIWISTA_SMB_WORK=<katalog-danych> \\
        .venv/bin/python -m pytest -m smb tests/perf/test_previews_perf.py --no-cov -s

The server runs as its own process over the fixtures (``previews-perf/`` next
to the 50 000-slot store) with its configuration, index and preview cache in
``perf-previews-<ssd|smb>/`` (rebuilt on each run; on a share in
``ARCHIWISTA_SMB_WORK``: the preview cache is local whatever the store, SPEC
4.6), its render pool and ``preview`` jobs as ``archiwista serve`` starts
them (``min(4, cpu)`` render processes, ``n = max(1, cpu // 2)`` build
processes of a job). In the order of the module, sharing that server:

- the first map tiles and thumbnail of the 22 528 × 24 326 px orthophoto with
  a warm render process (every tile once; the thumbnail drawn again after its
  file is taken out of the cache under the server);
- the local COG of single ASC 1 m (38 MB) and SM5 JPEG (125 Mpx) sheets, one
  ``preview`` job each, and of the real 320 Mpx SM5 sheet for information;
- the Wachlarz of a year of 35 ASC sheets and of a CZ orthophoto year of 50
  SM5 sheets from nothing: ``/local-layers`` of the area, the ``preview`` job
  it starts (its progress followed), the layer's thumbnail;
- layer thumbnails of those years drawn for new areas and from the cache;
- a year of 200 sheets on the map in Chromium: from a pan to the last layer
  tile of the 1440 × 900 px view, the tiles in the preview cache (the
  browser's own cache off);
- descriptions (``…/preview``) and thumbnails and tiles from the cache, p95
  of 40 after a warm-up; the memory of the server, its render processes and
  build processes, and the size of the preview cache.

Coverage must be off (``--no-cov``): its tracing would be measured too.
"""

import math
import os
import shutil
import statistics
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import morecantile
import pytest
from playwright.sync_api import Page, Request, sync_playwright

from archiwista.api.models_previews import DEFAULT_THUMBNAIL_SIZE
from archiwista.config import AppSettings, StoreConfig, StoreKind, detect_store_kind
from archiwista.previews.build import build_processes
from archiwista.previews.cache import thumbnail_name
from tests.fixtures.browser import (
    VIEWPORT,
    gpu_browser,
    pan_frames,
    webgl_renderer,
)
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
from tests.fixtures.preview_store import PreviewStore

STORE = "podglady"
PREVIEW_STORE = "previews-perf"
"""The fixtures' directory, next to the 50 000-slot store."""
RUNS = 40
FIRST_RUNS = 30
LAYER_SIZE = 512
MEMORY_BYTES = 500 * 10**6
RENDER_BYTES = 2**30
JOB_TIMEOUT_S = 1800.0
BUILDS = build_processes()
"""``n`` of decision 3: build processes of one ``preview`` job (2 on 4 CPUs)."""
# Every first layer thumbnail is of another area of the same sheets: its
# frame differs by 11 cm, so nothing of it is in the cache.
AREA_SHIFT_DEG = 1e-6
TILES_PATH = "/local-layers/tiles/"
FRAME_SECONDS = 4.0
POLAND_CZECHIA = (12.0, 48.5, 24.2, 54.9)
TILES = morecantile.tms.get("WebMercatorQuad")


@dataclass(frozen=True)
class Target:
    """Where the fixtures lie and the limits of decision 12 there (seconds)."""

    name: str
    variable: str
    kind: StoreKind
    first_tile_s: float
    first_thumbnail_s: float
    asc_cog_s: float
    sm5_cog_s: float
    description_s: float = 0.2
    cached_s: float = 0.1
    layer_thumbnail_s: float = 2.0
    year_view_s: float = 2.0


SSD = Target("ssd", "ARCHIWISTA_PERF_STORE", "local", 1.0, 2.0, 10.0, 15.0)
SMB = Target("smb", "ARCHIWISTA_SMB_STORE", "share", 2.0, 4.0, 20.0, 30.0)


@dataclass
class _Served(ServerProcess):
    """The server over the fixtures, with their groups and outlines."""

    target: Target = SSD
    fixtures: PreviewStore | None = None
    medium: Medium | None = None
    # WGS84 outline of every version: its path → the GeoJSON geometry.
    outlines: dict[str, dict[str, Any]] | None = None

    @property
    def store(self) -> PreviewStore:
        """The fixtures' groups."""
        assert self.fixtures is not None
        return self.fixtures

    def version(self, path: str) -> str:
        """Return a version's address below ``/api/v1``."""
        return f"/stores/{STORE}/versions/{path}"

    def timed(self, url: str, **params: str | int) -> tuple[float, bytes]:
        """GET an address (with or without ``/api/v1``); return seconds and body.

        ``params`` are added to the address's own query (as the interface
        adds ``size`` to a ``thumbnail_url``).
        """
        address = url if url.startswith("/api/") else f"/api/v1{url}"
        if params:
            address += ("&" if "?" in address else "?") + urlencode(params)
        started = time.perf_counter()
        response = self.client.get(address)
        seconds = time.perf_counter() - started
        assert response.status_code == 200, (url, response.text[:300])
        return seconds, response.content


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
    else:
        assert medium.rotational is False, f"not an SSD: {medium}"
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


@pytest.fixture(
    scope="module",
    params=[
        pytest.param(SSD, marks=pytest.mark.perf, id="ssd"),
        pytest.param(SMB, marks=pytest.mark.smb, id="smb"),
    ],
)
def served(request: pytest.FixtureRequest) -> Iterator[_Served]:
    """Serve the fixtures after the scheduler's full scan of them."""
    target: Target = request.param
    directory = _fixtures_dir(target)
    refuse_coverage()
    work = _work_dir(target, directory) / f"perf-previews-{target.name}"
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
    )
    with serve_process(work, settings) as server:
        served = _Served(
            server.process,
            server.client,
            server.memory,
            server.paths,
            target=target,
            fixtures=PreviewStore.load(directory),
            medium=Medium.of(directory),
        )
        deadline = time.monotonic() + 600
        while not (jobs := served.jobs(store=STORE, kind="scan")):
            assert time.monotonic() < deadline, "no scan at start"
            time.sleep(0.5)
        scan = served.wait(jobs[0]["id"], 600)
        assert scan["state"] == "succeeded", scan
        view = served.get(
            "/map/footprints", bbox=",".join(map(str, POLAND_CZECHIA)), limit=5000
        )
        served.outlines = {item["version"]: item["geometry"] for item in view["items"]}
        medium = served.medium.describe() if served.medium else "-"
        print(
            f"\n[{target.name}] fixtures on {medium}; scan {job_seconds(scan):.1f} s,"
            f" {len(served.outlines)} outlines; {BUILDS} build processes; {load()}"
        )
        yield served
        print(f"\n[{target.name}] end: {load()}")


def _bbox(geometries: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """Return the WGS84 box of GeoJSON polygons."""
    points = [
        point
        for geometry in geometries
        for polygon in (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        for ring in polygon
        for point in ring
    ]
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lons), min(lats), max(lons), max(lats)


def _area(
    served: _Served, paths: tuple[str, ...], name: str, shift: int = 0
) -> dict[str, Any]:
    """Keep the area of the box of versions' outlines, moved by ``shift`` steps.

    The box is shrunk by 1% of its side, so that no sheet merely touching it
    from outside joins the area's layers.
    """
    assert served.outlines is not None
    west, south, east, north = _bbox([served.outlines[path] for path in paths])
    inset_x, inset_y = (east - west) / 100, (north - south) / 100
    moved = shift * AREA_SHIFT_DEG
    west, east = west + inset_x + moved, east - inset_x + moved
    south, north = south + inset_y + moved, north - inset_y + moved
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    area: dict[str, Any] = served.post(
        "/areas",
        {
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "name": name,
            "source": "drawn",
        },
    )
    return area


def _layer(answer: dict[str, Any], paths: tuple[str, ...]) -> dict[str, Any]:
    """Return the layer of an answer whose previewable versions are ``paths``."""
    wanted = set(paths)
    for layer in answer["layers"]:
        refs = {item["ref"].split(":", 2)[2] for item in layer["versions"] or []}
        if wanted <= refs:
            return dict(layer)
    raise AssertionError(f"no layer with the versions of {sorted(wanted)[:2]}…")


def _build(served: _Served, path: str) -> dict[str, Any]:
    """Build one version's preview in a ``preview`` job of its own; return the job."""
    started = served.post(f"{served.version(path)}/preview", {"force": False})
    assert "kind" in started and started["kind"] == "preview", started
    job: dict[str, Any] = served.wait(started["id"], JOB_TIMEOUT_S, poll_s=0.2)
    assert job["state"] == "succeeded" and job["result"]["built"] == 1, job
    return job


def _follow(served: _Served, job_id: str) -> tuple[dict[str, Any], list[int]]:
    """Wait for a job, noting each progress it shows on the way."""
    seen: list[int] = []
    deadline = time.monotonic() + JOB_TIMEOUT_S
    while True:
        job: dict[str, Any] = served.get(f"/jobs/{job_id}")
        progress = job.get("progress")
        if progress and (not seen or seen[-1] != progress["current"]):
            seen.append(progress["current"])
        if job["state"] in ("succeeded", "failed", "interrupted", "cancelled"):
            return job, seen
        assert time.monotonic() < deadline, job
        time.sleep(0.5)


def _object_dir(served: _Served, sha256: str) -> Path:
    """Return the directory of a content's raster object in the preview cache."""
    found = sorted(
        (served.paths.previews_dir / "objects" / sha256[:2] / sha256).glob("raster-r*")
    )
    assert found, sha256
    return found[-1]


def test_previews_ortho_first_tile_and_thumbnail(served: _Served) -> None:
    """The orthophoto's first tiles ≤ 1 s and first thumbnail ≤ 2 s at p95 (SSD)."""
    path = served.store.ortho
    version = served.version(path)
    probe_s, _ = served.timed(f"{version}/preview")
    info = served.get(f"{version}/preview")
    first_s, _ = served.timed(f"{version}/preview.png")
    sha256 = served.get(version)["version"]["sha256"]
    thumbnail = _object_dir(served, sha256) / thumbnail_name(
        info["default_style"], DEFAULT_THUMBNAIL_SIZE
    )
    assert thumbnail.is_file(), thumbnail
    thumbnails = []
    for _ in range(FIRST_RUNS):
        thumbnail.unlink()
        seconds, image = served.timed(f"{version}/preview.png")
        thumbnails.append(seconds)
        assert image.startswith(b"\x89PNG")
    west, south, east, north = info["bounds"]
    tiles = []
    zooms = list(range(info["minzoom"], info["maxzoom"] + 1))
    for number in range(RUNS):
        z = zooms[number % len(zooms)]
        inside = list(TILES.tiles(west, south, east, north, zooms=[z]))
        tile = inside[(number * 7919) % len(inside)]
        seconds, _ = served.timed(f"{version}/tiles/{tile.z}/{tile.x}/{tile.y}.png")
        tiles.append(seconds)
    print(
        f"\n[{served.target.name}] orthophoto 22 528 × 24 326 px"
        f" (zoom {info['minzoom']}–{info['maxzoom']}): description with probe"
        f" {probe_s * 1000:.0f} ms; first thumbnail of all {first_s * 1000:.0f} ms;"
        f" first thumbnails p95 {p95(thumbnails) * 1000:.0f} ms (median"
        f" {statistics.median(thumbnails) * 1000:.0f} ms, max"
        f" {max(thumbnails) * 1000:.0f} ms, {FIRST_RUNS}); first tiles p95"
        f" {p95(tiles) * 1000:.0f} ms (median {statistics.median(tiles) * 1000:.0f}"
        f" ms, max {max(tiles) * 1000:.0f} ms, {RUNS})"
    )

    assert p95(tiles) <= served.target.first_tile_s
    assert p95(thumbnails) <= served.target.first_thumbnail_s


def test_previews_cog_of_one_asc_sheet(served: _Served) -> None:
    """A local COG of a 38 MB ASC 1 m sheet ≤ 10 s (SSD), one ``preview`` job."""
    jobs = [_build(served, path) for path in served.store.asc_singles]
    seconds = [job_seconds(job) for job in jobs]
    sizes = [
        served.get(served.version(path))["version"]["size_bytes"]
        for path in served.store.asc_singles
    ]
    print(
        f"\n[{served.target.name}] local COG of an ASC 1 m sheet"
        f" ({statistics.mean(sizes) / 10**6:.1f} MB): jobs "
        + ", ".join(f"{value:.1f}" for value in seconds)
        + " s (builds inside: "
        + ", ".join(f"{job['result']['seconds']:.1f}" for job in jobs)
        + " s)"
    )

    assert max(seconds) <= served.target.asc_cog_s


def test_previews_cog_of_one_sm5_sheet(served: _Served) -> None:
    """A local COG of a 125 Mpx SM5 JPEG ≤ 15 s (SSD); the real 320 Mpx sheet too."""
    jobs = [_build(served, path) for path in served.store.sm5_singles]
    seconds = [job_seconds(job) for job in jobs]
    real = _build(served, served.store.sm5_sheet)
    print(
        f"\n[{served.target.name}] local COG of an SM5 JPEG 12 500 × 10 000 px:"
        " jobs "
        + ", ".join(f"{value:.1f}" for value in seconds)
        + f" s; the real sheet 20 000 × 16 000 px (320 Mpx, for information):"
        f" {job_seconds(real):.1f} s"
    )

    assert max(seconds) <= served.target.sm5_cog_s


def _year_from_zero(
    served: _Served, paths: tuple[str, ...], product: str, name: str
) -> tuple[float, dict[str, Any], list[int], dict[str, Any]]:
    """Open a year's Wachlarz from nothing: layers, the job, the layer's thumbnail.

    Returns the seconds from the first ``/local-layers`` to the thumbnail,
    the job, the progress seen and the area.
    """
    area = _area(served, paths, name)
    started = time.perf_counter()
    answer = served.get(
        "/local-layers", store=STORE, product=product, area_id=area["id"]
    )
    layer = _layer(answer, paths)
    assert layer["preview"]["state"] in ("needs_build", "building"), layer["preview"]
    job, seen = _follow(served, layer["preview"]["job"]["id"])
    answer = served.get(
        "/local-layers", store=STORE, product=product, area_id=area["id"]
    )
    layer = _layer(answer, paths)
    _, image = served.timed(layer["preview"]["thumbnail_url"], size=LAYER_SIZE)
    seconds = time.perf_counter() - started
    assert image.startswith(b"\x89PNG")
    assert job["state"] == "succeeded", job
    assert layer["preview"]["state"] == "ready", layer["preview"]
    assert job["result"]["built"] == len(paths), job["result"]
    return seconds, job, seen, area


def test_previews_fan_of_35_asc_sheets_from_zero(served: _Served) -> None:
    """A Wachlarz year of 35 ASC sheets from nothing ≤ ⌈35/n⌉ × 10 s (SSD)."""
    paths = served.store.asc_year
    limit = math.ceil(len(paths) / BUILDS) * served.target.asc_cog_s
    seconds, job, seen, _ = _year_from_zero(served, paths, "nmt", "rok 2025 NMT")
    print(
        f"\n[{served.target.name}] Wachlarz of {len(paths)} ASC sheets from nothing:"
        f" {seconds:.1f} s (limit {limit:.0f} s; job {job_seconds(job):.1f} s,"
        f" builds {job['result']['seconds']:.1f} s); progress seen {seen}"
    )

    assert len(set(seen)) >= 3
    assert seconds <= limit


def test_previews_cz_year_of_50_sm5_sheets_from_zero(served: _Served) -> None:
    """A CZ orthophoto year of 50 SM5 sheets from nothing ≤ ⌈50/n⌉ × 15 s (SSD)."""
    paths = served.store.sm5_year
    limit = math.ceil(len(paths) / BUILDS) * served.target.sm5_cog_s
    seconds, job, seen, _ = _year_from_zero(
        served, paths, "orto", "rok 2024 ortofoto CZ"
    )
    print(
        f"\n[{served.target.name}] CZ orthophoto year of {len(paths)} SM5 sheets"
        f" from nothing: {seconds:.1f} s (limit {limit:.0f} s; job"
        f" {job_seconds(job):.1f} s, builds {job['result']['seconds']:.1f} s);"
        f" progress seen {seen}"
    )

    assert len(set(seen)) >= 3
    assert seconds <= limit


def _layer_thumbnails(
    served: _Served, paths: tuple[str, ...], product: str, name: str
) -> tuple[list[float], list[float]]:
    """Draw a ready layer's thumbnail for new areas, then again from the cache."""
    first = []
    address = ""
    for shift in range(1, FIRST_RUNS + 1):
        area = _area(served, paths, f"{name} {shift}", shift)
        answer = served.get(
            "/local-layers", store=STORE, product=product, area_id=area["id"]
        )
        layer = _layer(answer, paths)
        assert layer["preview"]["state"] == "ready", layer["preview"]
        address = layer["preview"]["thumbnail_url"]
        seconds, _ = served.timed(address, size=LAYER_SIZE)
        first.append(seconds)
    cached = [served.timed(address, size=LAYER_SIZE)[0] for _ in range(RUNS)]
    return first, cached


def test_previews_layer_thumbnail_first_and_cached(served: _Served) -> None:
    """A layer of ≤ 50 ready sheets: thumbnail ≤ 2 s at first, ≤ 100 ms cached."""
    found = {
        "35 ASC": _layer_thumbnails(
            served, served.store.asc_year, "nmt", "Wachlarz NMT"
        ),
        "50 SM5": _layer_thumbnails(
            served, served.store.sm5_year, "orto", "Wachlarz ortofoto CZ"
        ),
    }
    print(f"\n[{served.target.name}] layer thumbnails {LAYER_SIZE} px:")
    for name, (first, cached) in found.items():
        print(
            f"{name}: first p95 {p95(first) * 1000:.0f} ms (median"
            f" {statistics.median(first) * 1000:.0f} ms, max {max(first) * 1000:.0f}"
            f" ms, {FIRST_RUNS} areas); cached p95 {p95(cached) * 1000:.1f} ms"
            f" (median {statistics.median(cached) * 1000:.1f} ms)"
        )

    for first, cached in found.values():
        assert p95(first) <= served.target.layer_thumbnail_s
        assert p95(cached) <= served.target.cached_s


# Resource Timing of the layer tiles asked since ``since`` (page ms): their ends.
_TILE_ENDS = """
(since) => performance.getEntriesByType("resource")
  .filter((entry) => entry.name.includes("/local-layers/tiles/"))
  .filter((entry) => entry.startTime >= since)
  .map((entry) => entry.responseEnd)
"""


class _Tiles:
    """Layer tile requests of a page still waiting for their answers."""

    def __init__(self, page: Page) -> None:
        self.pending: set[Request] = set()
        self.last = time.monotonic()
        page.on("request", self._started)
        page.on("requestfinished", self._ended)
        page.on("requestfailed", self._ended)

    def settle(self, quiet_s: float = 1.0, timeout_s: float = 30.0) -> None:
        """Wait until no tile is asked for or awaited for ``quiet_s``."""
        deadline = time.monotonic() + timeout_s
        while self.pending or time.monotonic() - self.last < quiet_s:
            assert time.monotonic() < deadline, "tiles did not settle"
            time.sleep(0.05)

    def _started(self, request: Request) -> None:
        if TILES_PATH in request.url:
            self.pending.add(request)
            self.last = time.monotonic()

    def _ended(self, request: Request) -> None:
        if request in self.pending:
            self.pending.discard(request)
            self.last = time.monotonic()


def _drag(page: Page, dx: float) -> float:
    """Drag the map by ``dx`` pixels from near an edge; return when it began (ms)."""
    box = page.locator(".maplibregl-canvas").bounding_box()
    assert box is not None
    y = box["y"] + box["height"] / 2
    x = box["x"] + box["width"] - 40 if dx < 0 else box["x"] + 40
    page.mouse.move(x, y)
    began: float = page.evaluate("() => performance.now()")
    page.mouse.down()
    page.mouse.move(x + dx, y, steps=8)
    # Still before the release: no inertia carries the map past the view.
    page.wait_for_timeout(250)
    page.mouse.up()
    return began


def test_previews_year_view_of_200_sheets(served: _Served) -> None:
    """A year of 200 sheets on the map: pan → last tile of the view ≤ 2 s (cached)."""
    paths = served.store.map_year
    area = _area(served, paths, "rok 2023 NMT, 200 arkuszy")
    answer = served.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
    layer = _layer(answer, paths)
    if layer["preview"]["job"] is not None:
        job, _ = _follow(served, layer["preview"]["job"]["id"])
        assert job["state"] == "succeeded", job
    answer = served.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
    layer = _layer(answer, paths)
    assert layer["preview"]["state"] == "ready", layer["preview"]
    minzoom = layer["preview"]["minzoom"]
    west, south, east, north = area["bbox"]
    # MapLibre's zoom z asks for tiles of z + 1: the layer's first zoom. The
    # whole year fits a 1440 × 900 view there, so every pan starts with the
    # year just east of the view and drags it into the middle: all its tiles.
    zoom = minzoom - 1
    degrees = 360 / (512 * 2**zoom)
    lon, lat = (west + east) / 2, (south + north) / 2
    reach = VIEWPORT["width"] / 2 + (east - west) / 2 / degrees + 20
    chosen = f"&zoom={zoom}&product=nmt&area_id={area['id']}&layer={layer['key']}"
    year_url = f"{served.base}/?view=map&center={lon:.5f},{lat:.5f}{chosen}"
    start_url = f"{served.base}/?view=map&center={lon - reach * degrees:.5f},{lat:.5f}"
    start_url += chosen
    token = served.post("/session/tokens", None)["token"]
    samples = []
    counts = []
    with sync_playwright() as playwright:
        browser = gpu_browser(playwright)
        context = browser.new_context(viewport=VIEWPORT, locale="pl-PL")
        page = context.new_page()
        tiles = _Tiles(page)
        cdp = context.new_cdp_session(page)
        cdp.send("Network.enable")
        # Tiles come from the server's preview cache, never the browser's.
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        page.goto(f"{served.base}/#token={token}")
        renderer = webgl_renderer(page)
        # The year's tiles into the preview cache first.
        page.goto(year_url)
        page.wait_for_load_state("networkidle")
        tiles.settle()
        for number in range(FIRST_RUNS + 1):
            page.goto(start_url)
            page.wait_for_load_state("networkidle")
            tiles.settle()
            began = _drag(page, -reach)
            tiles.settle()
            ends: list[float] = page.evaluate(_TILE_ENDS, began)
            assert ends, "the pan asked for no layer tile"
            if number:  # the first is a warm-up
                samples.append((max(ends) - began) / 1000)
                counts.append(len(ends))
        page.goto(year_url)
        page.wait_for_load_state("networkidle")
        fps, frame_p95 = frame_rate(pan_frames(page, FRAME_SECONDS))
        context.close()
        browser.close()
    print(
        f"\n[{served.target.name}] year of {len(paths)} sheets on the map at zoom"
        f" {zoom} (tiles of {minzoom}): pan of {reach:.0f} px bringing the year into"
        " the empty view → last layer tile"
        f" p95 {p95(samples) * 1000:.0f} ms (median"
        f" {statistics.median(samples) * 1000:.0f} ms, max {max(samples) * 1000:.0f}"
        f" ms, {FIRST_RUNS} pans, {min(counts)}–{max(counts)} tiles each); panning"
        f" with the year shown {fps:.1f} frames/s (p95 {frame_p95:.0f} ms, for"
        f" information); WebGL: {renderer}"
    )

    assert p95(samples) <= served.target.year_view_s


def test_previews_description_and_cached_images_p95(served: _Served) -> None:
    """Descriptions ≤ 200 ms; thumbnails, tiles and layer tiles cached ≤ 100 ms."""
    store = served.store
    versions = [
        store.ortho,
        store.sm5_sheet,
        *store.asc_singles,
        *store.sm5_singles,
        *store.asc_year[:10],
        *store.sm5_year[:10],
        *store.map_year[:12],
    ]
    for path in versions:
        served.get(f"{served.version(path)}/preview")
    descriptions = [
        served.timed(f"{served.version(path)}/preview")[0] for path in versions[:RUNS]
    ]
    ortho = served.version(store.ortho)
    info = served.get(f"{ortho}/preview")
    served.timed(f"{ortho}/preview.png")
    thumbnails = [served.timed(f"{ortho}/preview.png")[0] for _ in range(RUNS)]
    tile = TILES.tile(
        (info["bounds"][0] + info["bounds"][2]) / 2,
        (info["bounds"][1] + info["bounds"][3]) / 2,
        info["maxzoom"] - 2,
    )
    address = f"{ortho}/tiles/{tile.z}/{tile.x}/{tile.y}.png"
    served.timed(address)
    tiles = [served.timed(address)[0] for _ in range(RUNS)]
    area = _area(served, store.map_year, "rok 2023 NMT, 200 arkuszy")
    answer = served.get("/local-layers", store=STORE, product="nmt", area_id=area["id"])
    layer = _layer(answer, store.map_year)
    west, south, east, north = area["bbox"]
    centre = TILES.tile(
        (west + east) / 2, (south + north) / 2, layer["preview"]["minzoom"]
    )
    template = layer["preview"]["tiles_url"]
    layer_tile = (
        template.replace("{z}", str(centre.z))
        .replace("{x}", str(centre.x))
        .replace("{y}", str(centre.y))
    )
    served.timed(layer_tile)
    layer_tiles = [served.timed(layer_tile)[0] for _ in range(RUNS)]
    found = {
        "description (…/preview)": (descriptions, served.target.description_s),
        "thumbnail from the cache": (thumbnails, served.target.cached_s),
        "tile from the cache": (tiles, served.target.cached_s),
        "layer tile from the cache": (layer_tiles, served.target.cached_s),
    }
    print(f"\n[{served.target.name}] over HTTP, {RUNS} requests each:")
    for name, (samples, _) in found.items():
        print(
            f"{name:28} p95 {p95(samples) * 1000:6.1f} ms   median"
            f" {statistics.median(samples) * 1000:6.1f} ms"
        )

    over = {
        name: round(p95(samples) * 1000, 1)
        for name, (samples, limit) in found.items()
        if p95(samples) > limit
    }
    assert over == {}


def test_previews_server_and_render_memory(served: _Served) -> None:
    """The server ≤ 500 MB resident; render processes (for information) ≤ 1 GiB."""
    status = memory_status(served.process.pid)
    assert status is not None
    groups = {
        "render process": served.memory.matching(RENDER_WORKER, POOL_FLAG),
        "build process": served.memory.matching(RENDER_WORKER, without=POOL_FLAG),
        "job worker": served.memory.matching(JOB_WORKER),
    }
    health = served.get("/health")
    print(
        f"\n[{served.target.name}] server: peak resident"
        f" {status['VmHWM'] / 1024:.0f} MiB, now {status['VmRSS'] / 1024:.0f} MiB;"
        f" preview cache {served.previews_bytes() / 10**6:.0f} MB on disk,"
        f" /health previews {health.get('previews')}"
    )
    for name, peaks in groups.items():
        if peaks:
            highest = max(peaks, key=lambda peak: peak.hwm_kib)
            print(
                f"{name}: {len(peaks)}, peak resident at most"
                f" {highest.hwm_kib / 1024:.0f} MiB (heap"
                f" {highest.anon_kib / 1024:.0f} MiB)"
            )
    renders = groups["render process"] + groups["build process"]
    over = [peak for peak in renders if peak.hwm_kib * 1024 > RENDER_BYTES]
    if over:
        print(
            f"over 1 GiB (for information): {[peak.hwm_kib // 1024 for peak in over]}"
        )

    assert status["VmHWM"] * 1024 <= MEMORY_BYTES
