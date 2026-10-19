"""The Wachlarz in Chromium on a real server (plan v0.2, step 13a).

One offline server over the layer store for the module
(``tests.fixtures.layer_browser``): the NMT layers of an area of four 1:10 000
sheets, newest first, as thumbnails on an arc — each whole in its own place,
the chosen one enlarged and, where the stage has room, large beside the
captions. The choice is the address's ``layer``, one with the map; the
keyboard moves between the layers (ARIA listbox); the Wachlarz stands beside
the map on a 3440 px screen and alone on a 390 px phone.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import FloatRect, Locator, Page, ViewportSize, expect

from tests.fixtures.browser import Tab
from tests.fixtures.layer_browser import (
    ServedLayerStore,
    address,
    area_id,
    built_layers,
    open_session,
    query_of,
    serve_layer_store,
)
from tests.fixtures.layer_store import PRODUCT

WIDE: ViewportSize = {"width": 3440, "height": 1440}
PHONE: ViewportSize = {"width": 390, "height": 844}
# Enlargement of the chosen thumbnail (fan/layout.js CHOSEN_SCALE).
CHOSEN_SCALE = 1.9
OVERFLOW = "() => document.documentElement.scrollWidth - innerWidth"
BLOB = re.compile(r"^blob:")


@pytest.fixture(scope="module")
def layers_server(
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[ServedLayerStore]:
    """Serve the layer store for the module."""
    with serve_layer_store(tmp_path_factory.mktemp("fan")) as served:
        yield served


def open_fan(
    tab: Tab,
    served: ServedLayerStore,
    *,
    viewport: ViewportSize | None = None,
    layer: str | None = None,
) -> tuple[Page, str, list[dict[str, Any]]]:
    """Open the Wachlarz of the area once every layer's previews are built."""
    page = open_session(tab, served.served)
    page.emulate_media(reduced_motion="reduce")
    if viewport is not None:
        page.set_viewport_size(viewport)
    area = area_id(page)
    layers = built_layers(page, area)
    params = {"view": "map", "product": PRODUCT, "area_id": area, "mode": "fan"}
    if layer is not None:
        params["layer"] = layer
    page.goto(address(served.served, **params))
    expect(options(page)).to_have_count(len(layers))
    return page, area, layers


def fan(page: Page) -> Locator:
    """Return the Wachlarz's list of layers."""
    return page.get_by_role("listbox", name="Warstwy Wachlarza")


def options(page: Page) -> Locator:
    """Return the layers' captions: one option each."""
    return fan(page).get_by_role("option")


def option(page: Page, key: str) -> Locator:
    """Return the caption of a layer."""
    return fan(page).locator(f'[role=option][data-layer="{key}"]')


def cards(page: Page) -> Locator:
    """Return the layers' thumbnails, in the layers' order."""
    return fan(page).locator(".fan-card")


def box(locator: Locator) -> FloatRect:
    """Return an element's box on the page (rotated: the box around it)."""
    found = locator.bounding_box()
    assert found is not None
    return found


def size(locator: Locator) -> tuple[float, float]:
    """Return an element's own width and height, before its rotation."""
    width, height = locator.evaluate("(e) => [e.offsetWidth, e.offsetHeight]")
    return float(width), float(height)


def overlap(a: FloatRect, b: FloatRect) -> bool:
    """Whether two boxes share any area."""
    return (
        a["x"] < b["x"] + b["width"]
        and b["x"] < a["x"] + a["width"]
        and a["y"] < b["y"] + b["height"]
        and b["y"] < a["y"] + a["height"]
    )


def inside(inner: FloatRect, outer: FloatRect) -> bool:
    """Whether a box lies wholly within another (half a pixel of rounding)."""
    return (
        inner["x"] >= outer["x"] - 0.5
        and inner["y"] >= outer["y"] - 0.5
        and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 0.5
        and inner["y"] + inner["height"] <= outer["y"] + outer["height"] + 0.5
    )


def assert_apart(boxes: list[FloatRect]) -> None:
    """No two of the boxes share any area."""
    for at, first in enumerate(boxes):
        for second in boxes[at + 1 :]:
            assert not overlap(first, second), (first, second)


def arc_boxes(page: Page) -> list[FloatRect]:
    """Return the boxes of every thumbnail and caption on the arc."""
    return [box(item) for item in cards(page).all()] + [
        box(item) for item in options(page).all()
    ]


def focused(page: Page) -> str | None:
    """Return the layer whose caption has the focus."""
    key: str | None = page.evaluate(
        "() => document.activeElement?.dataset?.layer ?? null"
    )
    return key


