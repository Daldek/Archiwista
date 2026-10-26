"""The actions of a project in its card and the new project, in Chromium (plan A13).

The Projects view over Kartograf's fixture store and project
(``kartograf.testing``), the real Kartograf adapter and real worker
processes whose sockets refuse every connection
(``tests/fixtures/job_worker.py``): a verification and a download of pins
the store already holds need no network. An administrator creates a project
of Kartograf in a project directory of the settings, adds a pasted command as
its task (Kartograf's text for a mistake at the field) and removes the task
after a confirmation; verifies the project and downloads it. A person the
project is shared with sees it with every change (its sharing too) disabled
and the reason, may create a project of her own, and never sees a project
that is not shared with her. Offline, the actions
that need the network say so, and a lock of the manifest that an interrupted
change left makes a removal fail with the instruction naming the lock, which
stays. With ``ARCHIWISTA_SCREENSHOTS=<directory>`` the steps keep screenshots
there (``docs/reports/v0.3-screenshots/``).
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import kartograf
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, build_project
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.jobs import JobSupervisor
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab
from tests.fixtures.job_worker import NO_NETWORK_ENV
from tests.fixtures.jobs import TEST_WORKER, worker_path
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

TEAM = "zespol"
PROJECT = "raba"
TASKS = ["nmt-pl", "nmt-cz"]
LOCK = ".kartograf-project.lock"
# A box of 1 km² in PL-1992 cut into 1:10 000 sheets, checked without the
# network; `-o` names a directory of the computer it was copied from.
KARTOGRAF_LINE = (
    "kartograf elevation download --product nmt --country pl"
    " --bbox 500000,250000,501000,251000 --bbox-crs EPSG:2180 --sheet-system 1992"
    " --resolution 1m --vertical-crs EVRF2007 --year 2023 -o ./dane"
)
NEW_TASK = "teren-2023"
NO_WRITE = "Zmienia projekt jego właściciel albo administrator."
OFFLINE = "Tryb offline: sprawdzenie, pobieranie i przepinanie potrzebują sieci."
INDEX_TIMEOUT_S = 60.0
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
# Whether every store had its first scan and no job runs (`/health`).
INDEXED = """async () => {
  const csrf = sessionStorage.getItem("archiwista_csrf") ?? "";
  const headers = { "X-Archiwista-CSRF": csrf };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}"""
# Covers the text of local paths for a screenshot. Through the CSSOM: the
# CSP allows no injected stylesheet.
COVER_PATHS = """(cover) => {
  for (const path of document.querySelectorAll("code.path, input.mono")) {
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
    """Kartograf's fixture store ``zespol`` with its project ``raba`` indexed."""

    served: Served
    built: FixtureStore
    projects: Path
    directory: Path
    key: str
    hidden: str | None


@pytest.fixture
def attempts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give the server workers that refuse the network; return their record."""
    worker_path(monkeypatch)
    record = tmp_path / "network.log"
    monkeypatch.setenv(NO_NETWORK_ENV, str(record))
    defaults = JobSupervisor.__init__.__kwdefaults__
    assert defaults is not None
    monkeypatch.setitem(defaults, "worker_command", TEST_WORKER)
    return record


def serve_team(
    serve: Serve, tmp_path: Path, *, offline: bool = False, hidden: bool = False
) -> Team:
    """Serve the fixture store and project; ``hidden`` adds a second project."""
    built = build_fixture_store(tmp_path / "nas" / "kartograf")
    projects = tmp_path / "nas" / "projekty"
    directory = build_project(projects / PROJECT, built)
    config = StoreConfig(id=TEAM, name="Zespół", kartograf=built.root, kind="local")
    settings = AppSettings(
        offline=offline, basemaps=(), stores=(config,), project_dirs=(projects,)
    )
    paths = local_paths(tmp_path)
    initialize(paths.index_file)
    adapter = load_registry(cache_dir=paths.cache_dir).adapter("kartograf")
    other = None
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({TEAM: config.roots()})
        key = record_project(adapter, writer, directory, stores=settings.stores)
        if hidden:
            secret = build_project(projects / "tajny", built)
            other = record_project(adapter, writer, secret, stores=settings.stores)
    return Team(serve(settings), built, projects, directory, key, other)


def open_projects(page: Page, served: Served, url: str, project: str | None) -> None:
    """Open the Projects view with the session of ``url`` once the store is scanned."""
    page.goto(f"{served.base}/?view=projects#{urlsplit(url).fragment}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the store was not scanned in time"
        page.wait_for_timeout(200)
    chosen = f"&project={project}" if project else ""
    page.goto(f"{served.base}/?view=projects{chosen}")
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def card(page: Page) -> Locator:
    """Return the side panel with the chosen project's card."""
    return page.get_by_role("complementary", name="Projekt")


def task(page: Page, name: str) -> Locator:
    """Return a task of the chosen project's card."""
    return card(page).locator(".pc-task").filter(has=page.get_by_text(name, exact=True))


def call(page: Page, method: str, path: str) -> dict[str, Any]:
    """Return the status and JSON answer of a request made with the page's session."""
    answer: dict[str, Any] = page.evaluate(API, [method, path])
    return answer


def described(page: Page, field: Locator) -> Locator:
    """Return the element a field names in ``aria-describedby``."""
    return page.locator(f"[id='{field.get_attribute('aria-describedby')}']")


def manifest_tasks(directory: Path) -> list[str]:
    """Return the names of the tasks in a project's manifest, as Kartograf reads it."""
    return [item.name for item in kartograf.open_project(directory).tasks]


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.evaluate(COVER_PATHS, True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))
        page.evaluate(COVER_PATHS, False)


def test_an_administrator_creates_a_project_and_adds_and_removes_its_task(
    serve: Serve, tab: Tab, tmp_path: Path, attempts: Path
) -> None:
    """New project → a pasted command as its task → the task removed after asking."""
    # Arrange
    team = serve_team(serve, tmp_path)
    page = tab.page
    open_projects(page, team.served, team.served.token_url(), None)
    rows = page.locator(".projects-table tbody tr")
    expect(rows).to_have_count(1)
    expect(page.get_by_role("columnheader", name="Producent")).to_be_visible()
    expect(rows.first.get_by_role("cell").nth(1)).to_have_text("kartograf")

    # Act: a directory outside the project directories first.
    page.get_by_role("button", name="Nowy projekt…").click()
    form = page.get_by_role("form", name="Nowy projekt")
    path = form.get_by_label("Katalog projektu")
    expect(form.get_by_label("Producent")).to_have_value("kartograf")
    expect(form.get_by_label("Magazyn")).to_have_value(TEAM)
    expect(path).to_have_value(f"{team.projects}/")
    path.fill(str(tmp_path / "gdzie-indziej"))
    form.get_by_role("button", name="Załóż projekt").click()

    # Assert: the server's refusal at the field; nothing was made.
    expect(path).to_have_attribute("aria-invalid", "true")
    expect(described(page, path)).to_have_attribute("role", "alert")
    expect(described(page, path)).to_contain_text(str(team.projects))
    assert not (tmp_path / "gdzie-indziej").exists()

    # Act
    directory = team.projects / "nowy"
    path.fill(str(directory))
    form.get_by_role("button", name="Załóż projekt").click()

    # Assert: Kartograf's manifest names the store; its card is open.
    expect(card(page).get_by_role("heading", name="nowy")).to_be_visible()
    expect(rows).to_have_count(2)
    expect(form).to_have_count(0)
    created = kartograf.open_project(directory)
    assert created.tasks == ()
    assert Path(created.root) == team.built.root
    expect(card(page)).to_contain_text("Manifest nie ma zadań.")

    # Act: a line Kartograf cannot read, then a name it refuses.
    card(page).get_by_role("button", name="Zadanie", exact=True).click()
    adding = card(page).get_by_role("form", name="Nowe zadanie")
    line = adding.get_by_label("Polecenie producenta")
    name = adding.get_by_label("Nazwa zadania")
    line.fill("kartograf elevation download --product")
    name.fill(NEW_TASK)
    adding.get_by_role("button", name="Dodaj zadanie").click()
    expect(line).to_have_attribute("aria-invalid", "true")
    expect(described(page, line)).to_have_attribute("role", "alert")
    expect(described(page, line)).not_to_be_empty()
    line.fill(KARTOGRAF_LINE)
    expect(line).not_to_have_attribute("aria-invalid", "true")
    name.fill("Teren 2023")
    adding.get_by_role("button", name="Dodaj zadanie").click()

    # Assert: Kartograf's text at the name field; the manifest as it was.
    expect(name).to_have_attribute("aria-invalid", "true")
    expect(described(page, name)).to_have_attribute("role", "alert")
    expect(described(page, name)).not_to_be_empty()
    assert manifest_tasks(directory) == []

    # Act
    name.fill(NEW_TASK)
    adding.get_by_role("button", name="Dodaj zadanie").click()

    # Assert: the task as the line said it, through Kartograf; no job.
    done = card(page).locator(".pc-done")
    expect(done).to_have_text(f"Dodano zadanie „{NEW_TASK}”.")
    expect(done).to_have_attribute("role", "status")
    expect(adding).to_have_count(0)
    expect(task(page, NEW_TASK)).to_contain_text("kartograf elevation download")
    added = kartograf.open_project(directory).tasks
    assert [item.name for item in added] == [NEW_TASK]
    assert added[0].command == "elevation download"
    assert dict(added[0].options) == dict(
        kartograf.parse_command(KARTOGRAF_LINE).options
    )
    expect(rows.filter(has_text="nowy").get_by_role("cell").nth(4)).to_have_text("1")

    # Act: „Usuń” asks first; „Zostaw” keeps the task.
    task(page, NEW_TASK).get_by_role("button", name="Usuń", exact=True).click()
    question = task(page, NEW_TASK).get_by_role(
        "group", name=f"Usunąć zadanie „{NEW_TASK}”"
    )
    expect(question).to_be_visible()
    question.get_by_role("button", name="Zostaw").click()
    expect(question).to_have_count(0)
    assert manifest_tasks(directory) == [NEW_TASK]
    task(page, NEW_TASK).get_by_role("button", name="Usuń", exact=True).click()
    task(page, NEW_TASK).get_by_role("button", name="Usuń zadanie").click()

    # Assert
    expect(done).to_have_text(f"Usunięto zadanie „{NEW_TASK}”.")
    expect(card(page)).to_contain_text("Manifest nie ma zadań.")
    assert manifest_tasks(directory) == []
    jobs = call(page, "GET", "/jobs?kind=project_download")["body"]["items"]
    assert jobs == []
    assert not attempts.exists()
    tab.assert_clean()


def test_the_owner_verifies_and_downloads_the_project_without_the_network(
    serve: Serve, tab: Tab, tmp_path: Path, attempts: Path
) -> None:
    """„Weryfikuj” and „Pobierz” run the project's jobs; their results in the card."""
    # Arrange
    team = serve_team(serve, tmp_path)
    page = tab.page
    open_projects(page, team.served, team.served.token_url(), team.key)
    actions = card(page).get_by_role("group", name="Działania projektu")
    for label in ("Weryfikuj", "Sprawdź aktualizacje", "Pobierz", "Zadanie"):
        expect(actions.get_by_role("button", name=label, exact=True)).to_be_enabled()
    for name in TASKS:
        expect(task(page, name).get_by_role("button", name="Przepnij")).to_be_enabled()
    expect(card(page).locator(".pc-why")).to_have_count(0)

    # Act
    actions.get_by_role("button", name="Weryfikuj").click()

    # Assert: Kartograf's verification of both pins, read from the store.
    status = card(page).locator(".job-status").first
    expect(status.locator(".job.succeeded")).to_be_visible()
    expect(status).to_contain_text("Weryfikacja projektu")
    expect(status).to_contain_text(
        "Pliki: 2 (nienaruszone 2); zadania bez przypięć: 0."
    )
    shot(page, "11-akcje-projektu")

    # Act
    actions.get_by_role("button", name="Pobierz", exact=True).click()

    # Assert: both tasks pinned already: nothing fetched, the card read again.
    expect(status).to_contain_text("Pobranie projektu")
    expect(status).to_contain_text("Zadania projektu: 2 (bez zmian 2).")
    expect(status.locator(".job.succeeded")).to_be_visible()
    kinds = sorted(
        job["kind"]
        for kind in ("project_verify", "project_download")
        for job in call(page, "GET", f"/jobs?kind={kind}")["body"]["items"]
    )
    assert kinds == ["project_download", "project_verify"]
    assert manifest_tasks(team.directory) == TASKS
    assert not attempts.exists()
    tab.assert_clean()


def test_a_person_the_project_is_shared_with_sees_every_change_disabled_with_why(
    serve: Serve, tab: Tab, tmp_path: Path, attempts: Path
) -> None:
    """Shared with her: verify and check, nothing that changes it; the hidden unseen."""
    # Arrange
    team = serve_team(serve, tmp_path, hidden=True)
    assert team.hidden is not None
    state = StateStore(team.served.paths.state_file)
    add_people(state)
    share(state, access_key(team.directory), "users")
    share(state, access_key(team.projects / "tajny"), "private")
    issued = issue_one_time_token(
        team.served.paths.index_file, "startup", minted_by=principal(state, "listed")
    )
    page = tab.page

    # Act
    open_projects(page, team.served, fragment_url(team.served.base, issued.token), None)

    # Assert: only the shared project; she may create one of her own.
    rows = page.locator(".projects-table tbody tr")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text(PROJECT)
    expect(page.get_by_role("button", name="Nowy projekt…")).to_be_enabled()
    assert call(page, "GET", f"/projects/{team.hidden}")["status"] == 404

    # Act
    rows.first.get_by_role("link", name=PROJECT).click()

    # Assert: she sees and checks it; every change says who may make it.
    actions = card(page).get_by_role("group", name="Działania projektu")
    expect(actions.get_by_role("button", name="Weryfikuj")).to_be_enabled()
    expect(actions.get_by_role("button", name="Sprawdź aktualizacje")).to_be_enabled()
    changes = [
        actions.get_by_role("button", name="Pobierz", exact=True),
        actions.get_by_role("button", name="Zadanie", exact=True),
        actions.get_by_role("button", name="Udostępnij…"),
    ]
    for name in TASKS:
        changes.append(task(page, name).get_by_role("button", name="Przepnij"))
        changes.append(task(page, name).get_by_role("button", name="Usuń", exact=True))
    for button in changes:
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(NO_WRITE)
    expect(card(page).locator(".pc-why li")).to_have_text([NO_WRITE])
    shot(page, "12-projekt-udostepniony")
    manifest = json.loads((team.directory / "kartograf-project.json").read_text())
    assert [item["name"] for item in manifest["tasks"]] == TASKS
    assert not attempts.exists()
    tab.assert_clean()


def test_offline_a_left_lock_stops_a_removal_with_the_instruction_naming_it(
    serve: Serve, tab: Tab, tmp_path: Path, attempts: Path
) -> None:
    """The network's actions say why offline; a lock that stays: `409`, its path."""
    # Arrange
    team = serve_team(serve, tmp_path, offline=True)
    lock = team.directory / LOCK
    lock.mkdir()
    page = tab.page
    open_projects(page, team.served, team.served.token_url(), team.key)
    actions = card(page).get_by_role("group", name="Działania projektu")

    # Assert: a verification and changes of the manifest need no network.
    expect(actions.get_by_role("button", name="Weryfikuj")).to_be_enabled()
    expect(actions.get_by_role("button", name="Zadanie", exact=True)).to_be_enabled()
    offline = [
        actions.get_by_role("button", name="Sprawdź aktualizacje"),
        actions.get_by_role("button", name="Pobierz", exact=True),
        *(task(page, name).get_by_role("button", name="Przepnij") for name in TASKS),
    ]
    for button in offline:
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(OFFLINE)

    # Act: Kartograf waits for its lock, then refuses.
    removed = task(page, TASKS[1])
    removed.get_by_role("button", name="Usuń", exact=True).click()
    removed.get_by_role("button", name="Usuń zadanie").click()

    # Assert: the conflict with the instruction; the lock and the task stay.
    alert = removed.get_by_role("alert")
    expect(alert).to_contain_text("Manifest projektu jest zablokowany")
    expect(alert).to_contain_text(f"usuń katalog {lock} i spróbuj ponownie")
    expect(removed.get_by_role("button", name="Usuń zadanie")).to_be_enabled()
    assert lock.is_dir()
    assert manifest_tasks(team.directory) == TASKS
    assert not attempts.exists()
    tab.assert_clean()
