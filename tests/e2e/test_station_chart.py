"""The chart of the station card, its tab "Wykres" (plan I8.5, ADR-045 decision 11).

The card draws ``GET /stations/{code}/series`` as SVG with ``max_points`` the
plot's width. In ``complete`` H of Raba Górna (``149190310``) has values on
2023.12.01 and 2024.02.29 only; its label counts four gaps in the
hydrological year 2024 (November before the first value, the producer's
gaps 2023.12.02–12.31 and 2024.02.01–28, and March to October after the last
value; January lies between two values in no gap), and the chart shows the
year, its known span, with those four grey bands (ADR-045 erratum 1): its
line is two subpaths of one vertex each, never a line across a band. A
request rewritten to ``max_points=30`` gives intervals of 13 days and the
note of a simplified chart. In ``complete_pl_cz`` the ČHMÚ gauge Špindlerův
Mlýn has 731 days of H, more than the plot's pixels: simplified until a drag
selection narrows the range to daily values, writing ``from`` and ``to``; a
selection of one month gives its 31 daily vertices. The keys zoom, move and
reset the range.
"""

import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Locator, Route, expect

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

RABA = "IMGW-PIB/149190310"
SPINDLER = "CHMI/0-203-1-900001"
VERTEX = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
MAX_POINTS = re.compile(r"[?&]max_points=(\d+)")


def card_address(served: Served, station: str, **params: str) -> str:
    """Return the Catalog's address with the card of a station of the fixture."""
    return address(
        served, view="catalog", product="hydro", station=f"{STORE}/{station}", **params
    )


def subpaths(line: Locator) -> list[list[float]]:
    """Return the x of each vertex of each subpath of a line (``M`` starts one)."""
    path = line.get_attribute("d") or ""
    return [
        [float(x) for x, _ in VERTEX.findall(part)] for part in path.split("M") if part
    ]


