"""Previews on the map in Chromium on a real server (plan v0.2, step 12b).

One generated store is served for the module, online with a basemap from a
local tile server on another origin, so every request MapLibre makes can be
told apart: preview tiles of the API carry the session's CSRF header
(``transformRequest``), basemap tiles never do. With an area and a product
the store's year layers are buttons on the map; the chosen one shows the
outlines of its versions and one raster source of the layer's tiles from its
``minzoom`` (below it the outlines and „Przybliż, aby zobaczyć podgląd”), and
the choice lives in the address (``layer``). A version's preview goes on the
map from its file card: its tiles within its bounds, or a vector's features
of the view asked with the map's zoom.
"""

import json
import math
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, Request, expect

from archiwista.config import AppSettings, BasemapConfig, ConfigStore, StoreConfig
from archiwista.security import CSRF_HEADER
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import Served, Tab, session_headers
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import NMT, Family, StoreManifest, make_store
from tests.fixtures.tile_server import TileServer, tile_server

STORE = "zespol"
INDEX_TIMEOUT_S = 60.0
# Every layer's missing previews are built by one job each, one job at a time.
BUILD_TIMEOUT_S = 180.0
STILL_S = 0.6
TILE = re.compile(r"/tiles/(\d+)/(\d+)/(\d+)\.png")
LOADED = re.compile("w widoku|Brak obrysów")
WORLD = "-180,-85,180,85"
INDEXED = """
async () => {
  const csrf = sessionStorage.getItem("archiwista_csrf") ?? "";
  const headers = { "X-Archiwista-CSRF": csrf };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}
"""
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""


@dataclass(frozen=True)
class MapStore:
    """The module's store, its server and the basemap's tile server."""

    store: StoreManifest
    served: Served
    tiles: TileServer


@dataclass(frozen=True)
class Seen:
    """A request of the page: its address and CSRF header."""

    url: str
    csrf: str | None


@pytest.fixture(scope="module")
def map_store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[MapStore]:
    """Serve one generated store, online with a basemap on another origin."""
    root = tmp_path_factory.mktemp("map-previews")
    store = make_store(root / "store", slots=24, seed=7)
    with tile_server() as tiles:
        paths = local_paths(root)
        basemap = BasemapConfig(
            name="Kafle testowe", url=tiles.template, attribution="© Kafle testowe"
        )
        ConfigStore(paths.config_file).save(
            AppSettings(
                offline=False,
                basemaps=(basemap,),
                stores=(
                    StoreConfig(
                        id=STORE, name="Zespół", kartograf=store.root, kind="local"
                    ),
                ),
            )
        )
        registry = load_registry(cache_dir=paths.cache_dir)
        with serving(paths, registry=registry) as (server, _):
            yield MapStore(store, Served(server, paths), tiles)


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


def watch(page: Page) -> list[Seen]:
    """Record the page's requests from now on, with their CSRF header."""
    seen: list[Seen] = []

    def record(request: Request) -> None:
        seen.append(Seen(request.url, request.headers.get(CSRF_HEADER.lower())))

    page.on("request", record)
    return seen


def wait_for(page: Page, found: Callable[[], list[Seen]], what: str) -> list[Seen]:
    """Wait until requests of a kind were made; return them.

    The page's events arrive only while Playwright runs, so the wait is the
    page's own.
    """
    deadline = time.monotonic() + 30
    while not (items := found()):
        assert time.monotonic() < deadline, f"no request: {what}"
        page.wait_for_timeout(100)
    return items


def address(served: Served, **params: str) -> str:
    """Return an address of the interface."""
    return f"{served.base}/?{urlencode(params)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def counter(page: Page) -> Locator:
    """Return the counter of outlines in the view."""
    return page.locator(".map-count")


def strip(page: Page) -> Locator:
    """Return the year buttons on the map."""
    return page.get_by_role("group", name="Lata na mapie")


def legend(page: Page) -> Locator:
    """Return the map legend."""
    return page.locator(".map-legend")


def wait_still(page: Page) -> None:
    """Wait until the map stopped moving and the outlines of its view arrived."""
    page.wait_for_timeout(700)
    deadline = time.monotonic() + 20
    current = page.url
    since = time.monotonic()
    while time.monotonic() - since < STILL_S:
        assert time.monotonic() < deadline, "the map did not stop"
        page.wait_for_timeout(100)
        if page.url != current:
            current = page.url
            since = time.monotonic()
    expect(page.locator(".map-counts .loading")).to_have_count(0)
    expect(counter(page)).to_have_text(LOADED)


