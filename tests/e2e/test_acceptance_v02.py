"""Acceptance of v0.2 in Chromium on real servers (plan v0.2, step 17).

The journey of SPEC 13 v0.2 runs on a real ``archiwista serve`` over a
generated store, offline, and asks nothing outside the server: file cards
with their previews and the reasons of files without one, the map with a
year layer's preview, the Wachlarz and the catalog's timeline of the same
layers, two layers compared with the curtain, then a project's own data — a
snapshot of a GeoPackage open in an editor, a change the next scan finds
(„zmieniony od migawki”), a second snapshot, and the same content again,
which makes none („bez zmian”). The failure scenarios: the real command
line over a store bind-mounted read-only (previews work from the local
cache, the store stays as it was) and a share that disconnects (the
previews seen before still show, the others say why not). With
``ARCHIWISTA_SCREENSHOTS=<katalog-danych>/…`` the journey keeps screenshots
there for the report (``docs/reports/v0.2-screenshots/``).
"""

import json
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import pytest
import shapely
from playwright.sync_api import Locator, Page, Request, expect

from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig, StoreKind
from archiwista.index import own_file_id
from archiwista.jobs import FINISHED_STATES
from archiwista.messages import message
from archiwista.security import CSRF_HEADER
from tests.fixtures.browser import Served, Tab, session_headers
from tests.fixtures.make_store import NMT, Family, StoreManifest, make_store
from tests.fixtures.own_data import GpkgEditor, make_own_folder
from tests.fixtures.preview_api import center_tile_url
from tests.fixtures.read_only_mount import (
    mount_options,
    require_read_only_mounts,
    serving_read_only,
    tree,
)

Serve = Callable[..., Served]

STORE = "zespol"
STORE_NAME = "Zespół"
PROJECT = "projekt-01"
# Criterion 6: a project folder with a GeoPackage, a Shapefile and a GeoTIFF.
OWN_FAMILIES = ("gpkg_layers", "shp_full", "tif_2180")
WAIT_S = 60.0
# Each layer of the area builds its missing previews in a job of its own,
# one job at a time.
BUILD_TIMEOUT_S = 240.0
WORLD = "-180,-85,180,85"
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
# Covers the text of local paths for a screenshot and uncovers it after.
# Through the CSSOM: the page's CSP allows no injected stylesheet.
COVER_PATHS = """(cover) => {
  for (const path of document.querySelectorAll("code.path")) {
    path.style.color = cover ? "transparent" : "";
    path.style.background = cover ? "#d0d5dd" : "";
  }
}"""
CURTAIN = "Kurtyna między A i B"
BLOB = re.compile(r"^blob:")
TILE = re.compile(r"/tiles/(\d+)/(\d+)/(\d+)\.png")
# A pipe inside the GeoPackage's area (EPSG:2180), as an editor adds it.
PIPE = shapely.LineString([(566_500, 241_500), (566_600, 241_600)])
API = """async ([method, path, body]) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  if (body !== null) headers["Content-Type"] = "application/json";
  const answer = await fetch(`/api/v1${path}`, { method, headers, body });
  return { status: answer.status, body: await answer.json() };
}"""
CLIP_B = "() => getComputedStyle(document.querySelector('.cmp-pane.b')).clipPath"


@dataclass(frozen=True)
class Seen:
    """A request of the page: its address, CSRF header and its answer to wait for."""

    url: str
    csrf: str | None
    request: Request = field(compare=False, repr=False)


# --- store, session and API ---------------------------------------------------


def offline_settings(store: StoreManifest, *, kind: StoreKind = "local") -> AppSettings:
    """Return offline settings: the generated store as ``zespol`` and its projects."""
    config = StoreConfig(id=STORE, name=STORE_NAME, kartograf=store.root, kind=kind)
    return AppSettings(
        offline=True, stores=(config,), project_dirs=(store.projects_dir,)
    )


