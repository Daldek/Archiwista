"""A pasted command to its plan and to a project's task, in Chromium (plan A11).

UC-15: „Wklej polecenie producenta” in the step „U źródła” reads a line with
the producer's own parser and checks it without the network against the
target store, with or without an area. A line the producer refuses shows the
producer's text at the field and starts nothing; a valid one opens the plan
window of the variants (no format to choose) with the target store in place
of the line's own root. With the stand-in producer
(``tests/fixtures/action_source``) online the line is planned and downloaded;
the stand-in changes no projects, so „Dodaj jako zadanie projektu” is
disabled with its reason. Offline, over Kartograf's fixture store and project
(``kartograf.testing``), Kartograf checks a Kartograf line without the
network, the plan's check is refused (``409 offline_mode``), and the line is
added as a task of the project through Kartograf's own validation: a name
Kartograf refuses shows at the name field first. A person the project is
shared with, who may not change it, sees the option disabled with the
reason. With ``ARCHIWISTA_SCREENSHOTS=<directory>`` the steps keep
screenshots there (``docs/reports/v0.3-screenshots/``).
"""

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import kartograf
import pytest
from kartograf.testing import build_fixture_store, build_project
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.jobs import JobSupervisor
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.fixtures.actions import ACTION_WORKER, standin_in_settings
from tests.fixtures.availability import register_standin
from tests.fixtures.browser import Served, Tab
from tests.fixtures.jobs import worker_path
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

STORE = "pomiary"
TEAM = "zespol"
STATION_LINE = "standin series fetch --station 150160190 --kind hydro"
# A box of 1 km² in PL-1992 cut into 1:10 000 sheets, checked without the
# network; `-o` names a directory of the computer it was copied from.
KARTOGRAF_LINE = (
    "kartograf elevation download --product nmt --country pl"
    " --bbox 500000,250000,501000,251000 --bbox-crs EPSG:2180 --sheet-system 1992"
    " --resolution 1m --vertical-crs EVRF2007 --year 2023 -o ./dane"
)
TASK = "teren-2023"
# The kinds of the jobs a plan window starts; the scheduler's scans are others.
ACTION_KINDS = ("check", "download", "project_download")
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
API = """async ([method, path]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch(`/api/v1${path}`, { method, headers });
  return { status: answer.status, body: await answer.json() };
}"""


@dataclass(frozen=True)
class Team:
    """Kartograf's fixture store ``zespol`` and its project, offline."""

    served: Served
    directory: Path
    key: str


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


def serve_standin(serve: Serve, tmp_path: Path) -> Served:
    """Serve the stand-in's store ``pomiary`` online."""
    root = tmp_path / STORE
    root.mkdir()
    store = StoreConfig(id=STORE, name="Pomiary", kartograf=root, kind="local")
    return serve(AppSettings(offline=False, basemaps=(), stores=(store,)))


def serve_team(serve: Serve, tmp_path: Path) -> Team:
    """Serve Kartograf's fixture store and project offline, the project indexed."""
    built = build_fixture_store(tmp_path / "nas" / "kartograf")
    projects = tmp_path / "nas" / "projekty"
    directory = build_project(projects / "raba", built)
    config = StoreConfig(id=TEAM, name="Zespół", kartograf=built.root, kind="local")
    settings = AppSettings(
        offline=True, basemaps=(), stores=(config,), project_dirs=(projects,)
    )
    paths = local_paths(tmp_path)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({TEAM: config.roots()})
        key = record_project(writer, directory, stores=settings.stores, geo=None)
    return Team(serve(settings), directory, key)


def open_step(page: Page, served: Served, url: str) -> Locator:
    """Open the map, no area chosen, with the session of ``url``; return „U źródła”."""
    page.goto(f"{served.base}/?view=map#{urlsplit(url).fragment}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    return page.get_by_role("region", name="U źródła")


def paste(step: Locator, line: str) -> None:
    """Paste a line into the step and ask for its plan."""
    step.get_by_label("Wklej polecenie producenta").fill(line)
    step.get_by_role("button", name="Zaplanuj…").click()


def call(page: Page, path: str) -> Any:
    """Return the JSON answer of a ``GET`` made with the page's session."""
    answer: dict[str, Any] = page.evaluate(API, ["GET", path])
    assert answer["status"] == 200, answer
    return answer["body"]


def action_jobs(page: Page) -> list[dict[str, Any]]:
    """Return the jobs of the kinds a plan window starts."""
    return [
        job
        for kind in ACTION_KINDS
        for job in call(page, f"/jobs?kind={kind}")["items"]
    ]


def described(page: Page, field: Locator) -> Locator:
    """Return the element a field names in ``aria-describedby``."""
    return page.locator(f"[id='{field.get_attribute('aria-describedby')}']")


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.evaluate(COVER_PATHS, True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))
        page.evaluate(COVER_PATHS, False)