def test_the_gaps_are_grey_bands_the_line_never_crosses(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """H of Raba Górna: four bands, two one-vertex subpaths, no vertex in a band."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    query = urlencode({"store": STORE, "provider": "IMGW-PIB", "variable": "H"})
    (variable,) = api(page, f"/stations/149190310/series?{query}")["variables"]
    valued = [point["t"] for point in variable["points"] if point["mean"] is not None]

    # Act
    page.goto(card_address(served, RABA))
    card = page.get_by_role("dialog", name="Raba Górna")
    line = card.locator(".sch-line[data-key=H]")
    expect(line).to_have_attribute("d", re.compile(r"^M"))
    bands = card.locator(".sch-gap[data-key=H]").all()
    shown = [
        (band.get_attribute("data-from"), band.get_attribute("data-to"))
        for band in bands
    ]
    spans = [
        (float(band.get_attribute("x") or 0), float(band.get_attribute("width") or 0))
        for band in bands
    ]
    runs = subpaths(line)
    frame = frame_of(card.locator(".sch-plot"))

    # Assert
    expect(card.get_by_role("tab", name="Wykres")).to_have_attribute(
        "aria-selected", "true"
    )
    assert shown == [(gap["from"], gap["to"]) for gap in variable["gaps"]]
    assert shown == [
        ("2023-11-01", "2023-11-30"),
        ("2023-12-02", "2023-12-31"),
        ("2024-02-01", "2024-02-28"),
        ("2024-03-01", "2024-10-31"),
    ]
    assert [len(run) for run in runs] == [1, 1]
    vertices = [x for run in runs for x in run]
    assert [frame.day_at(x).isoformat() for x in vertices] == valued
    assert valued == ["2023-12-01", "2024-02-29"]
    for x in vertices:
        assert all(not start <= x <= start + width for start, width in spans)
    expect(card.locator(".sch-note")).to_have_text("wartości dobowe")
    expect(card.locator(".sch-summary")).to_have_text(
        "2023.11.01–2024.10.31 (366 dni) · H: 2 z 366 punktów z wartością,"
        " 4 luki (333 dni)"
    )
    engine_tab.assert_clean()


def test_the_bands_are_the_gaps_of_the_cards_label_in_its_year_type(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """T of Špindlerův Mlýn: "luki 92%" has its band; calendar years have two."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    card = page.get_by_role("dialog", name="Špindlerův Mlýn")
    key = page.locator(".sc-key", has_text="T")
    label = card.locator(".sc-var").filter(has=key).locator(".sc-label")
    bands = card.locator(".sch-gap[data-key=T]")

    # Act
    page.goto(card_address(served, SPINDLER, chart_variable="T"))
    expect(label).to_contain_text("luki 92%")
    expect(bands).to_have_count(1)
    hydrological = [
        (b.get_attribute("data-from"), b.get_attribute("data-to")) for b in bands.all()
    ]
    page.goto(card_address(served, SPINDLER, chart_variable="T", year_type="calendar"))
    expect(label).to_contain_text("częściowy")
    expect(bands).to_have_count(2)
    calendar = [
        (b.get_attribute("data-from"), b.get_attribute("data-to")) for b in bands.all()
    ]

    # Assert
    assert hydrological == [("2023-12-01", "2024-10-31")]
    assert calendar == [("2023-01-01", "2023-09-30"), ("2023-12-01", "2023-12-31")]
    expect(card.locator(".sch-plot")).to_have_attribute("data-from", "2023-01-01")
    expect(card.locator(".sch-plot")).to_have_attribute("data-to", "2024-12-31")
    engine_tab.assert_clean()


def test_a_request_rewritten_to_30_points_shows_the_note_of_a_simplified_chart(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """``max_points=30`` over 366 days: intervals of 13 days, a band and the note."""
    # Arrange
    served = serve(station_settings(imgw_store("complete"), tmp_path))
    page = open_session(engine_tab, served)
    asked: list[int] = []

    def rewrite(route: Route) -> None:
        found = MAX_POINTS.search(route.request.url)
        assert found is not None
        asked.append(int(found[1]))
        url = route.request.url.replace(found[0], found[0][0] + "max_points=30")
        route.continue_(url=url)

    page.route(re.compile(r"/api/v1/stations/149190310/series\?"), rewrite)

    # Act
    page.goto(card_address(served, RABA))
    card = page.get_by_role("dialog", name="Raba Górna")
    expect(card.locator(".sch-note")).to_have_text(
        "wykres uproszczony: min./śr./maks. z 13 dni"
        " (cały okres; po przybliżeniu wartości dobowe)"
    )
    runs = subpaths(card.locator(".sch-line[data-key=H]"))
    width = float(card.locator(".sch-plot").get_attribute("data-width") or 0)

    # Assert
    assert asked[-1] == int(width)
    assert [len(run) for run in runs] == [1, 1]
    expect(card.locator(".sch-band")).to_have_count(1)
    expect(card.locator(".sch-gap[data-key=H]")).to_have_count(4)
    expect(card.locator(".sch-summary")).to_contain_text(
        "H: 2 z 29 punktów z wartością"
    )
    engine_tab.assert_clean()


def test_a_selection_narrows_the_whole_series_to_daily_values_and_writes_the_range(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """731 days simplified; a selection gives daily values, a month 31 vertices."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    page.goto(card_address(served, SPINDLER))
    card = page.get_by_role("dialog", name="Špindlerův Mlýn")
    note = card.locator(".sch-note")
    expect(note).to_contain_text("wykres uproszczony: min./śr./maks. z 2 dni")
    whole = frame_of(card.locator(".sch-plot"))

    # Act
    drag(page, whole, date(2024, 4, 1), date(2024, 7, 31))
    expect(note).to_have_text("wartości dobowe")
    narrowed = query_of(page)
    frame = frame_of(card.locator(".sch-plot"))
    drag(page, frame, date(2024, 5, 1), date(2024, 5, 31))
    expect(page).to_have_url(re.compile(r"[?&]to=2024-05-31(&|$)"))
    expect(card.locator(".sch-summary")).to_contain_text("(31 dni)")
    month = query_of(page)
    runs = subpaths(card.locator(".sch-line[data-key=H]"))

    # Assert
    assert (whole.first, whole.last) == (date(2023, 1, 1), date(2024, 12, 31))
    assert (frame.first.isoformat(), frame.last.isoformat()) == (
        narrowed["from"],
        narrowed["to"],
    )
    assert (month["from"], month["to"]) == ("2024-05-01", "2024-05-31")
    assert [len(run) for run in runs] == [31]
    expect(card.locator(".sch-summary")).to_have_text(
        "2024.05.01–2024.05.31 (31 dni) · H: 31 z 31 punktów z wartością, bez luk"
    )
    engine_tab.assert_clean()


def test_the_keys_zoom_move_and_give_back_the_whole_series(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """``+`` halves the range, an arrow moves it, ``Home`` removes it."""
    # Arrange
    served = serve(station_settings(imgw_store("complete_pl_cz"), tmp_path))
    page = open_session(engine_tab, served)
    page.goto(card_address(served, SPINDLER))
    card = page.get_by_role("dialog", name="Špindlerův Mlýn")
    plot = card.locator(".sch-plot")
    expect(plot).to_have_attribute("data-to", "2024-12-31")

    # Act
    plot.focus()
    page.keyboard.press("+")
    expect(page).to_have_url(re.compile(r"[?&]from="))
    zoomed = query_of(page)
    expect(plot).to_have_attribute("data-from", zoomed["from"])
    page.keyboard.press("ArrowRight")
    expect(plot).not_to_have_attribute("data-from", zoomed["from"])
    moved = query_of(page)
    page.keyboard.press("Home")
    expect(plot).to_have_attribute("data-from", "2023-01-01")
    reset = query_of(page)

    # Assert
    first, last = (date.fromisoformat(zoomed[name]) for name in ("from", "to"))
    assert abs((last - first).days + 1 - 366) <= 1
    later, end = (date.fromisoformat(moved[name]) for name in ("from", "to"))
    assert end - later == last - first
    assert abs((later - first).days - 73) <= 1
    assert "from" not in reset and "to" not in reset
    expect(card.locator(".sch-note")).to_contain_text("cały okres")
    engine_tab.assert_clean()