def call(page: Page, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Return the JSON answer of an API request made with the page's session."""
    data = None if body is None else json.dumps(body)
    answer: dict[str, Any] = page.evaluate(API, [method, path, data])
    assert answer["status"] in (200, 201, 202), answer
    return answer["body"]


def wait_for(
    page: Page, found: Callable[[], Any], what: str, timeout_s: float = WAIT_S
) -> Any:
    """Wait until ``found`` gives something true (the page's own wait); return it."""
    deadline = time.monotonic() + timeout_s
    while not (value := found()):
        assert time.monotonic() < deadline, f"not in time: {what}"
        page.wait_for_timeout(200)
    return value


def open_session(page: Page, url: str) -> None:
    """Start a session from a one-time address; wait until the store is indexed."""
    page.goto(url)
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


def finished(page: Page, job: dict[str, Any]) -> dict[str, Any]:
    """Wait for a job to end; it must have succeeded. Return it."""
    ended: dict[str, Any] = wait_for(
        page,
        lambda: (
            (state := call(page, "GET", f"/jobs/{job['id']}"))["state"]
            in FINISHED_STATES
            and state
        ),
        f"job {job['id']}",
    )
    assert ended["state"] == "succeeded", ended
    return ended


def watch(page: Page) -> list[Seen]:
    """Record the page's requests from now on, with their CSRF header."""
    seen: list[Seen] = []

    def record(request: Request) -> None:
        csrf = request.headers.get(CSRF_HEADER.lower())
        seen.append(Seen(request.url, csrf, request))

    page.on("request", record)
    return seen


def address(base: str, **params: str) -> str:
    """Return an address of the interface."""
    return f"{base}/?{urlencode(params)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def shot(page: Page, name: str) -> None:
    """Keep a screenshot for the report when ``ARCHIWISTA_SCREENSHOTS`` is set.

    Local paths (``code.path``: the test's directory) are covered, so the
    report has no private path.
    """
    directory = os.environ.get(SCREENSHOTS)
    if directory:
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.evaluate(COVER_PATHS, True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))
        page.evaluate(COVER_PATHS, False)


# --- file cards and their previews --------------------------------------------


def slot_of(store: StoreManifest, family: Family) -> tuple[str, str]:
    """Return the slot path of a family and the version its standard path holds."""
    link = next(
        entry
        for entry in store.by_family(family)
        if entry.kind == "link" and entry.version_path is not None
    )
    assert link.version_path is not None
    return link.path, link.version_path


def open_preview(
    page: Page, base: str, store: StoreManifest, family: Family
) -> Locator:
    """Open the preview tab of a family's current version; return the pane."""
    slot, version = slot_of(store, family)
    query = {
        "view": "store",
        "file": f"{STORE}/{slot}",
        "file_version": version,
        "file_tab": "preview",
    }
    page.goto(f"{base}/?{urlencode(query)}")
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card.get_by_role("tab", name="Podgląd")).to_have_attribute(
        "aria-selected", "true"
    )
    pane = card.get_by_role("tabpanel")
    expect(pane.locator(".pv-facts")).to_be_visible()
    return pane


def fact(pane: Locator, name: str) -> Locator:
    """Return the value of a fact of the preview pane (``<dt>`` → ``<dd>``)."""
    return pane.locator(f".pv-facts dt:text-is('{name}') + dd")


def thumbnail(pane: Locator) -> Locator:
    """Return the pane's thumbnail image."""
    return pane.get_by_role("img", name=re.compile("^Podgląd pliku"))


def assert_blob_image(image: Locator) -> None:
    """Check an image shows a decoded ``blob:`` address."""
    expect(image).to_have_attribute("src", BLOB)
    expect(image).to_have_js_property("complete", True)
    assert image.evaluate("(img) => img.naturalWidth > 0 && img.naturalHeight > 0")


