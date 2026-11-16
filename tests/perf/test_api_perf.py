r"""Latency of the read API on the 50 000-slot store over HTTP (SPEC 4.5).

The index is built like ``test_index_perf.py`` (its ``built`` fixture, into
``<katalog-danych>/perf-index``); requests go through the whole application
(security middleware, session, routing, models, JSON) with a test client::

    ARCHIWISTA_PERF_STORE=<katalog-danych>/store-50k \\
        .venv/bin/python -m pytest -m perf tests/perf/test_api_perf.py -s
"""

import os
import statistics
import time
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, running_api
from tests.perf.test_index_perf import STORE, _Build, built

pytestmark = pytest.mark.perf

RUNS = 40
LIST_MS = SEARCH_MS = CARD_MS = 200.0
MAP_MS = 300.0
__all__ = ["built"]


def _p95(caller: Caller, path: str) -> tuple[float, float]:
    assert caller.request("GET", path).status_code == 200, path
    samples = []
    for _ in range(RUNS):
        started = time.perf_counter()
        response = caller.request("GET", path)
        samples.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200, path
    samples.sort()
    return samples[int(0.95 * (len(samples) - 1))], statistics.median(samples)


def test_api_perf_latency_p95(built: _Build, tmp_path: Path) -> None:
    """List, search and card answers ≤ 200 ms, map ≤ 300 ms at p95 over HTTP."""
    root = Path(os.environ["ARCHIWISTA_PERF_STORE"]) / "data"
    paths = AppPaths(config_file=tmp_path / "config.toml", data_dir=built.path.parent)
    store = StoreConfig(id=STORE, name="Perf", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(store,)))
    registry = load_registry(cache_dir=tmp_path / "cache")
    with running_api(paths, registry) as api:
        caller = api.session(LOCAL_OWNER)
        sample = caller.request("GET", "/slots?product=nmt&limit=1").json()["items"][0]
        deep = caller.request("GET", "/slots?limit=50").json()
        for _ in range(100):
            deep = caller.request(
                "GET", f"/slots?limit=50&cursor={deep['next_cursor']}"
            ).json()
        sha8 = sample["version"]["sha256"][:8]
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
            "card: slot": (CARD_MS, f"/stores/{STORE}/slots/{sample['slot']}"),
            "card: version": (
                CARD_MS,
                f"/stores/{STORE}/versions/{sample['version']['path']}",
            ),
            "map: whole Poland (grid)": (
                MAP_MS,
                "/map/footprints?bbox=14.0,49.0,24.2,54.9",
            ),
            "map: city view": (MAP_MS, "/map/footprints?bbox=19.0,49.5,19.6,49.9"),
            "health": (CARD_MS, "/health"),
        }
        measured = {name: _p95(caller, path) for name, (_, path) in cases.items()}
    print()
    for name, (p95, median) in measured.items():
        print(f"{name:32} p95 {p95:7.1f} ms   median {median:7.1f} ms")
    over = {
        name: round(measured[name][0], 1)
        for name, (limit, _) in cases.items()
        if measured[name][0] > limit
    }
    assert over == {}
