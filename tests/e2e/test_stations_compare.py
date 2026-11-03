"""The comparison of stations (plan I8.6, ADR-045 decision 13).

``views/station-compare.js`` draws ``GET /stations/compare``: a panel per
station, stacked over one time axis, every panel with the same range and
interval, so a selection in one panel moves all of them and writes ``from``
and ``to``; below the panels the facts of each station as its card gives
them. Up to five rows of the Catalog's list (their button or ``P``) and
"Porównaj z…" of the card open it; "Dodaj stację" adds a station with a
series of the dataset, found by its name. In ``complete_pl_cz`` the IMGW-PIB
gauges Raba Górna and Stacja Bez Q share H of the hydrological year 2024;
the ČHMÚ gauges Špindlerův Mlýn and Zapadlá Ves have values two decades
apart (2004–2006 and 2023–2024).
"""

import re
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Page, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    STORE,
    address,
    api,
    drag,
    frame_of,
    open_session,
    query_of,
    station_settings,
)

Serve = Callable[..., Served]
Stores = Callable[[str], Path]

COMPARE = "station-compare"
DAILY = "pl.imgw.hydro_daily"
CZ_DAILY = "cz.chmi.hydro_daily"
RABA = f"{STORE}/IMGW-PIB/149190310"
BEZ_Q = f"{STORE}/IMGW-PIB/149190311"  # no position
UNSERIED = f"{STORE}/IMGW-PIB/149190312"  # no series at all
SPINDLER = f"{STORE}/CHMI/0-203-1-900001"  # values 2023-01-01 to 2024-12-31
ZAPADLA = f"{STORE}/CHMI/0-203-1-900002"  # values 2004 to 2006
# The range and the time grid of each panel, read at one moment.
PANELS = """
(panels) => [...panels.querySelectorAll(".sch-plot")].map((plot) => ({
  from: plot.dataset.from,
  to: plot.dataset.to,
  ticks: [...plot.querySelectorAll(":scope > svg > line.sch-grid")].map(
    (line) => line.getAttribute("x1")),
}))
"""
# Each row of the facts: its station and its cells (a cell's value, else its text).
FACTS = """
(table) => [...table.querySelectorAll("tbody tr")].map((row) => {
  const facts = { station: row.dataset.station };
  for (const cell of row.querySelectorAll("[data-fact]")) {
    const text = cell.textContent.replace(/\\s+/g, " ").trim();
    facts[cell.dataset.fact] = cell.dataset.value ?? text;
  }
  return facts;
})
"""


def compare_address(
    served: Served, stations: Sequence[str], dataset: str, **params: str
) -> str:
    """Return the address of the comparison of ``stations`` (H by default)."""
    return address(
        served,
        view=COMPARE,
        stations=",".join(stations),
        dataset=dataset,
        **{"variable": "H", **params},
    )


def open_list(page: Page, served: Served) -> None:
    """Open the Catalog's list of hydro stations; wait for its rows."""
    page.goto(address(served, view="catalog", product="hydro"))
    grid = page.get_by_role("grid", name="Lista stacji katalogu")
    expect(grid).to_have_attribute("aria-busy", "false")


def pick(page: Page, name: str) -> None:
    """Choose a station of the list for the comparison by its row's button."""
    page.get_by_role("button", name=f"Wybierz {name} do porównania (P)").click()


def panels(page: Page) -> list[dict[str, Any]]:
    """Return each panel's range and time grid, once no answer is awaited."""
    expect(page.locator(".scmp-figure")).not_to_have_class(re.compile(r"\bbusy\b"))
    shown: list[dict[str, Any]] = page.locator(".scmp-panels").evaluate(PANELS)
    return shown


def card_facts(page: Page, station: str) -> dict[str, str]:
    """Return the facts of H of a station as its card (``GET /stations/{code}``)."""
    store, provider, code = station.split("/")
    query = urlencode({"store": store, "provider": provider})
    card = api(page, f"/stations/{code}?{query}")["station"]
    (series,) = [item for item in card["series"] if item["dataset"] == DAILY]
    coverage = series["coverage"]["H"]
    gap = coverage["longest_gap"]
    first, last = coverage["valued"]["from"], coverage["valued"]["to"]
    return {
        "station": station,
        "years": str(first) if first == last else f"{first}–{last}",
        "label": coverage["label"],
        "longest": f"{dotted(gap['from'])}–{dotted(gap['to'])} ({gap['units']} dni)",
        "full": str(coverage["complete_years"]),
        "location": card["location"]["source"] or card["location"]["reason"],
    }


