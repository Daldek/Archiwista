"""The tier and publication of a version in the Catalog and the file card (A-ADR-059).

Obserwator 3.2.0 writes data that are not the verified archive: IMGW-PIB's
telemetry (tier ``telemetry``, public), answers of hydro-back captured as
they come and the hourly series built from them (tier ``operational``,
private). Each version says so where a person meets it: a badge in its row
of the Catalog's file list, on the version axis of its slot's card and under
the title of the chosen version, with the words of Nogat DEV-20.8; the
publication state stands beside it when the sidecar records one. A version
of verified data with no publication state recorded (public) gets neither.
The hourly series of Raba's gauge, its two monthly versions joined, shows its
coverage on the station card with the hours of its values in UTC and the
months it joins, and in the Timeline; Archiwista draws no chart of it, so the
card's chart is the daily series' and the comparison of it says why there is
none. The views are no map, so each test runs in Chromium and Firefox.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from playwright.sync_api import Locator, Page, expect

from tests.fixtures.browser import Served, Tab
from tests.fixtures.station_browser import (
    STORE,
    address,
    api,
    open_session,
    station_settings,
)

Serve = Callable[..., Served]

TELEMETRY = "pl.imgw.hydro_telemetry"
OPERATIONAL = "pl.imgw.hydro_operational"
SUBDAILY = "pl.imgw.hydro_subdaily"
DAILY = "pl.imgw.hydro_daily"
TELEMETRY_WORDS = "telemetria: dane operacyjne, niezweryfikowane"
OPERATIONAL_WORDS = "dane operacyjne, niezweryfikowane"
RABA = "149190310"
# The marks of a version: its tier's badge, then its publication's, as shown.
MARKS = """
(element) => [...element.querySelectorAll(".cat-tier, .cat-publication")]
  .map((mark) => mark.textContent.replace(/\\s+/g, " ").trim())
"""


def slots_of(page: Page, segment: str) -> list[dict[str, Any]]:
    """Return the Catalog's rows of a segment, every version of each slot."""
    answer = api(page, f"/slots?segment={quote(segment)}&versions=all&limit=200")
    items: list[dict[str, Any]] = answer["items"]
    assert items, segment
    return items


def row_marks(page: Page, served: Served, segment: str) -> list[list[str]]:
    """Open the Catalog's file list of a segment; return the marks of each row."""
    page.goto(address(served, view="catalog", segment=segment, versions="all"))
    grid = page.get_by_role("grid")
    expect(grid).to_have_attribute("aria-busy", "false")
    rows = grid.locator(".cat-rows [role=row][data-index]")
    expect(rows).to_have_count(len(slots_of(page, segment)))
    return [row.evaluate(MARKS) for row in rows.all()]


def file_card(page: Page, served: Served, item: dict[str, Any]) -> Locator:
    """Open the file card of a row's slot at its version; return the card."""
    page.goto(
        address(
            served,
            view="catalog",
            file=f"{STORE}/{item['slot']}",
            file_version=item["version"]["path"],
        )
    )
    card = page.get_by_role("dialog")
    expect(card.locator(".fc-version-title")).to_be_visible()
    return card


