"""From an area on the map to files in the store, in Chromium (plan A10, A11).

The stand-in producer (``tests/fixtures/action_source``) serves the store
``pomiary`` (its Kartograf directory is the stand-in's) and its workers run as
``ACTION_WORKER``; the index keeps the area ``AREA``. The step „U źródła” of
the map's panel asks the source for the stand-in's product, shows a row per
year with its label, variant, badge and the chip of the other variants, and
„Pobierz…” opens the plan window: the lines of the variant (one in 2023, three
in 2022) are checked by one ``check`` job, the plans' counts, size, positions
and lines are shown, and one download runs those plans with its progress and
files (ADR-044). A session without the permission to write the stores sees
the plan with the action disabled and the reason; offline mode keeps the
report and disables what needs the network.
Downloads go on in the background (ADR-043): while the store holds the
stand-in's ``HOLD`` a run waits after its first file, its window is closed or
minimised, the map pans and zooms, the Catalog opens and the page reloads,
and the top bar's „Pobieranie” follows the session's downloads all along,
lists them with their files at the end and toasts each end; a download stops
only by its „Anuluj pobieranie”.
With ``ARCHIWISTA_SCREENSHOTS=<directory>`` the steps keep screenshots there,
the local paths covered (``docs/reports/v0.3-screenshots/``).
"""

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexWriter
from archiwista.jobs import JobSupervisor
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.fixtures.actions import ACTION_WORKER, standin_in_settings
from tests.fixtures.availability import AREA, register_standin
from tests.fixtures.browser import Served, Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.permissions import add_people, principal

Serve = Callable[..., Served]

STORE = "pomiary"
PRODUCT = "standin/dem"
WAIT_S = 60.0
FINISHED = ("succeeded", "partial", "failed", "interrupted", "cancelled")
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
# Covers the text of local paths (the store root in the window and in the
# producer's line) for a screenshot. Through the CSSOM: the CSP allows no
# injected stylesheet.
COVER_PATHS = """(cover) => {
  for (const path of document.querySelectorAll("code.path")) {
    path.style.color = cover ? "transparent" : "";
    path.style.background = cover ? "#d0d5dd" : "";
  }
}"""
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""
# A call of the stand-in no plan window starts: a download of the session as
# another tab would start it.
OTHER_LINE = "series fetch --station 150160180 --kind hydro"
# The stations of the three lines of 2022's variant.
ROW_STATIONS = ("150160200", "150160210", "150160220")
# The address follows the map: its centre moved and it zoomed in.
MOVED = """([center, zoom]) => {
  const query = new URLSearchParams(location.search);
  return query.get("center") !== center && Number(query.get("zoom")) > zoom;
}"""


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in; the server's workers give it the store's directory."""
    worker_path(monkeypatch)
    module = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", ACTION_WORKER)
    return module


def serve_store(serve: Serve, tmp_path: Path) -> Served:
    """Serve the stand-in's store ``pomiary`` online, with the area kept."""
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    served = serve(AppSettings(offline=False, basemaps=(), stores=(store,)))
    with IndexWriter(served.paths.index_file) as writer:
        writer.write_area(AREA)
    return served


def open_area(page: Page, served: Served, url: str) -> Locator:
    """Open the map on the area with the session of ``url``; return „U źródła”."""
    query = urlencode({"view": "map", "area_id": AREA.id})
    page.goto(f"{served.base}/?{query}#{urlsplit(url).fragment}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    step = page.get_by_role("region", name="U źródła")
    step.get_by_label("Produkt u źródła").select_option(PRODUCT)
    return step


def check_at_source(step: Locator) -> Locator:
    """Ask the source and return the rows of its report."""
    step.get_by_role("button", name="Sprawdź u źródła").click()
    rows = step.get_by_role("list", name="Lata u źródła").locator("> li")
    expect(rows).to_have_count(2)
    return rows


def open_plan(page: Page, row: Locator, positions: str = "4 pozycje") -> Locator:
    """Open the plan window of a row's best variant and wait for its plan."""
    row.get_by_role("button", name="Pobierz…").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text(positions)
    return dialog


def call(page: Page, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    assert answer["status"] in (200, 202), answer
    return answer["body"]


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.evaluate(COVER_PATHS, True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))
        page.evaluate(COVER_PATHS, False)


def plan_window(page: Page, year: int) -> Locator:
    """Return the plan window of a year's best variant, planned or started."""
    return page.get_by_role(
        "dialog", name=re.compile(rf"^(Pobrać\?|Pobieranie) dem · {year} ")
    )


def indicator(page: Page) -> Locator:
    """Return the top bar's „Pobieranie”: the session's downloads together."""
    top = page.get_by_role("banner")
    return top.get_by_role("button", name=re.compile(r"^(Pobieranie|Pobrano) \d"))


def downloads(page: Page) -> Locator:
    """Return the downloads listed under the indicator, newest first."""
    panel = page.get_by_role("dialog", name="Pobrania w tle")
    return panel.get_by_role("list", name="Pobrania w tle").locator("> li")


def pan_and_zoom(page: Page) -> None:
    """Drag the map and zoom it in with the wheel; wait for the address to follow."""
    page.wait_for_function("() => new URLSearchParams(location.search).has('zoom')")
    before = parse_qs(urlsplit(page.url).query)
    box = page.locator(".maplibregl-canvas").bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 120, y + 60, steps=8)
    page.mouse.up()
    page.mouse.wheel(0, -600)
    page.wait_for_function(MOVED, arg=[before["center"][0], float(before["zoom"][0])])