def dotted(day: str) -> str:
    """Return a day as the interface writes it: ``2024.03.01``."""
    return day.replace("-", ".")


def test_two_rows_of_the_list_give_two_panels_on_one_time_axis(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Raba Górna and Stacja Bez Q chosen in the list: one range, the same ticks."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    query = urlencode(
        {"station": [RABA, BEZ_Q], "dataset": DAILY, "variable": "H"}, doseq=True
    )
    answer = api(page, f"/stations/compare?{query}")
    open_list(page, served)

    # Act
    pick(page, "Raba Górna")
    pick(page, "Stacja Bez Q")
    expect(page.locator(".cat-pick-bar")).to_contain_text("Do porównania: 2 z 5")
    page.get_by_role("button", name="Porównaj", exact=True).click()
    expect(page.locator(".scmp-panel .sch-plot")).to_have_count(2)
    shown = panels(page)

    # Assert
    assert query_of(page) == {
        "view": COMPARE,
        "stations": f"{RABA},{BEZ_Q}",
        "dataset": DAILY,
        "variable": "H",
    }
    assert (answer["from"], answer["to"]) == ("2023-11-01", "2024-10-31")
    assert [(panel["from"], panel["to"]) for panel in shown] == [
        (answer["from"], answer["to"])
    ] * 2
    assert shown[0]["ticks"] == shown[1]["ticks"] != []
    expect(page.locator(".scmp-panel .sch-title")).to_have_text(
        ["Raba Górna · 149190310", "Stacja Bez Q · 149190311"]
    )
    expect(page.locator(".scmp-figure .sch-summary")).to_have_text(
        "2023.11.01–2024.10.31 (366 dni)"
    )
    engine_tab.assert_clean()


