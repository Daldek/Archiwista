"""The comparison in Chromium on a real server (plan v0.2, step 14).

One generated store is served for the module, online with a basemap from a
local tile server on another origin. „Porównaj z…” in the file card opens
the comparison of two versions of a slot: the rows of ``GET /compare`` in a
table with the differences marked, „tylko różnice” and the CSV of the rows
shown; both versions' tiles on two maps at one position — the curtain
(moved with a mouse, a finger and the arrows), the fade (a slider) and two
maps side by side. Two year layers of an area compare the same way, with
their summaries side by side.
"""

import csv
import io
import json
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, Request, Route, expect

from archiwista.config import AppSettings, BasemapConfig, ConfigStore, StoreConfig
from archiwista.security import CSRF_HEADER
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import Served, Tab, session_headers
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import NMT, StoreManifest, make_store
from tests.fixtures.tile_server import TileServer, tile_server

STORE = "zespol"
INDEX_TIMEOUT_S = 60.0
# Every layer's missing previews are built by one job each, one job at a time.
BUILD_TIMEOUT_S = 180.0
WAIT_S = 30.0
TILE = re.compile(r"/tiles/(\d+)/(\d+)/(\d+)\.png")
WORLD = "-180,-85,180,85"
CURTAIN = "Kurtyna między A i B"
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
# Every row of the table: its field's name, whether it is marked, the text of
# its cells (a value shown for people without its raw value a click away).
TABLE_ROWS = """() => {
  const rows = document.querySelectorAll(".cmp-table tbody tr:not(.cmp-group)");
  return [...rows].map((row) => {
    const name = row.querySelector("th").cloneNode(true);
    name.querySelector(".cmp-mark")?.remove();
    const text = (cell) => (cell.querySelector(".tech-label") ?? cell).textContent;
    return {
      label: name.textContent.trim(),
      marked: row.classList.contains("diff") && row.querySelector(".cmp-mark") !== null,
      cells: [...row.querySelectorAll("td")].map((cell) => text(cell).trim()),
    };
  });
}"""
CLIP_B = "() => getComputedStyle(document.querySelector('.cmp-pane.b')).clipPath"
OPACITY_B = (
    "() => getComputedStyle(document.querySelector"
    "('.cmp-pane.b .maplibregl-canvas')).opacity"
)


@dataclass(frozen=True)
class CompareStore:
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
def compare_store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[CompareStore]:
    """Serve one generated store, online with a basemap on another origin."""
    root = tmp_path_factory.mktemp("compare")
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
            yield CompareStore(store, Served(server, paths), tiles)


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


def wait_for(page: Page, found: Callable[[], Any], what: str) -> Any:
    """Wait until ``found`` gives something true (the page's own wait); return it."""
    deadline = time.monotonic() + WAIT_S
    while not (value := found()):
        assert time.monotonic() < deadline, f"not in time: {what}"
        page.wait_for_timeout(100)
    return value


def address(served: Served, **params: str) -> str:
    """Return an address of the interface."""
    return f"{served.base}/?{urlencode(params)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def version_pair(page: Page, store: StoreManifest) -> tuple[str, list[dict[str, Any]]]:
    """Return an NMT cutout slot with two versions and its versions, older first."""
    slots = {
        entry.path
        for entry in store.by_family("tif_bbox")
        if entry.kind == "link" and entry.segment == NMT
    }
    for slot in sorted(slots):
        card = api(page, f"/stores/{STORE}/slots/{slot}")
        if len(card["versions"]) == 2:
            # Labelled by their download date: the older label first.
            return slot, sorted(card["versions"], key=lambda version: version["label"])
    raise AssertionError("the store has no NMT cutout with two versions")


def comparison(page: Page, versions: list[dict[str, Any]]) -> dict[str, Any]:
    """Return ``GET /compare`` of two versions, the older as A."""
    query = urlencode({"a": versions[0]["ref"], "b": versions[1]["ref"]})
    answer: dict[str, Any] = api(page, f"/compare?{query}")
    return answer


