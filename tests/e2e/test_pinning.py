"""„Dodaj do projektu…” in the views, in Chromium (A-ADR-049 decision 8, P3).

A generated Kartograf store served offline (``tests/fixtures/make_store.py``)
with its projects. „Stan lokalny” of an area pins the current versions of a
product's files in it into a new group; the Katalog, with filters, refuses a
taken name at the group's field and then adds its rows to that local group;
the file card pins an older version, and the project card unpins it and
removes its group, each after a question (the window also in Firefox). A
person who may change no project finds „Dodaj do projektu…” disabled with
the reason. No request leaves the server.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.sync_api import Locator, Page, expect

from archiwista.auth import access_key
from archiwista.config import AppSettings, StoreConfig
from archiwista.projects import PROJECT_FILE
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import NMT, StoreManifest, make_store
from tests.fixtures.permissions import add_people, principal, share

Serve = Callable[..., Served]

STORE = "zespol"
PROJECT = "projekt-01"
INDEX_TIMEOUT_S = 60.0
READ_TIMEOUT_MS = 30_000
NO_PROJECT = (
    "Ta sesja nie może zmienić żadnego projektu: przypina właściciel projektu albo"
    " administrator. Własny projekt zakłada „Nowy projekt…” w widoku Projekty."
)
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
API = """async (path) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch(`/api/v1${path}`, { headers });
  return answer.json();
}"""


def served_store(serve: Serve, tmp_path: Path) -> tuple[StoreManifest, Served]:
    """Generate a store with its projects and serve it offline."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store.root, kind="local")
    settings = AppSettings(
        offline=True, stores=(config,), project_dirs=(store.projects_dir,)
    )
    return store, serve(settings)


def start(page: Page, url: str) -> None:
    """Open the session of ``url`` and wait until the store is scanned."""
    page.goto(url)
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the store was not scanned in time"
        page.wait_for_timeout(200)


def api(page: Page, path: str, query: dict[str, str] | None = None) -> Any:
    """Return the JSON answer of a ``GET`` made with the page's session."""
    return page.evaluate(API, f"{path}?{urlencode(query)}" if query else path)


def rows(page: Page, query: dict[str, str]) -> int:
    """Return the rows of a ``GET /slots`` query on every page."""
    groups = api(page, "/slots", {**query, "limit": "1"})["groups"]
    return int(groups["footprint"] + groups["country"] + groups["none"])


def versions(page: Page, query: dict[str, str]) -> set[str]:
    """Return the versions of the rows of a query (one page of 200 holds them)."""
    answer = api(page, "/slots", {**query, "limit": "200"})
    assert answer["next_cursor"] is None
    return {item["version"]["path"] for item in answer["items"] if item["version"]}


def project_file(store: StoreManifest) -> Any:
    """Return the fixture project's file as JSON."""
    path = store.base / store.project(PROJECT).path / PROJECT_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def group_of(store: StoreManifest, name: str) -> Any:
    """Return a group of the fixture project's file."""
    return next(item for item in project_file(store)["groups"] if item["name"] == name)


def pin_window(page: Page) -> Locator:
    """Return the window of „Dodaj do projektu…”."""
    return page.get_by_role("dialog", name="Dodaj do projektu")


def choose_project(window: Locator) -> None:
    """Choose the fixture project in the window."""
    window.get_by_label("Projekt", exact=True).select_option(label=PROJECT)


def nmt_sheet(store: StoreManifest) -> str:
    """Return the sheet code of the first regular NMT sheet of the store."""
    sheet = next(
        entry
        for entry in store.by_kind("link")
        if entry.segment == NMT
        and entry.family == "asc_sheet"
        and entry.case == "regular"
    )
    assert sheet.unit is not None
    return sheet.unit


