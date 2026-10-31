"""The Projects view over Archiwista's project files, in Chromium (A-ADR-049, P2).

A generated Kartograf store served offline (``tests/fixtures/make_store.py``)
with its project directory: projects written as ``archiwista-project.json``
with plan and local groups pinning current and older versions, a project
pinning a version no longer in the store and one naming a store that is not
configured. The computer's owner creates a project in the form (a directory
outside the project directories refused at its field first) with a name, a
description and an area file, and finds the file on the disk; „Zmień…”
names the store of Kartograf's pins. A fixture project shows its groups with
their origin and pins with their state. A person the project is shared with
may change nothing of it: „Zmień…” and „Udostępnij…” are disabled with the
reason, „Nowy projekt…” is not.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.config import AppSettings, StoreConfig
from archiwista.projects import AREAS_DIR, read_project_file
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import StoreManifest, make_store
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

STORE = "zespol"
STORE_NAME = "Zespół"
INDEX_TIMEOUT_S = 60.0
NO_WRITE = "Zmienia i udostępnia projekt jego właściciel albo administrator."
# A square of about 1.4 km by 2.2 km in Kraków.
AREA = {
    "type": "Polygon",
    "coordinates": [
        [[19.90, 50.03], [19.92, 50.03], [19.92, 50.05], [19.90, 50.05], [19.90, 50.03]]
    ],
}
# True once every store has a finished scan and no job runs.
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


def served_store(serve: Serve, tmp_path: Path) -> tuple[StoreManifest, Served]:
    """Generate a store with its projects and serve it offline (``Z:`` an alias)."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    config = StoreConfig(
        id=STORE,
        name=STORE_NAME,
        kartograf=store.root,
        kind="local",
        path_aliases={f"{store.base}/": "Z:\\"},
    )
    settings = AppSettings(
        offline=True, stores=(config,), project_dirs=(store.projects_dir,)
    )
    return store, serve(settings)


def open_projects(page: Page, served: Served, url: str, project: str | None) -> None:
    """Open the Projects view with the session of ``url`` once the store is scanned."""
    page.goto(url)
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


def value(scope: Locator, name: str) -> Locator:
    """Return the value of a label in a definition list (``<dt>`` → ``<dd>``)."""
    return scope.locator(f"dt:text-is('{name}') + dd")


def group(page: Page, name: str) -> Locator:
    """Return a group of the chosen project's card."""
    head = page.locator(".pc-group-head b").get_by_text(name, exact=True)
    return card(page).locator(".pc-group").filter(has=head)


def described(page: Page, field: Locator) -> Locator:
    """Return the element a field names in ``aria-describedby``."""
    return page.locator(f"[id='{field.get_attribute('aria-describedby')}']")


