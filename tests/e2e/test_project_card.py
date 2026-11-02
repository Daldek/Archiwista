"""The project card's jobs, exports and activity, in Chromium (A-ADR-049, P5, P6).

A generated Kartograf store served offline with its projects
(``tests/fixtures/make_store.py``), and the stand-in producer's store
``pomiary`` served online (``tests/fixtures/action_source``). „Weryfikuj”
runs offline and marks each pin with what it found, while the check, the
re-pin and the restore are disabled with the offline reason; „Pokaż na
mapie” opens the project's area. On the stand-in's store a project without
sets (groups) cannot be verified, a derived file's pin shows the producer's reason
(D5) and disables its set's jobs, a set with nothing missing cannot be
restored, and the check and the re-pin of a set mark its pins. The
computer's owner writes an export of a fixture project with „Eksportuj…” and
finds its category folders and ``README.txt`` on the disk; once the project file
changes, the list says „projekt zmieniony po eksporcie — wygeneruj ponownie”
and the export is written again from the form opened on its name. With
„Utwórz też plik ZIP” the export's category folders and ``README.txt`` come
as one ZIP file from „Pobierz ZIP”. A person
the project is shared with sees the exports and „Eksportuj…” disabled with
the reason. „Aktywność” shows the 20 newest entries of the project's
activity, older ones on „Więcej”, never another project's, and a change made
on the card at once; the person it is shared with sees it too. With
``ARCHIWISTA_SCREENSHOTS=<directory>`` the card is kept as ``08-projekt.png``
(the guide's picture).
"""

import hashlib
import os
import re
import zipfile
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.projects import change_project_file
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.e2e.test_acceptance_v03 import (
    DERIVED,
    FOLDER,
    call,
    card_group,
    pin_files,
    pin_of,
    project_card,
    standin_project,
    standin_workers,
    station_line,
)
from tests.e2e.test_map import create_project_area
from tests.e2e.test_projects_view import AREA, card, group, open_projects, served_store
from tests.fixtures.browser import Served, Tab
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

PROJECT = "projekt-01"
ATTRIBUTION = "Archiwista synthetic test store\n"
CHANGED = "projekt zmieniony po eksporcie — wygeneruj ponownie"
NO_WRITE = "Eksport zapisuje tylko właściciel projektu albo administrator."
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
LOCAL = "Wodowskaz"
OFFLINE = "Tryb offline: sprawdzanie, przepinanie i przywracanie potrzebują sieci."
NO_GROUPS = "Projekt nie ma zestawów przypiętych wersji."
NO_MISSING = "Zestaw nie ma brakujących wersji."
NOT_REBUILDABLE = (
    "Producent nie odtworzy polecenia niektórych wersji (powód przy wersji): ich"
    " sprawdzanie i przywracanie, a ich zestawów przepięcie, są niedostępne."
)


def exports(page: Page) -> Locator:
    """Return the section „Eksport” of the chosen project's card."""
    panel = page.get_by_role("complementary", name="Projekt")
    return panel.get_by_role("region", name="Eksport")


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
    expect(section).to_contain_text("Projekt nie ma eksportów.")

    # Act: every group but the archive.
    section.get_by_role("button", name="Eksportuj…").click()
    form = section.get_by_role("form", name="Nowy eksport")
    form.get_by_label("Nazwa").fill("hydrograf")
    form.get_by_role("checkbox", name="archiwum").uncheck()
    form.get_by_role("button", name="Zapisz eksport").click()

    # Assert: what was written, the list, the files on the disk.
    done = section.get_by_role("status")
    expect(done).to_have_text("Zapisano eksport „hydrograf”: wersje 2.")
    expect(form).to_have_count(0)
    listed = section.get_by_role("list", name="Eksporty projektu").get_by_role(
        "listitem"
    )
    expect(listed).to_have_count(1)
    expect(listed).to_contain_text("hydrograf")
    target = directory / "eksport" / "hydrograf"
    expect(listed).to_contain_text(str(target))
    expect(listed).not_to_contain_text(CHANGED)
    assert sorted(path.name for path in target.iterdir()) == [
        "BDOT",
        "NMT",
        "README.txt",
    ]
    readme = (target / "README.txt").read_text(encoding="utf-8")
    assert readme.endswith(f"\n- {ATTRIBUTION}")

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
    form = exports(page).get_by_role("form", name="Nowy eksport")
    expect(form.get_by_label("Nazwa")).to_have_value("hydrograf")
    form.get_by_role("button", name="Zapisz eksport").click()

    # Assert
    expect(exports(page).get_by_role("status")).to_have_text(
        "Zapisano eksport „hydrograf”: wersje 3."
    )
    expect(item).not_to_contain_text(CHANGED)
    assert len(list((target / "NMT").iterdir())) == 2
    tab.assert_clean()