def test_a_pasted_line_is_planned_in_the_target_store_and_downloaded(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Pasted line → the same plan window → a download of what the plan showed."""
    # Arrange
    served = serve_standin(serve, tmp_path)
    page = tab.page
    step = open_step(page, served, served.token_url())

    # Act: the line names a store root of another computer.
    paste(step, f"{STATION_LINE} --root /data/standin")
    dialog = page.get_by_role("dialog")

    # Assert: the stand-in's plan in the target store, its root in the line.
    expect(dialog).to_have_accessible_name("Pobrać? standin · series fetch")
    expect(dialog).to_contain_text(
        "4 pozycje: aktualne 1, nowsze u źródła 1, brak w magazynie 1,"
        " nie do sprawdzenia 1"
    )
    expect(dialog).to_contain_text("Do pobrania: 2")
    expect(dialog).to_contain_text("rozmiar co najmniej 5,4 kB")
    positions = dialog.get_by_role("table", name="Pozycje planu").locator("tbody tr")
    expect(positions.nth(2)).to_contain_text("nieznany")
    expect(dialog).not_to_contain_text("0 B")
    expect(dialog.get_by_role("group", name="Format")).to_have_count(0)
    line = dialog.locator(".cmd code")
    expect(line).to_contain_text(f"--root {tmp_path / STORE}")
    expect(line).not_to_contain_text("/data/standin")
    option = dialog.get_by_label("Dodaj jako zadanie projektu")
    expect(option).to_be_disabled()
    expect(described(page, option)).to_have_text(
        "W magazynie „Pomiary” nie ma projektu producenta standin; projekt zakłada"
        " administrator w widoku Projekty."
    )
    shot(page, "09-wklejone-polecenie")

    # Act
    dialog.get_by_role("button", name="Pobierz 2 pozycje").click()

    # Assert: one check and one download of the pasted call, its plan run.
    expect(dialog).to_contain_text(
        "Pliki: 2 (nowe 2, bez zmian 0, z nową etykietą 0); jednostki z błędem: 0."
    )
    by_kind = {job["kind"]: job for job in action_jobs(page)}
    assert sorted(by_kind) == ["check", "download"]
    options = {"station": "150160190", "kind": "hydro"}
    calls = [{"command": "series fetch", "options": options}]
    assert by_kind["check"]["params"]["calls"] == calls
    assert by_kind["download"]["params"]["calls"] == calls
    assert by_kind["download"]["params"]["plan_job"] == by_kind["check"]["id"]
    folder = tmp_path / STORE / "hydro" / "150160190"
    assert sorted(path.name for path in folder.iterdir()) == ["2024.csv", "2025.csv"]
    dialog.get_by_role("button", name="Zamknij").click()
    expect(dialog).to_be_hidden()
    tab.assert_clean()


@pytest.mark.parametrize(
    ("line", "text"),
    [
        (
            "standin series fetch --station",
            "expected --<option> <value>, got '--station'",
        ),
        (
            f"{STATION_LINE.removesuffix(' hydro')} river",
            "kind is one of hydro, meteo, not 'river'",
        ),
    ],
    ids=["unread", "refused"],
)
def test_a_line_the_producer_refuses_shows_its_text_at_the_field(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType, line: str, text: str
) -> None:
    """A line not read, or read and refused, says why at the field; no job, no plan."""
    # Arrange
    served = serve_standin(serve, tmp_path)
    page = tab.page
    step = open_step(page, served, served.token_url())
    field = step.get_by_label("Wklej polecenie producenta")

    # Act
    paste(step, line)

    # Assert
    expect(field).to_have_attribute("aria-invalid", "true")
    error = described(page, field)
    expect(error).to_contain_text(text)
    expect(error).to_have_attribute("role", "alert")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert action_jobs(page) == []

    # Act: a change of the line clears the error.
    field.press("End")
    field.press_sequentially(" ")

    # Assert
    expect(field).not_to_have_attribute("aria-invalid", "true")
    tab.assert_clean()


def test_offline_a_pasted_kartograf_line_becomes_a_task_of_the_project(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Kartograf checks the line offline, the plan is refused, the task is added."""
    # Arrange
    team = serve_team(serve, tmp_path)
    page = tab.page
    step = open_step(page, team.served, team.served.token_url())

    # Act
    paste(step, KARTOGRAF_LINE)
    dialog = page.get_by_role("dialog")

    # Assert: the check needs the network, the window still offers the task.
    expect(dialog).to_have_accessible_name("Pobrać? kartograf · elevation download")
    expect(dialog.get_by_role("alert")).to_contain_text(
        "Tryb offline jest włączony: to zadanie potrzebuje sieci"
    )
    expect(dialog.get_by_role("button", name="Pobierz")).to_be_disabled()
    option = dialog.get_by_label("Dodaj jako zadanie projektu")
    expect(option).to_be_enabled()

    # Act: a name Kartograf refuses first.
    option.check()
    expect(dialog.get_by_label("Projekt", exact=True)).to_have_value(team.key)
    name = dialog.get_by_label("Nazwa zadania")
    name.fill("Teren 2023")
    dialog.get_by_role("button", name="Dodaj zadanie").click()

    # Assert: Kartograf's text at the name field; the manifest as it was.
    expect(name).to_have_attribute("aria-invalid", "true")
    expect(described(page, name)).to_have_attribute("role", "alert")
    expect(described(page, name)).not_to_be_empty()
    assert [task.name for task in kartograf.open_project(team.directory).tasks] == [
        "nmt-pl",
        "nmt-cz",
    ]

    # Act
    name.fill(TASK)
    dialog.get_by_role("button", name="Dodaj zadanie").click()

    # Assert: the task as the line said it, through Kartograf; no job, no network.
    expect(dialog.get_by_role("status")).to_contain_text(
        f"Dodano zadanie „{TASK}” do projektu raba"
    )
    shot(page, "10-zadanie-projektu")
    tasks = {task.name: task for task in kartograf.open_project(team.directory).tasks}
    assert list(tasks) == ["nmt-pl", "nmt-cz", TASK]
    added = tasks[TASK]
    assert added.command == "elevation download"
    assert dict(added.options) == dict(kartograf.parse_command(KARTOGRAF_LINE).options)
    card = call(page, f"/projects/{team.key}")
    assert [task["task"] for task in card["tasks"]] == ["nmt-pl", "nmt-cz", TASK]
    assert action_jobs(page) == []
    assert tab.foreign_requests(team.served.base) == []
    dialog.get_by_role("button", name="Zamknij").click()
    expect(dialog).to_be_hidden()
    tab.assert_clean()


def test_a_person_who_may_not_change_the_project_sees_the_option_disabled(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Shared with the person, the project is seen and cannot be changed: the reason."""
    # Arrange
    team = serve_team(serve, tmp_path)
    state = StateStore(team.served.paths.state_file)
    add_people(state)
    share(state, access_key(team.directory), "users")
    issued = issue_one_time_token(
        team.served.paths.index_file, "startup", minted_by=principal(state, "listed")
    )
    page = tab.page
    step = open_step(page, team.served, fragment_url(team.served.base, issued.token))
    listed = call(page, "/projects")["items"]

    # Act
    paste(step, KARTOGRAF_LINE)
    dialog = page.get_by_role("dialog")

    # Assert
    assert [(item["project"], item["project_write"]) for item in listed] == [
        (team.key, False)
    ]
    option = dialog.get_by_label("Dodaj jako zadanie projektu")
    expect(option).to_be_disabled()
    expect(described(page, option)).to_have_text(
        "Zadania dodaje właściciel projektu albo administrator, a ta sesja nie może"
        " zmienić żadnego projektu tego producenta w tym magazynie."
    )
    expect(dialog.get_by_role("button", name="Pobierz")).to_be_disabled()
    manifest = json.loads((team.directory / "kartograf-project.json").read_text())
    assert [task["name"] for task in manifest["tasks"]] == ["nmt-pl", "nmt-cz"]
    tab.assert_clean()
