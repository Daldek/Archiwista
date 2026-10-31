"""File card, Projects and Store in Chromium on a real server (plan v0.1, step 11).

Every test serves a generated Kartograf store offline, waits for the
scheduler's first full scan and checks what a person sees against what the
producer wrote — Kartograf's own sidecars and segment names — and against
the generator's manifest of the store and its project files.
"""

import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath, PureWindowsPath
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from kartograf import describe_segment, read_sidecar
from playwright.sync_api import Locator, Page, expect

from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import principal_for
from archiwista.config import AppSettings, StoreConfig
from archiwista.security import CSRF_HEADER, issue_one_time_token
from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import (
    ExpectedEntry,
    ExpectedPin,
    StoreManifest,
    make_store,
)

Serve = Callable[..., Served]

STORE = "zespol"
ALIAS = "Z:\\"
SHOW = "Pokaż wartość techniczną"
INDEX_TIMEOUT_S = 60.0
# True once every store has a finished scan and no job runs (the scheduler's
# first full scan, or a scan started by a test).
INDEXED = """
async () => {
  const csrf = sessionStorage.getItem("archiwista_csrf") ?? "";
  const answer = await fetch("/api/v1/health", {
    headers: { "X-Archiwista-CSRF": csrf },
  });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}
"""


def settings_of(store: StoreManifest) -> AppSettings:
    """Return offline settings: the store as ``zespol`` (``Z:``) and its projects."""
    config = StoreConfig(
        id=STORE,
        name="Zespół",
        kartograf=store.root,
        kind="local",
        path_aliases={f"{store.base}/": ALIAS},
    )
    return AppSettings(
        offline=True, stores=(config,), project_dirs=(store.projects_dir,)
    )


def wait_indexed(page: Page) -> None:
    """Wait until every store's scan has ended and no job runs (`/health`)."""
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the stores were not indexed in time"
        page.wait_for_timeout(200)


def served_store(
    serve: Serve, tab: Tab, tmp_path: Path
) -> tuple[StoreManifest, Served, Page]:
    """Generate a store, serve it and open a session once its first scan ended."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = serve(settings_of(store))
    page = tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    wait_indexed(page)
    return store, served, page


def open_card(
    page: Page, served: Served, slot: str, *, version: str | None = None
) -> Locator:
    """Open the file card of a slot (or one version of it) over the Store view."""
    params = {"view": "store", "file": f"{STORE}/{slot}"}
    if version is not None:
        params["file_version"] = version
    page.goto(f"{served.base}/?{urlencode(params)}")
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card).to_be_visible()
    return card


def value(scope: Locator | Page, name: str) -> Locator:
    """Return the value of a label in a definition list (``<dt>`` → ``<dd>``)."""
    return scope.locator(f"dt:text-is('{name}') + dd")


def reveal(scope: Locator) -> Locator:
    """Show the technical values of the first name in ``scope``; return it."""
    scope.get_by_role("button", name=SHOW).first.click()
    return scope


def raw(scope: Locator, text: str) -> Locator:
    """Return a technical value shown in ``scope`` (the exact text of a code)."""
    return scope.locator("code").get_by_text(text, exact=True)


def query(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def archive_pin(store: StoreManifest) -> ExpectedPin:
    """Return the pin of an older version: group ``archiwum`` of ``projekt-01``."""
    groups = store.project("projekt-01").groups
    return next(group for group in groups if group.name == "archiwum").pins[0]


def link_of(store: StoreManifest, slot: str) -> ExpectedEntry:
    """Return the standard-path entry of a slot."""
    return next(entry for entry in store.by_kind("link") if entry.path == slot)


def versions_of(store: StoreManifest, slot: str) -> list[ExpectedEntry]:
    """Return the versions of a slot: same segment, hierarchy and file name."""
    link = link_of(store, slot)
    name = PurePosixPath(slot).name
    return [
        entry
        for entry in store.by_kind("version")
        if (entry.segment, entry.hierarchy) == (link.segment, link.hierarchy)
        and PurePosixPath(entry.path).name == name
    ]


def current_of(store: StoreManifest, slot: str) -> ExpectedEntry:
    """Return the version a slot's standard path holds."""
    target = link_of(store, slot).version_path
    return next(entry for entry in versions_of(store, slot) if entry.path == target)