def test_a_project_created_in_the_form_appears_with_its_file_on_the_disk(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """New project → its file and area on the disk → „Zmień…” names its store."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    page = tab.page
    open_projects(page, served, served.token_url(), None)
    rows = page.locator(".projects-table tbody tr")
    expect(rows).to_have_count(len(store.projects))
    area = tmp_path / "krakow.geojson"
    area.write_text(json.dumps(AREA), encoding="utf-8")

    # Act: a directory outside the project directories first.
    page.get_by_role("button", name="Nowy projekt…").click()
    form = page.get_by_role("form", name="Nowy projekt")
    path = form.get_by_label("Katalog projektu")
    expect(path).to_have_value(f"{store.projects_dir}/")
    path.fill(str(tmp_path / "gdzie-indziej"))
    form.get_by_role("button", name="Załóż projekt").click()

    # Assert: the server's refusal at the field; nothing was made.
    expect(path).to_have_attribute("aria-invalid", "true")
    expect(described(page, path)).to_have_attribute("role", "alert")
    expect(described(page, path)).to_contain_text(str(store.projects_dir))
    assert not (tmp_path / "gdzie-indziej").exists()

    # Act
    directory = store.projects_dir / "raba"
    path.fill(str(directory))
    form.get_by_label("Nazwa", exact=True).fill("Raba")
    form.get_by_label("Opis").fill("Zlewnia Raby do Dobczyc")
    form.get_by_label("Obszar (opcjonalnie)").set_input_files(area)
    form.get_by_role("button", name="Załóż projekt").click()

    # Assert: its card is open; Archiwista's file and its area on the disk.
    expect(card(page).get_by_role("heading", name="Raba")).to_be_visible()
    expect(form).to_have_count(0)
    expect(rows).to_have_count(len(store.projects) + 1)
    expect(card(page)).to_contain_text("Zlewnia Raby do Dobczyc")
    expect(value(card(page), "Obszar")).to_contain_text("w porządku")
    expect(card(page)).to_contain_text("Projekt nie ma jeszcze przypiętych wersji.")
    created = read_project_file(directory)
    assert (created.name, created.description) == ("Raba", "Zlewnia Raby do Dobczyc")
    assert (created.created_by, created.stores, created.groups) == ("local", (), ())
    assert created.area is not None
    assert created.area.path.startswith(f"{AREAS_DIR}/")
    assert (directory / created.area.path).is_file()

    # Act: „Zmień…” names the store of Kartograf's pins.
    card(page).get_by_role("button", name="Zmień…").click()
    editing = card(page).get_by_role("form", name="Zmień projekt")
    editing.get_by_label("Magazyn: kartograf").select_option(label=STORE_NAME)
    editing.get_by_role("button", name="Zapisz").click()

    # Assert: the file names the store's directory, relative to the project.
    done = card(page).locator(".pc-done")
    expect(done).to_have_text("Zapisano zmiany projektu.")
    expect(done).to_have_attribute("role", "status")
    expect(editing).to_have_count(0)
    expect(value(card(page), "Magazyny")).to_contain_text(f"kartograf: {STORE_NAME}")
    (named,) = read_project_file(directory).stores
    assert named.producer == "kartograf"
    assert (directory / named.root).resolve() == store.root.resolve()
    tab.assert_clean()


def test_a_fixture_project_shows_its_groups_and_pin_states(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Groups by origin, pins by state; a missing pin; a store not configured."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    page = tab.page
    project = store.project("projekt-01")

    # Act
    open_projects(page, served, served.token_url(), project.name)

    # Assert: the row's counts; each group of the file in its order.
    row = page.locator(".projects-table tbody tr").filter(has_text=project.name)
    cells = row.get_by_role("cell")
    expect(cells.nth(1)).to_contain_text(f"kartograf: {STORE_NAME}")
    expect(cells.nth(2)).to_have_text(str(len(project.groups)))
    expect(cells.nth(3)).to_have_text(str(sum(len(g.pins) for g in project.groups)))
    expect(cells.nth(4)).to_have_text("0")
    heads = card(page).locator(".pc-group-head b")
    expect(heads).to_have_text([item.name for item in project.groups])
    for expected in project.groups:
        pins = group(page, expected.name).locator(".pc-pin")
        expect(pins).to_have_count(len(expected.pins))
        for pin in expected.pins:
            pinned = pins.filter(has=page.get_by_role("link", name=pin.label))
            expect(pinned).to_contain_text("w magazynie")
            expect(pinned).to_contain_text(
                "bieżąca" if pin.current else "starsza wersja"
            )
    expect(group(page, "teren")).to_contain_text("z planu pobrania · kartograf")
    expect(group(page, "teren").locator(".pc-cmd")).to_contain_text(
        "kartograf elevation download"
    )
    expect(group(page, "archiwum")).to_contain_text("z magazynu · karta pliku")
    expect(group(page, "plan")).to_contain_text("grupa jest pusta")

    # Act: a project pinning a version no longer in the store.
    missing = next(p for p in store.projects if p.case == "missing_version")
    page.goto(f"{served.base}/?view=projects&project={missing.name}")

    # Assert
    expect(card(page).get_by_role("heading", name=missing.name)).to_be_visible()
    expect(value(card(page), "Brakujące przypięcia")).to_have_text("1")
    expect(group(page, "teren").locator(".pc-pin")).to_contain_text("brak w magazynie")
    expect(card(page).locator(".issue")).to_contain_text(
        "Przypięty plik nie istnieje w magazynie"
    )

    # Act: a project naming a store that is not configured.
    foreign = next(p for p in store.projects if p.case == "other_store")
    page.goto(f"{served.base}/?view=projects&project={foreign.name}")

    # Assert
    expect(card(page).get_by_role("heading", name=foreign.name)).to_be_visible()
    expect(value(card(page), "Magazyny")).to_contain_text(
        "kartograf: żaden magazyn z ustawień"
    )
    expect(card(page).locator(".issue")).to_contain_text("Magazyn projektu nieznany")
    tab.assert_clean()


def test_a_person_who_may_change_nothing_sees_new_project_only(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Shared with her: the card's changes disabled with why; she may create one."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    project = store.project("projekt-01")
    state = StateStore(served.paths.state_file)
    add_people(state)
    share(state, access_key(store.base / project.path), "users")
    issued = issue_one_time_token(
        served.paths.index_file, "startup", minted_by=principal(state, "listed")
    )
    page = tab.page

    # Act
    open_projects(page, served, fragment_url(served.base, issued.token), project.name)

    # Assert
    expect(card(page).get_by_role("heading", name=project.name)).to_be_visible()
    actions = card(page).get_by_role("group", name="Działania projektu")
    for name in ("Zmień…", "Udostępnij…"):
        button = actions.get_by_role("button", name=name)
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(NO_WRITE)
    expect(card(page).locator(".pc-why")).to_have_text(NO_WRITE)
    expect(page.get_by_role("button", name="Nowy projekt…")).to_be_enabled()
    tab.assert_clean()