def test_an_export_with_a_zip_is_downloaded_from_the_card(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """„Utwórz też plik ZIP” → category folders and README.txt → „Pobierz ZIP”."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    project = store.project(PROJECT)
    directory = store.base / project.path
    pins = {pin.sha256 for group in project.groups for pin in group.pins}
    page = tab.page
    open_projects(page, served, served.token_url(), PROJECT)
    section = exports(page)
    expect(section).to_contain_text("NMT, BDOT, ORTO")

    # Act: every set, with the ZIP file.
    section.get_by_role("button", name="Eksportuj…").click()
    form = section.get_by_role("form", name="Nowy eksport")
    form.get_by_label("Nazwa").fill("hydro")
    form.get_by_role("checkbox", name="Utwórz też plik ZIP").check()
    form.get_by_role("button", name="Zapisz eksport").click()

    # Assert: the data copied into category folders, README.txt naming the sets.
    expect(section.get_by_role("status")).to_have_text(
        f"Zapisano eksport „hydro”: wersje {len(pins)}."
    )
    target = directory / "eksport" / "hydro"
    item = section.get_by_role("listitem").filter(has_text="hydro")
    expect(item).to_contain_text(str(target))
    expect(item).to_contain_text("README.txt")
    folders = sorted(path.name for path in target.iterdir() if path.is_dir())
    assert folders == ["BDOT", "NMT"]
    data = [path for path in target.rglob("*") if path.is_file()]
    copied = {
        hashlib.sha256(path.read_bytes()).hexdigest()
        for path in data
        if path.parent != target
    }
    assert copied == pins
    assert not any(path.stat().st_nlink > 1 for path in data)
    readme = (target / "README.txt").read_text(encoding="utf-8")
    for name in ("teren", "archiwum", "pokrycie"):
        assert name in readme
    assert (directory / "eksport" / "hydro.zip").is_file()

    # Act
    with page.expect_download() as started:
        item.get_by_role("link", name="Pobierz ZIP").click()
    download = started.value
    saved = tmp_path / "hydro.zip"
    download.save_as(saved)

    # Assert: the folder's content, file by file.
    assert download.suggested_filename == "hydro.zip"
    with zipfile.ZipFile(saved) as archive:
        names = sorted(name for name in archive.namelist() if not name.endswith("/"))
        assert names == sorted(path.relative_to(target).as_posix() for path in data)
        for path in data:
            member = path.relative_to(target).as_posix()
            assert archive.read(member) == path.read_bytes()
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
    old = directory / "eksport" / "stary" / "README.txt"
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
    """20 newest, „Więcej” for the rest, no other project; a set removed shows."""
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

    # Act: a set removed on the card, after the question.
    panel = page.get_by_role("complementary", name="Projekt")
    panel.get_by_role("button", name="Usuń zestaw archiwum").click()
    question = page.get_by_role("dialog", name="Usuń zestaw")
    question.get_by_role("button", name="Usuń zestaw").click()

    # Assert: the activity read again, the change first.
    expect(entries.first).to_contain_text(
        "właściciel lokalny odpięcie wersji, zestaw „archiwum”"
    )
    expect(entries).to_have_count(20)
    tab.assert_clean()


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in for the server and its workers."""
    return standin_workers(monkeypatch)


def shot(page: Page, panel: Locator) -> None:
    """Keep the card as ``08-projekt.png`` when ``ARCHIWISTA_SCREENSHOTS`` is set.

    The page grows to show the groups; the local path is covered.
    """
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        size = page.viewport_size
        assert size is not None
        page.set_viewport_size({"width": size["width"], "height": 1240})
        page.mouse.move(0, 0)
        panel.locator(".pc-path code").evaluate(
            "(code) => { code.textContent = '~/projekty/raba'; }"
        )
        panel.screenshot(path=str(Path(directory) / "08-projekt.png"))
        page.set_viewport_size(size)


def test_project_card_shows_area_holdings_and_catalog_link(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """The card shows what the store holds in the area and opens that catalog filter."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    page = tab.page
    open_projects(page, served, served.token_url(), None)
    created = create_project_area(page, store.projects_dir)
    page.goto(f"{served.base}/?view=projects&project={created['project']}")
    area = card(page).locator(".pc-area")
    groups = call(page, "GET", f"/slots?area_id={created['area_id']}&limit=1")
    assert groups["status"] == 200, groups
    assert groups["body"]["groups"]["footprint"] > 0

    # Assert: counts for the whole store, not merely the project's pinned files.
    expect(area.locator(".pc-area-holdings")).to_contain_text(
        f"Pliki w obszarze: {groups['body']['groups']['footprint']}"
    )
    expect(area.locator(".pc-area-holdings")).to_contain_text(
        f"{groups['body']['groups']['country']} plik"
    )
    expect(area.get_by_role("link", name="Pokaż na mapie")).to_have_attribute(
        "title",
        "Otwórz obszar na mapie: stan lokalny, dostępność u źródła i pobieranie",
    )

    # Act: the link opens the same area as a catalog filter.
    area.get_by_role("link", name="Pliki obszaru w Katalogu").click()

    # Assert
    expect(page).to_have_url(re.compile(f"view=catalog.*area_id={created['area_id']}"))
    expect(page.locator(".cat-area .area-card")).to_contain_text(
        "Obszar projektu Kamiennik"
    )
    tab.assert_clean()


def test_verify_runs_offline_and_marks_each_pin_while_network_jobs_say_why(
    serve: Serve, engine_tab: Tab, tmp_path: Path
) -> None:
    """„Weryfikuj” offline finds a changed file; check, re-pin, restore wait.

    In Chromium and Firefox: the card's layout of actions, reasons and marks.
    """
    # Arrange: a pinned file of the plan group changed on the disk; an area.
    tab = engine_tab
    store, served = served_store(serve, tmp_path)
    project = store.project(PROJECT)
    (changed,) = [g for g in project.groups if g.name == "teren"][0].pins[:1]
    total = sum(len(g.pins) for g in project.groups)
    page = tab.page
    open_projects(page, served, served.token_url(), PROJECT)
    (store.root / changed.version).write_bytes(b"inna tre\xc5\x9b\xc4\x87\n")
    area = call(page, "POST", "/areas", {"geometry": AREA, "name": "Raba"})
    assert area["status"] == 201, area
    page.goto(f"{served.base}/?view=map&area_id={area['body']['id']}")
    page.get_by_role("button", name="Ustaw jako obszar projektu…").click()
    form = page.get_by_role("form", name="Obszar projektu")
    form.get_by_label("Projekt").select_option(PROJECT)
    form.get_by_role("button", name="Ustaw").click()
    expect(
        page.get_by_role("status").filter(has_text="Ustawiono obszar")
    ).to_be_visible()
    page.goto(f"{served.base}/?view=projects&project={PROJECT}")
    panel = page.get_by_role("complementary", name="Projekt")
    actions = panel.get_by_role("group", name="Działania projektu")

    # Act
    actions.get_by_role("button", name="Weryfikuj").click()

    # Assert: the summary and the mark at the pin; the network jobs say why.
    expect(panel.locator(".job-status")).to_contain_text(
        f"Wersje: {total} — nienaruszona {total - 1}, inna treść w magazynie 1."
    )
    expect(group(page, "teren").locator(".pc-pin").first).to_contain_text(
        "inna treść w magazynie"
    )
    teren = group(page, "teren")
    buttons = [
        actions.get_by_role("button", name="Sprawdź aktualizacje"),
        teren.get_by_role("button", name="Sprawdź aktualizacje zestawu teren"),
        teren.get_by_role("button", name="Przepnij zestaw teren"),
        teren.get_by_role("button", name="Przywróć brakujące wersje zestawu teren"),
    ]
    for button in buttons:
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(OFFLINE)
    expect(panel.locator(".pc-why li")).to_have_text([OFFLINE])

    # Act: the project's area on the map.
    panel.locator(".pc-area").get_by_role("link", name="Pokaż na mapie").click()

    # Assert
    expect(page).to_have_url(re.compile(f"view=map.*area_id={area['body']['id']}"))
    tab.assert_clean()


def test_group_jobs_say_why_they_wait_check_and_repin_mark_the_pins(
    serve: Serve, tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """No sets; D5 at a derived pin; nothing missing; check; re-pin."""
    # Arrange: a station's two years and a derived file in the store.
    page = tab.page
    served, _, project = standin_project(
        serve,
        tmp_path,
        page,
        {
            f"{FOLDER}/2023.csv": station_line("2023.csv", "2023-12-31"),
            f"{FOLDER}/2024.csv": station_line("2024.csv", "2024-06-30"),
            DERIVED: "zlewnia\n",
        },
    )
    panel = project_card(page, served, project)
    verify = panel.get_by_role("button", name="Weryfikuj")
    expect(verify).to_be_disabled()
    expect(verify).to_have_accessible_description(NO_GROUPS)

    # Act: the years and the derived file pinned from the store.
    pin_files(page, project, LOCAL, f"{FOLDER}/2023.csv", f"{FOLDER}/2024.csv")
    pin_files(page, project, "Pochodne", DERIVED)
    panel = project_card(page, served, project)

    # Assert: D5 at the derived pin and its set; no missing version to restore.
    derived = card_group(panel, "Pochodne")
    expect(pin_of(derived, "zlewnia.csv")).to_contain_text("bez polecenia")
    expect(pin_of(derived, "zlewnia.csv")).to_contain_text("derived")
    for name in (
        "Sprawdź aktualizacje zestawu Pochodne",
        "Przepnij zestaw Pochodne",
        "Przywróć brakujące wersje zestawu Pochodne",
    ):
        button = derived.get_by_role("button", name=name)
        expect(button).to_be_disabled()
        expect(button).to_have_accessible_description(NOT_REBUILDABLE)
    local = card_group(panel, LOCAL)
    restore = local.get_by_role(
        "button", name=f"Przywróć brakujące wersje zestawu {LOCAL}"
    )
    expect(restore).to_have_accessible_description(NO_MISSING)

    # Act: the project's check (the local set only).
    panel.get_by_role("group", name="Działania projektu").get_by_role(
        "button", name="Sprawdź aktualizacje"
    ).click()

    # Assert
    status = panel.locator(".job-status")
    expect(status).to_contain_text("Wersje: 2 — aktualna 1, jest nowsza 1.")
    expect(pin_of(local, "2023.csv")).to_contain_text("aktualna")
    expect(pin_of(local, "2024.csv")).to_contain_text("nowsza: 2024-12-31")
    shot(page, panel)

    # Act
    local.get_by_role("button", name=f"Przepnij zestaw {LOCAL}").click()

    # Assert: the newer year pinned, the other kept.
    expect(status).to_contain_text(
        f"Zestaw „{LOCAL}” przepięty: bez zmian 1, nowe 1, odpięte 0."
    )
    expect(pin_of(local, "2024.csv")).to_contain_text("2024-12-31")
    tab.assert_clean()