def test_a_selection_in_one_panel_zooms_every_panel_and_writes_the_range(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Two ČHMÚ gauges two decades apart: a drag in one panel, ``Home`` in the other."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    page.goto(compare_address(served, [SPINDLER, ZAPADLA], CZ_DAILY))
    plots = page.locator(".scmp-panel .sch-plot")
    note = page.locator(".scmp-figure .sch-note")
    expect(plots).to_have_count(2)
    expect(note).to_contain_text("wykres uproszczony")
    whole = frame_of(plots.nth(1))

    # Act
    drag(page, whole, date(2024, 4, 1), date(2024, 7, 31))
    expect(page).to_have_url(re.compile(r"[?&]from="))
    expect(note).to_have_text("wartości dobowe")
    zoomed = query_of(page)
    narrowed = panels(page)
    plots.nth(0).focus()
    page.keyboard.press("Home")
    expect(page).not_to_have_url(re.compile(r"[?&]from="))
    expect(note).to_contain_text("wykres uproszczony")
    reset = query_of(page)
    again = panels(page)

    # Assert
    assert (whole.first, whole.last) == (date(2004, 1, 1), date(2024, 12, 31))
    first, last = (date.fromisoformat(zoomed[name]) for name in ("from", "to"))
    assert abs((first - date(2024, 4, 1)).days) <= 8
    assert abs((last - date(2024, 7, 31)).days) <= 8
    assert [(panel["from"], panel["to"]) for panel in narrowed] == [
        (zoomed["from"], zoomed["to"])
    ] * 2
    assert narrowed[0]["ticks"] == narrowed[1]["ticks"] != []
    assert "to" not in reset
    assert [(panel["from"], panel["to"]) for panel in again] == [
        ("2004-01-01", "2024-12-31")
    ] * 2
    engine_tab.assert_clean()


def test_the_facts_are_those_of_the_cards(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Years, label, longest gap, full years, location; "brak danych" without data."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    cards = [card_facts(page, station) for station in (RABA, BEZ_Q)]

    # Act
    page.goto(compare_address(served, [RABA, BEZ_Q, UNSERIED], DAILY))
    table = page.locator(".scmp-table")
    expect(table.locator("tbody tr")).to_have_count(3)
    facts = table.evaluate(FACTS)

    # Assert
    assert facts == [
        *cards,
        {"station": UNSERIED, "none": "brak danych", "location": "none"},
    ]
    expect(page.locator(".scmp-panel .sch-plot")).to_have_count(2)
    expect(page.locator(".scmp-panel.missing")).to_have_text(
        "Stacja Bez Miejsca · 149190312"
        " brak danych: stacja nie ma szeregu „Dane hydrologiczne dobowe”"
    )
    engine_tab.assert_clean()


def test_five_stations_at_most_neither_a_sixth_row_nor_an_added_one(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """``P`` on six rows chooses five; the sixth button and "Dodaj stację" disabled."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    found = [
        api(page, f"/stations?kind=hydro&location={group}&limit=200")["items"]
        for group in ("with", "none")
    ]
    order = [
        f"{item['store']}/{item['provider']}/{item['code']}"
        for items in found
        for item in items
    ]
    open_list(page, served)
    rows = page.locator(".cat-rows .cat-row:not(.st-group-row)")
    expect(rows).to_have_count(len(order))

    # Act
    for index in range(6):
        rows.nth(index).focus()
        page.keyboard.press("p")
    expect(page.locator(".cat-pick-bar")).to_contain_text("Do porównania: 5 z 5")
    pressed = [
        button.get_attribute("aria-pressed")
        for button in page.locator(".cat-rows .cat-pick").all()
    ]
    sixth = rows.nth(5).locator(".cat-pick")
    expect(sixth).to_be_disabled()
    full = sixth.get_attribute("title")
    page.get_by_role("button", name="Porównaj", exact=True).click()
    expect(page.locator(".scmp-panel")).to_have_count(5)
    add = page.get_by_role("searchbox", name="Dodaj stację")

    # Assert
    assert len(order) >= 6
    assert pressed == ["true"] * 5 + ["false"] * (len(order) - 5)
    assert full == "Porównanie ma już pięć stacji"
    assert query_of(page)["stations"].split(",") == order[:5]
    expect(add).to_be_disabled()
    expect(page.locator(".scmp-full")).to_have_text(
        "Porównanie ma już pięć stacji: najpierw usuń którąś."
    )
    engine_tab.assert_clean()


def test_compare_with_of_the_card_keeps_its_range_and_adds_a_found_station(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Raba Górna's zoomed chart, "Porównaj z…", "Dodaj stację" finds Stacja Bez Q."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    zoom = {"from": "2023-12-01", "to": "2024-02-29"}
    page.goto(address(served, view="catalog", product="hydro", station=RABA, **zoom))
    card = page.get_by_role("dialog", name="Raba Górna")
    expect(card.locator(".sch-plot")).to_have_attribute("data-from", zoom["from"])
    chips = page.locator(".scmp-chip")
    add = page.get_by_role("searchbox", name="Dodaj stację")

    # Act
    card.get_by_role("button", name="Porównaj z…").click()
    expect(page).to_have_url(re.compile(rf"[?&]view={COMPARE}(&|$)"))
    expect(chips).to_have_text(["Raba Górna"])
    alone = query_of(page)
    expect(page.locator(".scmp > p.hint")).to_contain_text("co najmniej dwóch stacji")
    add.fill("Bez Q")
    page.get_by_role("button", name=re.compile(r"^Stacja Bez Q")).click()
    expect(page.locator(".scmp-panel .sch-plot")).to_have_count(2)
    shown = panels(page)

    # Assert
    assert alone == {
        "view": COMPARE,
        "stations": RABA,
        "dataset": DAILY,
        "variable": "H",
        **zoom,
    }
    assert query_of(page) == {**alone, "stations": f"{RABA},{BEZ_Q}"}
    assert [(panel["from"], panel["to"]) for panel in shown] == [
        (zoom["from"], zoom["to"])
    ] * 2
    expect(chips).to_have_text(["Raba Górna", "Stacja Bez Q"])
    expect(add).to_have_value("")
    engine_tab.assert_clean()
