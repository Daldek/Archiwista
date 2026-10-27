"""The map view in Chromium on a real server (plan v0.1, step 10b).

The area tools (rectangle, polygon, the map view, a sheet typed or clicked in
the sheet grid, a geometry file), the local state of an area after the
store changed, more than 5000 outlines shown as their grid, the counter of
files without outline leading to the catalog, an online basemap from a tile
server on another origin within the CSP, offline mode without a single
external request, keyboard and ARIA, the layout at 1440 and 390 px, and in
Chromium and Firefox the panel scrolled by the wheel to its last step.
"""

import json
import re
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import FloatRect, Locator, Page, ViewportSize, expect

from archiwista.config import AppSettings, BasemapConfig, StoreConfig
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import (
    BUILDINGS,
    BUILDINGS_LOD2,
    NMT,
    ExpectedEntry,
    StoreManifest,
    make_store,
)
from tests.fixtures.store_edits import sidecar_path
from tests.fixtures.tile_server import tile_server

Serve = Callable[..., Served]

INDEX_TIMEOUT_S = 120.0
# Slots of a store whose current outlines exceed the 5000 drawn one by one.
MANY_SLOTS = 5400
# The map is still when its address has not changed for this long.
STILL_S = 0.6
WORLD = "-180,-85,180,85"
HEALTH = """async () => {
  const token = sessionStorage.getItem("archiwista_csrf");
  const headers = { "X-Archiwista-CSRF": token };
  const answer = await fetch("/api/v1/health", { headers });
  const health = await answer.json();
  return health.stores.length > 0 && health.stores.every(
    (item) => item.state.indexed_at !== null && item.state.running_job === null);
}"""
API_GET = """async (path) => {
  const token = sessionStorage.getItem("archiwista_csrf");
  const headers = { "X-Archiwista-CSRF": token };
  const answer = await fetch(`/api/v1${path}`, { headers });
  return { status: answer.status, body: await answer.json() };
}"""
LOADED = re.compile("w widoku|Brak obrysów")
# Installed before any page script: the canvas has no WebGL2 context to give.
NO_WEBGL2 = """
const getContext = HTMLCanvasElement.prototype.getContext;
HTMLCanvasElement.prototype.getContext = function (kind, ...options) {
  return kind === "webgl2" ? null : getContext.call(this, kind, ...options);
};
"""
# A laptop's window: the panel's steps reach below its fold.
SMALL: ViewportSize = {"width": 1280, "height": 600}


def zespol(root: Path) -> StoreConfig:
    """Return the generated store as the ``zespol`` store."""
    return StoreConfig(id="zespol", name="Zespół", kartograf=root, kind="local")


def offline_settings(store: StoreManifest) -> AppSettings:
    """Return test server settings: the store and its projects, offline."""
    return AppSettings(
        offline=True, stores=(zespol(store.root),), project_dirs=(store.projects_dir,)
    )


def api_get(page: Page, path: str) -> Any:
    """Return the JSON answer of an API read made with the page's session."""
    answer: dict[str, Any] = page.evaluate(API_GET, path)
    assert answer["status"] == 200, answer
    return answer["body"]


def wait_indexed(page: Page) -> None:
    """Wait for the first scan of the stores; the page has a session."""
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(HEALTH):
        assert time.monotonic() < deadline, "the store was not indexed in time"
        page.wait_for_timeout(250)


def open_map(tab: Tab, served: Served, query: str = "") -> Page:
    """Start a session, wait for the first scan and open the map view."""
    page = tab.page
    page.goto(served.token_url())
    wait_indexed(page)
    page.goto(f"{served.base}/?view=map{query}")
    expect(counter(page)).to_have_text(LOADED, timeout=30_000)
    return page


def counter(page: Page) -> Locator:
    """Return the counter of outlines in the view."""
    return page.locator(".map-count")


