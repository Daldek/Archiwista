"""The rows of „U źródła” over a kept report, in Chromium (plan 2026-10-25, A10).

The store ``zespol`` is a Kartograf store of three NMT flights over the sheets
of ``AREA_SHEET`` (``tests/fixtures/layer_store``): ``SHEET_NW`` and
``SHEET_NE`` of 2023 (campaign 82710) and ``SHEET_SW`` of 2022 (campaign
61003), scanned before the server starts; the report names those two by their
survey works, as a source does. The kept report of the area is a
stand-in report of the stand-in producer (``tests/fixtures/action_source``),
written by hand so that its rows need every Polish form of SPEC 6.4: 2, 5, 22
and 25 campaigns, 1, 2 and 5 partial sheets, a share below 1%, a partial set
that covers the whole land (99%, never 100%), the chips „+1 wariant”, „+2
warianty” and „+5 wariantów”, and the badges „pobrane”, „pobrane 1/3”,
„pobrane 1/5” and „niepobrane” counted from the index. The expected texts are
worked out here from the report: the share is ``full_m2`` over the land of
20 km², rounded down. „Sprawdź ponownie” asks the stand-in again with
``force`` although the report is two days old; offline without a report the
step shows the banner and points to the store's local share, which the step
„Stan lokalny” shows for the same product. With
``ARCHIWISTA_SCREENSHOTS=<directory>`` the pictures are kept there
(``docs/reports/v0.3-screenshots/``).
"""

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

import pytest
from kartograf import describe_segment
from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import AreaRecord, IndexWriter, initialize, scan_store
from archiwista.sources import (
    AvailabilityArea,
    AvailabilityCampaign,
    AvailabilityCombination,
    AvailabilityReport,
    AvailabilitySheet,
)
from archiwista.sources.registry import load_registry
from tests.fixtures.availability import register_standin
from tests.fixtures.browser import Served, Tab
from tests.fixtures.layer_store import (
    AREA_SHEET,
    SHEET_NE,
    SHEET_NW,
    SHEET_SE,
    SHEET_SW,
    add_campaign,
    sheet_bounds,
    sheet_polygon,
    survey_work,
)
from tests.fixtures.local_server import local_paths
from tests.fixtures.make_store import NMT
from tests.fixtures.store_marker import mark_store

Serve = Callable[..., Served]

STORE = "zespol"
PRODUCT = "standin/dem"
LAND_M2 = 20_000_000.0
DATASET = str(describe_segment(NMT).dataset_key)
LINE = "series fetch --station 150160180 --kind hydro"
WARSAW = ZoneInfo("Europe/Warsaw")
AREA = AreaRecord(
    id="3a7c5e9b1d2f4a6c",
    source="drawn",
    geometry=sheet_polygon(AREA_SHEET),
    created_at=datetime(2026, 10, 26, 8, 0, tzinfo=UTC),
    area_km2=20.0,
    countries=("PL",),
    name="Arkusz D-d-2",
)
# The survey works of the store's flights: the report's names of their campaigns.
WORK_2023 = survey_work("82710", "2023-06-02")
WORK_2022 = survey_work("61003", "2022-04-11")
# Sheets of the sets of many campaigns: one record per campaign.
SHEETS = tuple(
    f"N-34-130-D-{quarter}-{row}-{column}"
    for quarter in "abc"
    for row in range(1, 5)
    for column in range(1, 5)
)
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
API = """async ([method, path]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch(`/api/v1${path}`, { method, headers });
  return { status: answer.status, body: await answer.json() };
}"""


def _records(
    *pairs: tuple[str, str], full: bool = True
) -> tuple[AvailabilitySheet, ...]:
    """Return the records a download takes: ``(sheet, campaign)`` each."""
    return tuple(
        AvailabilitySheet(sheet=sheet, campaign=campaign, full_sheet=full)
        for sheet, campaign in pairs
    )


def _set(
    year: int,
    horizontal: str,
    records: tuple[AvailabilitySheet, ...],
    *,
    complete: bool,
    share: float,
    resolution: str = "1m",
    file_format: str = "ASC",
    size_bytes: int | None = None,
) -> AvailabilityCombination:
    """Return a combination whose full records cover ``share`` of the land.

    No campaign covers the land alone, so a complete set of two or more
    campaigns is „pełne · N kampanie”.
    """
    campaigns = tuple(dict.fromkeys(str(record.campaign) for record in records))
    full = tuple(record.sheet for record in records if record.full_sheet)
    return AvailabilityCombination(
        country="PL",
        product="dem",
        source=DATASET,
        year=year,
        horizontal=horizontal,
        resolution=resolution,
        vertical_crs="EVRF2007",
        format=file_format,
        campaigns=campaigns,
        complete=complete,
        sheets_full=tuple(dict.fromkeys(full)),
        sheets_partial=tuple(
            dict.fromkeys(record.sheet for record in records if not record.full_sheet)
        ),
        sheets_missing=(),
        uncovered_m2=0.0,
        full_m2=share * LAND_M2,
        size_bytes=size_bytes,
        sheet_records=records,
        campaign_coverage=tuple(
            AvailabilityCampaign(campaign, False, share * LAND_M2 / len(campaigns))
            for campaign in campaigns
        ),
        commands=(LINE,),
    )