def test_pins_from_the_local_state_and_the_catalog_into_one_group(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Area's NMT → new group; Katalog: a taken name refused, then added to it."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    page = tab.page
    start(page, served.token_url())
    page.goto(f"{served.base}/?view=map&product=nmt")
    page.get_by_label("Godło arkusza").fill(nmt_sheet(store))
    page.get_by_role("button", name="Wybierz", exact=True).click()
    local = page.get_by_role("region", name="Stan lokalny")
    expect(local.get_by_text("lokalnie 100% obszaru")).to_be_visible(
        timeout=READ_TIMEOUT_MS
    )
    page.wait_for_function("() => new URLSearchParams(location.search).has('area_id')")
    area = parse_qs(urlsplit(page.url).query)["area_id"][0]
    local_query = {"product": "nmt", "area_id": area, "store": STORE}
    in_area = rows(page, {**local_query, "versions": "current"})
    current = versions(page, {**local_query, "versions": "current"})

    # Act: the area's current NMT versions into a new group.
    local.get_by_role("button", name="Dodaj do projektu…").click()
    window = pin_window(page)
    expect(window).to_contain_text("Bieżące wersje plików")
    expect(window).to_contain_text(f"{in_area} wiersz")
    choose_project(window)
    window.get_by_label("Nazwa nowej grupy").fill("NMT obszaru")
    window.get_by_role("button", name="Przypnij").click()

    # Assert
    expect(window.get_by_role("status")).to_contain_text(
        f"Grupa „NMT obszaru” projektu „{PROJECT}”: przypięte {len(current)},"
        " już były 0,"
    )
    group = group_of(store, "NMT obszaru")
    assert group["origin"]["kind"] == "local"
    assert [item["from"] for item in group["origin"]["selections"]] == ["local_state"]
    assert {pin["version"] for pin in group["pins"]} == current
    window.get_by_role("button", name="Zamknij").click()
    expect(window).to_be_hidden()

    # Act: the Katalog of every NMT version; the taken name first.
    query = {"product": "nmt", "versions": "all"}
    page.goto(f"{served.base}/?view=catalog&{urlencode(query)}")
    every = rows(page, query)
    held = versions(page, query)
    page.get_by_role("button", name="Dodaj do projektu…").click()
    window = pin_window(page)
    expect(window).to_contain_text("Wiersze Katalogu z obecnymi filtrami")
    expect(window).to_contain_text(f"{every} wiersz")
    choose_project(window)
    name = window.get_by_label("Nazwa nowej grupy")
    name.fill("nmt OBSZARU")
    window.get_by_role("button", name="Przypnij").click()

    # Assert: refused at the group's field; nothing written.
    expect(name).to_have_attribute("aria-invalid", "true")
    expect(window.locator(".pin-group .field-error")).to_contain_text(
        "ma już grupę „NMT obszaru”"
    )
    assert len(group_of(store, "NMT obszaru")["pins"]) == len(current)

    # Act: into the local group instead.
    window.get_by_label("Grupa lokalna projektu", exact=True).check()
    window.get_by_role("combobox", name="Grupa lokalna projektu").select_option(
        "NMT obszaru"
    )
    window.get_by_role("button", name="Przypnij").click()

    # Assert: the versions the store cannot pin are listed with why.
    expect(window.get_by_role("status")).to_contain_text(
        f", już były {len(current)}, pominięte "
    )
    skipped = window.get_by_role("list", name="Pominięte wersje").locator("li")
    left_out = {text.split(":")[0].strip() for text in skipped.all_inner_texts()}
    assert left_out
    expect(window.get_by_role("status")).to_contain_text(
        f"przypięte {len(held - current - left_out)}, już były {len(current)},"
        f" pominięte {len(left_out)}."
    )
    group = group_of(store, "NMT obszaru")
    assert {pin["version"] for pin in group["pins"]} == held - left_out
    assert [item["from"] for item in group["origin"]["selections"]] == [
        "local_state",
        "catalog",
    ]
    assert tab.foreign_requests(served.base) == []
    tab.assert_clean()


def test_an_older_version_pinned_from_the_file_card_is_unpinned_on_the_card(
    serve: Serve, engine_tab: Tab, tmp_path: Path
) -> None:
    """File card's older version → new group; „Odepnij” and „Usuń grupę” asked first."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    page = engine_tab.page
    older = next(
        group for group in store.project(PROJECT).groups if group.name == "archiwum"
    ).pins[0]
    start(page, served.token_url())
    address = {
        "view": "catalog",
        "file": f"{STORE}/{older.path}",
        "file_version": older.version,
    }
    page.goto(f"{served.base}/?{urlencode(address)}")
    card = page.get_by_role("dialog", name=Path(older.path).name)

    # Act
    card.get_by_role("button", name="Dodaj do projektu…").click()
    window = pin_window(page)
    expect(window).to_contain_text(f"Wersja {older.label}")
    expect(window).to_contain_text("1 wersja")
    choose_project(window)
    window.get_by_label("Nazwa nowej grupy").fill("Starsza")
    window.get_by_role("button", name="Przypnij").click()

    # Assert
    expect(window.get_by_role("status")).to_contain_text("przypięte 1, już były 0")
    group = group_of(store, "Starsza")
    assert [pin["version"] for pin in group["pins"]] == [older.version]
    assert group["origin"]["selections"][0]["from"] == "file"

    # Act: the project card; its pin unpinned after the question.
    window.get_by_role("link", name="Otwórz projekt").click()
    expect(window).to_be_hidden()
    panel = page.get_by_role("complementary", name="Projekt")
    head = page.locator(".pc-group-head b").get_by_text("Starsza", exact=True)
    shown = panel.locator(".pc-group").filter(has=head)
    expect(shown.locator(".pc-pin")).to_contain_text("starsza wersja")
    shown.get_by_role("button", name=f"Odepnij {older.label} z grupy Starsza").click()
    question = page.get_by_role("dialog", name="Odepnij")
    expect(question).to_contain_text(f"Odpiąć {older.label} z grupy „Starsza”?")
    question.get_by_role("button", name="Odepnij").click()

    # Assert
    expect(question).to_be_hidden()
    expect(shown).to_contain_text("grupa jest pusta")
    assert group_of(store, "Starsza")["pins"] == []

    # Act: the group removed after the question.
    shown.get_by_role("button", name="Usuń grupę Starsza").click()
    question = page.get_by_role("dialog", name="Usuń grupę")
    question.get_by_role("button", name="Usuń grupę").click()

    # Assert
    expect(panel.get_by_role("status")).to_contain_text("Usunięto grupę „Starsza”.")
    expect(shown).to_have_count(0)
    names = [item["name"] for item in project_file(store)["groups"]]
    assert "Starsza" not in names
    assert engine_tab.foreign_requests(served.base) == []
    engine_tab.settle()
    engine_tab.assert_clean()


def test_a_person_who_may_change_no_project_finds_the_action_disabled(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Shared with her, not hers: disabled with the reason; no „Odepnij”."""
    # Arrange
    store, served = served_store(serve, tmp_path)
    project = store.project(PROJECT)
    state = StateStore(served.paths.state_file)
    add_people(state)
    share(state, access_key(store.base / project.path), "users")
    issued = issue_one_time_token(
        served.paths.index_file, "startup", minted_by=principal(state, "listed")
    )
    page = tab.page
    start(page, fragment_url(served.base, issued.token))

    # Act
    page.goto(f"{served.base}/?view=catalog&product=nmt")

    # Assert
    button = page.get_by_role("button", name="Dodaj do projektu…")
    expect(button).to_be_disabled()
    expect(button).to_have_accessible_description(NO_PROJECT)

    # Act: her view of the project.
    page.goto(f"{served.base}/?view=projects&project={project.name}")

    # Assert
    panel = page.get_by_role("complementary", name="Projekt")
    expect(panel.locator(".pc-pin").first).to_be_visible()
    expect(panel.get_by_role("button", name="Odepnij")).to_have_count(0)
    expect(panel.get_by_role("button", name="Usuń grupę")).to_have_count(0)
    tab.assert_clean()