def compare_address(
    served: Served, versions: list[dict[str, Any]], **params: str
) -> str:
    """Return the comparison of two versions, the older as A."""
    return address(
        served, view="compare", a=versions[0]["ref"], b=versions[1]["ref"], **params
    )


def panel(page: Page) -> Locator:
    """Return the comparison's details panel."""
    return page.get_by_role("complementary", name="Szczegóły porównania")


def shown_value(value: Any) -> str:
    """Return a raw value as the CSV writes it (and the table shows it raw)."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "tak" if value else "nie"
    return str(value)


def version_tiles(seen: list[Seen], served: Served, version: str) -> list[Seen]:
    """Return the requests of a version's tiles."""
    prefix = f"{served.base}/api/v1/stores/{STORE}/versions/{version}/tiles/"
    return [request for request in seen if request.url.startswith(prefix)]


def awaited_tiles(
    page: Page, seen: list[Seen], served: Served, version: str, style: str | None = None
) -> list[Seen]:
    """Wait for requests of a version's tiles (in a style); return them."""

    def found() -> list[Seen]:
        return [
            request
            for request in version_tiles(seen, served, version)
            if style is None or f"style={style}" in request.url
        ]

    tiles: list[Seen] = wait_for(page, found, f"tiles of {version}")
    return tiles


def awaited_layer_tiles(
    page: Page, seen: list[Seen], served: Served, key: str
) -> list[Seen]:
    """Wait for requests of a year layer's tiles; return them."""
    prefix = f"{served.base}/api/v1/local-layers/tiles/"

    def found() -> list[Seen]:
        return [
            request
            for request in seen
            if request.url.startswith(prefix)
            and dict(parse_qsl(urlsplit(request.url).query))["layer"] == key
        ]

    tiles: list[Seen] = wait_for(page, found, f"tiles of layer {key}")
    return tiles


def tiles_at(requests: list[Seen], zoom: int) -> set[tuple[int, int]]:
    """Return the ``x, y`` of tiles of one zoom among requests."""
    found = set()
    for request in requests:
        match = TILE.search(request.url)
        assert match is not None, request.url
        z, x, y = (int(value) for value in match.groups())
        if z == zoom:
            found.add((x, y))
    return found


def slow_drag(page: Page, start: tuple[float, float], end: tuple[float, float]) -> None:
    """Drag with the mouse in small steps, as a person does."""
    page.mouse.move(*start)
    page.mouse.down()
    for step in range(1, 13):
        page.mouse.move(
            start[0] + (end[0] - start[0]) * step / 12,
            start[1] + (end[1] - start[1]) * step / 12,
        )
        page.wait_for_timeout(16)
    page.mouse.up()


def curtain_at(page: Page) -> float:
    """Return where B starts, in percent of the maps' width (its ``clip-path``)."""
    clip = page.evaluate(CLIP_B)
    found = re.fullmatch(r"inset\(0px 0px 0px ([\d.]+)%\)", clip)
    assert found is not None, clip
    return float(found.group(1))


def middle(locator: Locator) -> tuple[float, float]:
    """Return the centre of an element on the page."""
    box = locator.bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


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


def ready_layers(page: Page, area_id: str, count: int) -> list[dict[str, Any]]:
    """Return year layers of two sheets each, once their previews are built."""
    query = urlencode({"store": STORE, "product": "nmt", "area_id": area_id})
    deadline = time.monotonic() + BUILD_TIMEOUT_S
    while True:
        layers = api(page, f"/local-layers?{query}")["layers"]
        titles = [layer["title"] for layer in layers]
        chosen = [
            layer
            for layer in layers
            if layer["kind"] == "year"
            and len(layer["versions"]) == 2
            and titles.count(layer["title"]) == 1
        ][:count]
        assert len(chosen) == count, "the area has too few year layers of two sheets"
        if all(layer["preview"]["state"] == "ready" for layer in chosen):
            return chosen
        assert time.monotonic() < deadline, "the layers were not built in time"
        page.wait_for_timeout(1000)