def _many(year: int, first: int, count: int) -> AvailabilityCombination:
    """Return a complete PL-1992 set of ``count`` campaigns, one per sheet."""
    pairs = [(SHEETS[n], str(first + n)) for n in range(count)]
    return _set(year, "PL-1992", _records(*pairs), complete=True, share=1.0)


def _partial(year: int, campaign: str, share: float) -> AvailabilityCombination:
    """Return a partial PL-2000 set of one campaign, no partial sheet."""
    records = _records(("7.120.10.1.1", campaign))
    return _set(year, "PL-2000", records, complete=False, share=share)


def stand_in_report(checked_at: datetime) -> AvailabilityReport:
    """Return the kept report: six years, best variant first by SPEC 6.4."""
    best_2023 = _records((SHEET_NW, WORK_2023), (SHEET_NE, WORK_2023))
    five = _records(
        (SHEET_NW, "61001"),
        (SHEET_NE, "61002"),
        (SHEET_SW, WORK_2022),
        (SHEET_SE, "61004"),
        (SHEETS[0], "61005"),
    )
    return AvailabilityReport(
        producer="standin",
        schema="standin-availability/1",
        checked_at=checked_at,
        request={"product": "dem", "countries": ["PL"]},
        areas=(
            AvailabilityArea(
                country="PL",
                crs="EPSG:2180",
                bounds=sheet_bounds(AREA_SHEET),
                area_m2=LAND_M2,
                land_m2=LAND_M2,
            ),
        ),
        combinations=(
            # 2023: two complete sets and a partial one; the store holds both
            # sheets of the first and one of the partial set's three.
            _set(
                2023,
                "PL-2000",
                _records(("7.120.10.1.1", "91001"), ("7.120.10.1.2", "91002")),
                complete=True,
                share=1.0,
            ),
            _set(
                2023,
                "PL-1992",
                best_2023,
                complete=True,
                share=1.0,
                size_bytes=265_000_000,
            ),
            _set(
                2023,
                "PL-1992",
                best_2023,
                complete=True,
                share=1.0,
                file_format="ASCII-NMT",
                size_bytes=410_000_000,
            ),
            _set(
                2023,
                "PL-1992",
                _records((SHEET_NW, WORK_2023))
                + _records((SHEET_SW, "82711"), (SHEET_SE, "82711"), full=False),
                complete=False,
                share=0.4,
                resolution="5m",
            ),
            _set(2022, "PL-1992", five, complete=True, share=1.0),
            _many(2021, 70001, 22),
            *(
                _partial(2021, f"7100{n}", share)
                for n, share in enumerate((0.5, 0.9, 0.6, 0.8, 0.7), start=1)
            ),
            _many(2020, 80001, 25),
            _partial(2020, "81001", 0.3),
            _set(
                2019,
                "PL-1992",
                _records(*((sheet, "50001") for sheet in SHEETS[:5]), full=False),
                complete=False,
                share=0.005,
            ),
            _set(
                2018,
                "PL-1992",
                _records((SHEET_NW, "40001"))
                + _records((SHEET_NE, "40001"), full=False),
                complete=False,
                share=1.0,
            ),
        ),
    )


def kept_store(tmp_path: Path, *, offline: bool, report: bool) -> AppSettings:
    """Write the store and the index (area, scan, report); return the settings."""
    root = tmp_path / STORE
    root.mkdir()
    mark_store(root)
    add_campaign(root, SHEET_NW, "2023-06-02", "82710", downloaded="2025-11-20")
    add_campaign(root, SHEET_NE, "2023-06-02", "82710", downloaded="2025-11-20")
    add_campaign(root, SHEET_SW, "2022-04-11", "61003", downloaded="2025-11-21")
    store = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="local")
    settings = AppSettings(offline=offline, basemaps=(), stores=(store,))
    paths = local_paths(tmp_path)
    initialize(paths.index_file)
    registry = load_registry(cache_dir=paths.cache_dir)
    with IndexWriter(paths.index_file) as writer:
        writer.write_area(AREA)
        writer.sync_stores({STORE: {"kartograf": root}})
        scan_store(registry.adapter("kartograf"), writer, settings, STORE, mode="full")
        if report:
            kept = stand_in_report(datetime.now(UTC) - timedelta(days=2))
            writer.write_availability(AREA.id, kept, product="dem", job_id=None)
    return settings


