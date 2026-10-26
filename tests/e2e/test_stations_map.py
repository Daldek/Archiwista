"""The stations of an IMGWTools product on the map (plan I8.1, ADR-045).

A product of the producer ``imgw`` shows its stations in place of outlines:
a point's tooltip names the station, its type and river and labels every
variable of the chosen dataset; far stations at a low zoom form a neutral
cluster that zooms in on a click, stations at one position spread around it
until ``Esc``, and above the limit the grid's cells fit on a click. These
are drawn on the WebGL canvas, so they run in Chromium. Beside the canvas,
in Chromium and Firefox (whose headless build has no WebGL2: the map says
so, and the view still counts the stations of the view it would show), the
legend names the three shapes and five fills, the counter of stations
without a position equals ``counts.unlocated`` and opens the Catalog with
``location=none``, and the "Kolor punktów" and dataset chips change the
address and the next request.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Locator, Page, Request, Response, Route, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    WORLD,
    address,
    api,
    hover_until,
    mercator_lat,
    open_session,
    query_of,
    screen_point,
    station_settings,
    wait_still,
)

Serve = Callable[..., Served]
Stores = Callable[[str], Path]

DAILY = "pl.imgw.hydro_daily"
CZ_DAILY = "cz.chmi.hydro_daily"
STATIONS = re.compile(r"/api/v1/map/stations\?")
LOADED = re.compile(r"\bstacj\w* w widoku|Brak stacji w widoku")
LEGEND = (
    "wodowskaz",
    "stacja klimatologiczna albo synoptyczna",
    "posterunek opadowy",
    "ciągły — wartość w każdej znanej jednostce",
    "luki — braki w znanych latach",
    "częściowy — zaczyna się albo kończy w zakresie lat",
    "brak danych — znane lata bez wartości",
    "nieznane — żaden rok zakresu nie jest znany",
    "skupisko: liczba stacji, bez koloru pokrycia",
)


def counter(page: Page) -> Locator:
    """Return the counter of stations in the view."""
    return page.locator(".map-count")


def tooltip(page: Page) -> Locator:
    """Return the tooltip of the map."""
    return page.locator(".map-tooltip")


def open_stations(page: Page, served: Served, **params: str) -> None:
    """Open the map of a station product; wait for its stations."""
    page.goto(address(served, view="map", **params))
    expect(counter(page)).to_have_text(LOADED)


def located(page: Page) -> list[dict[str, Any]]:
    """Return the located stations of the store, of every kind."""
    items: list[dict[str, Any]] = api(page, f"/map/stations?bbox={WORLD}")["items"]
    return items


def between(first: dict[str, Any], second: dict[str, Any]) -> tuple[float, float]:
    """Return the position of two stations' cluster: their Mercator middle."""
    lon = (float(first["lon"]) + float(second["lon"])) / 2
    return lon, mercator_lat(float(first["lat"]), float(second["lat"]))


