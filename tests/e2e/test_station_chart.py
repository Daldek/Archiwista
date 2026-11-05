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

The statistics store (``tests/fixtures/obserwator_statistics.py``, A-ADR-051)
adds IMGW-PIB's monthly series and half-year characteristics: the monthly Q
of Raba Górna is the mean line inside the band of each month's published
minimum and maximum, broken at the gap of March 2024; Stacja Bez Miejsca
(``149190312``), with half-year characteristics only, opens on the annual
chart of its Q, whose 2023 has no summer maximum: a hollow dot and a tooltip
naming the missing half.
"""

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import Locator, Route, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.obserwator_statistics import HALF_YEARS_ONLY, MONTHLY
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
HALF_YEARS = f"IMGW-PIB/{HALF_YEARS_ONLY}"
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


def vertices(path: Locator) -> list[list[tuple[float, float]]]:
    """Return each vertex (x, y) of each subpath of a path (``M`` starts one)."""
    drawn = path.get_attribute("d") or ""
    return [
        [(float(x), float(y)) for x, y in VERTEX.findall(part)]
        for part in drawn.split("M")
        if part
    ]


def test_the_gaps_are_grey_bands_the_line_never_crosses(
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """H of Raba Górna: four bands, two one-vertex subpaths, no vertex in a band."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
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
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """T of Špindlerův Mlýn: "luki 92%" has its band; calendar years have two."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete_pl_cz"), tmp_path))
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
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """``max_points=30`` over 366 days: intervals of 13 days, a band and the note."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete"), tmp_path))
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
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """731 days simplified; a selection gives daily values, a month 31 vertices."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete_pl_cz"), tmp_path))
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
    serve: Serve, engine_tab: Tab, obserwator_store: Stores, tmp_path: Path
) -> None:
    """``+`` halves the range, an arrow moves it, ``Home`` removes it."""
    # Arrange
    served = serve(station_settings(obserwator_store("complete_pl_cz"), tmp_path))
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


def test_a_monthly_chart_draws_the_mean_inside_the_band_of_the_minimum_and_maximum(
    serve: Serve, engine_tab: Tab, statistics_store: Path, tmp_path: Path
) -> None:
    """Q of Raba Górna, 24 months: lines of 16 and 7 months, March 2024 a band."""
    # Arrange
    served = serve(station_settings(statistics_store, tmp_path))
    page = open_session(engine_tab, served)
    months = [date(2022 + (10 + n) // 12, (10 + n) % 12 + 1, 1) for n in range(24)]

    # Act
    page.goto(card_address(served, RABA, chart_dataset=MONTHLY, chart_variable="Q"))
    card = page.get_by_role("dialog", name="Raba Górna")
    line = card.locator(".sch-line[data-key=Q]")
    expect(line).to_have_attribute("d", re.compile(r"^M"))
    runs = vertices(line)
    shapes = vertices(card.locator(".sch-band"))
    gaps = [
        (band.get_attribute("data-from"), band.get_attribute("data-to"))
        for band in card.locator(".sch-gap[data-key=Q]").all()
    ]
    chips = card.get_by_role("group", name="Szereg").get_by_role("button")
    plot = card.locator(".sch-plot")
    plot.scroll_into_view_if_needed()
    frame = frame_of(plot)
    page.mouse.move(frame.screen_x(date(2023, 1, 16)), frame.y)
    tip = card.locator(".sch-tip")

    # Assert
    assert [len(run) for run in runs] == [16, 7]
    shown = [frame.day_at(x).replace(day=1) for run in runs for x, _ in run]
    assert shown == [month for month in months if month != date(2024, 3, 1)]
    assert gaps == [("2024-03-01", "2024-03-31")]
    assert len(shapes) == len(runs)
    for run, shape in zip(runs, shapes, strict=True):
        upper, lower = shape[: len(run)], shape[len(run) :][::-1]
        assert [x for x, _ in upper] == [x for x, _ in run] == [x for x, _ in lower]
        assert all(
            top < y < low
            for (_, top), (_, y), (_, low) in zip(upper, run, lower, strict=True)
        )
    expect(chips).to_have_text(
        ["dobowe", "miesięczne", "Roczne (z charakterystyk półrocznych)"]
    )
    expect(chips.filter(has_text="miesięczne")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(tip).to_have_text(
        re.compile(r"^2023\.01\s*Q: śr\. 2,5 \(min\. 1,5 – maks\. 3,5\) m³/s$")
    )
    expect(card.locator(".sch-note")).to_have_text("wartości miesięczne")
    expect(card.locator(".sch-summary")).to_have_text(
        "2022.11.01–2024.10.31 (24 miesiące) · Q: 23 z 24 punktów z wartością,"
        " 1 luka (1 miesiąc)"
    )
    engine_tab.assert_clean()


def test_a_station_with_half_year_characteristics_only_opens_on_the_annual_chart(
    serve: Serve, engine_tab: Tab, statistics_store: Path, tmp_path: Path
) -> None:
    """Stacja Bez Miejsca: each year's Q maximum and minimum, hydrological years."""
    # Arrange
    served = serve(station_settings(statistics_store, tmp_path))
    page = open_session(engine_tab, served)
    years = [str(year) for year in range(2020, 2025)]

    # Act
    page.goto(card_address(served, HALF_YEARS))
    card = page.get_by_role("dialog", name="Stacja Bez Miejsca")
    dots = card.locator(".sch-year[data-key=Q]")
    expect(dots).to_have_count(10)
    drawn = [
        (dot.get_attribute("data-kind"), dot.get_attribute("data-year"))
        for dot in dots.all()
    ]
    lines = {
        kind: vertices(card.locator(f".sch-line.{kind}[data-key=Q]"))
        for kind in ("max", "min")
    }
    asked = [url for url in engine_tab.requests if "/series?" in url]

    # Assert
    assert drawn == [("max", year) for year in years] + [
        ("min", year) for year in years
    ]
    assert {kind: [len(run) for run in runs] for kind, runs in lines.items()} == {
        "max": [5],
        "min": [5],
    }
    assert asked and all(
        "resolution=annual" in url and "year_type" not in url for url in asked
    )
    expect(card.get_by_role("tab", name="Wykres")).to_have_attribute(
        "aria-selected", "true"
    )
    expect(card.locator(".sch-time .sch-tick")).to_have_text(years)
    expect(card.locator(".sch-note")).to_have_text(
        "roczne maksimum i minimum wyznaczone przez Archiwistę z charakterystyk"
        " półrocznych IMGW-PIB"
    )
    expect(card.locator(".sc-years-note")).to_have_text(
        "Wykres roczny: zawsze lata hydrologiczne"
    )
    expect(card.locator(".sch-summary")).to_have_text(
        "2019.11.01–2024.10.31 (5 lat) · Q: 5 z 5 lat z wartością, bez luk"
    )
    engine_tab.assert_clean()


