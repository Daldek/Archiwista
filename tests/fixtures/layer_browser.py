"""The layer store behind a real ``archiwista serve`` for interface tests.

The Wachlarz, the timeline and the details panel (plan v0.2, step 13) show
the layers of ``tests.fixtures.layer_store``: around the 1:25 000 sheet
``AREA_SHEET`` the NMT flights of 2019 and 2023 (one 2023 sheet also as an
ASCII-NMT archive: one variant in two formats), a sheet whose variant is its
segment, and a WCS cutout labelled by its download date — so a timeline of
2019–2023 has three years without data. The server is offline: no basemap,
nothing asked outside it. Helpers start a session, keep the area and wait
until every layer's previews are built (one ``preview`` job per layer).
"""

import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import Page, expect

from archiwista.config import ConfigStore
from archiwista.sources.registry import load_registry
from tests.fixtures.api_store import STORE, store_settings
from tests.fixtures.browser import Served, Tab
from tests.fixtures.layer_store import (
    AREA_SHEET,
    PRODUCT,
    LayerStore,
    make_layer_store,
    sheet_polygon,
)
from tests.fixtures.local_server import local_paths, serving

INDEX_TIMEOUT_S = 60.0
BUILD_TIMEOUT_S = 120.0
INDEXED = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}"""
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""


@dataclass(frozen=True)
class ServedLayerStore:
    """The layer store and the real server over it."""

    store: LayerStore
    served: Served


@contextmanager
def serve_layer_store(root: Path) -> Iterator[ServedLayerStore]:
    """Write the layer store under ``root`` and run an offline server over it."""
    store = make_layer_store(root / "store")
    paths = local_paths(root)
    settings = store_settings(store.manifest).model_copy(update={"offline": True})
    ConfigStore(paths.config_file).save(settings)
    registry = load_registry(cache_dir=paths.cache_dir)
    with serving(paths, registry=registry) as (server, _):
        yield ServedLayerStore(store, Served(server, paths))


def open_session(tab: Tab, served: Served) -> Page:
    """Start a session in the tab and wait until the store is indexed."""
    page = tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the store was not indexed in time"
        page.wait_for_timeout(200)
    return page


def api(page: Page, path: str, body: dict[str, Any] | None = None) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    method = "GET" if body is None else "POST"
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    assert answer["status"] in (200, 201), answer
    return answer["body"]


def area_id(page: Page) -> str:
    """Keep the area of ``AREA_SHEET`` (four 1:10 000 sheets); return its id."""
    area = api(
        page,
        "/areas",
        {"geometry": sheet_polygon(AREA_SHEET), "name": AREA_SHEET, "source": "drawn"},
    )
    found: str = area["id"]
    return found


def layer_set(page: Page, area: str | None = None) -> dict[str, Any]:
    """Return the NMT layers of the store, in the area when one is given."""
    query = {"store": STORE, "product": PRODUCT}
    if area is not None:
        query["area_id"] = area
    found: dict[str, Any] = api(page, f"/local-layers?{urlencode(query)}")
    return found


def built_layers(page: Page, area: str) -> list[dict[str, Any]]:
    """Wait until every layer of the area has its previews; return the layers."""
    deadline = time.monotonic() + BUILD_TIMEOUT_S
    while True:
        layers: list[dict[str, Any]] = layer_set(page, area)["layers"]
        if all(
            layer["preview"]["state"] in ("ready", "unavailable") for layer in layers
        ):
            return layers
        assert time.monotonic() < deadline, (
            "the layers' previews were not built in time"
        )
        page.wait_for_timeout(1000)


def address(served: Served, **params: str) -> str:
    """Return an address of the interface."""
    return f"{served.base}/?{urlencode(params)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))