def nmt_area(page: Page) -> str:
    """Keep an area around the store's NMT sheets (ASC); return its id."""
    view = api(page, f"/map/footprints?product=nmt&versions=all&bbox={WORLD}")
    rings = [
        item["geometry"]["coordinates"][0]
        for item in view["items"]
        if item["segment"] == NMT and item["slot"].endswith(".asc")
    ]
    assert rings, "the store has no NMT sheets"
    west = min(x for ring in rings for x, _ in ring)
    south = min(y for ring in rings for _, y in ring)
    east = max(x for ring in rings for x, _ in ring)
    north = max(y for ring in rings for _, y in ring)
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    area = api(
        page,
        "/areas",
        {
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "name": "Arkusze NMT",
            "source": "drawn",
        },
    )
    area_id: str = area["id"]
    return area_id


def layers_of(page: Page, area_id: str) -> list[dict[str, Any]]:
    """Return the NMT layers of the area as the page's session reads them."""
    query = urlencode({"store": STORE, "product": "nmt", "area_id": area_id})
    layers: list[dict[str, Any]] = api(page, f"/local-layers?{query}")["layers"]
    return layers


def sheet_layers(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the year layers of two sheets, each with a title of its own."""
    titles = [layer["title"] for layer in layers]
    return [
        layer
        for layer in layers
        if layer["kind"] == "year"
        and len(layer["versions"]) == 2
        and titles.count(layer["title"]) == 1
    ]


def ready_layer(page: Page, area_id: str, key: str) -> dict[str, Any]:
    """Wait until every preview of a layer is built; return the layer."""
    deadline = time.monotonic() + BUILD_TIMEOUT_S
    while True:
        layer = next(item for item in layers_of(page, area_id) if item["key"] == key)
        if layer["preview"]["state"] == "ready":
            return layer
        assert time.monotonic() < deadline, f"layer {key} was not built in time"
        page.wait_for_timeout(1000)


def tile_bounds(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return the WGS84 box of an XYZ tile."""
    n = 2**z

    def latitude(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))

    return (x / n * 360 - 180, latitude(y + 1), (x + 1) / n * 360 - 180, latitude(y))


def meets(box: tuple[float, ...], bounds: list[float]) -> bool:
    """Whether two WGS84 boxes meet (touching counts)."""
    return (
        box[0] <= bounds[2]
        and box[2] >= bounds[0]
        and box[1] <= bounds[3]
        and box[3] >= bounds[1]
    )


def union(boxes: list[list[float]]) -> list[float]:
    """Return the box of several boxes."""
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def tile_of(url: str) -> tuple[int, int, int]:
    """Return ``z, x, y`` of a tile address."""
    found = TILE.search(url)
    assert found is not None, url
    z, x, y = (int(value) for value in found.groups())
    return z, x, y


def template_of(url: str) -> str:
    """Return the template of a tile address: its source."""
    return TILE.sub("/tiles/{z}/{x}/{y}.png", url, count=1)


def layer_tiles(seen: list[Seen], served: Served, key: str | None = None) -> list[Seen]:
    """Return the requests of layer tiles, of one layer when ``key`` is given."""
    prefix = f"{served.base}/api/v1/local-layers/tiles/"
    return [
        request
        for request in seen
        if request.url.startswith(prefix)
        and (
            key is None or dict(parse_qsl(urlsplit(request.url).query))["layer"] == key
        )
    ]


def slot_of(store: StoreManifest, family: Family) -> tuple[str, str]:
    """Return the slot path of a family and the version its standard path holds."""
    link = next(
        entry
        for entry in store.by_family(family)
        if entry.kind == "link" and entry.version_path is not None
    )
    assert link.version_path is not None
    return link.path, link.version_path


def show_on_map(
    page: Page, served: Served, store: StoreManifest, family: Family
) -> str:
    """Put a family's current version on the map from its card's preview tab.

    The card opens over the Store view; the version path is returned.
    """
    slot, version = slot_of(store, family)
    page.goto(
        address(
            served,
            view="store",
            file=f"{STORE}/{slot}",
            file_version=version,
            file_tab="preview",
        )
    )
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    card.get_by_role("link", name="Pokaż podgląd na mapie").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    return version


