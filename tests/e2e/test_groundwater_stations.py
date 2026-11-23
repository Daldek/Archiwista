"""ČHMÚ's groundwater stations in the station views (Obserwator 3.2.0, A-ADR-059).

The product ``groundwater`` („Stacje wód podziemnych”) is a station kind
beside ``hydro`` and ``meteo``: its stations are drawn as Obserwator draws
them, a diamond, brown where the legend and the lists show a type; a
station's type names its object, an observation bore or a spring; the
positions of ČHMÚ's groundwater metadata have their source's words. The
Catalog lists the bore and the spring of the fixture, and the kind field of
the station catalog's list leaves the groundwater stations only. The bore's
card shows the coverage of its weekly series counted in weeks, and the
chart offers its daily series only: the server gives no chart of a weekly
series. The lists and the card run in Chromium and Firefox; the points of
the map are drawn on the WebGL canvas, so its test runs in Chromium.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, Response, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    STORE,
    WORLD,
    address,
    api,
    hover_until,
    open_session,
    query_of,
    screen_point,
    station_settings,
)

Serve = Callable[..., Served]

PROVIDER = "CHMU"
BORE = "0-203-1-VP0624"
SPRING = "0-203-1-PP0744"
DAILY = "cz.chmu.groundwater_daily"
WEEKLY = "cz.chmu.groundwater_weekly"
TYPES = {
    BORE: "stacja wód podziemnych: otwór obserwacyjny",
    SPRING: "stacja wód podziemnych: źródło",
}
SOURCES = {
    "cz.chmu.groundwater_now": "bieżące metadane ČHMÚ, wody podziemne",
    "cz.chmu.groundwater_stations": "wykaz obiektów ČHMÚ, wody podziemne",
}
WEEKS = ("tydzień", "tygodnie", "tygodni")
# The station rows of the list: code, type line, the shape of its symbol, location.
ROWS = """
() => [...document.querySelectorAll(".cat-rows [role=row][data-index]")]
  .filter((row) => !row.classList.contains("st-group-row"))
  .sort((a, b) => Number(a.dataset.index) - Number(b.dataset.index))
  .map((row) => {
    const text = (element) => element.textContent.replace(/\\s+/g, " ").trim();
    const type = row.querySelector(".c-st .cell-sub");
    return {
      code: text(row.querySelector(".c-code .mono")),
      type: text(type),
      shape: type.querySelector(".station-symbol").dataset.shape,
      location: text(row.querySelector(".c-loc .cell-sub")),
    };
  })
"""


def grid(page: Page) -> Locator:
    """Return the list of stations."""
    return page.get_by_role("grid", name="Lista stacji katalogu")


def groundwater(page: Page, **params: str) -> list[dict[str, Any]]:
    """Return the groundwater stations of ``GET /stations``, in the list's order."""
    query = urlencode({"kind": "groundwater", **params})
    items: list[dict[str, Any]] = api(page, f"/stations?{query}&limit=200")["items"]
    return items


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Return ``n`` with its Polish word form, as the interface counts."""
    one, few, many = forms
    if n == 1:
        return f"{n} {one}"
    few_ending = n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14)
    return f"{n} {few if few_ending else many}"


def test_catalog_lists_the_bore_and_the_spring_with_their_type_and_diamond(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """„Stacje wód podziemnych”: a brown diamond, the object, the source's words."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)
    items = groundwater(page)
    wanted = [
        {
            "code": item["code"],
            "type": TYPES[item["code"]],
            "shape": "diamond",
            "location": SOURCES[item["location"]["source"]],
        }
        for item in items
    ]

    # Act
    page.goto(address(served, view="catalog", product="groundwater"))
    expect(grid(page)).to_have_attribute("aria-busy", "false")
    expect(grid(page).locator(".st-name")).to_have_count(len(items))
    rows = page.evaluate(ROWS)
    fill = grid(page).locator(".c-st .station-symbol path").first.get_attribute("fill")

    # Assert
    assert sorted(item["code"] for item in items) == sorted([BORE, SPRING])
    assert [item["groundwater_kind"] for item in items] == [
        "bore" if item["code"] == BORE else "spring" for item in items
    ]
    assert rows == wanted
    assert fill == "#a0612a"
    expect(page.get_by_role("group", name="Typ stacji")).to_have_count(0)
    engine_tab.assert_clean()


