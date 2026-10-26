"""Projects' own data and snapshots in Chromium on a real server (plan v0.2, step 15).

One generated store is served for the module, offline; its project
``projekt-01`` gets a data folder with a GeoPackage of two layers, a
Shapefile, a GeoTIFF, a GeoJSON and a GeoPackage of a single point. The
project's view lists them with their change since the last snapshot, the
card of a file shows its metadata, versions and preview, „Zrób migawkę…”
opens the plan window and starts the ``snapshot`` job, the project's map
draws the files' extents, the Wachlarz shows the working file on top and
„Porównaj z migawką…” opens the comparison. A project's data folder changes
on its sharing screen, which a project without an owner offers only to
administrators.
"""

import json
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, ConfigStore, StoreConfig
from archiwista.index import own_file_id
from archiwista.security import fragment_url, issue_one_time_token
from archiwista.sources.registry import load_registry
from archiwista.state import StateStore
from tests.fixtures.browser import Served, Tab
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import StoreManifest, make_store
from tests.fixtures.own_data import OwnFolderManifest, make_own_folder
from tests.fixtures.permissions import Who, add_people, principal

STORE = "zespol"
PROJECT = "projekt-01"
OTHER_PROJECT = "projekt-02"
FAMILIES = ("gpkg_layers", "shp_full", "tif_2180", "geojson_wgs84", "gpkg_5514_control")
WAIT_S = 60.0
# Directory for the screenshots of a step's report; none are taken when unset.
SHOTS = os.environ.get("ARCHIWISTA_SCREENSHOTS")
BLOB = re.compile(r"^blob:")
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""


@dataclass(frozen=True)
class OwnServer:
    """The module's store, its served application and the project's data folder."""

    store: StoreManifest
    served: Served
    folder: OwnFolderManifest


@pytest.fixture(scope="module")
def own_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[OwnServer]:
    """Serve a generated store whose project ``projekt-01`` has own data."""
    root = tmp_path_factory.mktemp("own")
    store = make_store(root / "store", slots=24, seed=11, projects=5)
    project_dir = store.base / store.project(PROJECT).path
    folder = make_own_folder(project_dir / "dane", families=FAMILIES)
    paths = local_paths(root)
    ConfigStore(paths.config_file).save(
        AppSettings(
            offline=True,
            stores=(
                StoreConfig(
                    id=STORE, name="Zespół", kartograf=store.root, kind="local"
                ),
            ),
            project_dirs=(store.projects_dir,),
        )
    )
    with serving(paths, registry=load_registry(cache_dir=paths.cache_dir)) as (
        server,
        _,
    ):
        yield OwnServer(store, Served(server, paths), folder)


def call(page: Page, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    assert answer["status"] in (200, 201, 202), answer
    return answer["body"]


def wait_for(page: Page, found: Callable[[], Any], what: str) -> Any:
    """Wait until ``found`` gives something true; return it."""
    deadline = time.monotonic() + WAIT_S
    while not (value := found()):
        assert time.monotonic() < deadline, f"not in time: {what}"
        page.wait_for_timeout(200)
    return value


def finished(page: Page, job: dict[str, Any]) -> dict[str, Any]:
    """Wait for a job to end; return it."""
    done = ("succeeded", "failed", "interrupted", "cancelled")
    ended: dict[str, Any] = wait_for(
        page,
        lambda: (
            (state := call(page, "GET", f"/jobs/{job['id']}"))["state"] in done
            and state
        ),
        f"job {job['id']}",
    )
    assert ended["state"] == "succeeded", ended
    return ended


def open_session(tab: Tab, own: OwnServer) -> Page:
    """Start a session, wait for the store's index and scan the project's data."""
    page = tab.page
    page.goto(own.served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    wait_for(
        page,
        lambda: all(
            item["state"]["last_scan"] is not None
            and item["state"]["running_job"] is None
            for item in call(page, "GET", "/health")["stores"]
        ),
        "the store's index",
    )
    finished(page, call(page, "POST", f"/projects/{PROJECT}/scan"))
    return page


def file_url(path: str, route: str = "") -> str:
    """Return the API path of a file of ``projekt-01`` (below ``/api/v1``)."""
    base = f"/projects/{PROJECT}/files/{own_file_id(path)}"
    return f"{base}/{route}" if route else base


def snapshot(page: Page, path: str, note: str) -> dict[str, Any]:
    """Make a snapshot of a file through the API; return its job's result."""
    job = call(page, "POST", file_url(path, "snapshots"), {"note": note})
    result: dict[str, Any] = finished(page, job)["result"]
    return result


def card_address(own: OwnServer, path: str, **params: str) -> str:
    """Return the projects view with the card of an own file over it."""
    query = {
        "view": "projects",
        "project": PROJECT,
        "own": f"{PROJECT}/{own_file_id(path)}",
        **params,
    }
    return f"{own.served.base}/?{urlencode(query)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def shot(page: Page, name: str) -> None:
    """Keep a screenshot of the page for the step's report (if asked for)."""
    if SHOTS is None:
        return
    Path(SHOTS).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))


