"""The stations of an IMGWTools product in the Catalog (plan I8.2, ADR-045).

A product of the producer ``imgw`` lists its stations instead of files: the
rows are those of ``GET /stations`` (located ones first, then "Bez
położenia"), along rivers unless the order by name is chosen, a line per
variable with its label. A station without a position shows the catalog's
reason and never leads to the map; the map's counter opens that group
expanded, and it starts folded above 50 located stations. The river code
with its tributaries and the coverage chips are parameters of the address,
and the stations the coverage hides are counted. The year-type switch
numbers the labels as the API does with ``year_type``, stays in the address
and is remembered for the family. The rows move with the keys of the file
list. Everything stands beside the map, so each test runs in Chromium and
Firefox.
"""

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, Route, expect

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
Row = dict[str, Any]

DAILY = "pl.imgw.hydro_daily"
ROWS_TIMEOUT_S = 30.0
# The reasons of the catalog for a station without a position, as the list says them.
REASONS = {
    "none": "brak współrzędnych w źródłach",
    "zero": "źródło podaje 0,0",
    "outside_country": "poza krajem dostawcy",
}
# The rows of the list in their order: a group's heading or a station.
SHOWN_ROWS = """
() => [...document.querySelectorAll(".cat-rows [role=row][data-index]")]
  .sort((a, b) => Number(a.dataset.index) - Number(b.dataset.index))
  .map((row) => {
    const text = (element) => element.textContent.replace(/\\s+/g, " ").trim();
    if (row.classList.contains("st-group-row")) {
      const fold = row.querySelector("[aria-expanded]");
      return { group: text(row.querySelector(".st-group-name")),
        expanded: fold ? fold.getAttribute("aria-expanded") : null };
    }
    return {
      code: text(row.querySelector(".c-code .mono")),
      name: text(row.querySelector(".st-name")),
      lines: [...row.querySelectorAll(".st-var")].map((line) =>
        [text(line.querySelector(".st-key")), text(line.querySelector(".st-label"))]),
      location: text(row.querySelector(".c-loc .cell-sub")),
      map: row.querySelector(".cat-map") !== null,
    };
  })
"""


def grid(page: Page) -> Locator:
    """Return the list of stations."""
    return page.get_by_role("grid", name="Lista stacji katalogu")


def open_list(page: Page, served: Served, **params: str) -> None:
    """Open the Catalog of a station product; wait for its first rows."""
    page.goto(address(served, view="catalog", **params))
    expect(grid(page)).to_have_attribute("aria-busy", "false")


def stations(page: Page, **params: str) -> dict[str, Any]:
    """Return one page of ``GET /stations`` (every station of the fixture)."""
    answer: dict[str, Any] = api(page, f"/stations?{urlencode(params)}&limit=200")
    assert answer["next_cursor"] is None
    return answer


def row_of(item: dict[str, Any]) -> Row:
    """Return the row the list shows for a station of the API.

    A located station shows its source (not compared) and a map button; one
    without a position its reason and no button.
    """
    located = item["location"]["kind"] == "point"
    return {
        "code": item["code"],
        "name": item["name"],
        "lines": [
            [key, variable["label"]]
            for series in item["series"]
            for key, variable in series["coverage"].items()
        ],
        "location": None if located else REASONS[item["location"]["reason"]],
        "map": located,
    }


def expected(page: Page, **params: str) -> tuple[list[Row], dict[str, int]]:
    """Return the stations of the list of ``params`` (located, then not) and counts."""
    located = stations(page, **params, location="with")
    unlocated = stations(page, **params, location="none")
    items = located["items"] + unlocated["items"]
    return [row_of(item) for item in items], located["counts"]


def row_count(counts: dict[str, int], *, folded: bool = False) -> int:
    """Return the rows of a list of both groups: each group's heading and stations."""
    located = 1 + counts["located"] if counts["located"] else 0
    unlocated = 1 + (0 if folded else counts["unlocated"]) if counts["unlocated"] else 0
    return located + unlocated