def test_kind_field_of_the_station_catalog_leaves_groundwater_stations_only(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """„Rodzaj stacji: stacje wód podziemnych” writes ``kind`` and asks the API."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)
    codes = [item["code"] for item in groundwater(page)]
    page.goto(address(served, view="catalog", product="stations"))
    expect(grid(page)).to_have_attribute("aria-busy", "false")
    every = grid(page).locator(".st-name").count()

    def of_groundwater(response: Response) -> bool:
        return (
            "/api/v1/stations?" in response.url and "kind=groundwater" in response.url
        )

    # Act
    with page.expect_response(of_groundwater):
        page.get_by_label("Rodzaj stacji").select_option(label="stacje wód podziemnych")
    expect(grid(page).locator(".st-name")).to_have_count(len(codes))
    rows = page.evaluate(ROWS)

    # Assert
    assert every > len(codes)
    assert query_of(page)["kind"] == "groundwater"
    assert [row["code"] for row in rows] == codes
    assert [row["type"] for row in rows] == [TYPES[code] for code in codes]
    engine_tab.assert_clean()


def test_map_draws_the_bore_as_a_diamond_named_in_its_tooltip(
    serve: Serve, tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """The legend's diamond and fills, no type chips; the tooltip names the bore."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(tab, served)
    query = f"/map/stations?bbox={WORLD}&kind=groundwater&dataset={DAILY}"
    (bore,) = [item for item in api(page, query)["items"] if item["code"] == BORE]
    centre = f"{bore['lon']},{bore['lat']}"
    legend = page.get_by_role("region", name="Legenda")
    tooltip = page.locator(".map-tooltip")

    # Act
    page.goto(
        address(served, view="map", product="groundwater", center=centre, zoom="11")
    )
    expect(page.locator(".map-count")).to_have_text("1 stacja w widoku")
    hover_until(page, screen_point(page, bore["lon"], bore["lat"]), tooltip)
    rows = [text.strip() for text in legend.locator(".legend-row").all_inner_texts()]
    shapes = legend.locator(".legend-row .station-symbol").evaluate_all(
        "(symbols) => symbols.map((symbol) => symbol.dataset.shape)"
    )

    # Assert
    assert bore["groundwater_kind"] == "bore"
    expect(tooltip).to_have_text(
        f"Rakousy{TYPES[BORE]}{BORE} · ČHMÚKliknij, aby otworzyć kartę stacji"
    )
    assert "stacja wód podziemnych: otwór obserwacyjny albo źródło" in rows
    # The four type shapes, the five fills drawn as diamonds, then the cluster.
    assert shapes == ["triangle", "square", "circle", "diamond", *["diamond"] * 5, None]
    expect(page.get_by_text("Typ stacji", exact=True)).to_have_count(0)
    tab.assert_clean()


def test_bore_card_counts_its_weekly_coverage_in_weeks_and_charts_days_only(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """The weekly series' coverage and gap in weeks; no chart of it, even asked for."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)
    lookup = urlencode({"store": STORE, "provider": PROVIDER})
    answer = api(page, f"/stations/{BORE}?{lookup}")
    weekly = next(
        item for item in answer["station"]["series"] if item["dataset"] == WEEKLY
    )
    gap = weekly["coverage"]["H_asl"]["longest_gap"]
    station = f"{STORE}/{PROVIDER}/{BORE}"
    series = re.compile(r"/api/v1/stations/[^/]+/series\?")
    asked: list[str] = []
    page.on("request", lambda request: asked.append(request.url))

    # Act
    page.goto(
        address(
            served,
            view="catalog",
            product="groundwater",
            station=station,
            chart_dataset=WEEKLY,
        )
    )
    card = page.get_by_role("dialog", name="Rakousy")
    expect(card.locator(".sc-subline")).to_contain_text(
        "Stacja wód podziemnych: otwór obserwacyjny"
    )
    block = card.locator(".sc-series").nth(answer["station"]["series"].index(weekly))
    line = block.locator(".sc-var").filter(
        has=page.locator(".sc-key", has_text="H_asl")
    )
    expect(card.locator(".sch-frame svg").first).to_be_visible()
    charted = [url for url in asked if series.search(url)]

    # Assert
    assert weekly["time_unit"] == "week"
    assert [item["time_unit"] for item in answer["charts"]] == ["day"]
    expect(line.locator(".sc-name")).to_have_text("rzędna zwierciadła wody")
    expect(line.locator(".sc-label")).to_have_text(weekly["coverage"]["H_asl"]["label"])
    assert gap is not None
    expect(line.locator(".sc-gap")).to_contain_text(plural(gap["units"], WEEKS))
    assert charted and all(f"dataset={DAILY}" in url for url in charted)
    expect(card.get_by_role("group", name="Szereg", exact=True)).to_have_count(0)
    engine_tab.assert_clean()