def test_metadata_table_marks_differences(
    compare_store: CompareStore, tab: Tab
) -> None:
    """„Porównaj z…” shows the rows of /compare with their differences marked."""
    served = compare_store.served
    page = open_session(tab, served)
    slot, versions = version_pair(page, compare_store.store)
    expected = comparison(page, versions)
    differing = [row for row in expected["rows"] if row["differs"]]
    assert differing and len(differing) < len(expected["rows"])

    # From the card of the newer version: the other one is offered.
    page.goto(address(served, view="store", file=f"{STORE}/{slot}"))
    card = page.get_by_role("dialog")
    card.get_by_text("Porównaj z…").click()
    offered = card.get_by_role("list", name="Inne wersje pliku do porównania")
    expect(offered.get_by_role("link")).to_have_count(1)
    offered.get_by_role("link").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    query = query_of(page)
    assert query["view"] == "compare"
    assert (query["a"], query["b"]) == (versions[0]["ref"], versions[1]["ref"])

    details = panel(page)
    expect(details.get_by_role("article", name="Strona A")).to_contain_text(
        expected["a"]["title"]
    )
    expect(details.get_by_role("article", name="Strona B")).to_contain_text(
        expected["b"]["title"]
    )
    summary = f"Różne pola: {len(differing)} z {len(expected['rows'])}"
    expect(details).to_contain_text(summary)
    rows = page.evaluate(TABLE_ROWS)
    assert [row["label"] for row in rows] == [row["label"] for row in expected["rows"]]
    assert [row["marked"] for row in rows] == [
        row["differs"] for row in expected["rows"]
    ]
    # The raw sidecar's values are shown as they are (A-ADR-014).
    for row, wanted in zip(rows, expected["rows"], strict=True):
        if wanted["group"] == "sidecar":
            assert row["cells"] == [shown_value(wanted[side]) or "–" for side in "ab"]

    # „tylko różnice” keeps the marked rows, in the address too.
    details.get_by_role("checkbox", name="tylko różnice").check()
    expect(page.locator(".cmp-table tbody tr:not(.cmp-group)")).to_have_count(
        len(differing)
    )
    assert query_of(page)["only_diff"] == "1"
    only = page.evaluate(TABLE_ROWS)
    assert [row["label"] for row in only] == [row["label"] for row in differing]
    assert all(row["marked"] for row in only)
    details.get_by_role("checkbox", name="tylko różnice").uncheck()
    expect(page.locator(".cmp-table tbody tr:not(.cmp-group)")).to_have_count(
        len(expected["rows"])
    )

    # „Zamień A i B”: the sides change places, their values with them.
    page.get_by_role("button", name="Zamień A i B").click()
    expect(details.get_by_role("article", name="Strona A")).to_contain_text(
        expected["b"]["title"]
    )
    assert (query_of(page)["a"], query_of(page)["b"]) == (
        versions[1]["ref"],
        versions[0]["ref"],
    )
    label = next(row for row in differing if row["field"] == "label")
    swapped = next(
        row for row in page.evaluate(TABLE_ROWS) if row["label"] == label["label"]
    )
    assert swapped["cells"] == [label["b"], label["a"]]
    tab.assert_clean()