def test_the_annual_chart_saves_its_complete_years_maxima_as_a_hand_off_to_hydrolog(
    serve: Serve, engine_tab: Tab, statistics_store: Path, tmp_path: Path
) -> None:
    """„Plik przekazania”: nogat-handoff/1 around the maxima, 2023 left out and said."""
    # Arrange
    served = serve(station_settings(statistics_store, tmp_path))
    page = open_session(engine_tab, served)
    page.goto(card_address(served, HALF_YEARS))
    card = page.get_by_role("dialog", name="Stacja Bez Miejsca")
    expect(card.locator(".sch-year[data-key=Q]")).to_have_count(10)

    # Act
    with page.expect_download() as started:
        card.get_by_role("button", name="Plik przekazania").click()
    saved = started.value
    doc = json.loads(Path(saved.path()).read_text(encoding="utf-8"))

    # Assert
    assert saved.suggested_filename.endswith("— Q, maksima roczne.handoff.json")
    assert (doc["schema"], doc["payload"]["schema"]) == (
        "nogat-handoff/1",
        "hydrolog-series/1",
    )
    years = dict(zip(doc["payload"]["years"], doc["payload"]["values"], strict=True))
    assert years[2023] is None and all(years[year] is not None for year in (2020, 2024))
    assert doc["provenance"]["series"]["left_out"] == [2023]
    expect(card.locator(".sch-handoff-note")).to_contain_text(
        "pominięte lata bez jednego z półroczy: 2023"
    )
    engine_tab.assert_clean()


