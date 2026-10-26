"""A project's sharing screen on a team server, in Chromium and Firefox.

Plan v0.4, step T7. A real ``archiwista serve`` in team mode over TLS with a
store and a project directory: kasia, who is no administrator, creates a
project with „Nowy projekt…” and owns it, and on its sharing screen
(„Udostępnij…”) shares it with the group hydro: marek, outside hydro, does
not see it and ola, in hydro, does; made private, only kasia and the
administrator anna see it. A data folder outside the project is refused at
its field and one inside it is saved. Without ``admin`` the Store view's
scans are disabled with the reason. With ``ARCHIWISTA_SCREENSHOTS=<directory>``
Chromium keeps the screenshot 06 there (``docs/reports/v0.4-screenshots/``).
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.config import AppSettings, StoreConfig
from archiwista.state import StateStore
from tests.fixtures.browser import Tab
from tests.fixtures.team_pages import shot, signed_in
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    TeamServed,
    add_person,
)

TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]

STORE = "zespol"
PROJECT = "raba"
PASSWORD = "wiosla-na-Dunajcu-7"
PEOPLE = {"kasia": "Kasia Wrona", "marek": "Marek Lis", "ola": "Ola Brzoza"}
GROUP = "hydro"
NO_PROJECTS = "Nie znaleziono projektów w katalogach projektów z ustawień."
ADMIN_ONLY = (
    "Skan magazynu i obrysy jednostek zleca administrator; serwer i tak skanuje"
    " magazyn sam według harmonogramu."
)
INDEX_TIMEOUT_S = 60.0
# Whether every store had its first scan and no job runs (`/health`).
INDEXED = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}"""
# The status and JSON answer of an API request sent with the page's session.
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""


@dataclass(frozen=True)
class Team:
    """A team server with a store, a project directory and its people."""

    served: TeamServed
    projects: Path

    def person(self, tab: Tab, account: str) -> Page:
        """Sign ``account`` in (anna with her own password) and open Projects."""
        page = tab.page
        password = ADMIN_PASSWORD if account == ADMIN_ACCOUNT else PASSWORD
        signed_in(page, self.served.origin, account, password)
        deadline = time.monotonic() + INDEX_TIMEOUT_S
        while not page.evaluate(INDEXED):
            assert time.monotonic() < deadline, "the store was not scanned in time"
            page.wait_for_timeout(200)
        open_projects(page, self.served.origin)
        return page


def serve_team(team_serve: TeamServe, tmp_path: Path) -> Team:
    """Serve a team with a Kartograf store and a project directory.

    kasia, marek and ola are people without roles; hydro has kasia and ola.
    """
    share = tmp_path / "nas"
    kartograf.init_store(share / "kartograf")
    projects = share / "projekty"
    projects.mkdir()
    store = StoreConfig(
        id=STORE, name="Zespół", kartograf=share / "kartograf", kind="local"
    )
    settings = AppSettings(
        offline=True, basemaps=(), stores=(store,), project_dirs=(projects,)
    )
    served = team_serve(settings)
    for account, name in PEOPLE.items():
        add_person(served.paths, account, PASSWORD, name=name)
    StateStore(served.paths.state_file).add_group(
        GROUP, name="Dział hydrologii", members=("kasia", "ola"), actor=LOCAL_OWNER
    )
    return Team(served, projects)


def open_projects(page: Page, origin: str, project: str | None = None) -> None:
    """Open the Projects view, with a project's card when one is named."""
    chosen = f"&project={project}" if project else ""
    page.goto(f"{origin}/?view=projects{chosen}")
    expect(page.get_by_role("heading", name="Projekty")).to_be_visible()


def rows(page: Page) -> Locator:
    """Return the rows of the projects the page lists."""
    return page.locator(".projects-table tbody tr")


def sharing(page: Page) -> Locator:
    """Open „Udostępnij…” of the chosen project; return its window."""
    card = page.get_by_role("complementary", name="Projekt")
    card.get_by_role("button", name="Udostępnij…").click()
    window = page.get_by_role("dialog", name=f"Udostępnianie · projekt {PROJECT}")
    expect(window.get_by_label("wszyscy")).to_be_visible()
    return window