def test_curtain_drag_reveals_b(compare_store: CompareStore, tab: Tab) -> None:
    """The curtain moves with a mouse, a finger and the arrows; B shows right of it."""
    served = compare_store.served
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    _, versions = version_pair(page, compare_store.store)
    seen = watch(page)

    page.goto(compare_address(served, versions))
    handle = page.get_by_role("slider", name=CURTAIN)
    expect(handle).to_have_attribute("aria-valuenow", "50")
    assert page.evaluate(CLIP_B) == "inset(0px 0px 0px 50%)"
    # Both maps load their side's tiles, with the session's header.
    for version in versions:
        tiles = awaited_tiles(page, seen, served, version["path"])
        assert {request.csrf for request in tiles} == {token}

    # A mouse: B is revealed from a fifth of the width on.
    stage = page.locator(".cmp-stage").bounding_box()
    assert stage is not None
    grip = middle(page.locator(".cmp-grip"))
    slow_drag(page, grip, (stage["x"] + stage["width"] * 0.2, grip[1]))
    expect(handle).to_have_attribute("aria-valuenow", "20")
    expect(handle).to_have_attribute(
        "aria-valuetext", "A po lewej: 20%, B po prawej: 80%"
    )
    assert curtain_at(page) == pytest.approx(20, abs=0.2)

    # The arrows, with Shift a bigger step.
    handle.focus()
    page.keyboard.press("ArrowRight")
    expect(handle).to_have_attribute("aria-valuenow", "21")
    page.keyboard.press("Shift+ArrowRight")
    expect(handle).to_have_attribute("aria-valuenow", "31")
    assert curtain_at(page) == pytest.approx(31, abs=0.2)

    # A finger (the browser's touch events, not a mouse).
    grip = middle(page.locator(".cmp-grip"))
    touch = page.context.new_cdp_session(page)
    touch.send(
        "Input.dispatchTouchEvent",
        {"type": "touchStart", "touchPoints": [{"x": grip[0], "y": grip[1]}]},
    )
    target = stage["x"] + stage["width"] * 0.6
    for step in range(1, 9):
        x = grip[0] + (target - grip[0]) * step / 8
        touch.send(
            "Input.dispatchTouchEvent",
            {"type": "touchMove", "touchPoints": [{"x": x, "y": grip[1]}]},
        )
    touch.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    expect(handle).to_have_attribute("aria-valuenow", "60")
    assert curtain_at(page) == pytest.approx(60, abs=0.2)

    # Home and End: A or B over the whole map.
    handle.focus()
    page.keyboard.press("Home")
    expect(handle).to_have_attribute("aria-valuenow", "0")
    assert page.evaluate(CLIP_B) == "inset(0px 0px 0px 0%)"
    page.keyboard.press("End")
    expect(handle).to_have_attribute("aria-valuenow", "100")
    assert page.evaluate(CLIP_B) == "inset(0px 0px 0px 100%)"
    tab.assert_clean()


def test_fade_slider_changes_opacity(compare_store: CompareStore, tab: Tab) -> None:
    """„Przenikanie” lays B over A as opaque as its slider says."""
    served = compare_store.served
    page = open_session(tab, served)
    _, versions = version_pair(page, compare_store.store)

    page.goto(compare_address(served, versions))
    modes = page.get_by_role("group", name="Porównanie na mapie")
    modes.get_by_role("button", name="Przenikanie").click()
    assert query_of(page)["mode"] == "fade"
    expect(page.get_by_role("slider", name=CURTAIN)).to_have_count(0)
    slider = page.get_by_role("slider", name="Widoczność B")
    expect(slider).to_have_value("50")
    assert page.evaluate(OPACITY_B) == "0.5"
    assert page.evaluate(CLIP_B) == "none"

    slider.fill("20")
    expect(page.locator(".cmp-fade output")).to_have_text("20%")
    assert page.evaluate(OPACITY_B) == "0.2"
    slider.focus()
    page.keyboard.press("ArrowRight")
    expect(slider).to_have_value("21")
    assert page.evaluate(OPACITY_B) == "0.21"
    slider.fill("0")
    assert page.evaluate(OPACITY_B) == "0"

    # The curtain again: B is whole, cut by the curtain only.
    modes.get_by_role("button", name="Kurtyna").click()
    assert "mode" not in query_of(page)
    assert page.evaluate(OPACITY_B) == "1"
    expect(page.get_by_role("slider", name=CURTAIN)).to_be_visible()
    tab.assert_clean()