def test_version_tiles_on_map_with_csrf_header(map_store: MapStore, tab: Tab) -> None:
    """A version's tiles go on the map from its card, with the session's header."""
    served = map_store.served
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    slot, version = slot_of(map_store.store, "tif_bbox")
    info = api(page, f"/stores/{STORE}/versions/{version}/preview")
    assert info["state"] == "ready"
    assert info["tiles_url"] is not None and info["features_url"] is None
    seen = watch(page)

    show_on_map(page, served, map_store.store, "tif_bbox")
    query = query_of(page)
    assert query["view"] == "map"
    assert query["preview"] == info["ref"]
    assert query["preview_style"] == info["default_style"]
    assert not {"file", "file_version", "file_tab", "file_style"} & set(query)
    prefix = f"{served.base}/api/v1/stores/{STORE}/versions/{version}/tiles/"
    wait_for(
        page, lambda: [r for r in seen if r.url.startswith(prefix)], "version tiles"
    )
    wait_still(page)
    # The map frames the version and asks only for its tiles in its zooms.
    lon, lat = (float(value) for value in query_of(page)["center"].split(","))
    bounds = info["bounds"]
    assert bounds[0] <= lon <= bounds[2] and bounds[1] <= lat <= bounds[3]
    tiles = [r for r in seen if r.url.startswith(prefix)]
    for request in tiles:
        assert request.csrf == token
        z, x, y = tile_of(request.url)
        assert info["minzoom"] <= z <= info["maxzoom"]
        assert meets(tile_bounds(z, x, y), bounds)
        assert dict(parse_qsl(urlsplit(request.url).query)) == {
            "style": info["default_style"]
        }
    section = legend(page).get_by_role("region", name="Podgląd pliku")
    expect(section).to_contain_text(PurePosixPath(version).name)
    expect(section).to_contain_text("Obrys pliku")

    # Another style: its tiles and its legend; the style lives in the address.
    hypsometry = info["legends"]["hypsometry"]
    count = len(seen)
    section.get_by_role("group", name="Styl podglądu").get_by_role(
        "button", name="hipsometria"
    ).click()
    wait_for(
        page,
        lambda: [r for r in seen[count:] if "style=hypsometry" in r.url],
        "tiles of another style",
    )
    assert all(r.csrf == token for r in seen[count:] if r.url.startswith(prefix))
    assert query_of(page)["preview_style"] == "hypsometry"
    expect(section.locator(".pv-ramp")).to_have_attribute(
        "style", re.compile(re.escape(", ".join(hypsometry["colors"])))
    )

    # Back to the card, the preview stays on the map; then off the map.
    section.get_by_role("link", name="Karta pliku").click()
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card.get_by_role("tab", name="Podgląd")).to_have_attribute(
        "aria-selected", "true"
    )
    assert query_of(page)["preview"] == info["ref"]
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    section.get_by_role("button", name="Zamknij podgląd pliku").click()
    expect(section).to_have_count(0)
    assert not {"preview", "preview_style"} & set(query_of(page))
    tab.assert_clean()


def test_year_buttons_select_layer_and_tiles(map_store: MapStore, tab: Tab) -> None:
    """Year buttons choose a layer: its outlines, its tiles, the address."""
    served = map_store.served
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    area_id = nmt_area(page)
    layers = layers_of(page, area_id)
    first, second = sheet_layers(layers)[:2]
    seen = watch(page)

    page.goto(address(served, view="map", product="nmt", area_id=area_id))
    buttons = strip(page).get_by_role("button")
    expect(buttons).to_have_count(len(layers))
    # Newest first, as the server orders them; nothing chosen yet.
    titles = [text.split("\n")[0] for text in buttons.all_inner_texts()]
    assert titles == [layer["title"] for layer in layers]
    expect(strip(page).locator("[aria-pressed=true]")).to_have_count(0)
    wait_still(page)
    every = counter(page).inner_text()

    button = strip(page).get_by_role("button", name=first["title"], exact=True)
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    assert query_of(page)["layer"] == first["key"]
    expect(counter(page)).to_have_text("2 obrysy w widoku")
    section = legend(page).get_by_role("region", name=f"Warstwa {first['title']}")
    expect(section).to_contain_text(
        "gotowe podglądy: 2 z 2", timeout=BUILD_TIMEOUT_S * 1000
    )
    expect(legend(page)).to_contain_text(f"Obrysy plików warstwy {first['title']}")
    tiles = wait_for(
        page, lambda: layer_tiles(seen, served, first["key"]), "layer tiles"
    )
    assert {request.csrf for request in tiles} == {token}

    # Another year: its own tiles; the first one is no longer chosen.
    other = strip(page).get_by_role("button", name=second["title"], exact=True)
    other.click()
    expect(other).to_have_attribute("aria-pressed", "true")
    expect(button).to_have_attribute("aria-pressed", "false")
    assert query_of(page)["layer"] == second["key"]
    expect(
        legend(page).get_by_role("region", name=f"Warstwa {second['title']}")
    ).to_contain_text("gotowe podglądy: 2 z 2", timeout=BUILD_TIMEOUT_S * 1000)
    tiles = wait_for(
        page,
        lambda: layer_tiles(seen, served, second["key"]),
        "tiles of the other layer",
    )
    assert {request.csrf for request in tiles} == {token}

    # A second click clears the choice: every outline again, no layer.
    other.click()
    expect(strip(page).locator("[aria-pressed=true]")).to_have_count(0)
    assert "layer" not in query_of(page)
    expect(counter(page)).to_have_text(every)
    expect(legend(page).locator(".legend-section")).to_have_count(0)
    tab.assert_clean()


