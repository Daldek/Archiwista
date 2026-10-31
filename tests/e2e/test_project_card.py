"""The project card's exports and activity, in Chromium (A-ADR-049, plan P5, P6).

A generated Kartograf store served offline with its projects
(``tests/fixtures/make_store.py``). The computer's owner writes an export of
a fixture project with „Eksportuj…” and finds ``pliki.txt`` and
``ATRYBUCJE.txt`` on the disk; once the project file changes, the list says
„projekt zmieniony po eksporcie — wygeneruj ponownie” and the export is
written again from the form opened on its name. A person the project is
shared with sees the exports and „Eksportuj…” disabled with the reason.
„Aktywność” shows the 20 newest entries of the project's activity, older
ones on „Więcej”, never another project's, and a change made on the card at
once; the person it is shared with sees it too.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.projects import change_project_file
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.e2e.test_projects_view import open_projects, served_store
from tests.fixtures.browser import Served, Tab
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

PROJECT = "projekt-01"
ATTRIBUTION = "Archiwista synthetic test store\n"
CHANGED = "projekt zmieniony po eksporcie — wygeneruj ponownie"
NO_WRITE = "Zestaw zapisuje tylko właściciel projektu albo administrator."


def exports(page: Page) -> Locator:
    """Return the section „Zestawy” of the chosen project's card."""
    panel = page.get_by_role("complementary", name="Projekt")
    return panel.get_by_role("region", name="Zestawy")


def activity(page: Page) -> Locator:
    """Return the section „Aktywność” of the chosen project's card."""
    panel = page.get_by_role("complementary", name="Projekt")
    return panel.get_by_role("region", name="Aktywność")