def test_side_by_side_maps_stay_in_sync(compare_store: CompareStore, tab: Tab) -> None:
    """Two maps side by side: a move of either is the other's move too."""
    served = compare_store.served
    page = open_session(tab, served)
    _, versions = version_pair(page, compare_store.store)
    info = api(page, f"/stores/{STORE}/versions/{versions[0]['path']}/preview")
    minzoom = info["minzoom"]
    assert info["maxzoom"] >= minzoom + 2
    west, south, east, north = info["bounds"]
    center = f"{(west + east) / 2:.5f},{(south + north) / 2:.5f}"
    seen = watch(page)

    # MapLibre's zoom counts 512 px tiles: at minzoom - 0.4 it asks for the
    # API's tiles of minzoom + 1 (rounded).
    page.goto(
        compare_address(
            served, versions, mode="side", center=center, zoom=f"{minzoom - 0.4:.2f}"
        )
    )
    paths = [version["path"] for version in versions]
    boxes = [page.locator(f".cmp-pane.{side}").bounding_box() for side in "ab"]
    assert boxes[0] is not None and boxes[1] is not None
    assert boxes[0]["x"] + boxes[0]["width"] <= boxes[1]["x"]
    assert (boxes[0]["width"], boxes[0]["height"]) == (
        boxes[1]["width"],
        boxes[1]["height"],
    )

    def same_tiles(zoom: int, since: int) -> set[tuple[int, int]]:
        found = [
            tiles_at(version_tiles(seen[since:], served, path), zoom) for path in paths
        ]
        return found[0] if found[0] and found[0] == found[1] else set()

    wait_for(page, lambda: same_tiles(minzoom + 1, 0), "the first tiles of both maps")

    # A zooms in: B asks for the same tiles of the next zoom.
    count = len(seen)
    page.locator(".cmp-pane.a").get_by_role("button", name="Przybliż").click()
    wait_for(page, lambda: same_tiles(minzoom + 2, count), "B following A's zoom")
    wait_for(page, lambda: query_of(page)["zoom"] == f"{minzoom + 0.6:.2f}", "the zoom")

    # B is dragged and zoomed out: A follows to the same tiles.
    before = query_of(page)["center"]
    pane = middle(page.locator(".cmp-pane.b"))
    slow_drag(page, pane, (pane[0] - 120, pane[1] - 80))
    wait_for(page, lambda: query_of(page)["center"] != before, "the drag's end")
    count = len(seen)
    zoom_out = page.locator(".cmp-pane.b").get_by_role("button", name="Oddal")
    zoom_out.click()
    wait_for(page, lambda: query_of(page)["zoom"] == f"{minzoom - 0.4:.2f}", "zoom out")
    zoom_out.click()
    wait_for(page, lambda: same_tiles(minzoom, count), "A following B")
    wait_for(page, lambda: query_of(page)["zoom"] == f"{minzoom - 1.4:.2f}", "zoom out")
    scales = page.locator(".maplibregl-ctrl-scale").all_inner_texts()
    assert len(scales) == 2 and scales[0] == scales[1]
    tab.assert_clean()