def sharing(page: Page) -> Locator:
    """Open „Udostępnij…” of the chosen project; return its window."""
    card = page.get_by_role("complementary", name="Projekt")
    card.get_by_role("button", name="Udostępnij…").click()
    window = page.get_by_role("dialog")
    expect(window.get_by_label("Folder danych własnych")).to_be_visible()
    return window


def test_project_own_data_on_map_and_card(own_server: OwnServer, tab: Tab) -> None:
    """Criterion 6: the project lists GPKG, SHP, GeoTIFF; card, preview and map."""
    page = open_session(tab, own_server)
    gpkg = own_server.folder.file("gpkg_layers")
    point = own_server.folder.file("gpkg_5514_control")
    requests: list[tuple[str, int]] = []
    page.on(
        "response", lambda response: requests.append((response.url, response.status))
    )

    page.goto(f"{own_server.served.base}/?view=projects&project={PROJECT}")
    group = page.locator(".own-group")
    files = group.get_by_role("list", name="Pliki danych własnych")
    for entry in own_server.folder.files:
        expect(files).to_contain_text(entry.path.rsplit("/", 1)[-1])
    expect(group).to_contain_text("bez migawki")
    shot(page, "01-projekt-dane-wlasne")
    files.get_by_role("link", name=gpkg.path).click()
    card = page.get_by_role("dialog", name=gpkg.path)
    expect(card).to_contain_text("Warstwy i schemat")
    for layer in gpkg.layers:
        expect(card).to_contain_text(layer.name)
    expect(card).to_contain_text("PL-1992")
    card.get_by_role("tab", name="Podgląd").click()
    expect(card.locator("img.pv-image")).to_have_attribute("src", BLOB)
    shot(page, "02-karta-pliku-wlasnego")

    # The card's drawer covers the side panel: Esc closes it first.
    page.keyboard.press("Escape")
    expect(card).to_be_hidden()
    group.get_by_role("link", name="Pokaż na mapie").click()
    legend = page.locator(".own-legend")
    expect(legend).to_contain_text(f"Zasięgi plików: {len(own_server.folder.files)}")
    assert query_of(page)["project"] == PROJECT
    wait_for(
        page,
        lambda: any(
            "/map/footprints" in url and f"project={PROJECT}" in url
            for url, _ in requests
        ),
        "pinned outlines",
    )
    shot(page, "03-mapa-projektu")

    page.goto(
        f"{own_server.served.base}/?"
        + urlencode(
            {
                "view": "map",
                "project": PROJECT,
                "preview": f"file:{PROJECT}:{point.path}",
            }
        )
    )
    expect(page.locator(".legend-section").filter(has_text=point.path)).to_contain_text(
        "Obiekty pliku w widoku"
    )
    features = wait_for(
        page,
        lambda: [
            status
            for url, status in requests
            if "/features?" in url and own_file_id(point.path) in url
        ],
        "features",
    )
    # A single point's bounds have no area: the view asked for is widened.
    assert set(features) == {200}, features
    shot(page, "04-mapa-punkt")
    tab.assert_clean()


def test_snapshot_plan_then_job_then_new_snapshot(
    own_server: OwnServer, tab: Tab
) -> None:
    """The plan window shows the plan; the job runs; the snapshot stands on the axis."""
    page = open_session(tab, own_server)
    gpkg = own_server.folder.file("gpkg_layers")
    page.goto(card_address(own_server, gpkg.path))
    card = page.get_by_role("dialog", name=gpkg.path)
    card.get_by_role("button", name="Zrób migawkę…").click()
    plan = page.locator("dialog.own-plan")
    expect(plan).to_contain_text("Zrobić migawkę?")
    expect(plan).to_contain_text("kopia zapasowa SQLite")
    expect(plan).to_contain_text(".wersje")
    expect(plan).to_contain_text("Tylko przyrost")
    plan.get_by_label("Opis migawki").fill("nowy kolektor deszczowy")
    shot(page, "05-okno-planu-migawki")
    plan.get_by_role("button", name="Zrób migawkę").click()
    expect(plan.locator(".job-summary")).to_contain_text(
        "zapisana", timeout=WAIT_S * 1000
    )
    label = call(page, "GET", file_url(gpkg.path))["snapshots"][0]["label"]
    plan.get_by_role("button", name="Zamknij").click()
    expect(plan).to_be_hidden()
    axis = card.locator(".own-axis")
    expect(axis).to_contain_text(label)
    expect(axis).to_contain_text("nowy kolektor deszczowy")
    expect(card).to_contain_text("bez zmian od migawki z")
    shot(page, "06-po-migawce")
    tab.assert_clean()


