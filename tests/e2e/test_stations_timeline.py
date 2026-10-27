"""The Timeline tab of a station product's Catalog (plan I8.3, ADR-045).

``layout=timeline`` draws the stations of one dataset (the address's, else
the product's first) as ``GET /stations/timeline`` pages them with the
list's filters: an ARIA treegrid whose station row shows the years of the
"Kolor punktów" variable and expands into a row per variable. A year's cell
is the API's ``cell`` (``full``, ``fraction``, ``none``, ``unknown``), its
column header names the year by its convention, its tooltip gives the
year's units, the label and the longest gap. The tab is one click from the
list and keeps its filters, the keys move by year and row and fold a
station, and the year-type switch numbers the columns anew. Everything
stands beside the map, so each test runs in Chromium and Firefox.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    address,
    api,
    open_session,
    query_of,
    station_settings,
)

Serve = Callable[..., Served]
Stores = Callable[[str], Path]

DAILY = "pl.imgw.hydro_daily"
RABA = "149190310"
# The rows of the treegrid in their order: level, fold, heading, the kind of each year.
ROWS = """
() => {
  const text = (element) => element.textContent.replace(/\\s+/g, " ").trim();
  const kind = (cell) => cell.classList[1];
  return [...document.querySelectorAll(".stl-rows [role=row]")]
    .map((row) => ({ row, at: Number(row.getAttribute("aria-rowindex")) }))
    .sort((a, b) => a.at - b.at)
    .map(({ row }) => ({
      level: Number(row.getAttribute("aria-level")),
      expanded: row.getAttribute("aria-expanded"),
      head: text(row.querySelector("[role=rowheader]")),
      cells: [...row.querySelectorAll("[role=gridcell]")].map(kind),
    }));
}
"""
# The names of the year columns, in their order.
YEARS = """
() => [...document.querySelectorAll(".stl-header [role=columnheader]")]
  .slice(1)
  .map((cell) => cell.getAttribute("aria-label"))
"""
# Where the focus is: the row's index and level, and the cell's column.
FOCUS = """
() => {
  const cell = document.activeElement;
  const row = cell.closest("[role=row]");
  return [row.getAttribute("aria-rowindex"), row.getAttribute("aria-level"),
    cell.getAttribute("aria-colindex")];
}
"""


def treegrid(page: Page) -> Locator:
    """Return the Timeline of the stations."""
    return page.get_by_role(
        "treegrid", name="Oś czasu stacji: stacje w wierszach, lata w kolumnach"
    )


def open_timeline(page: Page, served: Served, **params: str) -> None:
    """Open the Timeline of a station product; wait for its first page."""
    page.goto(address(served, view="catalog", layout="timeline", **params))
    expect(treegrid(page)).to_have_attribute("aria-busy", "false")


def timeline(page: Page, **params: str) -> list[dict[str, Any]]:
    """Return the stations of ``GET /stations/timeline`` (one page holds them all)."""
    answer = api(page, f"/stations/timeline?{urlencode(params)}&limit=200")
    assert answer["next_cursor"] is None
    items: list[dict[str, Any]] = answer["items"]
    return items


def coverage(page: Page, code: str, **params: str) -> dict[str, Any]:
    """Return the series of ``GET /stations/{code}/coverage`` of one variable."""
    answer = api(page, f"/stations/{code}/coverage?{urlencode(params)}")
    series: dict[str, Any] = answer["series"][0]
    return series


def shown(page: Page, rows: int) -> list[dict[str, Any]]:
    """Return the rows once the treegrid has ``rows`` of them."""
    expect(treegrid(page)).to_have_attribute("aria-busy", "false")
    expect(page.locator(".stl-rows [role=row]")).to_have_count(rows)
    found: list[dict[str, Any]] = page.evaluate(ROWS)
    return found


def cells_of(series: dict[str, Any]) -> list[str]:
    """Return the kind of each year of a series' only variable."""
    return [year["cell"] for year in series["variables"][0]["years"]]


def head_of(item: dict[str, Any], key: str) -> str:
    """Return the heading of a station's row: name, code, the row's variable."""
    return f"{item['name']} {item['code']} {key}"


def hydrological(year: int) -> str:
    """Return the header of a hydrological year: its number and its days."""
    return f"r.h. {year} ({year - 1}.11.01–{year}.10.31)"