def call(
    page: Page, method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return the status and JSON answer of a request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    return answer


def test_a_person_shares_her_project_with_a_group_then_keeps_it_private(
    team_serve: TeamServe, team_tab: TeamTab, tmp_path: Path
) -> None:
    """Shared with hydro: ola sees it, marek not; private: kasia and anna only."""
    team = serve_team(team_serve, tmp_path)
    kasia, marek, ola, anna = (team_tab() for _ in range(4))
    page = team.person(kasia, "kasia")

    page.get_by_role("button", name="Nowy projekt…").click()
    form = page.get_by_role("form", name="Nowy projekt")
    form.get_by_label("Katalog projektu").fill(str(team.projects / PROJECT))
    form.get_by_role("button", name="Załóż projekt").click()
    window = sharing(page)
    expect(window.get_by_text("właściciel: Kasia Wrona")).to_be_visible()
    window.get_by_label("wybrane grupy").check()
    window.get_by_label("+ grupa").select_option(label="Dział hydrologii (hydro)")
    expect(window.get_by_role("button", name="Usuń: Dział hydrologii")).to_be_visible()
    shot(page, "06-udostepnianie")
    window.get_by_role("button", name="Zapisz").click()
    expect(window).to_be_hidden()
    outside = team.person(marek, "marek")
    inside = team.person(ola, "ola")
    expect(rows(inside)).to_have_count(1)
    expect(outside.get_by_text(NO_PROJECTS)).to_be_visible()
    shared = (
        call(outside, "GET", f"/projects/{PROJECT}")["status"],
        call(inside, "GET", f"/projects/{PROJECT}")["status"],
    )
    window = sharing(page)
    expect(window.get_by_label("wybrane grupy")).to_be_checked()
    window.get_by_label("tylko właściciel").check()
    window.get_by_role("button", name="Zapisz").click()
    expect(window).to_be_hidden()
    open_projects(inside, team.served.origin)
    open_projects(page, team.served.origin)
    administrator = team.person(anna, ADMIN_ACCOUNT)

    assert shared == (404, 200)
    expect(inside.get_by_text(NO_PROJECTS)).to_be_visible()
    for seeing in (page, administrator):
        expect(rows(seeing)).to_have_count(1)
        expect(rows(seeing).first).to_contain_text(PROJECT)
    for tab in (kasia, marek, ola, anna):
        tab.assert_clean()


def test_a_data_folder_outside_the_project_is_refused_at_its_field(
    team_serve: TeamServe, team_tab: TeamTab, tmp_path: Path
) -> None:
    """Kasia's folder elsewhere: the server's refusal at the field; inside: saved."""
    team = serve_team(team_serve, tmp_path)
    kasia = team_tab()
    page = team.person(kasia, "kasia")
    directory = team.projects / PROJECT
    body = {"producer": "kartograf", "path": str(directory), "store": STORE}
    created = call(page, "POST", "/projects", body)
    assert created["status"] == 201, created
    outside = tmp_path / "obce-dane"
    outside.mkdir()
    (directory / "dane-gis").mkdir()
    open_projects(page, team.served.origin, PROJECT)
    window = sharing(page)
    folder = window.get_by_label("Folder danych własnych")

    folder.fill(str(outside))
    window.get_by_role("button", name="Zapisz").click()
    expect(folder).to_have_attribute("aria-invalid", "true")
    expect(folder).to_have_accessible_description(
        re.compile("nie leży wewnątrz katalogu projektu")
    )
    folder.fill(str(directory / "dane-gis"))
    window.get_by_role("button", name="Zapisz").click()

    expect(window).to_be_hidden()
    own = page.locator(".own-group .own-folder")
    expect(own).to_contain_text(str(Path(access_key(directory)) / "dane-gis"))
    expect(own).to_contain_text("folder z ustawień Archiwisty")
    kasia.assert_clean()


def test_without_admin_the_store_scans_are_disabled_with_the_reason(
    team_serve: TeamServe, team_tab: TeamTab, tmp_path: Path
) -> None:
    """Kasia sees the Store view; its three scans say they are an administrator's."""
    team = serve_team(team_serve, tmp_path)
    kasia = team_tab()
    page = team.person(kasia, "kasia")

    page.goto(f"{team.served.origin}/?view=store")

    for name in ("Odśwież", "Pełny skan", "Uzupełnij obrysy jednostek"):
        button = page.get_by_role("button", name=name, exact=True)
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(ADMIN_ONLY)
    kasia.assert_clean()