def test_same_content_shows_unchanged_notice(own_server: OwnServer, tab: Tab) -> None:
    """Criterion 9: the plan says „bez zmian od migawki z …”; the job makes none."""
    page = open_session(tab, own_server)
    shp = own_server.folder.file("shp_full")
    first = snapshot(page, shp.path, "pierwsza")
    page.goto(card_address(own_server, shp.path))
    page.get_by_role("button", name="Zrób migawkę…").click()
    plan = page.locator("dialog.own-plan")
    expect(plan.locator(".own-plan-unchanged")).to_contain_text(
        "Bez zmian od migawki z"
    )
    expect(plan.locator(".own-plan-unchanged")).to_contain_text(first["label"])
    plan.get_by_role("button", name="Zrób migawkę").click()
    expect(plan.locator(".job-summary")).to_contain_text(
        "Bez nowej migawki", timeout=WAIT_S * 1000
    )
    assert [
        item["label"] for item in call(page, "GET", file_url(shp.path))["snapshots"]
    ] == [first["label"]]
    tab.assert_clean()


def test_changed_since_snapshot_badge(own_server: OwnServer, tab: Tab) -> None:
    """Criterion 10: a file changed after its snapshot: „zmieniony od migawki z …”."""
    page = open_session(tab, own_server)
    entry = own_server.folder.file("geojson_wgs84")
    snapshot(page, entry.path, "")
    working = own_server.folder.root / entry.path
    document = json.loads(working.read_text(encoding="utf-8"))
    document["features"][0]["geometry"]["coordinates"] = [19.96, 50.08]
    working.write_text(json.dumps(document), encoding="utf-8")

    page.goto(f"{own_server.served.base}/?view=projects&project={PROJECT}")
    group = page.locator(".own-group")
    group.get_by_role("button", name="Odśwież").click()
    expect(group.locator(".job.succeeded")).to_be_visible(timeout=WAIT_S * 1000)
    row = group.locator(".own-file").filter(has_text=entry.path)
    expect(row).to_contain_text("zmieniony od migawki z")
    row.get_by_role("link").click()
    expect(page.get_by_role("dialog", name=entry.path)).to_contain_text(
        "zmieniony od migawki z"
    )
    shot(page, "07-zmieniony-od-migawki")
    tab.assert_clean()


def test_snapshot_fan_current_on_top(own_server: OwnServer, tab: Tab) -> None:
    """The Wachlarz of a file: the working file on top, then snapshots newest first."""
    page = open_session(tab, own_server)
    tif = own_server.folder.file("tif_2180")
    snapshot(page, tif.path, "")
    labels = [
        item["label"] for item in call(page, "GET", file_url(tif.path))["snapshots"]
    ]
    page.goto(card_address(own_server, tif.path))
    card = page.get_by_role("dialog", name=tif.path)
    card.get_by_role("button", name="Wachlarz migawek").click()
    options = card.locator(".fan-tag[role=option]")
    expect(options).to_have_count(1 + len(labels))
    keys = [
        options.nth(index).get_attribute("data-layer")
        for index in range(1 + len(labels))
    ]
    assert keys == ["file", *(f"snapshot:{label}" for label in labels)]
    options.nth(1).click()
    assert query_of(page)["own_version"] == labels[0]
    expect(card.locator(".fc-version.on")).to_contain_text(labels[0])
    shot(page, "08-wachlarz-migawek")
    tab.assert_clean()


def test_compare_snapshot_with_current(own_server: OwnServer, tab: Tab) -> None:
    """„Porównaj z migawką…”: the snapshot as A, the working file as B, schema diff."""
    page = open_session(tab, own_server)
    gpkg = own_server.folder.file("gpkg_layers")
    snapshot(page, gpkg.path, "do porównania")
    newest = call(page, "GET", file_url(gpkg.path))["snapshots"][0]
    page.goto(card_address(own_server, gpkg.path))
    card = page.get_by_role("dialog", name=gpkg.path)
    card.locator(".fc-compare summary").click()
    card.locator(".fc-compare-list").get_by_role("link").filter(
        has_text=newest["label"]
    ).click()
    query = query_of(page)
    assert (query["view"], query["a"], query["b"]) == (
        "compare",
        newest["ref"],
        f"file:{PROJECT}:{gpkg.path}",
    )
    expect(page.locator(".cmp-table")).to_be_visible(timeout=WAIT_S * 1000)
    schema = page.locator(".cmp-schema")
    for layer in gpkg.layers:
        expect(schema).to_contain_text(layer.name)
    shot(page, "09-porownanie-migawki")
    page.locator(".cmp-side.b").get_by_role("link", name="Karta pliku").click()
    expect(page.get_by_role("dialog", name=gpkg.path)).to_be_visible()
    tab.assert_clean()