def test_the_tooltip_of_a_water_gauge_labels_each_variable(
    serve: Serve, tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Centred on the water gauge: its name, type, river and H, Q, T (Chromium)."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(tab, served)
    query = f"/map/stations?bbox={WORLD}&dataset={DAILY}&kind=hydro"
    (gauge,) = api(page, query)["items"]
    centre = f"{gauge['lon']},{gauge['lat']}"
    open_stations(page, served, product="hydro", center=centre, zoom="9")

    # Act
    hover_until(page, screen_point(page, gauge["lon"], gauge["lat"]), tooltip(page))

    # Assert
    expect(counter(page)).to_have_text("1 stacja w widoku")
    shown = tooltip(page)
    expect(shown).to_contain_text("Raba Górna")
    expect(shown).to_contain_text("wodowskaz · Raba")
    labels = shown.locator(".station-tip-labels li")
    expect(labels).to_have_count(3)
    coverage = gauge["coverage"].items()
    for row, (key, value) in zip(labels.all(), coverage, strict=True):
        expect(row).to_have_text(f"{key} {value['label']}")
    expect(labels.first).to_have_class("chosen")
    assert list(gauge["coverage"]) == ["H", "Q", "T"]
    tab.assert_clean()


def test_far_stations_at_a_low_zoom_form_a_cluster_that_zooms_in(
    serve: Serve, tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Raba Górna and Warszawa at zoom 2 are one cluster; a click zooms in."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(tab, served)
    lon, lat = between(*located(page))
    open_stations(page, served, product="stations", center=f"{lon},{lat}", zoom="2")

    # Act
    hover_until(page, screen_point(page, lon, lat), tooltip(page))
    shown = tooltip(page).inner_text()
    page.mouse.click(*screen_point(page, lon, lat))
    expect(page).not_to_have_url(re.compile(r"[?&]zoom=2\.00(&|$)"))
    wait_still(page)

    # Assert
    assert "2 stacje w skupisku" in shown
    assert float(query_of(page)["zoom"]) > 2
    expect(counter(page)).to_have_text("2 stacje w widoku")
    tab.assert_clean()


def test_stations_at_one_position_spread_around_their_cluster(
    serve: Serve, tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """A cluster that cannot fall apart spreads its stations until ``Esc``."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(tab, served)
    first, second = located(page)
    lon, lat = float(first["lon"]), float(first["lat"])

    def one_position(route: Route) -> None:
        # Both stations, wherever the view is, at the first one's position.
        url = re.sub(r"bbox=[^&]+", f"bbox={WORLD}", route.request.url)
        answer = route.fetch(url=url)
        body = answer.json()
        for item in body["items"]:
            item["lon"], item["lat"] = lon, lat
        route.fulfill(response=answer, body=json.dumps(body))

    page.route("**/api/v1/map/stations?*", one_position)
    open_stations(page, served, product="stations", center=f"{lon},{lat}", zoom="9")
    centre = screen_point(page, lon, lat)
    hover_until(page, centre, tooltip(page))
    clustered = tooltip(page).inner_text()

    # Act
    page.mouse.click(*centre)
    above = (centre[0], centre[1] - 34)
    hover_until(page, above, tooltip(page).filter(has_text="IMGW-PIB"))
    spread = tooltip(page).inner_text()
    page.keyboard.press("Escape")
    expect(tooltip(page)).to_have_count(0)
    # The spread drawn again would show its tooltip on the next move there.
    page.wait_for_timeout(300)
    page.mouse.move(above[0] + 1, above[1])
    page.wait_for_timeout(300)

    # Assert
    assert "2 stacje w skupisku" in clustered
    assert any(item["name"] in spread for item in (first, second))
    expect(tooltip(page)).to_have_count(0)
    assert query_of(page)["zoom"] == "9.00"
    tab.assert_clean()


def test_above_the_limit_the_cells_are_drawn_and_fit_on_click(
    serve: Serve, tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """``limit=1``: the grid's cells are neutral circles that fit on a click."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(tab, served)
    lon, lat = between(*located(page))

    def limit_one(route: Route) -> None:
        url = re.sub(r"([?&])limit=\d+", r"\g<1>limit=1", route.request.url)
        route.continue_(url=url)

    answers: list[Response] = []
    page.on("response", lambda response: answers.append(response))
    page.route("**/api/v1/map/stations?*", limit_one)
    open_stations(page, served, product="stations", center=f"{lon},{lat}", zoom="5")
    expect(counter(page)).to_contain_text("siatka zagęszczenia")
    # The longer counter may wrap the bar: the map is asked again at its new size.
    wait_still(page)
    page.wait_for_load_state("networkidle")
    drawn = [answer for answer in answers if STATIONS.search(answer.url)]
    view = drawn[-1].json()
    cell = view["cells"][0]
    middle = (
        (cell["min_lon"] + cell["max_lon"]) / 2,
        (cell["min_lat"] + cell["max_lat"]) / 2,
    )

    # Act
    hover_until(page, screen_point(page, *middle), tooltip(page))
    shown = tooltip(page).inner_text()
    page.mouse.click(*screen_point(page, *middle))
    wait_still(page)

    # Assert
    assert view["aggregated"] is True
    assert f"{cell['count']} stacja w tej komórce" in shown
    query = query_of(page)
    centre_lon, centre_lat = (float(value) for value in query["center"].split(","))
    assert cell["min_lon"] <= centre_lon <= cell["max_lon"]
    assert cell["min_lat"] <= centre_lat <= cell["max_lat"]
    assert float(query["zoom"]) > 5
    tab.assert_clean()


def test_legend_counter_and_chips_stand_beside_the_map(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Shapes and fills by text, the unlocated counter, "Kolor punktów", datasets."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    answer = api(page, "/stations/datasets")
    datasets = [item["dataset"] for item in answer["items"] if item["kind"] == "hydro"]
    query = f"/map/stations?bbox={WORLD}&dataset={DAILY}&kind=hydro"
    counts = api(page, query)["counts"]
    open_stations(page, served, product="hydro")
    legend = page.get_by_role("region", name="Legenda")
    colours = page.get_by_role("group", name="Kolor punktów")
    unlocated = page.get_by_role("link", name=re.compile("bez położenia"))

    def of_daily(request: Request) -> bool:
        asked = parse_qs(urlsplit(request.url).query)
        return bool(STATIONS.search(request.url)) and asked.get("dataset") == [DAILY]

    # Act
    rows = [text.strip() for text in legend.locator(".legend-row").all_inner_texts()]
    colours.get_by_role("button", name="Q", exact=True).click()
    coloured = query_of(page)
    with page.expect_response(lambda response: of_daily(response.request)):
        page.get_by_role("button", name="Dane hydrologiczne dobowe", exact=True).click()
    rechosen = query_of(page)
    expect(unlocated).to_have_text(
        re.compile(rf"^{counts['unlocated']} stacj\w* bez położenia")
    )
    unlocated.click()

    # Assert
    assert datasets == [CZ_DAILY, DAILY]
    # A row is its symbol (the cluster's count) and its text.
    assert all(any(row.endswith(text) for row in rows) for text in LEGEND), rows
    assert coloured["color"] == "Q"
    assert (rechosen["dataset"], "color" in rechosen) == (DAILY, False)
    assert counts["unlocated"] > 0
    expect(page).to_have_url(re.compile(r"[?&]view=catalog(&|$)"))
    catalog = query_of(page)
    assert (catalog["location"], catalog["product"]) == ("none", "hydro")
    engine_tab.assert_clean()
