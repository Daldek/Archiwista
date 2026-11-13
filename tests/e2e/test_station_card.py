"""The station card (plan I8.5, ADR-045 decision 10).

``station=<store>/<provider>/<code>`` opens the card over the current view: a
point of the map, whose tooltip says so (drawn on the WebGL canvas, so in
Chromium), a row of the Catalog's list and the address alone open it. It
names the station with its type, river and code and gives the label of each
variable as ``GET /stations/{code}`` does; its header switch numbers the
labels in calendar years, writes ``year_type`` to the address and remembers
it in the person's preferences (``PUT /preferences``). A station without a
position shows the catalog's reason and no map action, a located one opens
the map centred on it. At its foot stands its one strip of the IMGW-PIB
lines (S and P), whose dialog lists every line, byte for byte the card's
``attribution`` and ``terms_notice``, and „Kopiuj atrybucję” there copies
them one per line, as „Kopiuj ścieżkę pliku” copies the series file's path
(read back in Chromium, whose clipboard Playwright can grant); Esc closes
the dialog and not the card. The IMGW
station page is a plain link the page never requests.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, Response, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.provider_lines import (
    IMGW_HYDRO,
    IMGW_PROCESSED,
    IMGW_SOURCE,
    IMGW_TERMS,
    IMGW_TERMS_HYDRO,
    IMGW_TERMS_PUBLIC_DATA,
)
from tests.fixtures.station_browser import (
    SOURCES,
    SOURCES_BUTTON,
    SOURCES_DIALOG,
    STORE,
    WORLD,
    address,
    api,
    dialog_lines,
    hover_until,
    open_session,
    query_of,
    screen_point,
    station_settings,
    strip_lines,
)

Serve = Callable[..., Served]
Stores = Callable[[str], Path]

DAILY = "pl.imgw.hydro_daily"
PROVIDER = "IMGW-PIB"
RABA = "149190310"  # Raba Górna: located, H, Q and T
UNLOCATED = "149190311"  # Stacja Bez Q: the source says 0,0
STATION = re.compile(rf"[?&]station={STORE}%2F{PROVIDER}%2F{RABA}(&|$)")


def station_of(code: str) -> str:
    """Return the card's value of the address for a station of the fixture."""
    return f"{STORE}/{PROVIDER}/{code}"


def card_answer(page: Page, code: str, **params: str) -> dict[str, Any]:
    """Return ``GET /stations/{code}`` of a station of the fixture, in Polish."""
    query = urlencode({"store": STORE, "provider": PROVIDER, **params})
    answer: dict[str, Any] = api(page, f"/stations/{code}?{query}")
    return answer


def labels_of(answer: dict[str, Any]) -> list[str]:
    """Return the label of each variable of each series, in the card's order."""
    return [
        variable["label"]
        for series in answer["station"]["series"]
        for variable in series["coverage"].values()
    ]


def dialog(page: Page, name: str) -> Locator:
    """Return the station card named by its station."""
    return page.get_by_role("dialog", name=name)