def test_data_dir_change_admin_only(
    own_server: OwnServer, tab: Tab, chromium: Any
) -> None:
    """The owner gives another folder; an administrator's account may, another not.

    The folder changes on the sharing screen („Udostępnij…”), which a project
    without an owner offers the owner of the computer and an administrator;
    anyone else sees it disabled and gets a refusal from the API. An empty
    field brings back the default ``dane/``.
    """
    page = open_session(tab, own_server)
    other_dir = own_server.store.base.parent / "inne-dane"
    (other_dir / "warstwy").mkdir(parents=True, exist_ok=True)
    page.goto(f"{own_server.served.base}/?view=projects&project={OTHER_PROJECT}")
    group = page.locator(".own-group")
    window = sharing(page)
    window.get_by_label("Folder danych własnych").fill(str(other_dir))
    window.get_by_role("button", name="Zapisz").click()
    expect(window).to_be_hidden()
    expect(group.locator(".own-folder")).to_contain_text(str(other_dir))
    expect(group.locator(".own-folder")).to_contain_text("folder z ustawień Archiwisty")
    assert own_server.served.settings().own_data_dirs  # saved in the settings
    shot(page, "10-zmiana-folderu")

    state = StateStore(own_server.served.paths.state_file)
    add_people(state)
    accounts: tuple[tuple[Who, bool], ...] = (("admin", True), ("other", False))
    for who, offered in accounts:
        issued = issue_one_time_token(
            own_server.served.paths.index_file,
            "startup",
            minted_by=principal(state, who),
        )
        context = chromium.new_context(locale="pl-PL", timezone_id="Europe/Warsaw")
        try:
            person = context.new_page()
            person.goto(fragment_url(own_server.served.base, issued.token))
            expect(person.get_by_role("navigation", name="Widoki")).to_be_visible()
            person.goto(
                f"{own_server.served.base}/?view=projects&project={OTHER_PROJECT}"
            )
            expect(person.locator(".own-group .own-folder")).to_be_visible(
                timeout=WAIT_S * 1000
            )
            share = person.get_by_role("complementary", name="Projekt").get_by_role(
                "button", name="Udostępnij…"
            )
            expect(share).to_be_enabled(enabled=offered)
            if not offered:
                refused = person.evaluate(
                    API,
                    [
                        "PUT",
                        f"/projects/{OTHER_PROJECT}/data-dir",
                        json.dumps({"path": None}),
                    ],
                )
                assert (refused["status"], refused["body"]["code"]) == (
                    403,
                    "forbidden",
                )
                assert refused["body"]["details"]["reason"] == "permission_denied"
        finally:
            context.close()

    window = sharing(page)
    window.get_by_label("Folder danych własnych").fill("")
    window.get_by_role("button", name="Zapisz").click()
    expect(window).to_be_hidden()
    expect(group.locator(".own-folder")).to_contain_text(
        "domyślny folder dane/ projektu"
    )
    tab.assert_clean()


def test_no_csp_violations_own_data(own_server: OwnServer, tab: Tab) -> None:
    """Card, its tabs, the plan window and the project's map stay within the CSP."""
    page = open_session(tab, own_server)
    tif = own_server.folder.file("tif_2180")
    page.goto(card_address(own_server, tif.path, own_tab="preview"))
    card = page.get_by_role("dialog", name=tif.path)
    expect(card.locator("img.pv-image")).to_have_attribute("src", BLOB)
    card.get_by_role("button", name="Zrób migawkę…").click()
    expect(page.locator("dialog.own-plan")).to_contain_text("Zrobić migawkę?")
    page.locator("dialog.own-plan").get_by_role("button", name="Anuluj").click()
    expect(card).to_be_visible()
    card.locator(".own-actions").get_by_role("link", name="Pokaż na mapie").click()
    expect(page.locator(".own-legend")).to_contain_text("Zasięgi plików")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(card_address(own_server, tif.path))
    expect(page.get_by_role("dialog", name=tif.path)).to_be_visible()
    shot(page, "11-telefon-karta")
    tab.assert_clean()