def test_the_tab_is_one_click_from_the_list_and_keeps_the_filters(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The tab "Oś czasu" beside "Lista": one address, the filters' stations."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    filters = {"q": "raba", "sort": "name"}
    stations = timeline(page, kind="hydro", dataset=DAILY, **filters)
    page.goto(address(served, view="catalog", product="hydro", **filters))
    listed = page.get_by_role("grid", name="Lista stacji katalogu")
    expect(listed).to_have_attribute("aria-busy", "false")
    layouts = page.get_by_role("group", name="Układ katalogu")

    # Act
    layouts.get_by_role("button", name="Oś czasu").click()
    expect(page).to_have_url(re.compile(r"[?&]layout=timeline(&|$)"))
    rows = shown(page, len(stations))
    opened = query_of(page)
    layouts.get_by_role("button", name="Lista").click()

    # Assert
    assert {name: opened[name] for name in filters} == filters
    assert [row["head"] for row in rows] == [head_of(item, "H") for item in stations]
    assert [row["level"] for row in rows] == [1] * len(stations)
    expect(page.get_by_role("searchbox", name="Szukaj w katalogu")).to_have_value(
        "raba"
    )
    expect(listed).to_have_attribute("aria-busy", "false")
    expect(treegrid(page)).to_have_count(0)
    assert "layout" not in query_of(page)
    engine_tab.assert_clean()


def test_a_station_row_shows_its_years_and_a_tooltip_names_the_longest_gap(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The H cells of 149190310 are those of its coverage; Q replaces them."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    stations = timeline(page, kind="hydro", dataset=DAILY)
    at = [item["code"] for item in stations].index(RABA)
    water = coverage(page, RABA, dataset=DAILY, variable="H")
    flow = coverage(page, RABA, dataset=DAILY, variable="Q")
    years = water["variables"][0]["years"]
    gap = water["variables"][0]["longest_gap"]
    fraction = next(year for year in years if year["cell"] == "fraction")
    open_timeline(page, served, product="hydro")
    row = page.locator(".stl-rows [role=row]").nth(at)
    tooltip = page.get_by_role("tooltip")
    variables = page.get_by_role("group", name="Wiersz stacji")

    # Act
    before = shown(page, len(stations))[at]
    header = page.evaluate(YEARS)[years.index(fraction)]
    row.locator(".stl-c.fraction").first.hover()
    expect(tooltip).to_be_visible()
    tip = tooltip.inner_text()
    variables.get_by_role("button", name="Q", exact=True).click()
    expect(page).to_have_url(re.compile(r"[?&]color=Q(&|$)"))
    expect(row.get_by_role("rowheader")).to_contain_text("Q")
    after = shown(page, len(stations))[at]

    # Assert
    assert before["head"] == head_of(stations[at], "H")
    assert before["cells"] == cells_of(water)
    assert "fraction" in before["cells"]
    assert header == hydrological(fraction["year"])
    start, end = (gap[name].replace("-", ".") for name in ("from", "to"))
    assert f"Najdłuższa przerwa: {start}–{end} ({gap['units']} dni)" in tip
    assert header in tip
    days = f"{fraction['units']} dni w roku · znane: {fraction['known']}"
    assert f"{days} · z wartością: {fraction['with_value']}" in tip
    assert water["variables"][0]["label"] in tip
    assert after["head"] == head_of(stations[at], "Q")
    assert after["cells"] == cells_of(flow)
    engine_tab.assert_clean()


def test_keys_move_by_year_and_row_and_fold_a_station(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Enter expands a station, arrows and Home/End move, Space folds it."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    stations = timeline(page, kind="hydro", dataset=DAILY)
    series = stations[0]["series"][0]
    keys = [variable["key"] for variable in series["variables"]]
    columns = series["years"]["to"] - series["years"]["from"] + 1
    open_timeline(page, served, product="hydro")
    shown(page, len(stations))
    first = page.locator(".stl-rows [role=row]").first

    # Act
    first.get_by_role("rowheader").focus()
    page.keyboard.press("Enter")
    expanded = shown(page, len(stations) + len(keys))
    moves = []
    for key in ("ArrowDown", "ArrowRight", "ArrowRight", "End", "Home", "ArrowUp"):
        page.keyboard.press(key)
        moves.append(page.evaluate(FOCUS))
    page.keyboard.press("Space")
    folded = shown(page, len(stations))

    # Assert
    assert expanded[0]["expanded"] == "true"
    children = expanded[1 : 1 + len(keys)]
    assert [row["level"] for row in children] == [2] * len(keys)
    assert [row["head"].split()[0] for row in children] == keys
    assert [row["cells"] for row in children] == [
        [year["cell"] for year in variable["years"]] for variable in series["variables"]
    ]
    assert moves == [
        ["3", "2", "1"],
        ["3", "2", "2"],
        ["3", "2", "3"],
        ["3", "2", str(columns + 1)],
        ["3", "2", "1"],
        ["2", "1", "1"],
    ]
    assert folded[0]["expanded"] == "false"
    assert [row["level"] for row in folded] == [1] * len(stations)
    engine_tab.assert_clean()


def test_the_year_type_switch_numbers_the_columns_anew(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The switch "kalendarzowe": calendar years and the API's cells of them."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    stations = timeline(page, kind="hydro", dataset=DAILY)
    at = [item["code"] for item in stations].index(RABA)
    calendar = coverage(page, RABA, dataset=DAILY, variable="H", year_type="calendar")
    last = calendar["years"]["to"]
    open_timeline(page, served, product="hydro")
    switch = page.get_by_role("button", name="kalendarzowe", exact=True)

    # Act
    before = page.evaluate(YEARS)
    hydrological_row = shown(page, len(stations))[at]
    switch.click()
    expect(page).to_have_url(re.compile(r"[?&]year_type=calendar(&|$)"))
    header = page.get_by_role("columnheader", name=f"{last} (kalendarzowy)")
    expect(header).to_be_visible()
    after = page.evaluate(YEARS)
    row = shown(page, len(stations))[at]

    # Assert
    assert before[-1] == hydrological(last)
    assert after[-1] == f"{last} (kalendarzowy)"
    assert len(after) == calendar["years"]["to"] - calendar["years"]["from"] + 1
    assert row["cells"] == cells_of(calendar)
    assert row["cells"] != hydrological_row["cells"]
    engine_tab.assert_clean()