def test_an_export_is_written_and_written_again_after_a_change(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """„Eksportuj…” → files on the disk → a changed project → „Wygeneruj ponownie…”."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    project = store.project(PROJECT)
    directory = store.base / project.path
    page = tab.page
    open_projects(page, served, served.token_url(), PROJECT)
    section = exports(page)
    expect(section).to_contain_text("Projekt nie ma zestawów.")

    # Act: every group but the archive.
    section.get_by_role("button", name="Eksportuj…").click()
    form = section.get_by_role("form", name="Nowy zestaw")
    form.get_by_label("Nazwa").fill("hydrograf")
    form.get_by_role("checkbox", name="archiwum").uncheck()
    form.get_by_role("button", name="Zapisz zestaw").click()

    # Assert: what was written, the list, the files on the disk.
    done = section.get_by_role("status")
    expect(done).to_have_text("Zapisano zestaw „hydrograf”: wersje 2.")
    expect(form).to_have_count(0)
    listed = section.get_by_role("list", name="Zestawy projektu").get_by_role(
        "listitem"
    )
    expect(listed).to_have_count(1)
    expect(listed).to_contain_text("hydrograf")
    target = directory / "zestawy" / "hydrograf"
    expect(listed).to_contain_text(str(target))
    expect(listed).not_to_contain_text(CHANGED)
    pins = [
        pin.version
        for group in project.groups
        if group.name != "archiwum"
        for pin in group.pins
    ]
    assert (target / "pliki.txt").read_text(encoding="utf-8") == "".join(
        f"../../../../data/{version}\n" for version in pins
    )
    assert (target / "ATRYBUCJE.txt").read_text(encoding="utf-8") == ATTRIBUTION

    # Act: the project file changes after the export; the card is read again.
    def describe(data: dict[str, Any]) -> None:
        data["description"] = "Zlewnia Raby"

    change_project_file(directory, describe)
    page.reload()

    # Assert
    item = exports(page).get_by_role("listitem").filter(has_text="hydrograf")
    expect(item).to_contain_text(CHANGED)

    # Act: written again from the form opened on its name, every group.
    item.get_by_role("button", name="Wygeneruj ponownie…").click()
    form = exports(page).get_by_role("form", name="Nowy zestaw")
    expect(form.get_by_label("Nazwa")).to_have_value("hydrograf")
    form.get_by_role("button", name="Zapisz zestaw").click()

    # Assert
    expect(exports(page).get_by_role("status")).to_have_text(
        "Zapisano zestaw „hydrograf”: wersje 3."
    )
    expect(item).not_to_contain_text(CHANGED)
    assert len((target / "pliki.txt").read_text(encoding="utf-8").splitlines()) == 3
    tab.assert_clean()


def test_a_person_who_may_not_change_the_project_sees_its_exports_only(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Shared with her: the list, „Eksportuj…” disabled with why, the activity."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    directory = store.base / store.project(PROJECT).path
    state = StateStore(served.paths.state_file)
    add_people(state)
    share(state, access_key(directory), "users")
    old = directory / "zestawy" / "stary" / "pliki.txt"
    old.parent.mkdir(parents=True)
    old.write_text("", encoding="utf-8")
    os.utime(old, (1_600_000_000, 1_600_000_000))  # before the project file
    issued = issue_one_time_token(
        served.paths.index_file, "startup", minted_by=principal(state, "listed")
    )
    page = tab.page

    # Act
    open_projects(page, served, fragment_url(served.base, issued.token), PROJECT)

    # Assert
    section = exports(page)
    button = section.get_by_role("button", name="Eksportuj…")
    expect(button).to_be_disabled()
    expect(button).to_have_accessible_description(NO_WRITE)
    item = section.get_by_role("listitem").filter(has_text="stary")
    expect(item).to_contain_text(CHANGED)
    expect(item.get_by_role("button", name="Wygeneruj ponownie…")).to_have_count(0)
    entries = activity(page).get_by_role("listitem")
    expect(entries.first).to_contain_text("zmiana udostępnienia projektu")
    tab.assert_clean()


def test_the_activity_shows_the_newest_entries_and_a_change_made_on_the_card(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """20 newest, „Więcej” for the rest, no other project; a group removed shows."""
    # Arrange: 22 job starts of the project (the newest failed), one of another.
    store, served = served_store(serve, tmp_path)
    state = StateStore(served.paths.state_file)
    add_people(state)
    owner = principal(state, "owner")
    pinning = {"kind": "download", "project": PROJECT, "group": "NMT"}
    for number in range(21):
        state.record(owner, "job.start", f"job-{number}", details=pinning)
    state.record(owner, "job.start", "job-21", outcome="failed", details=pinning)
    state.record(
        owner,
        "job.start",
        "job-other",
        details={"kind": "download", "project": "brak-wersji"},
    )
    page = tab.page
    open_projects(page, served, served.token_url(), PROJECT)
    section = activity(page)
    entries = section.get_by_role("list", name="Aktywność projektu").get_by_role(
        "listitem"
    )

    # Assert: the 20 newest, the failed one first.
    expect(entries).to_have_count(20)
    expect(entries.first).to_contain_text(
        "Olga Owczarek uruchomienie zadania, pobranie"
    )
    expect(entries.first).to_contain_text("nieudane")
    expect(entries.nth(1)).not_to_contain_text("nieudane")

    # Act
    section.get_by_role("button", name="Więcej").click()

    # Assert: the other two, and nothing more to read.
    expect(entries).to_have_count(22)
    expect(section.get_by_role("button", name="Więcej")).to_have_count(0)

    # Act: a group removed on the card, after the question.
    panel = page.get_by_role("complementary", name="Projekt")
    panel.get_by_role("button", name="Usuń grupę archiwum").click()
    question = page.get_by_role("dialog", name="Usuń grupę")
    question.get_by_role("button", name="Usuń grupę").click()

    # Assert: the activity read again, the change first.
    expect(entries.first).to_contain_text(
        "właściciel lokalny odpięcie wersji, grupa „archiwum”"
    )
    expect(entries).to_have_count(20)
    tab.assert_clean()
