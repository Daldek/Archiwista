"""The API with a render pool and a job supervisor over a generated store.

``preview_api`` writes the store of ``make_store`` (with the file families
of plan v0.2), scans it fully into a fresh index and serves the application
with real render processes (``RenderPool``, the renderers of
``archiwista.previews.renderers``) and a ``JobSupervisor`` with the real
worker, so ``POST …/preview`` builds local COGs. ``serve_previews`` serves
an already scanned store again, as a restarted server would.
"""

import math
import warnings
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from fastapi.testclient import TestClient
from rasterio.errors import NotGeoreferencedWarning
from rasterio.io import MemoryFile

from archiwista.app import create_app
from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, ConfigStore, SettingsService
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.jobs import ACTIVE_STATES, JobRecord, JobSupervisor
from archiwista.previews.cache import PreviewCache
from archiwista.previews.pool import RenderPool
from archiwista.security import CSRF_HEADER, SESSION_COOKIE
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.api_session import BASE_URL, PORT, Api, Caller
from tests.fixtures.api_store import STORE, store_settings
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import (
    MIN_SLOTS,
    ExpectedEntry,
    StoreManifest,
    make_store,
)

JOB_TIMEOUT_S = 120.0
CACHE_LIMIT_BYTES = 1024**3
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True)
class PreviewApi:
    """The served store with its render pool, job supervisor and owner."""

    store: StoreManifest
    api: Api
    owner: Caller
    jobs: JobSupervisor
    pool: RenderPool

    def get(
        self, url: str, *, etag: str | None = None, csrf: bool = True
    ) -> httpx.Response:
        """``GET`` an address as the owner (``/api/v1…``, e.g. from an answer)."""
        response: httpx.Response = self.api.client.get(
            url, headers=self._headers(etag, csrf=csrf)
        )
        return response

    def post(
        self, url: str, body: object = None, *, csrf: bool = True
    ) -> httpx.Response:
        """``POST`` to an address as the owner, with a JSON body."""
        response: httpx.Response = self.api.client.post(
            url, json=body, headers=self._headers(None, csrf=csrf)
        )
        return response

    def versions(self) -> list[dict[str, Any]]:
        """Return every version of the catalog (``GET /slots?versions=all``)."""
        found: list[dict[str, Any]] = []
        cursor = None
        while True:
            query = "/slots?versions=all&limit=200"
            if cursor is not None:
                query += f"&cursor={cursor}"
            page = self.owner.request("GET", query).json()
            found += [item["version"] for item in page["items"] if item["version"]]
            cursor = page["next_cursor"]
            if cursor is None:
                return found

    def wait(self, job_id: str) -> JobRecord:
        """Wait for a job to end and return it."""
        record = self.jobs.wait(job_id, timeout=JOB_TIMEOUT_S)
        assert record.state not in ACTIVE_STATES, record
        return record

    def _headers(self, etag: str | None, *, csrf: bool) -> dict[str, str]:
        headers = {"cookie": f"{SESSION_COOKIE}={self.owner.session_id}"}
        if csrf:
            headers[CSRF_HEADER] = self.owner.csrf
        if etag is not None:
            headers["If-None-Match"] = etag
        return headers


def version_url(path: str, route: str = "preview") -> str:
    """Return the address of a route of a version (``preview``, ``preview.png``…)."""
    return f"/api/v1/stores/{STORE}/versions/{path}/{route}"


def entry_of(
    store: StoreManifest, family: str, case: str | None = None
) -> ExpectedEntry:
    """Return the first version of a family (and generator case) in the store."""
    return next(
        entry
        for entry in store.by_kind("version")
        if entry.family == family and (case is None or entry.case == case)
    )


def center_tile(bounds: list[float], z: int) -> tuple[int, int]:
    """Return ``x``, ``y`` of the map tile at zoom ``z`` holding an extent's centre."""
    west, south, east, north = bounds
    longitude, latitude = (west + east) / 2, (south + north) / 2
    scale = 2**z
    x = int((longitude + 180) / 360 * scale)
    radians = math.radians(latitude)
    y = int((1 - math.asinh(math.tan(radians)) / math.pi) / 2 * scale)
    return x, y


def center_tile_url(info: Mapping[str, Any], z: int | None = None) -> str:
    """Return the address of a ``PreviewInfo``'s tile holding its centre.

    At zoom ``z``, or at the file's ``minzoom`` when omitted.
    """
    zoom = info["minzoom"] if z is None else z
    x, y = center_tile(info["bounds"], zoom)
    return str(info["tiles_url"]).format(z=zoom, x=x, y=y)


def decoded_png(data: bytes) -> np.ndarray[Any, Any]:
    """Decode a PNG into its bands (``count``, ``height``, ``width``)."""
    assert data.startswith(PNG_SIGNATURE)
    with warnings.catch_warnings(), MemoryFile(data) as memory:
        warnings.simplefilter("ignore", NotGeoreferencedWarning)
        with memory.open(driver="PNG") as image:
            return np.asarray(image.read())


def scanned_store(
    tmp_path: Path,
    *,
    slots: int = MIN_SLOTS,
    seed: int = 7,
    before_scan: Callable[[StoreManifest], object] | None = None,
) -> tuple[StoreManifest, AppPaths]:
    """Generate a store and scan it fully into a fresh index under ``tmp_path``."""
    store = make_store(tmp_path / "store", slots=slots, seed=seed)
    paths = local_paths(tmp_path)
    settings = store_settings(store)
    ConfigStore(paths.config_file).save(settings)
    if before_scan is not None:
        before_scan(store)
    registry = load_registry(cache_dir=paths.cache_dir)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: {"kartograf": store.root}})
        scan_store(registry.adapter("kartograf"), writer, settings, STORE, mode="full")
    return store, paths


@contextmanager
def serve_previews(
    store: StoreManifest, paths: AppPaths, *, workers: int = 2
) -> Iterator[PreviewApi]:
    """Serve a scanned store with a new render pool, preview cache and jobs."""
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = SettingsService(ConfigStore(paths.config_file), registry)
    state = StateStore(paths.state_file)
    with (
        JobSupervisor(paths, settings) as jobs,
        PreviewCache(paths.previews_dir, limit_bytes=CACHE_LIMIT_BYTES) as cache,
        RenderPool(workers=workers, cache=cache, work_dir=paths.work_dir) as pool,
    ):
        app = create_app(
            port=PORT,
            settings=settings,
            index_path=paths.index_file,
            state=state,
            registry=registry,
            areas_dir=paths.areas_dir,
            jobs=jobs,
            previews=pool,
        )
        with TestClient(app, base_url=BASE_URL) as client:
            api = Api(client, paths, state)
            yield PreviewApi(store, api, api.session(LOCAL_OWNER), jobs, pool)


@contextmanager
def preview_api(
    tmp_path: Path,
    *,
    slots: int = MIN_SLOTS,
    seed: int = 7,
    workers: int = 2,
    before_scan: Callable[[StoreManifest], object] | None = None,
) -> Iterator[PreviewApi]:
    """Generate a store, scan it fully and serve it with previews and jobs."""
    store, paths = scanned_store(
        tmp_path, slots=slots, seed=seed, before_scan=before_scan
    )
    with serve_previews(store, paths, workers=workers) as served:
        yield served
