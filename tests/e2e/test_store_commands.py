"""Obserwator's commands from the Store view to a download (plan 2026-11-05 A4).

„Polecenia producenta” of the Store view is a form read from Obserwator's
catalog (Polish texts): ``store sync`` with the dataset ``pl.imgw.hydro_daily``
and the years typed in, checked against the store without the network, opens
the plan window of the line Obserwator writes, whose root is the store's.
The plan and the run go to Obserwator in the server's workers, with IMGW-PIB
stood in for by Obserwator's own fixture archives
(``tests.fixtures.obserwator_worker``). A store of only Kartograf has no such
section: Kartograf's downloads start from an area on the map. Pasted into
„Wklej polecenie producenta” of the map, the same line ignores the area of
step 1 it was only offered.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from kartograf.testing import build_fixture_store
from playwright.sync_api import expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.jobs import JobSupervisor
from tests.e2e.test_pasted_command import action_jobs, open_step, paste
from tests.fixtures.browser import Served, Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.obserwator_worker import OBSERWATOR_WORKER

Serve = Callable[..., Served]

STORE = "imgw"
LINE = "obserwator store sync --datasets pl.imgw.hydro_daily --years 2023,2024"


@pytest.fixture
def observed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the server's workers Obserwator with IMGW-PIB stood in for."""
    pytest.importorskip("obserwator")
    worker_path(monkeypatch)
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", OBSERWATOR_WORKER)


def serve_imgw(serve: Serve, tmp_path: Path) -> Served:
    """Serve an empty Obserwator store ``imgw`` online."""
    root = tmp_path / "obserwator"
    root.mkdir()
    store = StoreConfig(id=STORE, name="Dane IMGW", obserwator=root, kind="local")
    return serve(AppSettings(offline=False, basemaps=(), stores=(store,)))


def test_store_commands_form_plans_and_downloads_imgw_archives(
    serve: Serve, tab: Tab, tmp_path: Path, observed: None
) -> None:
    """Form → plan of the line Obserwator writes → a download of what it showed."""
    # Arrange
    served = serve_imgw(serve, tmp_path)
    page = tab.page
    page.goto(f"{served.base}/?view=store#{served.token_url().split('#', 1)[1]}")
    section = page.get_by_role("region", name="Polecenia producenta")
    expect(section).to_be_visible()

    # Act
    section.get_by_label("Polecenie").select_option(label="obserwator · store sync")
    datasets = section.get_by_role("group", name="datasets")
    datasets.get_by_role("checkbox", name=re.compile(r"pl\.imgw\.hydro_daily$")).check()
    section.get_by_label("years").fill("2023, 2024")
    section.get_by_role("button", name="Zaplanuj…").click()
    dialog = page.get_by_role("dialog")

    # Assert: the plan of both national archives and the series, in this store.
    expect(dialog).to_have_accessible_name("Pobrać? obserwator · store sync")
    expect(dialog).to_contain_text("brak w magazynie 3")
    line = dialog.locator(".cmd code")
    expect(line).to_contain_text(f"--root {tmp_path / 'obserwator'}")
    expect(line).to_contain_text("--datasets pl.imgw.hydro_daily")

    # Act
    dialog.get_by_role("button", name="Pobierz 3 pozycje").click()

    # Assert
    expect(dialog).to_contain_text("Pliki: 3 (nowe 3")
    by_kind = {job["kind"]: job for job in action_jobs(page)}
    assert sorted(by_kind) == ["check", "download"]
    assert by_kind["download"]["params"]["plan_job"] == by_kind["check"]["id"]
    archives = tmp_path / "obserwator" / "archives" / "versions"
    assert len(list(archives.rglob("codz_*.zip"))) == 2
    tab.assert_clean()


def test_store_commands_section_absent_for_a_kartograf_store(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Kartograf's data are chosen by an area: its store offers no such form."""
    built = build_fixture_store(tmp_path / "kartograf")
    store = StoreConfig(id="zespol", name="Zespół", kartograf=built.root, kind="local")
    served = serve(AppSettings(offline=True, basemaps=(), stores=(store,)))
    page = tab.page

    page.goto(f"{served.base}/?view=store#{served.token_url().split('#', 1)[1]}")

    expect(page.get_by_role("heading", name="Stan")).to_be_visible()
    expect(page.get_by_role("region", name="Polecenia producenta")).to_have_count(0)
    tab.assert_clean()


def test_pasted_obserwator_line_ignores_the_offered_area(
    serve: Serve, tab: Tab, tmp_path: Path, observed: None
) -> None:
    """The map's „Wklej polecenie producenta” plans a line that takes no area."""
    served = serve_imgw(serve, tmp_path)
    page = tab.page
    step = open_step(page, served, served.token_url())

    paste(step, LINE)

    dialog = page.get_by_role("dialog")
    expect(dialog).to_have_accessible_name("Pobrać? obserwator · store sync")
    expect(dialog).to_contain_text("brak w magazynie 3")