def test_catalog_rows_mark_telemetry_and_private_operational_versions_only(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """Telemetry: tier and „publiczne”; a capture and an hourly month: „prywatne”."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)

    # Act
    telemetry = row_marks(page, served, TELEMETRY)
    captured = row_marks(page, served, OPERATIONAL)
    hourly = row_marks(page, served, SUBDAILY)
    verified = row_marks(page, served, DAILY)

    # Assert
    assert telemetry == [[TELEMETRY_WORDS, "publiczne"]] * 2
    assert captured == [[OPERATIONAL_WORDS, "prywatne"]]
    assert hourly == [[OPERATIONAL_WORDS, "prywatne"]] * 2
    assert verified == [[]] * len(verified)
    engine_tab.assert_clean()


def test_file_card_marks_each_version_on_its_axis_and_under_its_title(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """An hourly month's version and a telemetry one; a verified one has no badge."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)
    hourly = slots_of(page, SUBDAILY)[0]
    telemetry = slots_of(page, TELEMETRY)[0]
    verified = slots_of(page, DAILY)[0]

    # Act
    card = file_card(page, served, hourly)
    hourly_axis = card.locator(".fc-version .fc-tier .state-badge").all_inner_texts()
    hourly_head = card.locator(".fc-version-tier .state-badge").all_inner_texts()
    card = file_card(page, served, telemetry)
    telemetry_head = card.locator(".fc-version-tier .state-badge").all_inner_texts()
    card = file_card(page, served, verified)
    expect(card.locator(".fc-version").first).to_be_visible()
    verified_axis = card.locator(".fc-version .fc-tier").count()
    verified_head = card.locator(".fc-version-tier").count()

    # Assert
    assert [text.strip() for text in hourly_axis] == [OPERATIONAL_WORDS, "prywatne"]
    assert [text.strip() for text in hourly_head] == [OPERATIONAL_WORDS, "prywatne"]
    assert [text.strip() for text in telemetry_head] == [TELEMETRY_WORDS, "publiczne"]
    assert (verified_axis, verified_head) == (0, 0)
    engine_tab.assert_clean()


def utc_hour(moment: str) -> str:
    """Return an hour of the API (``2026-09-01T00:00:00Z``) as the card shows it."""
    day, clock = moment.rstrip("Z").split("T")
    return f"{day.replace('-', '.')} {clock[:5]} UTC"


def test_hourly_series_shows_its_coverage_in_utc_hours_and_draws_no_chart(
    serve: Serve, engine_tab: Tab, tiers_store: Path, tmp_path: Path
) -> None:
    """The card's hours and months, the Timeline's row, the comparison's refusal."""
    # Arrange
    served = serve(station_settings(tiers_store, tmp_path))
    page = open_session(engine_tab, served)
    lookup = urlencode({"store": STORE, "provider": "IMGW"})
    answer = api(page, f"/stations/{RABA}?{lookup}")
    series = answer["station"]["series"]
    hourly = next(item for item in series if item["dataset"] == SUBDAILY)
    level = hourly["coverage"]["H"]
    station = f"{STORE}/IMGW/{RABA}"
    card = page.get_by_role("dialog", name="Raba Górna")
    block = card.locator(".sc-series").nth(series.index(hourly))
    line = block.locator(".sc-var").filter(has=page.locator(".sc-key", has_text="H"))

    # Act
    page.goto(
        address(
            served,
            view="catalog",
            product="hydro",
            station=station,
            chart_dataset=SUBDAILY,
        )
    )
    expect(line.locator(".sc-label")).to_have_text(level["label"])
    span = line.locator(".sc-span").inner_text()
    expect(card.locator(".sch-frame svg").first).to_be_visible()
    card.get_by_role("tab", name="Pochodzenie").click()
    origin = card.locator(".sc-origin").nth(series.index(hourly)).inner_text()
    page.goto(
        address(
            served, view="catalog", product="hydro", layout="timeline", dataset=SUBDAILY
        )
    )
    timeline = page.locator(".stl-rowhead", has_text="Raba Górna")
    expect(timeline).to_have_count(1)
    page.goto(
        address(
            served,
            view="station-compare",
            stations=f"{station},{STORE}/CHMU/0-203-1-VP0624",
            dataset=SUBDAILY,
            variable="H",
        )
    )
    refusal = page.get_by_role("alert").or_(page.locator(".problem"))

    # Assert
    assert (hourly["time_unit"], hourly["months"]) == ("hour", ["2026-09", "2026-10"])
    assert [item["time_unit"] for item in answer["charts"]] == ["day"]
    assert span == f"· wartości {utc_hour(level['first'])}–{utc_hour(level['last'])}"
    assert "Miesiące szeregu\n2026-09–2026-10" in origin
    expect(refusal.first).to_contain_text("nie rysuje wykresu")
    engine_tab.assert_clean()
