"""The catalog's timeline and the details panel in Chromium (plan v0.2, step 13b).

One offline server over the layer store for the module
(``tests.fixtures.layer_browser``): the NMT layers of the store — of an area
of four 1:10 000 sheets, or without an area — as variants × years in the
catalog (``layout=timeline``). The years run from 2019 to 2023 with three
years without data, then the cutout's label; a row is a variant whatever the
file format; a bar is the local coverage of the area, without an area the
number of versions. One choice (``layer``) for the timeline, the details
panel, the Wachlarz, the map and the address; the keyboard moves between the
cells with data (ARIA grid); the map stands beside the catalog on a 3440 px
screen, the details are a bottom sheet on a 390 px phone.
"""

import re
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any

import pytest
from playwright.sync_api import FloatRect, Locator, Page, ViewportSize, expect

from tests.fixtures.browser import Tab
from tests.fixtures.layer_browser import (
    ServedLayerStore,
    address,
    area_id,
    built_layers,
    layer_set,
    open_session,
    query_of,
    serve_layer_store,
)
from tests.fixtures.layer_store import PRODUCT

WIDE: ViewportSize = {"width": 3440, "height": 1440}
PHONE: ViewportSize = {"width": 390, "height": 844}
OVERFLOW = "() => document.documentElement.scrollWidth - innerWidth"
NO_DATA = "brak danych"


@pytest.fixture(scope="module")
def layers_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[ServedLayerStore]:
    """Serve the layer store for the module."""
    with serve_layer_store(tmp_path_factory.mktemp("timeline")) as served:
        yield served


def open_timeline(
    tab: Tab,
    served: ServedLayerStore,
    *,
    viewport: ViewportSize | None = None,
    in_area: bool = True,
) -> tuple[Page, str | None, list[dict[str, Any]]]:
    """Open the catalog's timeline of the NMT layers, of the area or the store."""
    page = open_session(tab, served.served)
    page.emulate_media(reduced_motion="reduce")
    if viewport is not None:
        page.set_viewport_size(viewport)
    area = area_id(page) if in_area else None
    layers = built_layers(page, area) if area else layer_set(page)["layers"]
    params = {"view": "catalog", "layout": "timeline", "product": PRODUCT}
    if area is not None:
        params["area_id"] = area
    page.goto(address(served.served, **params))
    expect(grid(page).locator("[data-layer]")).to_have_count(len(layers))
    return page, area, layers


def grid(page: Page) -> Locator:
    """Return the timeline."""
    return page.get_by_role(
        "grid", name="Oś czasu: warianty w wierszach, lata w kolumnach"
    )


def cell(page: Page, key: str) -> Locator:
    """Return the cell of a layer."""
    return grid(page).locator(f'[role=gridcell][data-layer="{key}"]')


def panel(page: Page) -> Locator:
    """Return the panel „Szczegóły zestawu”."""
    return page.get_by_role("complementary", name="Szczegóły zestawu")


def switch(page: Page, name: str) -> Locator:
    """Return a button of the switch „Mapa / Wachlarz / Katalog”."""
    return page.get_by_role("group", name="Widok środka").get_by_role(
        "button", name=name
    )


def years(page: Page) -> Locator:
    """Return the year buttons on the map."""
    return page.get_by_role("group", name="Lata na mapie")


def box(locator: Locator) -> FloatRect:
    """Return an element's box on the page."""
    found = locator.bounding_box()
    assert found is not None
    return found


def variant(layer: dict[str, Any]) -> str:
    """Return the variant part of a layer's key."""
    return str(layer["key"]).split(":", 1)[0]


def focused(page: Page) -> str | None:
    """Return the layer of the cell with the focus."""
    key: str | None = page.evaluate(
        "() => document.activeElement?.dataset?.layer ?? null"
    )
    return key