def test_year_layer_is_one_raster_source(map_store: MapStore, tab: Tab) -> None:
    """A layer of several sheets is one source of layer tiles, none per version."""
    served = map_store.served
    page = open_session(tab, served)
    area_id = nmt_area(page)
    chosen = sheet_layers(layers_of(page, area_id))[0]
    layer = ready_layer(page, area_id, chosen["key"])
    seen = watch(page)

    page.goto(
        address(served, view="map", product="nmt", area_id=area_id, layer=layer["key"])
    )
    wait_for(page, lambda: layer_tiles(seen, served, layer["key"]), "layer tiles")
    wait_still(page)
    api_tiles = [
        r
        for r in seen
        if r.url.startswith(f"{served.base}/api/") and "/tiles/" in r.url
    ]
    template = f"{served.base}{layer['preview']['tiles_url']}"
    assert {template_of(request.url) for request in api_tiles} == {template}
    assert not [r for r in api_tiles if "/versions/" in r.url]
    bounds = union([version["bounds"] for version in layer["versions"]])
    for request in api_tiles:
        z, x, y = tile_of(request.url)
        assert z >= layer["preview"]["minzoom"]
        assert meets(tile_bounds(z, x, y), bounds)
    # Per-version sources would give one template per sheet of the layer.
    assert len(layer["versions"]) == 2
    tab.assert_clean()


def test_below_layer_minzoom_outlines_and_hint(map_store: MapStore, tab: Tab) -> None:
    """Below the layer's minzoom only its outlines and a way to zoom in."""
    served = map_store.served
    page = open_session(tab, served)
    area_id = nmt_area(page)
    chosen = sheet_layers(layers_of(page, area_id))[0]
    layer = ready_layer(page, area_id, chosen["key"])
    minzoom = layer["preview"]["minzoom"]
    west, south, east, north = union(
        [version["bounds"] for version in layer["versions"]]
    )
    center = f"{(west + east) / 2:.5f},{(south + north) / 2:.5f}"
    seen = watch(page)

    # MapLibre's zoom counts 512 px tiles: its tiles of 256 px are one deeper.
    page.goto(
        address(
            served,
            view="map",
            product="nmt",
            area_id=area_id,
            layer=layer["key"],
            center=center,
            zoom=str(minzoom - 3),
        )
    )
    expect(counter(page)).to_have_text("2 obrysy w widoku")
    hint = page.get_by_role("status").filter(has_text="Przybliż, aby zobaczyć podgląd")
    expect(hint).to_be_visible()
    wait_still(page)
    assert layer_tiles(seen, served) == []
    assert query_of(page)["zoom"] == f"{minzoom - 3:.2f}"

    hint.get_by_role("button", name="Przybliż").click()
    tiles = wait_for(
        page, lambda: layer_tiles(seen, served, layer["key"]), "tiles after zooming in"
    )
    expect(hint).to_have_count(0)
    wait_still(page)
    assert float(query_of(page)["zoom"]) == pytest.approx(minzoom - 1, abs=0.01)
    assert {tile_of(request.url)[0] for request in tiles} == {minzoom}
    expect(counter(page)).to_have_text("2 obrysy w widoku")
    tab.assert_clean()


