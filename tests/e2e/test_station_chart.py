"""The chart of the station card, its tab "Wykres" (plan I8.5, ADR-045 decision 11).

The card draws ``GET /stations/{code}/series`` as SVG with ``max_points`` the
plot's width. In ``complete`` H of Raba Górna (``149190310``) has values on
2023.12.01 and 2024.02.29 only, between the producer's gaps 2023.12.02–12.31
and 2024.02.01–28 (January has no value and no gap: it is not known), so its
line is two subpaths of one vertex each beside two grey bands, never a line
across them. A request rewritten to ``max_points=30`` gives intervals of 4
days and the note of a simplified chart. In ``complete_pl_cz`` the ČHMÚ gauge
Špindlerův Mlýn has 731 days of H, more than the plot's pixels: simplified
until a drag selection narrows the range to daily values, writing ``from``
and ``to``; a selection of one month gives its 31 daily vertices. The keys
zoom, move and reset the range.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, Route, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    STORE,
    address,
    api,
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


@dataclass(frozen=True)
class Frame:
    """The plot's range of days and where it lies: its svg on the screen, px."""

    first: date
    last: date
    svg_x: float
    left: float
    width: float
    y: float

    @property
    def days(self) -> int:
        """Return the days of the range."""
        return (self.last - self.first).days + 1

    def day_at(self, x: float) -> date:
        """Return the day under an x of the svg (its own coordinates)."""
        return self.first + timedelta(
            days=int((x - self.left) / self.width * self.days)
        )

    def screen_x(self, day: date) -> float:
        """Return the screen x of the middle of a day."""
        offset = (day - self.first).days + 0.5
        return self.svg_x + self.left + offset / self.days * self.width


def card_address(served: Served, station: str, **params: str) -> str:
    """Return the Catalog's address with the card of a station of the fixture."""
    return address(
        served, view="catalog", product="hydro", station=f"{STORE}/{station}", **params
    )


def frame_of(card: Locator) -> Frame:
    """Return the plot's range and place in the card."""
    plot = card.locator(".sch-plot")
    box = plot.locator("svg").bounding_box()
    assert box is not None
    return Frame(
        first=date.fromisoformat(plot.get_attribute("data-from") or ""),
        last=date.fromisoformat(plot.get_attribute("data-to") or ""),
        svg_x=box["x"],
        left=float(plot.get_attribute("data-left") or 0),
        width=float(plot.get_attribute("data-width") or 0),
        y=box["y"] + 100,
    )


def subpaths(line: Locator) -> list[list[float]]:
    """Return the x of each vertex of each subpath of a line (``M`` starts one)."""
    path = line.get_attribute("d") or ""
    return [
        [float(x) for x, _ in VERTEX.findall(part)] for part in path.split("M") if part
    ]


def drag(page: Page, frame: Frame, first: date, last: date) -> None:
    """Select the days from ``first`` to ``last`` by dragging over the plot."""
    start, end = frame.screen_x(first), frame.screen_x(last)
    page.mouse.move(start, frame.y)
    page.mouse.down()
    page.mouse.move((start + end) / 2, frame.y)
    page.mouse.move(end, frame.y)
    page.mouse.up()


def test_the_gaps_are_grey_bands_the_line_never_crosses(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """H of Raba Górna: two bands, two one-vertex subpaths, no vertex in a band."""
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
    frame = frame_of(card)

    # Assert
    expect(card.get_by_role("tab", name="Wykres")).to_have_attribute(
        "aria-selected", "true"
    )
    assert shown == [(gap["from"], gap["to"]) for gap in variable["gaps"]]
    assert shown == [("2023-12-02", "2023-12-31"), ("2024-02-01", "2024-02-28")]
    assert [len(run) for run in runs] == [1, 1]
    vertices = [x for run in runs for x in run]
    assert [frame.day_at(x).isoformat() for x in vertices] == valued
    assert valued == ["2023-12-01", "2024-02-29"]
    for x in vertices:
        assert all(not start <= x <= start + width for start, width in spans)
    expect(card.locator(".sch-note")).to_have_text("wartości dobowe")
    expect(card.locator(".sch-summary")).to_have_text(
        "2023.12.01–2024.02.29 (91 dni) · H: 2 z 91 punktów z wartością,"
        " 2 luki (58 dni)"
    )
    engine_tab.assert_clean()


def test_a_request_rewritten_to_30_points_shows_the_note_of_a_simplified_chart(
    serve: Serve, engine_tab: Tab, imgw_store: Stores, tmp_path: Path
) -> None:
    """``max_points=30`` over 91 days: intervals of 4 days, a band and the note."""
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
        "wykres uproszczony: min./śr./maks. z 4 dni"
        " (cały okres; po przybliżeniu wartości dobowe)"
    )
    runs = subpaths(card.locator(".sch-line[data-key=H]"))
    width = float(card.locator(".sch-plot").get_attribute("data-width") or 0)

    # Assert
    assert asked[-1] == int(width)
    assert [len(run) for run in runs] == [1, 1]
    expect(card.locator(".sch-band")).to_have_count(1)
    expect(card.locator(".sch-gap[data-key=H]")).to_have_count(2)
    expect(card.locator(".sch-summary")).to_contain_text(
        "H: 2 z 23 punktów z wartością"
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
    whole = frame_of(card)

    # Act
    drag(page, whole, date(2024, 4, 1), date(2024, 7, 31))
    expect(note).to_have_text("wartości dobowe")
    narrowed = query_of(page)
    frame = frame_of(card)
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