def test_the_hand_off_takes_the_kind_and_variable_chosen_beside_any_chart(
    serve: Serve, engine_tab: Tab, statistics_store: Path, tmp_path: Path
) -> None:
    """On the monthly chart: „wartości dobowe” of H go, not the chart's monthly Q."""
    # Arrange
    served = serve(station_settings(statistics_store, tmp_path))
    page = open_session(engine_tab, served)
    page.goto(card_address(served, RABA, chart_dataset=MONTHLY, chart_variable="Q"))
    card = page.get_by_role("dialog", name="Raba Górna")
    panel = card.get_by_role("group", name="Do Hydrologa")
    expect(panel.get_by_label("Dane")).to_have_value(
        re.compile(r"^unit:pl\.imgw\.hydro_daily$")
    )

    # Act
    panel.get_by_label("Zmienna").select_option("H")
    with page.expect_download() as started:
        panel.get_by_role("button", name="Plik przekazania").click()
    doc = json.loads(Path(started.value.path()).read_text(encoding="utf-8"))
    panel.get_by_label("Dane").select_option(
        label="maksima roczne (pełne lata hydrologiczne)"
    )

    # Assert
    payload = doc["payload"]
    assert (payload["step"], payload["variable"]) == ("day", "H")
    assert doc["provenance"]["series"]["dataset"] == "pl.imgw.hydro_daily"
    expect(panel.locator(".sch-handoff-what")).to_have_text(
        "przekazanie: maksima roczne pełnych lat hydrologicznych H [cm]"
    )
    engine_tab.assert_clean()


def test_an_incomplete_year_is_a_hollow_dot_whose_tooltip_names_the_missing_half(
    serve: Serve, engine_tab: Tab, statistics_store: Path, tmp_path: Path
) -> None:
    """2023 of Stacja Bez Miejsca: the winter maximum alone, the summer missing."""
    # Arrange
    served = serve(station_settings(statistics_store, tmp_path))
    page = open_session(engine_tab, served)
    page.goto(card_address(served, HALF_YEARS))
    card = page.get_by_role("dialog", name="Stacja Bez Miejsca")
    hollow = card.locator(".sch-year.partial")
    expect(hollow).to_have_count(1)
    plot = card.locator(".sch-plot")
    plot.scroll_into_view_if_needed()
    frame_of(plot)
    box = hollow.bounding_box()
    assert box is not None

    # Act
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    tip = card.locator(".sch-tip")
    expect(tip).to_be_visible()

    # Assert
    assert (hollow.get_attribute("data-kind"), hollow.get_attribute("data-year")) == (
        "max",
        "2023",
    )
    fills = card.locator(".sch-year.max").evaluate_all(
        "(dots) => dots.map((dot) => getComputedStyle(dot).fill)"
    )
    assert fills[3] == "rgb(255, 255, 255)"
    assert "rgb(255, 255, 255)" not in fills[:3] + fills[4:]
    expect(tip.locator("b")).to_have_text("rok hydrologiczny 2023")
    expect(tip.locator(".sch-tip-row")).to_have_text(
        [
            "Q maks.: 63 m³/s · 2023.02.01 (półrocze zimowe)"
            " · niepełny rok: brak półrocza letniego",
            "Q min.: 7 m³/s · 2023.07.01 (półrocze letnie)",
        ]
    )
    engine_tab.assert_clean()