def wait_still(page: Page) -> None:
    """Wait until the map stopped moving and the outlines of its view arrived.

    The address changes only when a move ends, so the wait starts after the
    longest framing animation (600 ms).
    """
    page.wait_for_timeout(700)
    deadline = time.monotonic() + 20
    address = page.url
    since = time.monotonic()
    while time.monotonic() - since < STILL_S:
        assert time.monotonic() < deadline, "the map did not stop"
        page.wait_for_timeout(100)
        if page.url != address:
            address = page.url
            since = time.monotonic()
    expect(page.locator(".map-counts .loading")).to_have_count(0)
    expect(counter(page)).to_have_text(LOADED)


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def map_box(page: Page) -> FloatRect:
    """Return the map's box on the page."""
    box = page.locator(".map-gl").bounding_box()
    assert box is not None
    return box


def nmt_sheets(store: StoreManifest) -> list[ExpectedEntry]:
    """Return the regular NMT sheets of the store (standard paths)."""
    return [
        entry
        for entry in store.by_kind("link")
        if entry.segment == NMT
        and entry.family == "asc_sheet"
        and entry.case == "regular"
    ]


def choose_area_sheet(page: Page, sheet: str) -> None:
    """Type a sheet code into the area tools, wait for the area and the map."""
    page.get_by_label("Godło arkusza").fill(sheet)
    page.get_by_role("button", name="Wybierz", exact=True).click()
    expect(page.locator(".area-card .big")).to_have_text(sheet)
    wait_still(page)


def area_of(page: Page) -> dict[str, Any]:
    """Return the area of the address as the API keeps it."""
    area: dict[str, Any] = api_get(page, f"/areas/{query_of(page)['area_id']}")
    return area