def test_timeline_shows_years_without_data(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """The years run 2019–2023 with the three without data, then the label."""
    page, _, layers = open_timeline(tab, layers_server)
    labels = sorted(layer["title"] for layer in layers if layer["year"] is None)
    assert labels == ["2025-03-14"]

    heads = grid(page).get_by_role("columnheader")
    texts = [(item.text_content() or "").strip() for item in heads.all()]
    assert texts == ["Wariant", "2019", "2020", "2021", "2022", "2023", *labels]
    empty = grid(page).locator("[role=columnheader].empty")
    texts_empty = [(item.text_content() or "").strip() for item in empty.all()]
    assert texts_empty == ["2020", "2021", "2022"]
    # Every layer is one cell; the years without data hold none in any row.
    keys = {
        item.get_attribute("data-layer")
        for item in grid(page).locator("[data-layer]").all()
    }
    assert keys == {layer["key"] for layer in layers}
    rows = grid(page).get_by_role("row")
    expect(rows).to_have_count(len({variant(layer) for layer in layers}) + 1)
    for row in rows.all()[1:]:
        cells = row.get_by_role("gridcell")
        expect(cells).to_have_count(len(texts) - 1)
        for at in (1, 2, 3):
            expect(cells.nth(at)).to_have_text(NO_DATA)
            expect(cells.nth(at)).not_to_have_attribute("data-layer", re.compile(".*"))
    tab.assert_clean()


def test_timeline_bar_height_is_local_coverage(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """A bar is the layer's local coverage; without an area its versions."""
    page, _, layers = open_timeline(tab, layers_server)
    for layer in layers:
        coverage = layer["coverage"]
        found = cell(page, layer["key"])
        track = found.locator(".tl-track").evaluate("(e) => e.clientHeight")
        bar = found.locator(".tl-bar").evaluate(
            "(e) => e.getBoundingClientRect().height"
        )
        assert bar == pytest.approx(max(coverage["ratio"] * track, 2), abs=1)
        expect(found).to_contain_text(f"{coverage['percent']}%")
        expect(found).to_have_attribute(
            "aria-label", re.compile(re.escape(coverage["label"]))
        )
    assert {layer["coverage"]["percent"] for layer in layers} >= {51, 26}
    expect(
        page.get_by_text("Słupek: pokrycie lokalne obszaru", exact=False)
    ).to_be_visible()

    # Without an area: the counts of the whole store against the largest.
    page.goto(
        address(
            layers_server.served, view="catalog", layout="timeline", product=PRODUCT
        )
    )
    counts = layer_set(page)["layers"]
    expect(grid(page).locator("[data-layer]")).to_have_count(len(counts))
    most = max(layer["versions_count"] for layer in counts)
    for layer in counts:
        found = cell(page, layer["key"])
        track = found.locator(".tl-track").evaluate("(e) => e.clientHeight")
        bar = found.locator(".tl-bar").evaluate(
            "(e) => e.getBoundingClientRect().height"
        )
        assert bar == pytest.approx(layer["versions_count"] / most * track, abs=1)
        expect(found.locator(".tl-value")).to_have_text(str(layer["versions_count"]))
    expect(
        page.get_by_text("Słupek: liczba wersji w magazynie", exact=False)
    ).to_be_visible()
    tab.assert_clean()


def test_two_formats_one_timeline_row(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """One variant in two formats is one row and one cell, formats as badges."""
    page, _, layers = open_timeline(tab, layers_server)
    both = next(layer for layer in layers if "ZIP" in layer["variant"]["formats"])
    assert both["variant"]["formats"] == ["ASCII Grid", "ZIP"]
    assert len(both["variant"]["segments"]) == 2

    inside = page.locator(f'[data-layer="{both["key"]}"]')
    rows = grid(page).get_by_role("row").filter(has=inside)
    expect(rows).to_have_count(1)
    head = rows.get_by_role("rowheader")
    expect(head).to_contain_text("1m · PL-1992 · PL-EVRF2007-NH")
    for name in both["variant"]["formats"]:
        expect(
            head.locator(".fmt").filter(has_text=re.compile(f"^{name}$"))
        ).to_have_count(1)
    # The same variant's other years share the row; the formats one cell.
    same = [layer["key"] for layer in layers if variant(layer) == variant(both)]
    expect(rows.locator("[data-layer]")).to_have_count(len(same))
    expect(cell(page, both["key"])).to_have_attribute(
        "title", re.compile("ASCII Grid, ZIP")
    )

    # The panel counts the sheet in both formats once.
    cell(page, both["key"]).click()
    expect(panel(page)).to_contain_text(f"{both['versions_count']} wersje")
    expect(panel(page)).to_contain_text(f"arkusze lub jednostki: {both['units_count']}")
    assert both["units_count"] < both["versions_count"]
    tab.assert_clean()


def test_selection_syncs_map_fan_timeline_panel_and_url(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """One choice: the timeline, the panel, the Wachlarz, the map, the address."""
    page, _, layers = open_timeline(tab, layers_server)
    newest, older = layers[0], layers[2]

    cell(page, older["key"]).click()
    expect(cell(page, older["key"])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == older["key"]
    assert query_of(page)["layout"] == "timeline"
    expect(panel(page)).to_be_visible()
    expect(panel(page).locator(".sd-title")).to_have_text(older["title"])
    expect(panel(page)).to_contain_text(older["coverage"]["label"])

    # The Wachlarz: the same layer chosen.
    switch(page, "Wachlarz").click()
    option = page.get_by_role("listbox", name="Warstwy Wachlarza").locator(
        f'[role=option][data-layer="{older["key"]}"]'
    )
    expect(option).to_have_attribute("aria-selected", "true")
    assert query_of(page)["view"] == "map"
    assert query_of(page)["mode"] == "fan"
    expect(panel(page).locator(".sd-title")).to_have_text(older["title"])

    # The map: its year button pressed; another year chosen there.
    switch(page, "Mapa").click()
    expect(years(page).locator("[aria-pressed=true]")).to_contain_text(older["title"])
    years(page).get_by_role("button").first.click()
    assert query_of(page)["layer"] == newest["key"]

    # Back in the catalog: the timeline again, with the map's choice.
    switch(page, "Katalog").click()
    assert query_of(page)["view"] == "catalog"
    assert query_of(page)["layout"] == "timeline"
    expect(cell(page, newest["key"])).to_have_attribute("aria-selected", "true")
    expect(cell(page, older["key"])).to_have_attribute("aria-selected", "false")
    expect(panel(page)).to_contain_text(newest["coverage"]["label"])

    # A sheet of the panel opens its file card over the timeline.
    sheet = panel(page).locator(".sd-sheets a").first
    name = (sheet.text_content() or "").strip()
    sheet.click()
    expect(page.get_by_role("dialog", name=PurePosixPath(name).name)).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)

    # „Pokaż na mapie”: the map with the layer, framed on the area.
    panel(page).get_by_role("button", name="Pokaż na mapie").click()
    assert query_of(page)["view"] == "map"
    assert query_of(page)["layer"] == newest["key"]
    assert "mode" not in query_of(page)
    expect(page.locator(".map-gl")).to_be_visible()
    expect(years(page).locator("[aria-pressed=true]")).to_have_count(1)
    tab.assert_clean()


def test_timeline_keyboard_selection(layers_server: ServedLayerStore, tab: Tab) -> None:
    """Arrows move between cells with data, Enter and Space choose; one tab stop."""
    page, _, layers = open_timeline(tab, layers_server)
    rows: list[str] = []
    for layer in layers:
        if variant(layer) not in rows:
            rows.append(variant(layer))
    key = {(variant(layer), layer["title"]): layer["key"] for layer in layers}
    first, second = rows
    stops = grid(page).locator('[role=gridcell][tabindex="0"]')
    expect(stops).to_have_count(1)
    expect(stops).to_have_attribute("data-layer", key[(first, "2019")])

    stops.focus()
    page.keyboard.press("ArrowRight")
    assert focused(page) == key[(first, "2023")]
    page.keyboard.press("ArrowRight")
    assert focused(page) == key[(first, "2025-03-14")]
    page.keyboard.press("ArrowRight")
    assert focused(page) == key[(first, "2025-03-14")]
    page.keyboard.press("ArrowDown")
    assert focused(page) == key[(second, "2023")]
    page.keyboard.press("ArrowUp")
    assert focused(page) == key[(first, "2023")]
    assert "layer" not in query_of(page)
    page.keyboard.press("Enter")
    expect(cell(page, key[(first, "2023")])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == key[(first, "2023")]
    page.keyboard.press("Home")
    assert focused(page) == key[(first, "2019")]
    page.keyboard.press("Space")
    assert query_of(page)["layer"] == key[(first, "2019")]
    page.keyboard.press("End")
    assert focused(page) == key[(first, "2025-03-14")]
    page.keyboard.press("Control+End")
    assert focused(page) == key[(second, "2023")]
    page.keyboard.press("Control+Home")
    assert focused(page) == key[(first, "2019")]
    expect(stops).to_have_count(1)
    expect(grid(page).locator("[aria-selected=true]")).to_have_count(1)
    tab.assert_clean()


def test_wide_3440_catalog_beside_map(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """On a 3440 px screen the map stands beside the catalog."""
    page, _, layers = open_timeline(tab, layers_server, viewport=WIDE)
    beside = page.locator(".cat-beside .map-gl")
    expect(beside).to_be_visible()
    map_box = box(beside)
    catalog = box(page.locator("section.cat"))
    assert map_box["x"] + map_box["width"] <= catalog["x"] + 1
    assert map_box["width"] >= 1000 and catalog["width"] >= 1000

    # A cell chosen: the map beside shows the layer; no „Pokaż na mapie”.
    cell(page, layers[0]["key"]).click()
    expect(panel(page)).to_be_visible()
    expect(years(page).get_by_role("button").first).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(panel(page).get_by_role("button", name="Pokaż na mapie")).to_have_count(0)
    map_box = box(beside)
    catalog = box(page.locator("section.cat"))
    assert map_box["x"] + map_box["width"] <= catalog["x"] + 1
    tab.assert_clean()


def test_phone_390_timeline_and_panel(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """On a phone the timeline scrolls in its box; the details are a sheet."""
    page, _, layers = open_timeline(tab, layers_server, viewport=PHONE)
    assert page.evaluate(OVERFLOW) == 0
    scroll = page.locator(".tl-scroll")
    assert scroll.evaluate("(e) => e.scrollWidth > e.clientWidth")
    assert box(scroll)["x"] + box(scroll)["width"] <= PHONE["width"]
    chosen = layers[0]

    cell(page, chosen["key"]).click()
    expect(cell(page, chosen["key"])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == chosen["key"]
    expect(panel(page)).to_be_hidden()
    page.get_by_role("button", name="Szczegóły", exact=True).click()
    expect(panel(page)).to_be_visible()
    expect(panel(page)).to_contain_text(chosen["coverage"]["label"])
    assert box(panel(page))["width"] == PHONE["width"]
    panel(page).get_by_role("button", name="Zwiń panel „Szczegóły zestawu”").click()
    expect(panel(page)).to_be_hidden()
    assert page.evaluate(OVERFLOW) == 0
    tab.assert_clean()