def test_a_point_of_the_map_opens_its_card(
    serve: Serve, tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """The tooltip says a click opens the card; the click opens it (Chromium)."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(tab, served)
    query = f"/map/stations?bbox={WORLD}&dataset={DAILY}&kind=hydro"
    (gauge,) = api(page, query)["items"]
    answer = card_answer(page, RABA)
    centre = f"{gauge['lon']},{gauge['lat']}"
    page.goto(address(served, view="map", product="hydro", center=centre, zoom="9"))
    expect(page.locator(".map-count")).to_have_text("1 stacja w widoku")
    point = screen_point(page, gauge["lon"], gauge["lat"])
    tooltip = page.locator(".map-tooltip")

    # Act
    hover_until(page, point, tooltip)
    hint = tooltip.inner_text()
    page.mouse.click(*point)

    # Assert
    assert hint.endswith("Kliknij, aby otworzyć kartę stacji")
    expect(page).to_have_url(STATION)
    card = dialog(page, "Raba Górna")
    expect(card.locator(".sc-label")).to_have_text(labels_of(answer))
    tab.assert_clean()


def test_a_row_of_the_list_opens_the_card_and_so_does_its_address(
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """A click on a row, ``Esc`` back to the row, the address alone; the IMGW link."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    answer = card_answer(page, RABA)
    page.goto(address(served, view="catalog", product="hydro"))
    grid = page.get_by_role("grid", name="Lista stacji katalogu")
    expect(grid).to_have_attribute("aria-busy", "false")
    row = grid.get_by_role("row").filter(has_text="Raba Górna")
    card = dialog(page, "Raba Górna")

    # Act
    row.click()
    expect(page).to_have_url(STATION)
    expect(card.locator(".sc-label")).to_have_text(labels_of(answer))
    selected = row.get_attribute("aria-selected")
    index = row.get_attribute("aria-rowindex")
    page.keyboard.press("Escape")
    expect(card).to_have_count(0)
    closed = query_of(page)
    focused = page.evaluate("document.activeElement.getAttribute('aria-rowindex')")
    page.goto(address(served, view="map", station=station_of(RABA)))
    expect(card.locator(".sc-label")).to_have_text(labels_of(answer))
    link = card.get_by_role("link", name="Strona stacji IMGW")

    # Assert
    assert selected == "true"
    assert "station" not in closed
    assert focused == index
    expect(card.locator(".sc-subline")).to_have_text(
        "Wodowskaz · Raba (kod hydrograficzny 213) · 149190310"
    )
    catalog = answer["station"]["catalog"].replace("-", ".")
    expect(card.locator(".sc-location p")).to_have_text(
        "Położenie: 49,7000° N, 20,1000° E · źródło: API IMGW (hydro)"
        f" · katalog {catalog} · niepewność ±5566 m"
    )
    assert link.get_attribute("href") == f"https://hydro.imgw.pl/#/station/hydro/{RABA}"
    assert (link.get_attribute("target"), link.get_attribute("rel")) == (
        "_blank",
        "noopener noreferrer",
    )
    assert engine_tab.foreign_requests(served.base) == []
    engine_tab.assert_clean()


def test_esc_at_once_after_a_row_opens_the_card_closes_it(
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """``Esc`` before the opened card has rendered still takes it off the address."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    page.goto(address(served, view="catalog", product="hydro"))
    grid = page.get_by_role("grid", name="Lista stacji katalogu")
    expect(grid).to_have_attribute("aria-busy", "false")
    row = grid.get_by_role("row").filter(has_text="Raba Górna")

    # Act: the click and the key in one task, as a busy host delivers them.
    searches = row.evaluate(
        """(row) => {
          row.click();
          const opened = location.search;
          const key = { key: "Escape", bubbles: true };
          document.activeElement.dispatchEvent(new KeyboardEvent("keydown", key));
          return [opened, location.search];
        }"""
    )

    # Assert
    assert STATION.search(searches[0])
    assert "station=" not in searches[1]
    expect(page).not_to_have_url(re.compile(r"[?&]station="))
    expect(dialog(page, "Raba Górna")).to_have_count(0)
    engine_tab.assert_clean()


def test_the_header_switch_numbers_the_labels_in_calendar_years(
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """Switched to calendar years: the API's labels, the address, the preference."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    hydrological = labels_of(card_answer(page, RABA))
    calendar = labels_of(card_answer(page, RABA, year_type="calendar"))
    page.goto(
        address(served, view="catalog", product="hydro", station=station_of(RABA))
    )
    card = dialog(page, "Raba Górna")
    switch = card.get_by_role("group", name="Lata", exact=True)
    preferences_put = re.compile(r"/api/v1/preferences$")

    def saved(response: Response) -> bool:
        return response.request.method == "PUT" and bool(
            preferences_put.search(response.url)
        )

    # Act
    expect(card.locator(".sc-label")).to_have_text(hydrological)
    with page.expect_response(saved) as put:
        switch.get_by_role("button", name="kalendarzowe", exact=True).click()
    expect(page).to_have_url(re.compile(r"[?&]year_type=calendar(&|$)"))
    expect(card.locator(".sc-label")).to_have_text(calendar)
    preferences = api(page, "/preferences")

    # Assert
    assert calendar != hydrological
    expect(card.locator(".sc-series-title")).to_contain_text("lata kalendarzowe")
    expect(
        switch.get_by_role("button", name="kalendarzowe", exact=True)
    ).to_have_attribute("aria-pressed", "true")
    assert put.value.ok
    assert preferences["year_types"] == {"hydro": "calendar", "meteo": "calendar"}
    engine_tab.assert_clean()


def test_a_station_without_a_position_has_its_reason_and_no_map_action(
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """The catalog's reason, no "Pokaż na mapie"; a located one opens the map on it."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    located = card_answer(page, RABA)["station"]["location"]
    page.goto(
        address(served, view="catalog", product="hydro", station=station_of(UNLOCATED))
    )
    unlocated = dialog(page, "Stacja Bez Q")
    expect(unlocated.locator(".sc-label")).not_to_have_count(0)

    # Act
    reason = unlocated.locator(".sc-location").inner_text()
    actions = unlocated.get_by_role("button", name="Pokaż na mapie").count()
    page.goto(
        address(served, view="catalog", product="hydro", station=station_of(RABA))
    )
    dialog(page, "Raba Górna").get_by_role("button", name="Pokaż na mapie").click()
    expect(page).to_have_url(re.compile(r"[?&]view=map(&|$)"))
    opened = query_of(page)

    # Assert
    assert reason.startswith("Bez położenia: źródło podaje 0,0\n")
    assert actions == 0
    lon, lat = (float(value) for value in opened["center"].split(","))
    assert (round(lon, 4), round(lat, 4)) == (located["lon"], located["lat"])
    assert (opened["product"], opened["store"], float(opened["zoom"])) == (
        "hydro",
        STORE,
        11,
    )
    assert "station" not in opened
    engine_tab.assert_clean()


def test_the_lines_and_the_file_path_are_copied_as_the_card_gives_them(
    serve: Serve, tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """One strip at the card's foot: S and P; its dialog copies all lines (Chromium)."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
    page = open_session(tab, served)
    page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin=served.base
    )
    answer = card_answer(page, RABA)
    (series,) = answer["station"]["series"]
    page.goto(
        address(served, view="catalog", product="hydro", station=station_of(RABA))
    )
    card = dialog(page, "Raba Górna")
    strip = card.locator(SOURCES)
    copied: dict[str, str] = {}

    # Act
    shown = strip_lines(strip)
    full = dialog_lines(strip)
    action = card.locator(".copy-action").filter(
        has=page.get_by_role("button", name="Kopiuj ścieżkę pliku", exact=True)
    )
    action.get_by_role("button").click()
    expect(action.get_by_role("status")).to_have_text("Skopiowano")
    copied["path"] = page.evaluate("navigator.clipboard.readText()")
    strip.get_by_role("button", name=SOURCES_BUTTON).click()
    sources = page.get_by_role("dialog", name=SOURCES_DIALOG)
    sources.get_by_role("button", name="Kopiuj atrybucję", exact=True).click()
    expect(sources.get_by_role("status")).to_have_text("Skopiowano")
    copied["lines"] = page.evaluate("navigator.clipboard.readText()")
    page.keyboard.press("Escape")

    # Assert
    lines = [*answer["attribution"], *answer["terms_notice"]]
    assert lines == [
        IMGW_SOURCE,
        IMGW_PROCESSED,
        IMGW_HYDRO,
        IMGW_TERMS,
        IMGW_TERMS_PUBLIC_DATA,
        IMGW_TERMS_HYDRO,
    ]
    assert shown == [IMGW_SOURCE, IMGW_PROCESSED]
    assert full == lines
    assert copied == {
        "lines": "\n".join(lines),
        "path": str(tmp_path / "obserwator" / series["file"]),
    }
    assert answer["paths"][DAILY]["local"] == copied["path"]
    expect(sources).to_be_hidden()
    expect(card).to_be_visible()
    expect(card.locator(SOURCES)).to_have_count(1)
    tab.assert_clean()