def shown(page: Page, rows: int, rendered: int | None = None) -> list[Row]:
    """Return the rows drawn once the list has ``rows`` (``rendered`` drawn)."""
    expect(grid(page)).to_have_attribute("aria-busy", "false")
    expect(grid(page)).to_have_attribute("aria-rowcount", str(rows + 1))
    drawn = page.locator(".cat-rows [role=row]")
    expect(drawn).to_have_count(rows if rendered is None else rendered)
    found: list[Row] = page.evaluate(SHOWN_ROWS)
    return [{**row, "location": None} if row.get("map") else row for row in found]


def stations_of(rows: list[Row]) -> list[Row]:
    """Return the stations among rows, without the groups' headings."""
    return [row for row in rows if "group" not in row]


def settled(
    page: Page, wanted: list[Row], rows: int, rendered: int | None = None
) -> list[Row]:
    """Return the rows once their stations are ``wanted`` or the time is up.

    A new query keeps the previous rows until its answer is drawn, so a list
    of as many rows is read until it changes.
    """
    deadline = time.monotonic() + ROWS_TIMEOUT_S
    while True:
        found = shown(page, rows, rendered)
        if stations_of(found) == wanted or time.monotonic() > deadline:
            return found
        page.wait_for_timeout(100)


def test_the_rows_are_those_of_the_api_along_rivers_or_by_name(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Both groups as ``GET /stations`` reads them; "Nazwa" orders by name."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    along, counts = expected(page)
    by_name, _ = expected(page, sort="name")
    rivers = [item["hydrographic_code"] for item in stations(page)["items"]]
    total = row_count(counts)
    open_list(page, served, product="stations")

    # Act
    first = settled(page, along, total)
    river_header = page.get_by_role("columnheader", name="Rzeka (kod)")
    expect(river_header).to_have_attribute("aria-sort", "ascending")
    page.get_by_role("button", name="Nazwa", exact=True).click()
    expect(page).to_have_url(re.compile(r"[?&]sort=name(&|$)"))
    second = settled(page, by_name, total)

    # Assert
    groups = [row["group"] for row in first if "group" in row]
    assert groups == [
        f"Z położeniem {counts['located']}",
        f"Bez położenia {counts['unlocated']}",
    ]
    assert stations_of(first) == along
    assert stations_of(second) == by_name
    assert along != by_name
    # Along rivers: a river's stations by its code, the stations without one last.
    known = [code for code in rivers if code is not None]
    assert rivers == sorted(known) + [None] * (len(rivers) - len(known))
    name_header = page.get_by_role("columnheader", name="Stacja")
    expect(name_header).to_have_attribute("aria-sort", "ascending")
    engine_tab.assert_clean()


def test_stations_without_a_position_show_the_reason_and_no_map_link(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The group "Bez położenia" is last: the reason, the card, no way to the map."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    rows, counts = expected(page, kind="hydro")
    open_list(page, served, product="hydro")
    unlocated = page.locator(".cat-rows .cat-row.unlocated")

    # Act
    found = settled(page, rows, row_count(counts))
    unlocated.first.click()
    expect(page).to_have_url(re.compile(r"[?&]station="))
    opened = query_of(page)
    page.keyboard.press("Escape")
    expect(page.locator(".station-card")).to_have_count(0)
    page.keyboard.press("m")
    after = query_of(page)

    # Assert
    assert found[-1 - counts["unlocated"]] == {
        "group": f"Bez położenia {counts['unlocated']}",
        "expanded": "true",
    }
    assert stations_of(found) == rows
    reasons = {row["location"] for row in rows if not row["map"]}
    assert reasons == set(REASONS.values())
    expect(unlocated).to_have_count(counts["unlocated"])
    expect(unlocated.locator(".cat-map")).to_have_count(0)
    expect(unlocated.first).to_be_focused()
    assert opened["view"] == "catalog"
    assert after == {"view": "catalog", "product": "hydro"}
    engine_tab.assert_clean()


def test_the_map_counter_opens_the_group_expanded(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The map's "N stacji bez położenia" opens the Catalog's group, unfolded.

    The map shows the product's first dataset, so the counter counts and the
    Catalog lists the stations with its series.
    """
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    unlocated = stations(page, kind="hydro", dataset=DAILY, location="none")
    count = unlocated["counts"]["unlocated"]
    rows = [row_of(item) for item in unlocated["items"]]
    page.goto(address(served, view="map", product="hydro"))
    counter = page.get_by_role("link", name=re.compile("bez położenia"))

    # Act
    expect(counter).to_have_text(re.compile(r"^\d+ stacj\w* bez położenia"))
    counted = int(counter.inner_text().split()[0])
    counter.click()
    expect(page).to_have_url(re.compile(r"[?&]location=none(&|$)"))
    found = settled(page, rows, 1 + count)

    # Assert
    opened = query_of(page)
    assert (opened["view"], opened["dataset"]) == ("catalog", DAILY)
    assert counted == count
    assert found[0] == {"group": f"Bez położenia {count}", "expanded": None}
    assert stations_of(found) == rows
    note = page.get_by_role("note").filter(has_text="nie zgaduje położenia")
    expect(note).to_be_visible()
    expect(page.get_by_role("link", name="Pokaż wynik na mapie")).to_have_count(0)
    engine_tab.assert_clean()


def test_above_50_located_stations_the_group_starts_folded(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """With more than 50 located "Bez położenia" is folded until Enter."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    rows, counts = expected(page, kind="hydro")
    many = {**counts, "located": 51}

    def many_located(route: Route) -> None:
        # The fixture has one located gauge: the counts say 51.
        answer = route.fetch()
        body = answer.json()
        body["counts"]["located"] = many["located"]
        route.fulfill(response=answer, body=json.dumps(body))

    page.route("**/api/v1/stations?*", many_located)
    open_list(page, served, product="hydro")
    heading = page.locator(".cat-row.st-group-row", has_text="Bez położenia")
    drawn = 2 + counts["located"]

    # Act
    folded = settled(
        page, rows[: counts["located"]], row_count(many, folded=True), drawn
    )
    heading.focus()
    page.keyboard.press("Enter")
    unfolded = settled(page, rows, row_count(many), drawn + counts["unlocated"])

    # Assert
    assert folded[-1] == {
        "group": f"Bez położenia {counts['unlocated']}",
        "expanded": "false",
    }
    assert stations_of(folded) == rows[: counts["located"]]
    assert unfolded[-1 - counts["unlocated"]]["expanded"] == "true"
    assert stations_of(unfolded) == rows
    engine_tab.assert_clean()


def test_river_and_coverage_filters_change_the_address_and_the_rows(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """A river code with tributaries, then a coverage chip; the hidden count."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    river = {"kind": "hydro", "river_code": "21", "river_scope": "tributaries"}
    tributaries, along = expected(page, **river)
    chip = {**river, "dataset": DAILY, "coverage": "Q:no_data"}
    covered, counts = expected(page, **chip)
    open_list(page, served, product="hydro")
    code = page.get_by_label("Kod hydrograficzny rzeki")
    variable = page.get_by_role("group", name="Pokrycie Q")

    # Act
    code.fill("21")
    code.press("Enter")
    expect(page).to_have_url(re.compile(r"[?&]river_code=21(&|$)"))
    expect(page.get_by_text("Brak stacji pasujących do filtrów.")).to_be_visible()
    page.get_by_label("z dopływami").check()
    expect(page).to_have_url(re.compile(r"[?&]river_scope=tributaries(&|$)"))
    with_tributaries = settled(page, tributaries, row_count(along))
    page.get_by_label("Zbiór danych").select_option(DAILY)
    expect(page).to_have_url(re.compile(rf"[?&]dataset={re.escape(DAILY)}(&|$)"))
    variable.get_by_role("button", name="brak danych").click()
    expect(page).to_have_url(re.compile(r"[?&]coverage=Q(%3A|:)no_data(&|$)"))
    filtered = settled(page, covered, row_count(counts))

    # Assert
    assert {row["code"] for row in tributaries} > {row["code"] for row in covered}
    assert stations_of(with_tributaries) == tributaries
    assert stations_of(filtered) == covered
    assert counts["hidden"] > 0
    note = page.get_by_role("note").filter(has_text="Ukryte przez filtry pokrycia")
    expect(note).to_have_text(f"Ukryte przez filtry pokrycia: {counts['hidden']}")
    expect(variable.get_by_role("button", name="brak danych")).to_have_attribute(
        "aria-pressed", "true"
    )
    engine_tab.assert_clean()


def test_the_year_type_switch_numbers_the_labels_and_is_remembered(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """The switch "kalendarzowe": the API's labels with ``year_type``, kept."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    hydrological, counts = expected(page, kind="hydro")
    calendar, _ = expected(page, kind="hydro", year_type="calendar")
    total = row_count(counts)
    open_list(page, served, product="hydro")
    calendar_button = page.get_by_role("button", name="kalendarzowe", exact=True)
    hydrological_button = page.get_by_role("button", name="hydrologiczne", exact=True)
    settings_put = re.compile(r"/api/v1/settings/year-types$")

    # Act
    expect(hydrological_button).to_have_attribute("aria-pressed", "true")
    before = settled(page, hydrological, total)
    with page.expect_response(settings_put) as put:
        calendar_button.click()
    expect(page).to_have_url(re.compile(r"[?&]year_type=calendar(&|$)"))
    switched = settled(page, calendar, total)
    page.reload()
    reloaded = settled(page, calendar, total)
    reloaded_pressed = calendar_button.get_attribute("aria-pressed")
    settings = api(page, "/settings")
    open_list(page, served, product="hydro")
    remembered = settled(page, calendar, total)

    # Assert
    assert put.value.ok
    assert stations_of(before) == hydrological
    assert calendar != hydrological
    assert stations_of(switched) == calendar
    assert (stations_of(reloaded), reloaded_pressed) == (calendar, "true")
    assert settings["year_types"] == {"hydro": "calendar", "meteo": "calendar"}
    assert "year_type" not in query_of(page)
    assert stations_of(remembered) == calendar
    expect(calendar_button).to_have_attribute("aria-pressed", "true")
    engine_tab.assert_clean()


def test_keys_move_through_the_rows_fold_the_group_open_the_card_and_the_map(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Arrows, Home/End, Enter on "Bez położenia" and on a station (its card), M."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    rows, counts = expected(page)
    first = stations(page, location="with")["items"][0]
    total = row_count(counts)
    open_list(page, served, product="stations")
    settled(page, rows, total)
    focused = "document.activeElement.getAttribute('aria-rowindex')"

    # Act
    grid(page).get_by_role("row").nth(1).focus()
    page.keyboard.press("ArrowDown")
    second = page.evaluate(focused)
    page.keyboard.press("End")
    last = page.evaluate(focused)
    page.keyboard.press("Home")
    first_row = page.evaluate(focused)
    for _ in range(counts["located"] + 1):
        page.keyboard.press("ArrowDown")
    heading = page.evaluate(focused)
    page.keyboard.press("Enter")
    folded = shown(page, row_count(counts, folded=True))
    page.keyboard.press("Enter")
    unfolded = shown(page, total)
    page.keyboard.press("Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page).to_have_url(re.compile(r"[?&]station="))
    card = query_of(page)["station"]
    page.keyboard.press("Escape")
    expect(page.locator(".station-card")).to_have_count(0)
    page.keyboard.press("m")
    expect(page).to_have_url(re.compile(r"[?&]view=map(&|$)"))
    opened = query_of(page)

    # Assert
    assert (first_row, second, last) == ("2", "3", str(total + 1))
    assert heading == str(counts["located"] + 3)
    assert stations_of(folded) == rows[: counts["located"]]
    assert stations_of(unfolded) == rows
    assert card == f"{first['store']}/{first['provider']}/{first['code']}"
    lon, lat = (float(value) for value in opened["center"].split(","))
    located = first["location"]
    assert (round(lon, 4), round(lat, 4)) == (located["lon"], located["lat"])
    assert (opened["product"], float(opened["zoom"])) == ("stations", 11)
    engine_tab.assert_clean()