def test_fan_newest_on_top_and_no_overlap(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """The layers run newest first from the top; nothing covers anything."""
    page, _, layers = open_fan(tab, layers_server)
    keys = [layer["key"] for layer in layers]

    # The server's order, newest first, from the top of the arc down.
    assert [item.get_attribute("data-layer") for item in options(page).all()] == keys
    tops = [box(item)["y"] for item in cards(page).all()]
    assert tops == sorted(tops) and len(set(tops)) == len(tops)
    expect(fan(page).locator("[aria-selected=true]")).to_have_count(0)
    # Every thumbnail and caption whole in its own place on the stage.
    boxes = arc_boxes(page)
    assert_apart(boxes)
    stage = box(page.locator(".fan-stage"))
    assert all(inside(item, stage) for item in boxes)
    # A thumbnail is the layer's image of the API (blob:) under its sheets.
    images = cards(page).locator("image")
    expect(images).to_have_count(len(layers))
    assert all(
        (image.get_attribute("href") or "").startswith("blob:")
        for image in images.all()
    )
    for card in cards(page).all():
        expect(card.locator("path.fan-sheet")).not_to_have_count(0)
    tab.assert_clean()


def test_selected_layer_fully_visible_and_enlarged(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """The chosen layer is enlarged on the arc, whole, and large beside it."""
    page, _, layers = open_fan(tab, layers_server)
    keys = [layer["key"] for layer in layers]
    # The 2023 flights: two campaigns, one sheet also as an ASCII-NMT archive.
    chosen = next(layer for layer in layers if len(layer["campaigns"]) == 2)
    at = keys.index(chosen["key"])
    page.get_by_role("button", name="Wybór", exact=True).click()

    option(page, chosen["key"]).click()
    expect(option(page, chosen["key"])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == chosen["key"]
    panel = page.get_by_role("complementary", name="Szczegóły zestawu")
    expect(panel).to_be_visible()
    expect(page.locator(".fan-large")).to_be_visible()

    # Enlarged on the arc, every other one of the same size, nothing covered.
    sizes = [size(card) for card in cards(page).all()]
    others = [item for index, item in enumerate(sizes) if index != at]
    assert len(set(others)) == 1
    width, height = sizes[at]
    assert width == pytest.approx(others[0][0] * CHOSEN_SCALE, abs=1.5)
    assert height == pytest.approx(others[0][1] * CHOSEN_SCALE, abs=1.5)
    stage = box(page.locator(".fan-stage"))
    large = box(page.locator(".fan-large"))
    boxes = arc_boxes(page)
    assert_apart([*boxes, large])
    assert all(inside(item, stage) for item in [*boxes, large])
    # Its caption: title, local coverage, variant and formats, campaigns, previews.
    caption = option(page, chosen["key"])
    for text in [
        chosen["title"],
        chosen["coverage"]["label"],
        "1m · PL-1992 · PL-EVRF2007-NH",
        *chosen["variant"]["formats"],
        "2 kampanie",
        f"podglądy: {chosen['preview']['ready']} z {chosen['preview']['total']}",
    ]:
        expect(caption).to_contain_text(text)
    expect(page.locator(".fan-large image")).to_have_attribute("href", BLOB)

    # The bottom layer chosen from its thumbnail: whole on the stage too.
    cards(page).nth(len(keys) - 1).click()
    expect(option(page, keys[-1])).to_have_attribute("aria-selected", "true")
    expect(option(page, chosen["key"])).to_have_attribute("aria-selected", "false")
    last = cards(page).nth(len(keys) - 1)
    assert inside(box(last), box(page.locator(".fan-stage")))
    assert size(last)[0] == pytest.approx(others[0][0] * CHOSEN_SCALE, abs=1.5)
    tab.assert_clean()


def test_fan_selection_syncs_map_and_url(
    layers_server: ServedLayerStore, tab: Tab
) -> None:
    """A layer chosen in the Wachlarz is the map's year, and back again."""
    page, _, layers = open_fan(tab, layers_server)
    newest, older = layers[0], layers[2]
    switch = page.get_by_role("group", name="Widok środka")
    panel = page.get_by_role("complementary", name="Szczegóły zestawu")

    cards(page).nth(2).click()
    expect(option(page, older["key"])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == older["key"]
    assert query_of(page)["mode"] == "fan"
    expect(panel).to_contain_text(older["coverage"]["label"])
    expect(page.locator(".map-gl")).to_be_hidden()

    # The map shows the same layer: its year button is the pressed one.
    switch.get_by_role("button", name="Mapa").click()
    expect(page.locator(".map-gl")).to_be_visible()
    assert "mode" not in query_of(page)
    assert query_of(page)["layer"] == older["key"]
    years = page.get_by_role("group", name="Lata na mapie")
    pressed = years.locator("[aria-pressed=true]")
    expect(pressed).to_have_count(1)
    expect(pressed).to_contain_text(older["title"])
    expect(years.get_by_role("button")).to_have_count(len(layers))

    # A year chosen on the map is the Wachlarz's choice.
    years.get_by_role("button").first.click()
    assert query_of(page)["layer"] == newest["key"]
    switch.get_by_role("button", name="Wachlarz").click()
    expect(option(page, newest["key"])).to_have_attribute("aria-selected", "true")
    expect(option(page, older["key"])).to_have_attribute("aria-selected", "false")
    assert query_of(page)["mode"] == "fan"

    # Back walks the changes: the map with the newest layer.
    page.go_back()
    expect(page.locator(".map-gl")).to_be_visible()
    assert "mode" not in query_of(page)
    assert query_of(page)["layer"] == newest["key"]
    tab.assert_clean()


def test_fan_keyboard_selection(layers_server: ServedLayerStore, tab: Tab) -> None:
    """Arrows move between the layers, Enter and Space choose; one tab stop."""
    page, _, layers = open_fan(tab, layers_server)
    keys = [layer["key"] for layer in layers]
    expect(fan(page)).to_have_attribute("aria-orientation", "vertical")
    stops = fan(page).locator('[role=option][tabindex="0"]')
    expect(stops).to_have_count(1)
    expect(stops).to_have_attribute("data-layer", keys[0])

    stops.focus()
    page.keyboard.press("ArrowDown")
    assert focused(page) == keys[1]
    assert "layer" not in query_of(page)
    page.keyboard.press("Enter")
    expect(option(page, keys[1])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == keys[1]
    page.keyboard.press("ArrowRight")
    assert focused(page) == keys[2]
    page.keyboard.press("Space")
    expect(option(page, keys[2])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == keys[2]
    page.keyboard.press("End")
    assert focused(page) == keys[-1]
    page.keyboard.press("ArrowDown")
    assert focused(page) == keys[-1]
    page.keyboard.press("Home")
    assert focused(page) == keys[0]
    page.keyboard.press("ArrowUp")
    assert focused(page) == keys[0]
    expect(stops).to_have_count(1)
    expect(stops).to_have_attribute("data-layer", keys[0])
    # Moving the focus chose nothing: the last choice stays.
    assert query_of(page)["layer"] == keys[2]
    expect(fan(page).locator("[aria-selected=true]")).to_have_count(1)
    tab.assert_clean()


def test_wide_3440_fan_beside_map(layers_server: ServedLayerStore, tab: Tab) -> None:
    """On a 3440 px screen the Wachlarz stands beside the map, not over it."""
    page, _, layers = open_fan(tab, layers_server, viewport=WIDE)
    keys = [layer["key"] for layer in layers]
    map_box = box(page.locator(".map-gl"))
    stage = box(page.locator(".fan-stage"))
    expect(page.locator(".map-gl")).to_be_visible()
    assert map_box["x"] + map_box["width"] <= stage["x"] + 1
    assert map_box["width"] >= 1000 and stage["width"] >= 1000
    assert abs(map_box["height"] - stage["height"]) < 200

    # A choice in the Wachlarz: the map beside it shows the same layer.
    option(page, keys[1]).click()
    expect(page.get_by_role("complementary", name="Szczegóły zestawu")).to_be_visible()
    expect(page.locator(".fan-large")).to_be_visible()
    years = page.get_by_role("group", name="Lata na mapie")
    expect(years.locator("[aria-pressed=true]")).to_have_count(1)
    expect(years.get_by_role("button").nth(1)).to_have_attribute("aria-pressed", "true")
    # Still side by side with the details open, nothing covered on the stage.
    map_box = box(page.locator(".map-gl"))
    stage = box(page.locator(".fan-stage"))
    assert map_box["x"] + map_box["width"] <= stage["x"] + 1
    boxes = [*arc_boxes(page), box(page.locator(".fan-large"))]
    assert_apart(boxes)
    assert all(inside(item, stage) for item in boxes)
    tab.assert_clean()


def test_phone_390_fan(layers_server: ServedLayerStore, tab: Tab) -> None:
    """On a phone the Wachlarz takes the map's place; the details are a sheet."""
    page, _, layers = open_fan(tab, layers_server, viewport=PHONE)
    keys = [layer["key"] for layer in layers]
    expect(page.locator(".map-gl")).to_be_hidden()
    boxes = arc_boxes(page)
    assert_apart(boxes)
    screen = FloatRect(x=0, y=0, width=PHONE["width"], height=PHONE["height"])
    assert all(inside(item, screen) for item in boxes)
    assert page.evaluate(OVERFLOW) == 0

    option(page, keys[0]).click()
    expect(option(page, keys[0])).to_have_attribute("aria-selected", "true")
    assert query_of(page)["layer"] == keys[0]
    panel = page.get_by_role("complementary", name="Szczegóły zestawu")
    expect(panel).to_be_hidden()
    page.get_by_role("button", name="Szczegóły", exact=True).click()
    expect(panel).to_be_visible()
    expect(panel).to_contain_text(layers[0]["coverage"]["label"])
    sheet = box(panel)
    assert sheet["width"] == PHONE["width"]
    panel.get_by_role("button", name="Zwiń panel „Szczegóły zestawu”").click()
    expect(panel).to_be_hidden()
    assert page.evaluate(OVERFLOW) == 0
    tab.assert_clean()