def built_preview(page: Page, base: str, store: StoreManifest) -> dict[str, Any]:
    """Open an ASC sheet's preview, which builds its local COG; return its info.

    A sheet in ASCII Grid has no map tiles of its own: its first view
    starts the ``preview`` job, followed in the pane to its end.
    """
    _, version = slot_of(store, "asc_sheet")
    assert preview_info(page, version)["state"] == "needs_build"
    pane = open_preview(page, base, store, "asc_sheet")
    job = pane.locator(".pv-build .job")
    expect(job).to_have_class(re.compile(r"\bsucceeded\b"), timeout=WAIT_S * 1000)
    expect(fact(pane, "Stan podglądu")).to_contain_text("gotowy")
    expect(fact(pane, "Na mapie")).to_contain_text("tak, powiększenia")
    assert_blob_image(thumbnail(pane))
    info = preview_info(page, version)
    assert info["state"] == "ready"
    return info


def preview_info(page: Page, version: str) -> dict[str, Any]:
    """Return a version's ``PreviewInfo`` as the page's session reads it."""
    info: dict[str, Any] = call(
        page, "GET", f"/stores/{STORE}/versions/{version}/preview"
    )
    return info


def map_tile(page: Page, base: str, info: dict[str, Any]) -> bytes:
    """Return the PNG of a preview's map tile holding its centre."""
    answer = page.request.get(
        f"{base}{center_tile_url(info)}", headers=session_headers(page)
    )
    assert answer.status == 200, answer.text()
    assert answer.headers["content-type"] == "image/png"
    return answer.body()


def cards_with_previews_and_reasons(
    page: Page, base: str, store: StoreManifest
) -> None:
    """Show a raster's thumbnail in two styles; a world file's and a ZIP's reasons."""
    raster = open_preview(page, base, store, "tif_bbox")
    image = thumbnail(raster)
    assert_blob_image(image)
    shaded = image.get_attribute("src")
    assert shaded is not None
    expect(fact(raster, "Stan podglądu")).to_contain_text("gotowy")
    raster.get_by_role("group", name="Styl podglądu").get_by_role(
        "button", name="hipsometria"
    ).click()
    expect(raster.locator(".pv-ramp")).to_be_visible()
    expect(image).not_to_have_attribute("src", shaded)
    assert_blob_image(image)
    shot(page, "01-karta-pliku-podglad")

    world = open_preview(page, base, store, "jgw_sheet")
    reason = world.locator(".pv-reason")
    expect(reason).to_contain_text(message("preview.reason_auxiliary_file", "pl"))
    expect(reason).to_contain_text(message("preview.fix_auxiliary_file", "pl"))
    expect(fact(world, "Stan podglądu")).to_contain_text("niedostępny")
    shot(page, "02-karta-pliku-powod")

    archive = open_preview(page, base, store, "zip_citygml")
    expect(archive.locator(".pv-members tbody tr").first).to_be_visible()
    expect(archive.locator(".pv-reason")).to_contain_text(
        message("preview.reason_archive_members_only", "pl")
    )


# --- the area's year layers ---------------------------------------------------


def nmt_area(page: Page) -> str:
    """Keep an area around the store's NMT sheets (ASC); return its id."""
    view = call(page, "GET", f"/map/footprints?product=nmt&versions=all&bbox={WORLD}")
    rings = [
        item["geometry"]["coordinates"][0]
        for item in view["items"]
        if item["segment"] == NMT and item["slot"].endswith(".asc")
    ]
    assert rings, "the store has no NMT sheets"
    west = min(x for ring in rings for x, _ in ring)
    south = min(y for ring in rings for _, y in ring)
    east = max(x for ring in rings for x, _ in ring)
    north = max(y for ring in rings for _, y in ring)
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    area = call(
        page,
        "POST",
        "/areas",
        {
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "name": "Arkusze NMT",
            "source": "drawn",
        },
    )
    found: str = area["id"]
    return found


def layers_of(page: Page, area_id: str) -> list[dict[str, Any]]:
    """Return the NMT layers of the area (asking builds their missing previews)."""
    query = urlencode({"store": STORE, "product": "nmt", "area_id": area_id})
    layers: list[dict[str, Any]] = call(page, "GET", f"/local-layers?{query}")["layers"]
    return layers