def test_two_year_layers_compared(compare_store: CompareStore, tab: Tab) -> None:
    """Two year layers: each map shows its layer's tiles, the panel their summaries."""
    served = compare_store.served
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    area_id = nmt_area(page)
    newer, older = ready_layers(page, area_id, 2)
    seen = watch(page)

    page.goto(
        address(
            served,
            view="compare",
            store=STORE,
            product="nmt",
            area_id=area_id,
            a_layer=older["key"],
            b_layer=newer["key"],
        )
    )
    for layer in (older, newer):
        tiles = awaited_layer_tiles(page, seen, served, layer["key"])
        assert {request.csrf for request in tiles} == {token}
    expect(page.locator(".cmp-badge.a")).to_contain_text(older["title"])
    expect(page.locator(".cmp-badge.b")).to_contain_text(newer["title"])
    assert not [r for r in seen if "/versions/" in r.url and "/tiles/" in r.url]

    details = panel(page)
    expect(details.get_by_role("heading", name="Warstwy obok siebie")).to_be_visible()
    rows = {row["label"]: row for row in page.evaluate(TABLE_ROWS)}
    year = rows["Rok, wydanie albo etykieta"]
    assert year["cells"] == [older["title"], newer["title"]] and year["marked"]
    counts = rows["Wersje"]
    assert counts["cells"] == ["2", "2"] and not counts["marked"]
    assert rows["Wariant"]["cells"] == [older["subtitle"], newer["subtitle"]]

    # Another layer for B from the set, and the sides swapped.
    other = next(
        layer
        for layer in api(
            page,
            "/local-layers?"
            + urlencode({"store": STORE, "product": "nmt", "area_id": area_id}),
        )["layers"]
        if layer["key"] not in (older["key"], newer["key"])
    )
    details.get_by_label("Warstwa B").select_option(other["key"])
    assert query_of(page)["b_layer"] == other["key"]
    expect(page.locator(".cmp-badge.b")).to_contain_text(other["title"])
    page.get_by_role("button", name="Zamień A i B").click()
    assert (query_of(page)["a_layer"], query_of(page)["b_layer"]) == (
        other["key"],
        older["key"],
    )
    tab.assert_clean()


def test_csv_export_matches_table(
    compare_store: CompareStore, tab: Tab, tmp_path: Path
) -> None:
    """„Eksportuj CSV” saves the rows shown, with the raw values of A and B."""
    served = compare_store.served
    page = open_session(tab, served)
    _, versions = version_pair(page, compare_store.store)
    expected = comparison(page, versions)
    titles = [expected["a"]["title"], expected["b"]["title"]]
    groups = {"metadata": "Metadane z indeksu", "sidecar": "Pola surowego sidecara"}

    def export() -> list[list[str]]:
        with page.expect_download() as started:
            panel(page).get_by_role("button", name="Eksportuj CSV").click()
        download = started.value
        assert re.fullmatch(r"porownanie-[\w.-]+\.csv", download.suggested_filename)
        saved = tmp_path / download.suggested_filename
        download.save_as(saved)
        data = saved.read_bytes()
        assert data.startswith(b"\xef\xbb\xbf") and data.endswith(b"\r\n")
        return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))

    page.goto(compare_address(served, versions))
    expect(page.locator(".cmp-table")).to_be_visible()
    header, *lines = export()
    assert header == [
        "grupa",
        "pole",
        "nazwa pola",
        f"A: {titles[0]}",
        f"B: {titles[1]}",
        "różne",
    ]
    wanted = [
        [
            groups[row["group"]],
            row["field"],
            row["label"],
            shown_value(row["a"]),
            shown_value(row["b"]),
            "tak" if row["differs"] else "nie",
        ]
        for row in expected["rows"]
    ]
    assert lines == wanted
    labels = [row["label"] for row in page.evaluate(TABLE_ROWS)]
    assert [line[2] for line in lines] == labels

    # With „tylko różnice” the file holds the rows shown, nothing more.
    panel(page).get_by_role("checkbox", name="tylko różnice").check()
    expect(page.locator(".cmp-table tbody tr:not(.cmp-group)")).to_have_count(
        sum(row["differs"] for row in expected["rows"])
    )
    _, *only = export()
    assert only == [line for line in wanted if line[5] == "tak"]
    assert [line[2] for line in only] == [
        row["label"] for row in page.evaluate(TABLE_ROWS)
    ]
    tab.assert_clean()