def test_human_labels_expose_raw_values(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """Names, year and licence for people; segment, EPSG, SHA-256, path a click away."""
    store, served, page = served_store(serve, tab, tmp_path)
    slot = archive_pin(store).path
    current = current_of(store, slot)
    sidecar = read_sidecar(store.root / current.path)
    segment = describe_segment(current.segment)
    unknown = next(e for e in store.by_case("unknown_segment") if e.kind == "link")
    assert segment.known and not describe_segment(unknown.segment).known
    assert sidecar.data_year == current.data_year and sidecar.data_date is not None
    assert (sidecar.horizontal_crs, sidecar.vertical_crs) == ("EPSG:2180", "EPSG:9651")

    card = open_card(page, served, slot)
    product = reveal(card.locator(".fc-product"))
    horizontal = reveal(value(card, "Układ poziomy"))
    vertical = reveal(value(card, "Układ wysokości"))
    sha = reveal(value(card, "SHA-256"))

    expect(product).to_contain_text(segment.name)
    expect(raw(product, current.segment)).to_be_visible()
    expect(raw(product, str(current.dataset_key))).to_be_visible()
    expect(value(card, "Rok danych")).to_have_text(str(current.data_year))
    expect(value(card, "Data danych")).to_have_text(
        str(sidecar.data_date).replace("-", ".")
    )
    expect(horizontal).to_contain_text("PL-1992")
    expect(raw(horizontal, "EPSG:2180")).to_be_visible()
    expect(vertical).to_contain_text("PL-EVRF2007-NH")
    expect(raw(vertical, "EPSG:9651")).to_be_visible()
    expect(sha).to_contain_text(f"{str(current.sha256)[:12]}…")
    expect(raw(sha, str(current.sha256))).to_be_visible()
    assert sidecar.license is not None
    expect(card.locator(".fc-license")).to_contain_text(sidecar.license["id"])
    expect(card.locator(".fc-attribution")).to_have_text(
        f"Atrybucja: {sidecar.license['attribution']}"
    )
    expect(raw(card, str(store.root / current.path))).to_be_visible()

    other = open_card(page, served, unknown.path)
    other_product = reveal(other.locator(".fc-product"))

    expect(other_product).to_contain_text(
        "Nieznany produkt — segment nierozpoznany przez wtyczkę kartograf"
    )
    expect(raw(other_product, unknown.segment)).to_be_visible()
    tab.assert_clean()


def test_pinned_old_version_visible(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """An older pinned version names its project on the axis and in the project."""
    store, served, page = served_store(serve, tab, tmp_path)
    pin = archive_pin(store)
    pins = [
        (project.name, group.name, task_pin)
        for project in store.projects
        if project.valid
        for group in project.groups
        for task_pin in group.pins
        if task_pin.path == pin.path and task_pin.present
    ]
    assert not pin.current and len(pins) > 1

    card = open_card(page, served, pin.path)
    axis = card.locator(".fc-axis").get_by_role("listitem")

    for project, name, pinned in pins:
        expect(axis.filter(has_text=pinned.label)).to_contain_text(
            f"Przypięta w: {project} ({name})"
        )

    page.goto(f"{served.base}/?view=projects&project=projekt-01")
    group = page.locator(".pc-group").filter(has_text="archiwum")
    expect(group).to_contain_text("starsza wersja")
    group.get_by_role("link", name=pin.label).click()
    opened = page.get_by_role("dialog", name=PurePosixPath(pin.path).name)

    # The axis only: the version's copy button names its path, which holds the label.
    picked = opened.locator(".fc-axis").get_by_role("button", name=pin.label)
    expect(picked).to_have_attribute("aria-pressed", "true")
    expect(opened.get_by_role("heading", name=f"Wersja {pin.label}")).to_be_visible()
    assert query(page) == {
        "view": "projects",
        "project": "projekt-01",
        "file": f"{STORE}/{pin.path}",
        "file_version": pin.version,
    }
    tab.assert_clean()


def test_copy_attribution_and_path(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The attribution, the version's path, the standard path and its alias copy."""
    store, served, page = served_store(serve, tab, tmp_path)
    page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin=served.base
    )
    slot = archive_pin(store).path
    current = current_of(store, slot)
    licence = read_sidecar(store.root / current.path).license
    assert licence is not None
    attribution = licence["attribution"]
    alias = str(PureWindowsPath(ALIAS, "data", *PurePosixPath(slot).parts))
    copied: dict[str, str] = {}

    card = open_card(page, served, slot, version=current.path)
    for name in (
        "Kopiuj atrybucję",
        "Kopiuj ścieżkę wersji",
        "Kopiuj ścieżkę standardową",
    ):
        action = card.locator(".copy-action").filter(
            has=page.get_by_role("button", name=name, exact=True)
        )
        action.get_by_role("button").click()
        expect(action.get_by_role("status")).to_have_text("Skopiowano")
        copied[name] = page.evaluate("navigator.clipboard.readText()")
    card.get_by_role("button", name=f"Kopiuj: {alias}", exact=True).click()
    expect(
        card.get_by_role("button", name=f"Skopiowano: {alias}", exact=True)
    ).to_be_visible()
    copied["alias"] = page.evaluate("navigator.clipboard.readText()")
    page.keyboard.press("Escape")

    assert copied == {
        "Kopiuj atrybucję": attribution,
        "Kopiuj ścieżkę wersji": str(store.root / current.path),
        "Kopiuj ścieżkę standardową": str(store.root / slot),
        "alias": alias,
    }
    expect(card).to_have_count(0)
    assert query(page) == {"view": "store"}
    tab.assert_clean()


def test_invalid_project_file_visible(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """A project file breaking a rule: listed with why; its card says how to fix it."""
    store, served, page = served_store(serve, tab, tmp_path)
    broken = next(p for p in store.projects if p.case == "invalid_project_file")

    page.goto(f"{served.base}/?view=projects")
    row = page.get_by_role("row").filter(has_text=broken.name)
    expect(row).to_contain_text("Błędny plik projektu: Archiwista nie używa żadnej")
    row.get_by_role("link", name=broken.name).click()
    panel = page.get_by_role("complementary", name="Projekt")

    expect(panel.get_by_role("heading", name=broken.name)).to_be_visible()
    issue = panel.locator(".issue")
    expect(issue).to_contain_text("Niepoprawny plik projektu")
    expect(issue).to_contain_text("/groups/0/name")
    expect(issue).to_contain_text("Jak naprawić: Popraw archiwista-project.json")
    expect(panel).to_contain_text("Archiwista nie czyta grup tego pliku projektu.")
    assert query(page) == {"view": "projects", "project": broken.name}
    tab.assert_clean()


def test_two_links_counted_once(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """A version behind the standard path and full_sheet/ counts once in the usage."""
    store, served, page = served_store(serve, tab, tmp_path)
    nmt = [e for e in store.entries if e.segment.startswith("nmt/")]
    versions = {e.path: e.size_bytes or 0 for e in nmt if e.kind == "version"}
    plain = [e for e in nmt if e.kind == "link" and e.version_path is None]
    standard = {e.version_path: e.path for e in nmt if e.kind == "link"}
    shared = [e for e in nmt if e.kind == "full_sheet" and e.version_path in standard]
    slot = standard[shared[0].version_path]

    page.goto(f"{served.base}/?view=store")
    row = page.get_by_role("row").filter(has=page.get_by_text("nmt", exact=True))
    cells = row.get_by_role("cell")
    expect(cells.nth(0)).to_have_text(str(len(versions) + len(plain)))
    reveal(cells.nth(1))
    expect(raw(cells.nth(1), str(sum(versions.values())))).to_be_visible()
    card = open_card(page, served, slot)
    axis = card.locator(".fc-axis").get_by_role("listitem")

    expect(axis).to_have_count(len(versions_of(store, slot)))
    expect(
        axis.filter(has_text="bieżąca").filter(has_text="pełny arkusz")
    ).to_have_count(1)
    tab.assert_clean()


def test_disconnected_store_banner(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """A disconnected store: a banner with its last pass, the index's answers kept."""
    store, served, page = served_store(serve, tab, tmp_path)
    slot = archive_pin(store).path
    page.goto(f"{served.base}/?view=store")
    indexed = value(page, "Ostatnie pełne przejście").inner_text()
    disconnected = store.root.with_name("data-odlaczony")
    banner = page.get_by_role("region", name="Stan indeksu")

    store.root.rename(disconnected)
    page.get_by_role("button", name="Odśwież").click()
    expect(page.locator(".job")).to_contain_text("Skan: błąd")
    expect(banner).to_contain_text(
        f"Magazyn „Zespół” jest niedostępny. Wyniki pochodzą z indeksu z {indexed}"
    )
    card = open_card(page, served, slot)
    expect(card.get_by_role("note")).to_contain_text(
        f"Magazyn „Zespół” jest niedostępny — stan z indeksu z {indexed}"
    )
    expect(card.locator(".fc-axis").get_by_role("listitem")).to_have_count(
        len(versions_of(store, slot))
    )
    page.keyboard.press("Escape")
    disconnected.rename(store.root)
    page.get_by_role("button", name="Odśwież").click()

    expect(page.locator(".job")).to_contain_text("Skan: zakończone")
    expect(banner).to_have_count(0)
    tab.assert_clean()


def test_link_check_result_on_file_card(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The link check's result arrives on the card; a mismatch becomes a problem."""
    store, served, page = served_store(serve, tab, tmp_path)
    slot = archive_pin(store).path
    current = current_of(store, slot)
    mismatch = next(e for e in store.by_case("link_mismatch") if e.kind == "link")

    card = open_card(page, served, slot)
    card.get_by_role("button", name="Potwierdź bieżącą wersję").click()
    expect(card.locator(".job-summary")).to_have_text(
        f"Potwierdzono: ścieżka standardowa trzyma wersję {current.label}."
    )
    other = open_card(page, served, mismatch.path)
    expect(other.locator(".issue")).to_have_count(0)
    other.get_by_role("button", name="Potwierdź bieżącą wersję").click()

    expect(other.locator(".job-summary")).to_contain_text("Niezgodność")
    expect(other.locator(".job-notices")).to_contain_text(mismatch.path)
    expect(other.locator(".issue")).to_have_count(1)
    expect(other.locator(".issue")).to_contain_text(mismatch.path)
    expect(other.locator(".issue")).to_contain_text("Jak naprawić:")
    tab.assert_clean()


def test_store_scan_row_shows_actor(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The last scan names who started it: the local owner, then an administrator."""
    _, served, page = served_store(serve, tab, tmp_path)
    page.goto(f"{served.base}/?view=store")
    row = value(page, "Ostatni skan")
    expect(row).to_contain_text("zakończone")
    expect(row).to_contain_text("Wykonawca: właściciel lokalny")
    expect(raw(reveal(row), "local")).to_be_visible()
    state = StateStore(served.paths.state_file)
    # Scanning a store is an administrator's (`store.scan`).
    state.add_user("olga", name="Olga Owczarek", roles=["admin"], actor=LOCAL_OWNER)
    olga = principal_for(state, "olga")
    assert olga is not None
    token = issue_one_time_token(served.paths.index_file, "startup", minted_by=olga)

    with httpx.Client(base_url=served.base) as client:
        session = client.post("/api/v1/session", json={"token": token.token})
        started = client.post(
            f"/api/v1/stores/{STORE}/scan",
            json={"mode": "incremental"},
            headers={CSRF_HEADER: session.json()["csrf_token"]},
        )
    wait_indexed(page)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")

    assert started.status_code == 202, started.text
    assert started.json()["actor"] == "olga"
    expect(row).to_contain_text("Wykonawca: olga")
    expect(raw(row, started.json()["id"])).to_be_visible()
    tab.assert_clean()


def test_store_full_scan_row_and_button(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The last full scan shows with its interval; „Pełny skan” asks for a full one."""
    _, served, page = served_store(serve, tab, tmp_path)
    page.goto(f"{served.base}/?view=store")
    row = value(page, "Ostatni pełny skan")
    expect(row).not_to_contain_text("jeszcze nie było")
    expect(row).to_contain_text("co 24 h")

    with page.expect_request(
        lambda request: (
            request.method == "POST"
            and request.url.endswith(f"/api/v1/stores/{STORE}/scan")
        )
    ) as posted:
        page.get_by_role("button", name="Pełny skan").click()
    wait_indexed(page)

    assert posted.value.post_data_json == {"mode": "full"}
    expect(page.locator(".job")).to_contain_text("Skan: zakończone")
    tab.assert_clean()