def sheet_layers(layers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the year layers of two sheets, each with a title of its own."""
    titles = [layer["title"] for layer in layers]
    return [
        layer
        for layer in layers
        if layer["kind"] == "year"
        and len(layer["versions"]) == 2
        and titles.count(layer["title"]) == 1
    ]


def built_layers(page: Page, area_id: str) -> list[dict[str, Any]]:
    """Wait until every layer of the area has its previews; return the layers."""
    deadline = time.monotonic() + BUILD_TIMEOUT_S
    while True:
        layers = layers_of(page, area_id)
        if layers and all(
            layer["preview"]["state"] in ("ready", "unavailable") for layer in layers
        ):
            return layers
        assert time.monotonic() < deadline, "the layers' previews were not built"
        page.wait_for_timeout(1000)


def layer_tiles(seen: list[Seen], base: str, key: str) -> list[Seen]:
    """Return the requests of a layer's tiles."""
    prefix = f"{base}/api/v1/local-layers/tiles/"
    return [
        request
        for request in seen
        if request.url.startswith(prefix)
        and TILE.search(request.url) is not None
        and dict(parse_qsl(urlsplit(request.url).query)).get("layer") == key
    ]


def drawn(page: Page, tiles: list[Seen]) -> None:
    """Wait until the map got the tiles' answers and faded them in."""
    for tile in tiles:
        tile.request.response()
    # A raster layer fades its tiles in over 150 ms (map/canvas.js).
    page.wait_for_timeout(500)


def switch(page: Page, name: str) -> Locator:
    """Return a button of the switch „Mapa / Wachlarz / Katalog”."""
    return page.get_by_role("group", name="Widok środka").get_by_role(
        "button", name=name
    )


def details(page: Page) -> Locator:
    """Return the panel „Szczegóły zestawu”."""
    return page.get_by_role("complementary", name="Szczegóły zestawu")


# --- own data -----------------------------------------------------------------


def own_files(page: Page) -> Locator:
    """Return the list of the project's own files."""
    return page.locator(".own-group").get_by_role("list", name="Pliki danych własnych")


def rescan(page: Page) -> None:
    """„Odśwież” the project's own data and wait for its ``own_scan``."""
    with page.expect_response(
        lambda response: (
            response.request.method == "POST"
            and response.url.endswith(f"/projects/{PROJECT}/scan")
        )
    ) as started:
        page.locator(".own-group").get_by_role("button", name="Odśwież").click()
    finished(page, started.value.json())


def open_own_card(page: Page, path: str) -> Locator:
    """Open the card of an own file from the project's list."""
    own_files(page).get_by_role("link", name=path).click()
    card = page.get_by_role("dialog", name=path)
    expect(card).to_be_visible()
    return card


def snapshot_from_card(page: Page, card: Locator, path: str, note: str) -> str:
    """Make a snapshot in the card's plan window of a file being edited.

    The plan names the SQLite backup copy and warns that only committed
    changes are copied; the job's summary names the new snapshot. Returns
    its label.
    """
    card.get_by_role("button", name="Zrób migawkę…").click()
    plan = page.locator("dialog.own-plan")
    expect(plan).to_contain_text("Zrobić migawkę?")
    expect(plan).to_contain_text("kopia zapasowa SQLite")
    expect(plan).to_contain_text(message("snapshot.editing_detected", "pl", file=path))
    plan.get_by_label("Opis migawki").fill(note)
    with page.expect_response(
        lambda response: (
            response.request.method == "POST" and response.url.endswith("/snapshots")
        )
    ) as started:
        plan.get_by_role("button", name="Zrób migawkę").click()
    result: dict[str, Any] = finished(page, started.value.json())["result"]
    assert result["status"] == "created", result
    label: str = result["label"]
    expect(plan.locator(".job-summary")).to_contain_text(f"Migawka {label} zapisana")
    plan.get_by_role("button", name="Zamknij").click()
    expect(plan).to_be_hidden()
    return label


# --- tests --------------------------------------------------------------------


def test_acceptance_v02_walkthrough(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """From a file card's preview to the second snapshot, asking nothing outside.

    Cards show a raster's thumbnail with its styles and why a world file
    and a ZIP have no map preview; a year button puts a layer's tiles on
    the map, the Wachlarz and the timeline keep it chosen, its details
    compare it with another year under the curtain. In the project, a
    GeoPackage open in an editor (WAL, an open transaction) gets a snapshot
    of its committed rows; the editor's next commit is found by the scan
    („zmieniony od migawki”), a second snapshot follows and the same
    content once more makes none („bez zmian od migawki”).
    """
    store = make_store(tmp_path / "store", slots=24, seed=7)
    project_dir = store.output_dir / store.project(PROJECT).path
    folder = make_own_folder(project_dir / "dane", families=OWN_FAMILIES)
    served = serve(offline_settings(store))
    base = served.base
    page = tab.page
    page.emulate_media(reduced_motion="reduce")
    open_session(page, served.token_url())
    token = session_headers(page)[CSRF_HEADER]
    seen = watch(page)

    cards_with_previews_and_reasons(page, base, store)

    # The map: a year button shows the layer's outlines and its tiles.
    area_id = nmt_area(page)
    layers = layers_of(page, area_id)
    chosen, other = sheet_layers(layers)[:2]
    page.goto(address(base, view="map", product="nmt", area_id=area_id))
    years = page.get_by_role("group", name="Lata na mapie")
    expect(years.get_by_role("button")).to_have_count(len(layers))
    button = years.get_by_role("button", name=chosen["title"], exact=True)
    button.click()
    expect(button).to_have_attribute("aria-pressed", "true")
    count = len(chosen["versions"])
    expect(
        page.locator(".map-legend").get_by_role(
            "region", name=f"Warstwa {chosen['title']}"
        )
    ).to_contain_text(
        f"gotowe podglądy: {count} z {count}", timeout=BUILD_TIMEOUT_S * 1000
    )
    on_map = wait_for(page, lambda: layer_tiles(seen, base, chosen["key"]), "tiles")
    drawn(page, on_map)
    shot(page, "03-mapa-podglad-roku")
    chosen_at = query_of(page)

    # The Wachlarz of the area's layers, the map's choice kept.
    layers = built_layers(page, area_id)
    switch(page, "Wachlarz").click()
    fan = page.get_by_role("listbox", name="Warstwy Wachlarza")
    expect(fan.get_by_role("option")).to_have_count(len(layers))
    expect(
        fan.locator(f'[role=option][data-layer="{chosen["key"]}"]')
    ).to_have_attribute("aria-selected", "true")
    images = fan.locator(".fan-card image")
    expect(images).to_have_count(len(layers))
    for image in images.all():
        expect(image).to_have_attribute("href", BLOB)
    expect(details(page).locator(".sd-title")).to_have_text(chosen["title"])
    shot(page, "04-wachlarz")
    fan_at = query_of(page)

    # The catalog's timeline: one cell per layer, the same one chosen.
    switch(page, "Katalog").click()
    page.get_by_role("group", name="Układ katalogu").get_by_role(
        "button", name="Oś czasu"
    ).click()
    timeline = page.get_by_role(
        "grid", name="Oś czasu: warianty w wierszach, lata w kolumnach"
    )
    expect(timeline.locator("[data-layer]")).to_have_count(len(layers))
    expect(
        timeline.locator(f'[role=gridcell][data-layer="{chosen["key"]}"]')
    ).to_have_attribute("aria-selected", "true")
    expect(details(page).locator(".sd-title")).to_have_text(chosen["title"])
    shot(page, "05-os-czasu")
    timeline_at = query_of(page)

    # „Porównaj z…”: the other year beside it, under the curtain.
    compared_from = len(seen)
    details(page).locator(".sd-compare summary").click()
    details(page).locator(".sd-compare").get_by_role("link").filter(
        has_text=re.compile(rf"^{re.escape(other['title'])} ·")
    ).click()
    handle = page.get_by_role("slider", name=CURTAIN)
    expect(handle).to_have_attribute("aria-valuenow", "50")
    wait_for(
        page,
        lambda: all(
            layer_tiles(seen[compared_from:], base, layer["key"])
            for layer in (chosen, other)
        ),
        "the tiles of both compared layers",
    )
    expect(page.locator(".cmp-badge.a")).to_contain_text(chosen["title"])
    expect(page.locator(".cmp-badge.b")).to_contain_text(other["title"])
    handle.focus()
    page.keyboard.press("Shift+ArrowLeft")
    expect(handle).to_have_attribute("aria-valuenow", "40")
    clip = page.evaluate(CLIP_B)
    shot(page, "06-porownanie-kurtyna")
    compare_at = query_of(page)

    # The project's own data, scanned from its view.
    page.get_by_role("navigation", name="Widoki").get_by_role(
        "link", name="Projekty"
    ).click()
    page.get_by_role("link", name=PROJECT, exact=True).click()
    rescan(page)
    for entry in folder.indexed:
        expect(
            own_files(page).locator(".own-file").filter(has_text=entry.path)
        ).to_contain_text("bez migawki")
    page.locator(".own-group").evaluate("(group) => group.scrollIntoView()")
    shot(page, "07-projekt-dane-wlasne")

    gpkg = folder.file("gpkg_layers")
    with GpkgEditor(folder.root / gpkg.path) as editor:
        # As in QGIS: one edit committed (its frames wait in -wal), one not yet.
        editor.begin()
        editor.insert("przewody", PIPE, srednica_mm=999, material="PE")
        editor.commit()
        editor.begin()
        editor.insert("przewody", PIPE, srednica_mm=777, material="PE")
        rescan(page)
        card = open_own_card(page, gpkg.path)
        expect(card).to_contain_text("bez migawki")
        first = snapshot_from_card(page, card, gpkg.path, "w trakcie edycji")
        expect(card).to_contain_text("bez zmian od migawki z")
        shot(page, "08-migawka-w-edycji")

        # The editor commits its second pipe: the next scan finds a change.
        editor.commit()
        page.keyboard.press("Escape")
        expect(card).to_be_hidden()
        rescan(page)
        expect(
            own_files(page).locator(".own-file").filter(has_text=gpkg.path)
        ).to_contain_text("zmieniony od migawki z")
        card = open_own_card(page, gpkg.path)
        expect(card).to_contain_text("zmieniony od migawki z")
        shot(page, "09-zmieniony-od-migawki")
        second = snapshot_from_card(page, card, gpkg.path, "drugi przewód")
        expect(card).to_contain_text("bez zmian od migawki z")

        # The same content once more: the plan says so, the job makes none.
        card.get_by_role("button", name="Zrób migawkę…").click()
        plan = page.locator("dialog.own-plan")
        expect(plan.locator(".own-plan-unchanged")).to_contain_text(
            "Bez zmian od migawki z"
        )
        expect(plan.locator(".own-plan-unchanged")).to_contain_text(second)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/snapshots")
            )
        ) as started:
            plan.get_by_role("button", name="Zrób migawkę").click()
        again = finished(page, started.value.json())["result"]
        expect(plan.locator(".job-summary")).to_contain_text(
            f"Bez nowej migawki: ostatnia migawka {second} ma tę samą treść."
        )
        shot(page, "10-ta-sama-tresc")
        plan.get_by_role("button", name="Zamknij").click()
    file_card = call(page, "GET", f"/projects/{PROJECT}/files/{own_file_id(gpkg.path)}")

    assert {request.csrf for request in on_map} == {token}
    assert (chosen_at["view"], chosen_at["layer"]) == ("map", chosen["key"])
    assert (fan_at["mode"], fan_at["layer"]) == ("fan", chosen["key"])
    assert (timeline_at["view"], timeline_at["layout"], timeline_at["layer"]) == (
        "catalog",
        "timeline",
        chosen["key"],
    )
    assert (compare_at["view"], compare_at["a_layer"], compare_at["b_layer"]) == (
        "compare",
        chosen["key"],
        other["key"],
    )
    assert clip == "inset(0px 0px 0px 40%)"
    assert (again["status"], again["label"]) == ("unchanged", second)
    assert [item["label"] for item in file_card["snapshots"]] == [second, first]
    assert file_card["change"] == "unchanged"
    assert tab.foreign_requests(base) == []
    tab.assert_clean()