def open_area(page: Page, served: Served, product: str) -> Locator:
    """Open the map on the area; return „U źródła” with ``product`` chosen."""
    query = urlencode({"view": "map", "area_id": AREA.id, "product": "nmt"})
    fragment = urlsplit(served.token_url()).fragment
    page.goto(f"{served.base}/?{query}#{fragment}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    step = page.get_by_role("region", name="U źródła")
    step.get_by_label("Produkt u źródła").select_option(product)
    return step


def call(page: Page, path: str) -> Any:
    """Return the JSON answer of a ``GET`` made with the page's session."""
    answer: dict[str, Any] = page.evaluate(API, ["GET", path])
    assert answer["status"] == 200, answer
    return answer["body"]


def stamp(checked_at: str) -> str:
    """Return a report's date as the page writes it (Warsaw time)."""
    moment = datetime.fromisoformat(checked_at).astimezone(WARSAW)
    return moment.strftime("%Y.%m.%d %H:%M")


def variant_texts(variant: Locator) -> tuple[str, str, str]:
    """Return a variant's dimensions, label (or ``""``) and badge, as shown."""
    label = variant.locator(".src-label")
    return (
        variant.locator(".src-dims").inner_text(),
        label.inner_text() if label.count() else "",
        variant.locator(".local").inner_text(),
    )


def shot(page: Page, shown: Locator, name: str) -> None:
    """Keep a picture of the page when ``ARCHIWISTA_SCREENSHOTS`` names a directory."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        shown.scroll_into_view_if_needed()
        page.screenshot(path=str(Path(directory) / f"{name}.png"))


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register the stand-in here and for the server's workers."""
    register_standin(monkeypatch)


@pytest.mark.usefixtures("standin")
def test_rows_show_labels_plural_forms_chips_and_badges_as_text(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Each year's label, best variant, badge and chip; the chip by keyboard."""
    # Arrange
    served = serve(kept_store(tmp_path, offline=False, report=True))
    page = tab.page

    # Act
    step = open_area(page, served, PRODUCT)
    rows = step.get_by_role("list", name="Lata u źródła").locator("> li")

    # Assert: years in the report's order, each with its label and badge;
    # PL-1992 · 1m is every year's best variant.
    expect(rows).to_have_count(6)
    expected = [
        ("2023", "pełne", "pobrane", "+2 warianty"),
        ("2022", "pełne · 5 kampanii", "pobrane 1/5", None),
        ("2021", "pełne · 22 kampanie", "niepobrane", "+5 wariantów"),
        ("2020", "pełne · 25 kampanii", "niepobrane", "+1 wariant"),
        ("2019", "częściowe · <1% · 5 ark. niepełnych", "niepobrane", None),
        ("2018", "częściowe · 99% · 1 ark. niepełny", "niepobrane", None),
    ]
    for row, (year, label, badge, chips) in zip(rows.all(), expected, strict=True):
        best = row.locator(".src-variant").first
        expect(row.locator(".src-year")).to_have_text(year)
        expect(row.locator(".src-row-head .src-label")).to_have_text(label)
        assert variant_texts(best) == ("PL-1992 · 1m · EVRF2007", "", badge)
        more = row.locator(".src-more")
        expect(more).to_have_count(0 if chips is None else 1)
        if chips is not None:
            expect(more).to_have_text(chips)
            expect(more).to_have_attribute("aria-expanded", "false")
    first = rows.nth(0).locator(".src-variant").first
    expect(first.locator(".fmt")).to_have_text(["ASC", "ASCII-NMT"])
    expect(first.locator(".fmt").first).to_have_attribute("title", "format domyślny")
    expect(first).to_contain_text("265,0 MB")
    expect(rows.nth(1).locator(".src-variant")).to_contain_text("rozmiar nieznany")

    # Act: from the year, Tab passes the label's technical value to the chip.
    chip = rows.nth(0).get_by_role("button", name="+2 warianty")
    rows.nth(0).locator(".src-year").click()
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")
    expect(chip).to_be_focused()
    outline = chip.evaluate("(element) => getComputedStyle(element).outlineStyle")
    page.keyboard.press("Enter")

    # Assert: the focus ring shows and the other variants open, best first.
    assert outline == "solid"
    expect(chip).to_have_attribute("aria-expanded", "true")
    others = step.get_by_role("list", name="Pozostałe warianty roku 2023")
    expect(others.locator("> li")).to_have_count(2)
    assert [variant_texts(item) for item in others.locator("> li").all()] == [
        ("PL-2000 · 1m · EVRF2007", "pełne · 2 kampanie", "niepobrane"),
        ("PL-1992 · 5m · EVRF2007", "częściowe · 40% · 2 ark. niepełne", "pobrane 1/3"),
    ]  # fmt: skip
    shot(page, rows.nth(0), "07-wiersze-u-zrodla")
    page.keyboard.press("Tab")
    expect(first.get_by_role("button", name="Pobierz…")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Space")
    expect(chip).to_have_attribute("aria-expanded", "false")
    expect(others).to_have_count(0)

    # Act: the other years' variants, by the chips.
    rows.nth(2).get_by_role("button", name="+5 wariantów").click()
    rows.nth(3).get_by_role("button", name="+1 wariant").click()

    # Assert: the larger share first; every label and badge is text, the
    # ring beside a badge is decoration (colour is never the only carrier).
    labels = step.get_by_role("list", name="Pozostałe warianty roku 2021")
    expect(labels.locator(".src-label")).to_have_text(
        [f"częściowe · {percent}%" for percent in (90, 80, 70, 60, 50)]
    )
    expect(
        step.get_by_role("list", name="Pozostałe warianty roku 2020").locator(
            ".src-label"
        )
    ).to_have_text(["częściowe · 30%"])
    for item in step.locator(".src-label, .local").all():
        expect(item).to_be_visible()
        assert item.inner_text().strip()
    rings = step.locator(".local .ring")
    expect(step.locator(".local .ring[aria-hidden='true']")).to_have_count(
        rings.count()
    )
    tab.assert_clean()


@pytest.mark.usefixtures("standin")
def test_check_again_asks_the_source_with_force(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A two-day-old report is asked again; the source's answer replaces it."""
    # Arrange
    served = serve(kept_store(tmp_path, offline=False, report=True))
    page = tab.page
    step = open_area(page, served, PRODUCT)
    rows = step.get_by_role("list", name="Lata u źródła").locator("> li")
    expect(rows).to_have_count(6)
    query = f"area_id={AREA.id}&producer=standin&product=dem&store={STORE}"
    kept = call(page, f"/availability?{query}")["checked_at"]
    expect(step).to_contain_text(f"Raport z {stamp(kept)}")

    # Act
    step.get_by_role("button", name="Sprawdź ponownie").click()

    # Assert: one forced job, and the stand-in's own rows from its answer.
    expect(rows).to_have_count(2)
    jobs = call(page, "/jobs?kind=availability")["items"]
    assert [(job["state"], job["params"]["force"]) for job in jobs] == [
        ("succeeded", True)
    ]
    fresh = call(page, f"/availability?{query}")
    assert fresh["job_id"] == jobs[0]["id"]
    assert fresh["checked_at"] > kept
    expect(step).to_contain_text(f"Raport z {stamp(fresh['checked_at'])}")
    expect(rows.nth(0).locator(".src-row-head")).to_contain_text("pełne")
    expect(rows.nth(0).get_by_role("button", name="+1 wariant")).to_be_visible()
    expect(rows.nth(1).locator(".src-row-head .src-label")).to_have_text(
        "częściowe · 58% · 1 ark. niepełny"
    )
    tab.assert_clean()


def test_offline_without_a_report_shows_the_banner_and_the_local_share(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """No report and no network: the source step points to the store's share."""
    # Arrange
    served = serve(kept_store(tmp_path, offline=True, report=False))
    page = tab.page

    # Act
    step = open_area(page, served, "kartograf/nmt")

    # Assert: the banner and the reason at the source, no check and no job.
    expect(step).to_contain_text("Brak sieci — pokazuję tylko magazyn.")
    expect(step).to_contain_text(
        "Archiwista nie ma raportu źródła dla tego obszaru i produktu, a bez sieci"
        " go nie sprawdzi. Co z obszaru jest już w magazynie, pokazuje krok „Stan"
        " lokalny”."
    )
    expect(step.get_by_role("button", name="Sprawdź u źródła")).to_be_disabled()
    expect(step.get_by_role("button", name="Sprawdź ponownie")).to_have_count(0)
    expect(step.locator(".local")).to_have_count(0)

    # Assert: that step shows the share of the same product in the store,
    # partial (three of the four sheets), as the server measures it.
    local = page.get_by_role("region", name="Stan lokalny")
    share = local.locator(".coverage-row .local")
    expect(share).to_have_count(1)
    coverage = call(
        page, f"/local-coverage?area_id={AREA.id}&product=nmt&store={STORE}"
    )
    (result,) = coverage["results"]
    assert 0 < result["percent"] < 100, result
    expect(share).to_have_text(result["label"])
    expect(local.locator(".coverage-row")).to_contain_text("Polska")
    assert call(page, "/jobs?kind=availability")["items"] == []
    assert tab.foreign_requests(served.base) == []
    shot(page, step, "08-offline-lokalnie")
    tab.assert_clean()