def test_draw_rectangle_and_polygon_areas(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A dragged rectangle and clicked polygon become areas; Esc cancels drawing."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = serve(offline_settings(store))
    page = open_map(tab, served)
    wait_still(page)
    box = map_box(page)
    rectangle = page.get_by_role("button", name="Prostokąt")
    polygon = page.get_by_role("button", name="Wielokąt")

    rectangle.click()
    expect(rectangle).to_have_attribute("aria-pressed", "true")
    expect(
        page.get_by_role("status").filter(has_text="Przeciągnij po mapie")
    ).to_be_visible()
    page.keyboard.press("Escape")
    expect(rectangle).to_have_attribute("aria-pressed", "false")
    rectangle.click()
    page.mouse.move(box["x"] + 300, box["y"] + 200)
    page.mouse.down()
    page.mouse.move(box["x"] + 450, box["y"] + 300, steps=5)
    page.mouse.move(box["x"] + 600, box["y"] + 420, steps=5)
    page.mouse.up()
    expect(page.locator(".area-card .big")).to_have_text("Prostokąt")
    drawn = area_of(page)
    wait_still(page)
    polygon.click()
    for x, y in ((320, 180), (620, 210), (660, 480), (330, 500)):
        page.mouse.click(box["x"] + x, box["y"] + y)
    expect(
        page.get_by_role("status").filter(has_text="Stawiaj wierzchołki (4)")
    ).to_be_visible()
    page.keyboard.press("Backspace")
    expect(
        page.get_by_role("status").filter(has_text="Stawiaj wierzchołki (3)")
    ).to_be_visible()
    page.keyboard.press("Enter")
    expect(page.locator(".area-card .big")).to_have_text("Wielokąt")
    shape = area_of(page)

    assert (drawn["source"], drawn["name"]) == ("drawn", "Prostokąt")
    assert "PL" in drawn["countries"]
    assert len(drawn["geometry"]["coordinates"][0]) == 5
    assert (shape["source"], shape["name"]) == ("drawn", "Wielokąt")
    assert len(shape["geometry"]["coordinates"][0]) == 4
    expect(page.locator(".area-badge")).to_contain_text("Obszar: Wielokąt")
    expect(page.locator(".area-card")).to_contain_text("km²")
    tab.assert_clean()


def test_area_from_map_view_sheet_and_geometry_file(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """The view, a sheet typed or clicked in the grid, and a file become areas."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    sheet = nmt_sheets(store)[0].unit
    assert sheet is not None
    served = serve(offline_settings(store))
    page = open_map(tab, served)
    ring = [
        [15.69, 54.75],
        [15.75, 54.75],
        [15.75, 54.78],
        [15.69, 54.78],
        [15.69, 54.75],
    ]
    geojson = tmp_path / "zlewnia.geojson"
    geojson.write_text(
        json.dumps(
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ),
        encoding="utf-8",
    )
    broken = tmp_path / "zepsuty.geojson"
    broken.write_text("{nie json", encoding="utf-8")
    grid = page.get_by_role("button", name="Siatka godeł")

    page.get_by_role("button", name="Widok mapy").click()
    expect(page.locator(".area-card .big")).to_have_text("Widok mapy")
    view = area_of(page)
    choose_area_sheet(page, sheet)
    typed = area_of(page)
    grid.click()
    expect(
        page.get_by_text(re.compile(r"Kliknij arkusz siatki PL-1992 1:10\s000"))
    ).to_be_visible()
    box = map_box(page)
    # The grid's features are queryable once MapLibre has tiled them.
    deadline = time.monotonic() + 15
    while page.locator(".area-card .big").inner_text() == sheet:
        assert time.monotonic() < deadline, "no sheet of the grid was chosen"
        page.mouse.click(box["x"] + 16, box["y"] + box["height"] / 2)
        page.wait_for_timeout(500)
    clicked = area_of(page)
    grid.click()
    page.get_by_label("Godło arkusza").fill("N-34-999-Z")
    page.get_by_role("button", name="Wybierz", exact=True).click()
    expect(page.get_by_text("Nie ma arkusza „N-34-999-Z”")).to_be_visible()
    page.get_by_label("Plik geometrii obszaru").set_input_files(geojson)
    expect(page.locator(".area-card .big")).to_have_text("zlewnia.geojson")
    uploaded = area_of(page)
    page.get_by_label("Plik geometrii obszaru").set_input_files(broken)
    expect(
        page.get_by_role("alert").filter(has_text="Nie można odczytać")
    ).to_be_visible()

    assert (view["source"], view["name"]) == ("view", "Widok mapy")
    assert (typed["source"], typed["name"]) == ("sheet", sheet)
    assert clicked["source"] == "sheet"
    assert re.fullmatch(r"[A-Z]-\d{2}-[\w-]+", clicked["name"])
    assert clicked["name"] != sheet
    assert clicked["bbox"][2] == pytest.approx(typed["bbox"][0])
    assert (uploaded["source"], uploaded["name"]) == ("file", "zlewnia.geojson")
    assert uploaded["bbox"] == pytest.approx([15.69, 54.75, 15.75, 54.78])
    tab.assert_clean()


def test_local_coverage_after_refresh(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The local state re-reads the area's slots: a removed file is gone at once."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    link = nmt_sheets(store)[0]
    assert link.unit is not None
    served = serve(offline_settings(store))
    page = open_map(tab, served, "&product=nmt")
    choose_area_sheet(page, link.unit)
    local = page.get_by_role("region", name="Stan lokalny")
    expect(local.get_by_text("lokalnie 100% obszaru")).to_be_visible()
    expect(local).to_contain_text("Polska")
    before = counter(page).inner_text()

    (store.root / link.path).unlink()
    sidecar_path(store.root, link.path).unlink()
    local.get_by_role("button", name="Odśwież").click()

    expect(local.get_by_text("lokalnie 100% obszaru")).to_have_count(0)
    expect(
        local.get_by_text(re.compile(r"lokalnie (?:<1|[0-9]{1,2})% obszaru"))
    ).to_be_visible()
    expect(local).to_contain_text("0 plików z obrysem w obszarze")
    expect(counter(page)).not_to_have_text(before)
    slot = api_get(page, f"/stores/zespol/slots/{link.path}")
    assert slot["current"] is None
    tab.assert_clean()


def test_more_than_5000_footprints_aggregate_to_grid(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Above 5000 outlines the view is their grid; closer in, the outlines."""
    store = make_store(tmp_path / "store", slots=MANY_SLOTS, seed=3)
    served = serve(offline_settings(store))
    page = open_map(tab, served)
    whole = api_get(page, f"/map/footprints?bbox={WORLD}&limit=5000&grid_columns=64")
    densest = max(whole["cells"], key=lambda cell: cell["count"])
    box = ",".join(
        str(densest[key]) for key in ("min_lon", "min_lat", "max_lon", "max_lat")
    )
    inside = api_get(page, f"/map/footprints?bbox={box}&limit=5000")
    lon, lat = inside["items"][0]["geometry"]["coordinates"][0][0]

    expect(counter(page)).to_contain_text("siatka zagęszczenia")
    expect(page.get_by_text("Siatka zagęszczenia: liczba obrysów")).to_be_visible()
    with page.expect_response(re.compile("/api/v1/map/footprints")) as answered:
        page.goto(f"{served.base}/?view=map&center={lon:.5f},{lat:.5f}&zoom=11")
    closer = answered.value.json()
    expect(counter(page)).to_have_text(re.compile(r"^\d+ obrys\S* w widoku$"))

    assert whole["aggregated"] is True
    assert whole["total"] > 5000
    assert sum(cell["count"] for cell in whole["cells"]) == whole["total"]
    assert inside["aggregated"] is False
    assert closer["aggregated"] is False
    assert 0 < len(closer["items"]) <= 5000
    expect(page.get_by_text("Obrysy plików w magazynie")).to_be_visible()
    tab.assert_clean()


def test_no_outline_counter_opens_catalog(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Files without outline are counted on the map and open in the catalog."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    # Buildings come as ZIP packages per TERYT unit: none has an outline.
    buildings = [
        entry
        for entry in store.by_kind("link")
        if entry.segment in (BUILDINGS, BUILDINGS_LOD2)
    ]
    unit = next(
        entry.unit
        for entry in buildings
        if entry.family == "zip_teryt" and entry.case == "regular"
    )
    assert unit is not None
    served = serve(offline_settings(store))
    page = open_map(tab, served, "&product=buildings&versions=all")
    every = f"/map/footprints?bbox={WORLD}&product=buildings&versions=all"
    unlocated = api_get(page, every)["groups"]["none"]
    in_unit = api_get(page, f"{every}&unit={unit}")["groups"]["none"]
    link = page.get_by_role("link", name=re.compile("bez obrysu"))
    expect(link).to_have_text(re.compile(rf"^{unlocated} plik\S* bez obrysu"))
    filters = page.locator("details.map-filters")
    expect(filters).to_have_attribute("open", "")
    filters.get_by_label("Kod jednostki").fill(unit)
    filters.get_by_label("Kod jednostki").press("Enter")
    expect(
        page.get_by_role("listitem").filter(has_text=f"jednostka: {unit}")
    ).to_be_visible()
    expect(link).to_have_text(re.compile(rf"^{in_unit} plik\S* bez obrysu"))

    link.click()

    expect(page).to_have_url(re.compile(r"view=catalog"))
    assert query_of(page) == {
        "view": "catalog",
        "product": "buildings",
        "versions": "all",
        "unit": unit,
        "location": "none",
    }
    assert (unlocated, in_unit) == (
        len(buildings),
        sum(entry.unit == unit for entry in buildings),
    )
    assert in_unit < unlocated
    tab.assert_clean()


def test_online_basemap_from_local_tile_server_without_csp_violations(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """An online basemap on another origin loads within the CSP, without Referer."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    with tile_server() as tiles:
        basemap = BasemapConfig(
            name="Kafle testowe",
            url=tiles.template,
            attribution="© Kafle testowe",
            grayscale=True,
        )
        served = serve(
            AppSettings(
                offline=False,
                basemaps=(basemap,),
                stores=(zespol(store.root),),
                project_dirs=(store.projects_dir,),
            )
        )
        page = tab.page
        page.goto(served.token_url())
        expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
        document = page.goto(f"{served.base}/?view=map&center=19.0,52.0&zoom=6")
        expect(page.get_by_text("© Kafle testowe")).to_be_attached()
        deadline = time.monotonic() + 30
        while not tiles.tiles():
            assert time.monotonic() < deadline, "no basemap tile was requested"
            page.wait_for_timeout(100)
        wait_still(page)
        requested = tiles.tiles()

    assert document is not None
    policy = document.headers["content-security-policy"]
    assert f"img-src 'self' data: blob: {tiles.origin};" in policy
    assert f"connect-src 'self' {tiles.origin};" in policy
    assert {request.referer for request in requested} == {None}
    assert {request.origin for request in requested} <= {served.base, None}
    foreign = tab.foreign_requests(served.base)
    assert foreign
    assert all(url.startswith(f"{tiles.origin}/") for url in foreign)
    expect(page.get_by_label("Podkład")).to_have_value("Kafle testowe")
    tab.assert_clean()


def test_offline_makes_no_external_requests(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Offline, the whole flow asks nothing outside Archiwista.

    The built-in basemaps stay configured: neither the vector one's TileJSON
    nor any tile is asked for, and the CSP names no other origin.
    """
    store = make_store(tmp_path / "store", slots=24, seed=7)
    sheet = nmt_sheets(store)[0].unit
    assert sheet is not None
    served = serve(offline_settings(store))
    page = open_map(tab, served, "&product=nmt")
    document = page.goto(page.url)
    expect(counter(page)).to_have_text(LOADED)

    choose_area_sheet(page, sheet)
    expect(page.get_by_text("lokalnie 100% obszaru")).to_be_visible()
    page.get_by_role("button", name="Siatka godeł").click()
    expect(page.get_by_text(re.compile("Kliknij arkusz siatki"))).to_be_visible()
    wait_still(page)

    assert document is not None
    policy = document.headers["content-security-policy"]
    assert "img-src 'self' data: blob:;" in policy
    assert "connect-src 'self';" in policy
    assert tab.foreign_requests(served.base) == []
    expect(page.get_by_text("Tryb offline: bez podkładu")).to_be_visible()
    expect(page.get_by_label("Podkład")).to_have_count(0)
    tab.assert_clean()


def test_map_keyboard_and_aria(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The map moves with keys; tools, panel, legend and the file list speak ARIA."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    versions = Counter(
        entry.unit
        for entry in store.by_kind("version")
        if entry.segment == NMT
        and entry.family == "asc_sheet"
        and entry.case == "regular"
    )
    sheet, count = versions.most_common(1)[0]
    assert sheet is not None and count >= 2
    served = serve(offline_settings(store))
    page = open_map(tab, served, "&product=nmt&versions=all")
    wait_still(page)
    toggle = page.get_by_role("button", name="Wybór", exact=True)
    panel = page.get_by_role("complementary", name="Wybór")
    legend = page.get_by_role("button", name="Legenda")

    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(panel).to_be_visible()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(panel).to_be_hidden()
    toggle.click()
    expect(panel).to_be_visible()
    expect(legend).to_have_attribute("aria-expanded", "true")
    legend.click()
    expect(legend).to_have_attribute("aria-expanded", "false")
    start = query_of(page)
    page.get_by_role("region", name=re.compile("Mapa magazynu")).focus()
    page.keyboard.press("ArrowRight")
    wait_still(page)
    page.keyboard.press("Equal")
    wait_still(page)
    moved = query_of(page)
    choose_area_sheet(page, sheet)
    box = map_box(page)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    expect(page.get_by_text("Kliknij, aby otworzyć kartę pliku")).to_be_visible()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    files = page.get_by_role("dialog", name="Pliki w tym miejscu")
    expect(files).to_be_visible()
    choices = files.get_by_role("button", name=re.compile(re.escape(sheet)))
    expect(choices).to_have_count(count)
    page.keyboard.press("Escape")
    expect(files).to_have_count(0)

    assert moved["center"] != start["center"]
    assert float(moved["zoom"]) > float(start["zoom"])
    tab.assert_clean()


def test_a_browser_without_webgl2_is_told_why_the_map_is_missing(
    serve: Serve, tab: Tab
) -> None:
    """Without WebGL2 the map says it cannot be drawn here, and why."""
    served = serve(AppSettings(offline=True))
    page = tab.page
    page.add_init_script(NO_WEBGL2)
    fragment = urlsplit(served.token_url()).fragment

    page.goto(f"{served.base}/?view=map#{fragment}")

    expect(page.get_by_role("alert")).to_have_text(
        re.compile(r"^Mapa nie działa w tej przeglądarce: \S")
    )
    expect(page.get_by_role("complementary", name="Wybór")).to_be_visible()
    tab.assert_clean()


def test_map_layout_at_1440_and_390(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """At 1440 px the panel stands beside the map; at 390 px it is a bottom sheet."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = serve(offline_settings(store))
    page = open_map(tab, served)
    toggle = page.get_by_role("button", name="Wybór", exact=True)
    panel = page.get_by_role("complementary", name="Wybór")
    overflow = "() => document.documentElement.scrollWidth - innerWidth"

    wide_panel = panel.bounding_box()
    wide_map = map_box(page)
    wide_overflow = page.evaluate(overflow)
    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    expect(counter(page)).to_have_text(LOADED)
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(panel).to_be_hidden()
    narrow_map = map_box(page)
    toggle.click()
    expect(panel).to_be_visible()
    expect(panel.get_by_role("button", name="Prostokąt")).to_be_visible()
    sheet = panel.bounding_box()
    panel.get_by_role("button", name="Zwiń panel „Wybór”").click()
    expect(panel).to_be_hidden()

    assert wide_panel is not None and wide_panel["x"] < wide_map["x"]
    assert wide_map["width"] >= 900
    assert narrow_map["width"] == 390
    assert sheet is not None and sheet["width"] == 390
    assert (wide_overflow, page.evaluate(overflow)) == (0, 0)
    tab.assert_clean()


def test_wheel_over_the_panel_brings_its_last_step_into_view(
    serve: Serve, engine_tab: Tab, tmp_path: Path
) -> None:
    """At 1280×600 the panel scrolls itself under the wheel, inside the window.

    The map opens in one page load: Firefox fails the stylesheets of a page
    left while they load, an uncaught rejection of the shell. Headless Firefox
    has no WebGL2, so there the map only says it cannot be drawn; the panel
    beside it is the same. The panel is measured once the shell's index
    banner is gone: the shell polls the health every 2 s during a scan, so its
    scan line can stand above the panel after ``wait_indexed`` and leave later,
    which moves the panel up.
    """
    store = make_store(tmp_path / "store", slots=24, seed=7)
    sheet = nmt_sheets(store)[0].unit
    assert sheet is not None
    served = serve(offline_settings(store))
    page = engine_tab.page
    page.set_viewport_size(SMALL)
    fragment = urlsplit(served.token_url()).fragment
    page.goto(f"{served.base}/?view=map&product=nmt#{fragment}")
    wait_indexed(page)
    expect(page.get_by_role("region", name="Stan indeksu")).to_have_count(0)
    panel = page.get_by_role("complementary", name="Wybór")
    panel.get_by_label("Godło arkusza").fill(sheet)
    panel.get_by_role("button", name="Wybierz", exact=True).click()
    expect(panel.get_by_text("lokalnie 100% obszaru")).to_be_visible()
    source = panel.get_by_role("heading", name="U źródła")
    expect(source).not_to_be_in_viewport()
    box = panel.bounding_box()
    assert box is not None

    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(8):
        page.mouse.wheel(0, 300)

    # The panel's content moved, not the panel: the page did not scroll.
    expect(source).to_be_in_viewport()
    assert panel.bounding_box() == box
    assert box["y"] + box["height"] <= SMALL["height"]
    engine_tab.assert_clean()