def test_a_variant_of_a_row_is_planned_and_downloaded(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Row → plan window (counts, size, positions, line) → download → its files."""
    # Arrange
    served = serve_store(serve, tmp_path)
    page = tab.page
    step = open_area(page, served, served.token_url())

    # Act: the source's rows, the best variant of 2023 and the others.
    rows = check_at_source(step)
    first = rows.nth(0)
    first.get_by_role("button", name="+1 wariant").click()

    # Assert
    expect(first).to_contain_text("2023")
    expect(first).to_contain_text("pełne")
    expect(first.locator(".src-variant").first).to_contain_text(
        "PL-2000 · 1m · EVRF2007"
    )
    expect(first.locator(".src-variant").first).to_contain_text("rozmiar nieznany")
    expect(first.locator(".src-variant").first).to_contain_text("niepobrane")
    others = first.get_by_role("list", name="Pozostałe warianty roku 2023")
    expect(others).to_contain_text("pełne · 2 kampanie")
    expect(others).to_contain_text("PL-1992 · 1m · EVRF2007")
    expect(rows.nth(1)).to_contain_text("2022")
    expect(rows.nth(1)).to_contain_text("częściowe · 58% · 1 ark. niepełny")
    step.scroll_into_view_if_needed()
    shot(page, "01-u-zrodla")

    # Act: the plan of the best variant.
    dialog = open_plan(page, first)

    # Assert: what the stand-in planned, the unknown size never 0.
    expect(dialog).to_have_accessible_name(
        "Pobrać? dem · 2023 · PL-2000 · 1m · EVRF2007 · obszar Kraków"
    )
    expect(dialog).to_contain_text(
        "4 pozycje: aktualne 1, nowsze u źródła 1, brak w magazynie 1,"
        " nie do sprawdzenia 1"
    )
    expect(dialog).to_contain_text("Do pobrania: 2")
    expect(dialog).to_contain_text("rozmiar co najmniej 5,4 kB")
    positions = dialog.get_by_role("table", name="Pozycje planu").locator("tbody tr")
    expect(positions).to_have_count(4)
    expect(positions.nth(1)).to_contain_text("hydro/150160190/2024.csv")
    expect(positions.nth(1)).to_contain_text("nowsze u źródła")
    expect(positions.nth(2)).to_contain_text("brak w magazynie")
    expect(positions.nth(2)).to_contain_text("nieznany")
    expect(dialog.locator(".cmd code")).to_contain_text(
        "series fetch --station 150160190 --kind hydro --root"
    )
    shot(page, "02-okno-planu")

    # Act: the download waits after its first file while the store holds HOLD.
    hold = tmp_path / STORE / standin.HOLD
    hold.touch()
    dialog.get_by_role("button", name="Pobierz 2 pozycje").click()
    expect(dialog.locator(".job-progress")).to_contain_text("1 z 2")
    shot(page, "03-pobieranie")
    hold.unlink()

    # Assert: the run fetched the plan's two positions, no more.
    expect(dialog).to_contain_text(
        "Pliki: 2 (nowe 2, bez zmian 0, z nową etykietą 0); jednostki z błędem: 0."
    )
    files = dialog.get_by_role("list", name="Pliki w magazynie").locator("> li")
    expect(files).to_have_count(2)
    expect(files.nth(0)).to_contain_text("hydro/150160190/2024.csv")
    expect(files.nth(0)).to_contain_text("nowe")
    shot(page, "04-pliki")
    folder = tmp_path / STORE / "hydro" / "150160190"
    assert sorted(path.name for path in folder.iterdir()) == ["2024.csv", "2025.csv"]
    dialog.get_by_role("button", name="Zamknij").click()
    expect(dialog).to_be_hidden()
    tab.assert_clean()


def test_a_row_of_several_lines_is_one_check_and_one_download(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """The three lines of 2022: one check, one download, one in the top bar."""
    # Arrange: the run waits after its first file while the store holds HOLD.
    served = serve_store(serve, tmp_path)
    page = tab.page
    rows = check_at_source(open_area(page, served, served.token_url()))
    hold = tmp_path / STORE / standin.HOLD
    hold.touch()

    # Act: the plan window of the row.
    dialog = open_plan(page, rows.nth(1), "12 pozycji")

    # Assert: one check of the three lines; their plans together, each line.
    (check,) = call(page, "GET", "/jobs?kind=check")["items"]
    planned = [item["options"]["station"] for item in check["params"]["calls"]]
    assert planned == list(ROW_STATIONS)
    expect(dialog).to_contain_text(
        "12 pozycji: aktualne 3, nowsze u źródła 3, brak w magazynie 3,"
        " nie do sprawdzenia 3"
    )
    expect(dialog).to_contain_text("Do pobrania: 6")
    expect(dialog).to_contain_text("rozmiar co najmniej 16,2 kB")
    positions = dialog.get_by_role("table", name="Pozycje planu").locator("tbody tr")
    expect(positions).to_have_count(12)
    lines = dialog.locator(".cmd code")
    expect(lines).to_have_count(3)
    for place, station in enumerate(ROW_STATIONS):
        expect(lines.nth(place)).to_contain_text(f"--station {station} --kind hydro")

    # Act: one download of the three plans.
    dialog.get_by_role("button", name="Pobierz 6 pozycji").click()
    expect(dialog.locator(".job-progress")).to_contain_text("polecenie 1 z 3 · 1 z 2")

    # Assert: one job in the top bar, a sixth of the row done.
    expect(indicator(page)).to_have_text("Pobieranie 0/1 · 16%")
    (download,) = call(page, "GET", "/jobs?kind=download")["items"]
    assert download["params"] == {**check["params"], "plan_job": check["id"]}

    # Act
    hold.unlink()

    # Assert: the six files of the three lines, one download ended.
    expect(dialog).to_contain_text(
        "Pliki: 6 (nowe 6, bez zmian 0, z nową etykietą 0); jednostki z błędem: 0."
    )
    expect(indicator(page)).to_have_text("Pobrano 1/1")
    indicator(page).click()
    expect(downloads(page)).to_have_count(1)
    for station in ROW_STATIONS:
        folder = tmp_path / STORE / "hydro" / station
        assert sorted(path.name for path in folder.iterdir()) == [
            "2024.csv",
            "2025.csv",
        ]
    assert len(call(page, "GET", "/jobs?kind=check")["items"]) == 1
    tab.assert_clean()


def test_a_session_that_may_not_write_sees_the_download_disabled_with_its_reason(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """The plan needs no permission; the download needs `store_write` and says so."""
    # Arrange
    served = serve_store(serve, tmp_path)
    state = StateStore(served.paths.state_file)
    add_people(state)
    issued = issue_one_time_token(
        served.paths.index_file, "startup", minted_by=principal(state, "other")
    )
    page = tab.page
    step = open_area(page, served, fragment_url(served.server.port, issued.token))

    # Act
    dialog = open_plan(page, check_at_source(step).nth(0))

    # Assert
    expect(dialog).to_contain_text("Do pobrania: 2")
    expect(dialog.get_by_role("button", name="Pobierz 2 pozycje")).to_be_disabled()
    expect(dialog).to_contain_text(
        "Pobieranie zapisuje magazyn, a ta sesja nie ma uprawnienia „zapis do"
        " magazynu” (rola store_writer). Plan można obejrzeć."
    )
    shot(page, "05-bez-uprawnienia")
    assert call(page, "GET", "/jobs?kind=download")["items"] == []
    tab.assert_clean()


def test_offline_mode_keeps_the_report_and_disables_the_network_actions(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """A kept report still shows with its rows; checking and downloading do not."""
    # Arrange: a report kept online, then offline mode.
    served = serve_store(serve, tmp_path)
    page = tab.page
    open_area(page, served, served.token_url())
    job = call(
        page,
        "POST",
        "/availability",
        {"area_id": AREA.id, "producer": "standin", "product": "dem", "store": STORE},
    )
    deadline = time.monotonic() + WAIT_S
    while call(page, "GET", f"/jobs/{job['id']}")["state"] not in FINISHED:
        assert time.monotonic() < deadline, "the availability job did not end"
        page.wait_for_timeout(200)
    current = call(page, "GET", "/settings")
    call(page, "PUT", "/settings", {**current, "offline": True})

    # Act
    page.reload()
    step = page.get_by_role("region", name="U źródła")
    step.get_by_label("Produkt u źródła").select_option(PRODUCT)

    # Assert
    expect(step).to_contain_text("Brak sieci — pokazuję tylko magazyn.")
    rows = step.get_by_role("list", name="Lata u źródła").locator("> li")
    expect(rows).to_have_count(2)
    expect(rows.nth(0).get_by_role("button", name="Pobierz…")).to_be_disabled()
    expect(step.get_by_role("button", name="Sprawdź ponownie")).to_have_count(0)
    step.scroll_into_view_if_needed()
    shot(page, "06-offline")
    tab.assert_clean()


def test_downloads_go_on_in_the_background_across_views_and_a_reload(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Windows closed and minimised mid-run; map, Catalog, reload; the top bar."""
    # Arrange: the runs wait after their first file while the store holds HOLD.
    served = serve_store(serve, tmp_path)
    page = tab.page
    rows = check_at_source(open_area(page, served, served.token_url()))
    hold = tmp_path / STORE / standin.HOLD
    hold.touch()

    # Act: the first download starts and its window closes while it runs.
    first = open_plan(page, rows.nth(0))
    first.get_by_role("button", name="Pobierz 2 pozycje").click()
    expect(first.locator(".job-progress")).to_contain_text("1 z 2")
    first.get_by_role("button", name="Zamknij").click()

    # Assert: nothing cancelled it; the top bar follows it.
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(indicator(page)).to_have_text("Pobieranie 0/1 · 50%")

    # Act: a second one from the other row, its three lines in one download;
    # its window is minimised, shown again from the list and minimised again.
    open_plan(page, rows.nth(1), "12 pozycji")
    second = plan_window(page, 2022)
    second.get_by_role("button", name="Pobierz 6 pozycji").click()
    expect(second.locator(".job-progress")).to_contain_text("polecenie 1 z 3 · 1 z 2")
    second.get_by_role("button", name="Zwiń").click()
    expect(second).to_be_hidden()
    expect(indicator(page)).to_be_focused()
    # The share of the row: half the units of the first of its three lines.
    expect(indicator(page)).to_have_text("Pobieranie 0/2 · 33%")
    indicator(page).click()
    listed = downloads(page)
    expect(listed).to_have_count(2)
    expect(listed.nth(0)).to_contain_text("dem · 2022")
    expect(listed.nth(1)).to_contain_text("dem · 2023")
    listed.nth(0).get_by_role("button", name="Pokaż okno planu").click()
    expect(second.locator(".job-progress")).to_contain_text("polecenie 1 z 3 · 1 z 2")
    second.get_by_role("button", name="Zwiń").click()
    expect(second).to_be_hidden()

    # Act: the map pans and zooms, the Catalog opens, the map comes back.
    pan_and_zoom(page)
    nav = page.get_by_role("navigation", name="Widoki")
    nav.get_by_role("link", name="Katalog").click()
    expect(page).to_have_url(re.compile(r"view=catalog"))
    expect(indicator(page)).to_have_text("Pobieranie 0/2 · 33%")
    page.go_back()
    expect(page).to_have_url(re.compile(r"view=map&area_id="))
    expect(page.get_by_role("region", name="U źródła")).to_be_visible()

    # Act: a third download of the session starts elsewhere (the API, as
    # another tab would) and waits behind the two; then the page reloads.
    line = {"producer": "standin", "line": OTHER_LINE}
    other = call(page, "POST", "/commands/parse", line)
    calls = [{"command": other["command"], "options": other["options"]}]
    body = {"kind": "download", "producer": "standin", "store": STORE, "calls": calls}
    third = call(page, "POST", "/jobs", body)
    page.reload()

    # Assert: the session's three downloads are back, named as before.
    expect(indicator(page)).to_have_text("Pobieranie 0/3 · 22%")
    indicator(page).click()
    expect(listed).to_have_count(3)
    expect(listed.nth(0)).to_contain_text("standin · series fetch")
    expect(listed.nth(0)).to_contain_text("Pobranie: w kolejce")
    expect(listed.nth(1)).to_contain_text("dem · 2022")
    expect(listed.nth(1).locator(".job-progress")).to_contain_text("polecenie 1 z 3")
    expect(listed.nth(2)).to_contain_text("dem · 2023")
    expect(listed.nth(2).locator(".job-progress")).to_contain_text("1 z 2")
    assert call(page, "GET", f"/jobs/{third['id']}")["state"] == "queued"
    shot(page, "13-pobieranie-w-tle")
    page.keyboard.press("Escape")
    expect(indicator(page)).to_be_focused()

    # Act: the store lets the runs go on.
    hold.unlink()

    # Assert: a toast at each end; the files are in the list of the indicator.
    toasts = page.get_by_role("status", name="Powiadomienia o pobieraniu")
    expect(toasts).to_contain_text("Pobrano: dem · 2023")
    expect(toasts).to_contain_text("Pobrano: dem · 2022")
    expect(toasts).to_contain_text("Pobrano: standin · series fetch")
    expect(indicator(page)).to_have_text("Pobrano 3/3")
    indicator(page).click()
    expect(listed.nth(2)).to_contain_text(
        "Pliki: 2 (nowe 2, bez zmian 0, z nową etykietą 0); jednostki z błędem: 0."
    )
    files = listed.nth(2).get_by_role("list", name="Pliki w magazynie").locator("> li")
    expect(files).to_have_count(2)
    expect(files.nth(0)).to_contain_text("hydro/150160190/2024.csv")
    expect(files.nth(1)).to_contain_text("hydro/150160190/2025.csv")
    expect(listed.nth(1)).to_contain_text(
        "Pliki: 6 (nowe 6, bez zmian 0, z nową etykietą 0); jednostki z błędem: 0."
    )
    expect(listed.nth(0)).to_contain_text("Pliki: 4 (nowe 4")
    for station in ("150160190", *ROW_STATIONS):
        folder = tmp_path / STORE / "hydro" / station
        names = sorted(path.name for path in folder.iterdir())
        assert names == ["2024.csv", "2025.csv"], station
    tab.assert_clean()


def test_a_download_stops_only_by_its_cancel(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """`Esc` closes a run's window, not the run; its cancel in the list stops it."""
    # Arrange: a run held after its first file.
    served = serve_store(serve, tmp_path)
    page = tab.page
    rows = check_at_source(open_area(page, served, served.token_url()))
    hold = tmp_path / STORE / standin.HOLD
    hold.touch()
    dialog = open_plan(page, rows.nth(0))
    dialog.get_by_role("button", name="Pobierz 2 pozycje").click()
    expect(dialog.locator(".job-progress")).to_contain_text("1 z 2")
    (download,) = call(page, "GET", "/jobs?kind=download")["items"]

    # Act
    page.keyboard.press("Escape")

    # Assert: the window is closed, the run goes on.
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(indicator(page)).to_have_text("Pobieranie 0/1 · 50%")
    assert call(page, "GET", f"/jobs/{download['id']}")["state"] == "running"

    # Act
    indicator(page).click()
    downloads(page).nth(0).get_by_role("button", name="Anuluj pobieranie").click()

    # Assert: cancelled, with the file it fetched kept.
    toasts = page.get_by_role("status", name="Powiadomienia o pobieraniu")
    expect(toasts).to_contain_text("Pobieranie anulowane: dem · 2023")
    expect(indicator(page)).to_have_text("Pobrano 0/1")
    expect(downloads(page).nth(0)).to_contain_text("Pobranie: anulowane")
    assert call(page, "GET", f"/jobs/{download['id']}")["state"] == "cancelled"
    folder = tmp_path / STORE / "hydro" / "150160190"
    assert sorted(path.name for path in folder.iterdir()) == ["2024.csv"]
    hold.unlink()
    tab.assert_clean()