def test_layer_in_url_restores_view(map_store: MapStore, tab: Tab) -> None:
    """An address with a layer opens it again; an unknown layer leaves it."""
    served = map_store.served
    page = open_session(tab, served)
    area_id = nmt_area(page)
    chosen = sheet_layers(layers_of(page, area_id))[0]
    layer = ready_layer(page, area_id, chosen["key"])
    west, south, east, north = union(
        [version["bounds"] for version in layer["versions"]]
    )
    position = {
        "center": f"{(west + east) / 2:.5f},{(south + north) / 2:.5f}",
        "zoom": f"{layer['preview']['minzoom']:.2f}",
    }
    shared = address(
        served,
        view="map",
        product="nmt",
        area_id=area_id,
        layer=layer["key"],
        **position,
    )
    seen = watch(page)

    for _ in range(2):
        page.goto(shared)
        button = strip(page).get_by_role("button", name=layer["title"], exact=True)
        expect(button).to_have_attribute("aria-pressed", "true")
        expect(counter(page)).to_have_text("2 obrysy w widoku")
        expect(
            legend(page).get_by_role("region", name=f"Warstwa {layer['title']}")
        ).to_contain_text("gotowe podglądy: 2 z 2")
        wait_for(page, lambda: layer_tiles(seen, served, layer["key"]), "layer tiles")
        wait_still(page)
        # The position of the link is kept: no framing of the area.
        assert {name: query_of(page)[name] for name in position} == position
        assert query_of(page)["layer"] == layer["key"]
        seen.clear()

    unknown = address(
        served, view="map", product="nmt", area_id=area_id, layer=f"{layer['key']}0"
    )
    page.goto(unknown)
    expect(strip(page).get_by_role("button").first).to_be_visible()
    expect(page).not_to_have_url(re.compile(r"[?&]layer="))
    expect(strip(page).locator("[aria-pressed=true]")).to_have_count(0)
    tab.assert_clean()


def test_no_csp_violations_map_previews(map_store: MapStore, tab: Tab) -> None:
    """Layer tiles, a version's tiles and a vector's features obey the CSP."""
    served = map_store.served
    tiles = map_store.tiles
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    area_id = nmt_area(page)
    chosen = sheet_layers(layers_of(page, area_id))[0]
    layer = ready_layer(page, area_id, chosen["key"])
    seen = watch(page)

    page.goto(
        address(served, view="map", product="nmt", area_id=area_id, layer=layer["key"])
    )
    wait_for(page, lambda: layer_tiles(seen, served, layer["key"]), "layer tiles")
    wait_still(page)
    show_on_map(page, served, map_store.store, "tif_bbox")
    legend(page).get_by_role("group", name="Styl podglądu").get_by_role(
        "button", name="hipsometria"
    ).click()
    wait_for(
        page,
        lambda: [r for r in seen if "style=hypsometry" in r.url],
        "hypsometry tiles",
    )
    wait_still(page)

    # A vector: the features of the view, simplified to the map's zoom.
    version = show_on_map(page, served, map_store.store, "gpkg_layers")
    prefix = f"{served.base}/api/v1/stores/{STORE}/versions/{version}/features?"
    wait_for(page, lambda: [r for r in seen if r.url.startswith(prefix)], "features")
    wait_still(page)
    section = legend(page).get_by_role("region", name="Podgląd pliku")
    expect(section).to_contain_text("Obiekty pliku w widoku")
    expect(section.locator(".loading")).to_have_count(0)
    features = [r for r in seen if r.url.startswith(prefix)]
    last = dict(parse_qsl(urlsplit(features[-1].url).query))
    # The API's zoom is that of 256 px tiles, one deeper than MapLibre's (the
    # address rounds the map's zoom to 0.01).
    zoom = float(query_of(page)["zoom"])
    assert int(last["zoom"]) in {math.ceil(zoom + 0.995), math.ceil(zoom + 1.005)}
    west, south, east, north = (float(value) for value in last["bbox"].split(","))
    lon, lat = (float(value) for value in query_of(page)["center"].split(","))
    assert west < lon < east and south < lat < north

    # The session's header goes to the API only, never to the basemap.
    api_requests = [r for r in seen if r.url.startswith(f"{served.base}/api/")]
    assert {r.csrf for r in api_requests} == {token}
    basemap = [r for r in seen if r.url.startswith(f"{tiles.origin}/")]
    assert basemap
    assert {r.csrf for r in basemap} == {None}
    assert all(
        url.startswith(f"{tiles.origin}/") for url in tab.foreign_requests(served.base)
    )
    tab.assert_clean()
