"""From an area on the map to files in the store, in Chromium (plan 2026-10-25, A10, A11).

The stand-in producer (``tests/fixtures/action_source``) serves the store
``pomiary`` (its Kartograf directory is the stand-in's) and its workers run as
``ACTION_WORKER``; the index keeps the area ``AREA``. The step „U źródła” of
the map's panel asks the source for the stand-in's product, shows a row per
year with its label, variant, badge and the chip of the other variants, and
„Pobierz…” opens the plan window: the line of the variant is checked by a
``check`` job, the plan's counts, size and positions are shown, and the
download runs that plan with its progress and files. A session without the
permission to write the stores sees the plan with the action disabled and the
reason; offline mode keeps the report and disables what needs the network.
With ``ARCHIWISTA_SCREENSHOTS=<directory>`` the steps keep screenshots there,
the local paths covered (``docs/reports/v0.3-screenshots/``).
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlencode, urlsplit

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


def open_plan(page: Page, row: Locator) -> Locator:
    """Open the plan window of a row's best variant and wait for its plan."""
    row.get_by_role("button", name="Pobierz…").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text("4 pozycje")
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
    expect(first.locator(".src-variant").first).to_contain_text("PL-2000 · 1m · EVRF2007")
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
        "4 pozycje: aktualne 1, nowsze u źródła 1, brak w magazynie 1, nie do sprawdzenia 1"
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