def test_csv_export_neutralizes_every_cell(
    compare_store: CompareStore, tab: Tab, tmp_path: Path
) -> None:
    """Sidecar keys, labels, groups and values remain visible but cannot run as formulas."""
    served = compare_store.served
    page = open_session(tab, served)
    _, versions = version_pair(page, compare_store.store)
    original_count = len(comparison(page, versions)["rows"])
    attack = '=HYPERLINK("https://example.invalid/?x=1,2","click")'
    rows = [
        {
            "group": "=1+2",
            "field": "+SUM(1,2)",
            "label": attack,
            "a": "@SUM(1,2)",
            "b": "\t=1+2",
            "differs": True,
        },
        {
            "group": "sidecar",
            "field": "\r=1+2",
            "label": "-1+2",
            "a": "\n=1+2",
            "b": attack,
            "differs": True,
        },
    ]

    def inject_comparison(route: Route) -> None:
        answer = route.fetch()
        comparison = answer.json()
        comparison["a"]["title"] = attack
        comparison["b"]["title"] = "+SUM(1,2)"
        comparison["rows"].extend(rows)
        route.fulfill(response=answer, json=comparison)

    page.route("**/api/v1/compare?*", inject_comparison)
    page.goto(compare_address(served, versions))
    expect(page.locator(".cmp-table tbody tr:not(.cmp-group)")).to_have_count(
        original_count + len(rows)
    )
    assert attack in [row["label"] for row in page.evaluate(TABLE_ROWS)]
    with page.expect_download() as started:
        panel(page).get_by_role("button", name="Eksportuj CSV").click()
    saved = tmp_path / "comparison.csv"
    started.value.save_as(saved)
    data = list(
        csv.reader(io.StringIO(saved.read_bytes().decode("utf-8-sig"), newline=""))
    )
    assert data[0][3:5] == [f"A: {attack}", "B: +SUM(1,2)"]
    assert data[-2:] == [
        ["'=1+2", "'+SUM(1,2)", f"'{attack}", "'@SUM(1,2)", "'\t=1+2", "tak"],
        ["Pola surowego sidecara", "'\r=1+2", "'-1+2", "'\n=1+2", f"'{attack}", "tak"],
    ]
    assert all(
        not cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
        or re.fullmatch(r"-\d+(?:\.\d+)?", cell)
        for line in data
        for cell in line
    )
    tab.assert_clean()


def test_no_csp_violations_compare(compare_store: CompareStore, tab: Tab) -> None:
    """Every mode, one colour scale and the card over the comparison obey the CSP."""
    served = compare_store.served
    tiles = compare_store.tiles
    page = open_session(tab, served)
    token = session_headers(page)[CSRF_HEADER]
    slot, versions = version_pair(page, compare_store.store)
    infos = [
        api(page, f"/stores/{STORE}/versions/{version['path']}/preview")
        for version in versions
    ]
    seen = watch(page)

    page.goto(compare_address(served, versions))
    page.get_by_role("group", name="Styl podglądu").get_by_role(
        "button", name="hipsometria"
    ).click()
    # Both sides on one range of colours: from the lower minimum to the higher maximum.
    ramps = [info["legends"]["hypsometry"] for info in infos]
    common = (
        f"{min(ramp['min'] for ramp in ramps):g},{max(ramp['max'] for ramp in ramps):g}"
    )
    for version in versions:
        found = awaited_tiles(page, seen, served, version["path"], "hypsometry")
        rescale = {dict(parse_qsl(urlsplit(r.url).query))["rescale"] for r in found}
        assert {
            ",".join(f"{float(v):g}" for v in value.split(",")) for value in rescale
        } == {common}
    expect(page.locator(".cmp-legend")).to_contain_text("Wspólna skala barw A i B")
    modes = page.get_by_role("group", name="Porównanie na mapie")
    for mode in ("Przenikanie", "Obok siebie", "Kurtyna"):
        modes.get_by_role("button", name=mode).click()
        page.wait_for_timeout(500)

    # The file card of a side opens over the comparison, which stays.
    panel(page).get_by_role("article", name="Strona B").get_by_role(
        "link", name="Karta pliku"
    ).click()
    card = page.get_by_role("dialog")
    expect(card).to_contain_text(versions[1]["label"])
    assert query_of(page)["view"] == "compare" and query_of(page)["file"] == (
        f"{STORE}/{slot}"
    )
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_role("slider", name=CURTAIN)).to_be_visible()

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