def test_acceptance_v02_read_only_store_previews(
    tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real ``archiwista serve`` on a read-only mount: previews, nothing written.

    The store's whole directory (data and projects) is bind-mounted
    read-only in the server's own mount namespace; the settings, the index
    and the preview cache live in the test's XDG directories. Thumbnails, a
    vector's layers, a ZIP's members and an ASC sheet's local COG with its
    map tile come from there; the store keeps every name, size, time and
    inode — no ``.aux.xml`` or anything else beside its files.
    """
    require_read_only_mounts(tmp_path)
    store = make_store(tmp_path / "store", slots=17, seed=7)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("PYTHONUNBUFFERED", "1")
    paths = AppPaths.default()
    ConfigStore(paths.config_file).save(offline_settings(store))
    before = tree(store.output_dir)
    page = tab.page

    with serving_read_only(store.output_dir, dict(os.environ), tmp_path) as (
        process,
        url,
    ):
        base = url.partition("/#")[0]
        open_session(page, url)
        cards_with_previews_and_reasons(page, base, store)
        vector = open_preview(page, base, store, "gpkg_layers")
        expect(vector.locator(".pv-layer")).to_have_count(2)
        info = built_preview(page, base, store)
        tile = map_tile(page, base, info)
        options = mount_options(process.pid, store.output_dir)
        tab.assert_clean()
        page.goto("about:blank")

    cached = [path for path in paths.previews_dir.rglob("*") if path.is_file()]
    assert "ro" in options
    assert process.returncode == 0, (tmp_path / "serve.err").read_text("utf-8")
    assert tile
    assert cached
    assert tree(store.output_dir) == before


def test_acceptance_v02_disconnected_share_serves_cached_previews(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A share gone after its previews were seen: those still show, others say why.

    The share's directory is replaced by an empty mount point. A raster's
    thumbnail and an ASC sheet's preview with its local COG's tiles come
    from the preview cache; a version nobody looked at says that the store
    is disconnected. With the share back, that version shows too.
    """
    store = make_store(tmp_path / "store", slots=17, seed=7)
    served = serve(offline_settings(store, kind="share"))
    base = served.base
    page = tab.page
    open_session(page, served.token_url())
    assert_blob_image(thumbnail(open_preview(page, base, store, "tif_bbox")))
    info = built_preview(page, base, store)
    tile = map_tile(page, base, info)
    away = store.root.with_name("data-away")

    store.root.rename(away)
    store.root.mkdir()  # the empty mount point of a share that is gone
    try:
        raster = open_preview(page, base, store, "tif_bbox")
        assert_blob_image(thumbnail(raster))
        expect(fact(raster, "Stan podglądu")).to_contain_text("gotowy")
        sheet = open_preview(page, base, store, "asc_sheet")
        assert_blob_image(thumbnail(sheet))
        expect(fact(sheet, "Na mapie")).to_contain_text("tak, powiększenia")
        cached_tile = map_tile(page, base, info)
        unseen = open_preview(page, base, store, "tif_classes")
        reason = unseen.locator(".pv-reason")
        expect(reason).to_contain_text(
            message("preview.reason_store_unavailable", "pl")
        )
        expect(reason).to_contain_text(message("preview.fix_store_unavailable", "pl"))
        expect(unseen.get_by_role("img")).to_have_count(0)
    finally:
        store.root.rmdir()
        away.rename(store.root)  # the share is back
    back = open_preview(page, base, store, "tif_classes")
    assert_blob_image(thumbnail(back))

    assert cached_tile == tile
    tab.assert_clean()
