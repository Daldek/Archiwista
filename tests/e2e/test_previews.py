"""Previews in the file card and the preview cache in the settings (v0.2, step 12a).

Every test serves a generated store offline — the v0.2 file families of
``make_store`` among the v0.1 ones — on a real ``archiwista serve`` with its
render pool and job supervisor, waits for the scheduler's first scan and
checks what a person sees: thumbnails arrive as ``blob:`` images fetched
with the session's CSRF header, a file without a preview says why and what
to do, an ASC sheet builds its local preview by itself with the job's
progress, and the settings change the cache limit next to its usage from
``/health`` — without a CSP violation or a request outside the server.
"""

import re
import time
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from archiwista.messages import message
from archiwista.security import CSRF_HEADER
from tests.fixtures.browser import Served, Tab, session_headers
from tests.fixtures.make_store import Family, StoreManifest, make_store

Serve = Callable[..., Served]

STORE = "zespol"
INDEX_TIMEOUT_S = 60.0
BUILD_TIMEOUT_MS = 60_000
# True once every store has a finished scan and no job runs.
INDEXED = """
async () => {
  const csrf = sessionStorage.getItem("archiwista_csrf") ?? "";
  const headers = { "X-Archiwista-CSRF": csrf };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.every(
    (item) => item.state.last_scan !== null && item.state.running_job === null,
  );
}
"""
# Records whether a progress bar of a preview build was ever on the page.
WATCH_PROGRESS = """
() => {
  window.__buildProgress = false;
  new MutationObserver(() => {
    if (document.querySelector(".pv-build .job-progress progress")) {
      window.__buildProgress = true;
    }
  }).observe(document.body, { childList: true, subtree: true });
}
"""


def served_store(
    serve: Serve, tab: Tab, tmp_path: Path
) -> tuple[StoreManifest, Served]:
    """Generate the store, serve it offline and open a session after its scan."""
    store = make_store(tmp_path / "store", slots=17, seed=7)
    config = StoreConfig(id=STORE, name="Zespół", kartograf=store.root, kind="local")
    served = serve(AppSettings(offline=True, stores=(config,)))
    page = tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the store was not indexed in time"
        page.wait_for_timeout(200)
    return store, served


def slot_of(store: StoreManifest, family: Family) -> tuple[str, str]:
    """Return the slot path of a family and the version its standard path holds."""
    link = next(
        entry
        for entry in store.by_family(family)
        if entry.kind == "link" and entry.version_path is not None
    )
    assert link.version_path is not None
    return link.path, link.version_path


def card_address(served: Served, slot: str, version: str, **params: str) -> str:
    """Return the address of a version's card over the Store view."""
    query = {"view": "store", "file": f"{STORE}/{slot}", "file_version": version}
    return f"{served.base}/?{urlencode({**query, **params})}"


def open_preview(
    page: Page, served: Served, store: StoreManifest, family: Family
) -> Locator:
    """Open the preview tab of a family's current version; return the pane."""
    slot, version = slot_of(store, family)
    page.goto(card_address(served, slot, version, file_tab="preview"))
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card.get_by_role("tab", name="Podgląd")).to_have_attribute(
        "aria-selected", "true"
    )
    pane = card.get_by_role("tabpanel")
    expect(pane.locator(".pv-facts")).to_be_visible()
    return pane


def preview_info(page: Page, served: Served, version: str) -> dict[str, Any]:
    """Return the version's ``PreviewInfo`` as the page's session reads it."""
    answer = page.request.get(
        f"{served.base}/api/v1/stores/{STORE}/versions/{version}/preview",
        headers=session_headers(page),
    )
    assert answer.ok, answer.text()
    info: dict[str, Any] = answer.json()
    return info


def fact(pane: Locator, name: str) -> Locator:
    """Return the value of a fact of the pane (``<dt>`` → ``<dd>``)."""
    return pane.locator(f".pv-facts dt:text-is('{name}') + dd")


def thumbnail(pane: Locator) -> Locator:
    """Return the pane's thumbnail image."""
    return pane.get_by_role("img", name=re.compile("^Podgląd pliku"))


def assert_blob_image(image: Locator) -> None:
    """Check an image shows a decoded ``blob:`` address."""
    expect(image).to_have_attribute("src", re.compile(r"^blob:"))
    expect(image).to_have_js_property("complete", True)
    assert image.evaluate("(img) => img.naturalWidth > 0 && img.naturalHeight > 0")


def visit_every_kind(page: Page, served: Served, store: StoreManifest) -> None:
    """Open the preview of a raster with each legend, a vector, a cloud and a ZIP."""
    for family in ("tif_bbox", "tif_classes", "png_preview"):
        assert_blob_image(thumbnail(open_preview(page, served, store, family)))
    pane = open_preview(page, served, store, "tif_bbox")
    pane.get_by_role("button", name="hipsometria").click()
    expect(pane.locator(".pv-ramp")).to_be_visible()
    assert_blob_image(thumbnail(pane))
    expect(
        open_preview(page, served, store, "gpkg_layers").locator(".pv-layer")
    ).to_have_count(2)
    expect(
        open_preview(page, served, store, "laz_compressed").locator(".pv-share").first
    ).to_be_visible()
    expect(
        open_preview(page, served, store, "zip_citygml")
        .locator(".pv-members tbody tr")
        .first
    ).to_be_visible()
    expect(
        open_preview(page, served, store, "pdf_map").locator(".pv-reason")
    ).to_be_visible()


def test_card_preview_thumbnail_via_blob_with_csrf(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A thumbnail is a blob: image fetched with the CSRF header; a style its legend."""
    store, served = served_store(serve, tab, tmp_path)
    page = tab.page
    token = session_headers(page)[CSRF_HEADER]
    _, version = slot_of(store, "tif_bbox")
    info = preview_info(page, served, version)
    assert info["styles"] == ["hillshade", "hypsometry", "gray"]
    hypsometry = info["legends"]["hypsometry"]

    with page.expect_request(lambda request: "/preview.png" in request.url) as first:
        pane = open_preview(page, served, store, "tif_bbox")
    assert_blob_image(thumbnail(pane))
    styles = pane.get_by_role("group", name="Styl podglądu")
    expect(styles.get_by_role("button", name="cieniowanie")).to_have_attribute(
        "aria-pressed", "true"
    )
    expect(pane.locator(".pv-legend")).to_have_count(0)
    with page.expect_request(
        lambda request: "style=hypsometry" in request.url
    ) as second:
        styles.get_by_role("button", name="hipsometria").click()
    expect(pane.locator(".pv-ramp")).to_have_attribute(
        "style", re.compile(re.escape(", ".join(hypsometry["colors"])))
    )
    expect(pane.locator(".pv-range")).to_contain_text(f" {hypsometry['unit']}")
    assert_blob_image(thumbnail(pane))

    for request in (first.value, second.value):
        assert request.all_headers()[CSRF_HEADER.lower()] == token
        assert request.url.startswith(f"{served.base}/api/v1/stores/{STORE}/versions/")
    assert "file_style=hypsometry" in page.url
    expect(fact(pane, "Stan podglądu")).to_contain_text("gotowy")
    expect(fact(pane, "Na mapie")).to_contain_text(
        f"tak, powiększenia {info['minzoom']}–{info['maxzoom']}"
    )
    # The metadata tab is the card of v0.1: one click away, the tab in the address.
    page.get_by_role("tab", name="Metadane").click()
    expect(
        page.get_by_role("tabpanel").locator("dt:text-is('SHA-256')")
    ).to_be_visible()
    assert "file_tab" not in page.url
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert page.url == f"{served.base}/?view=store"
    tab.assert_clean()


def test_card_shows_reason_for_jgw_png_and_zip_members(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A world file says why it has no preview, a PNG why no map, a ZIP its members."""
    store, served = served_store(serve, tab, tmp_path)
    page = tab.page

    world = open_preview(page, served, store, "jgw_sheet")
    expect(world.locator(".pv-reason")).to_contain_text(
        message("preview.reason_auxiliary_file", "pl")
    )
    expect(world.locator(".pv-reason")).to_contain_text(
        message("preview.fix_auxiliary_file", "pl")
    )
    expect(fact(world, "Stan podglądu")).to_contain_text("niedostępny")
    expect(world.get_by_role("img")).to_have_count(0)

    image = open_preview(page, served, store, "png_preview")
    assert_blob_image(thumbnail(image))
    expect(image.locator(".pv-reason")).to_contain_text(
        message("preview.reason_no_georeference", "pl")
    )
    expect(image.locator(".pv-reason")).to_contain_text(
        message("preview.fix_no_georeference", "pl")
    )
    expect(fact(image, "Na mapie")).to_have_text("nie")

    slot, _ = slot_of(store, "zip_citygml")
    with zipfile.ZipFile(store.root / slot) as archive:
        names = [member.filename for member in archive.infolist()]
    archive_pane = open_preview(page, served, store, "zip_citygml")
    rows = archive_pane.locator(".pv-members tbody tr")
    expect(rows).to_have_count(len(names))
    for name in names:
        expect(rows.filter(has_text=name)).to_have_count(1)
    expect(archive_pane.locator(".pv-reason")).to_contain_text(
        message("preview.reason_archive_members_only", "pl")
    )
    expect(
        archive_pane.get_by_role("heading", name=re.compile("Pliki w archiwum"))
    ).to_contain_text(f"· {len(names)} pli")
    tab.assert_clean()


def test_card_builds_asc_preview_with_progress(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """An ASC sheet builds its local preview at its first view, its job followed."""
    store, served = served_store(serve, tab, tmp_path)
    page = tab.page
    slot, version = slot_of(store, "asc_sheet")
    assert preview_info(page, served, version)["state"] == "needs_build"
    page.goto(card_address(served, slot, version))
    card = page.get_by_role("dialog", name=PurePosixPath(slot).name)
    expect(card.locator("dt:text-is('SHA-256')")).to_be_visible()
    page.evaluate(WATCH_PROGRESS)

    with page.expect_request(
        lambda request: request.method == "POST" and request.url.endswith("/preview")
    ) as posted:
        card.get_by_role("tab", name="Podgląd").click()
    job = card.locator(".pv-build .job")
    expect(job).to_contain_text("Budowa podglądów")
    expect(job).to_have_class(re.compile(r"\bsucceeded\b"), timeout=BUILD_TIMEOUT_MS)
    expect(job).to_contain_text("Zbudowane: 1")
    pane = card.get_by_role("tabpanel")
    expect(fact(pane, "Stan podglądu")).to_contain_text("gotowy")
    expect(fact(pane, "Na mapie")).to_contain_text("tak, powiększenia")
    assert_blob_image(thumbnail(pane))

    assert posted.value.post_data_json == {"force": False}
    assert (
        posted.value.all_headers()[CSRF_HEADER.lower()]
        == session_headers(page)[CSRF_HEADER]
    )
    assert page.evaluate("window.__buildProgress") is True
    assert preview_info(page, served, version)["state"] == "ready"
    # Seen again, a built preview asks for no second build.
    with page.expect_request(lambda request: request.url.endswith("/preview")) as seen:
        page.reload()
    assert seen.value.method == "GET"
    expect(fact(page.get_by_role("tabpanel"), "Stan podglądu")).to_contain_text(
        "gotowy"
    )
    expect(page.locator(".pv-build")).to_have_count(0)
    tab.assert_clean()


def test_settings_cache_limit_and_usage(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """The settings show the cache's usage from /health and save a new limit."""
    store, served = served_store(serve, tab, tmp_path)
    page = tab.page
    assert_blob_image(thumbnail(open_preview(page, served, store, "tif_bbox")))
    health = page.request.get(
        f"{served.base}/api/v1/health", headers=session_headers(page)
    )
    used = health.json()["previews"]
    assert used["objects"] >= 1 and used["used_bytes"] > 0

    page.goto(f"{served.base}/?view=setup&step=mode")
    cache = page.get_by_role("group", name="Pamięć podglądów")
    field = cache.get_by_label("Limit pamięci podglądów (GB)")
    usage = cache.locator(".cache-usage")
    expect(field).to_have_value("20")
    expect(usage).to_contain_text("Zajęte teraz:")
    expect(usage).to_contain_text("z 20 GB")
    expect(usage).to_contain_text(re.compile(r"· [1-9]\d* plik(i|ów)? z podglądami"))
    expect(
        usage.get_by_role("progressbar", name="Zajętość pamięci podglądów")
    ).to_have_attribute("max", str(used["limit_bytes"]))

    field.fill("0")
    page.get_by_role("button", name="Dalej").click()
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(cache).to_contain_text(
        "Limit pamięci podglądów to liczba całkowita od 1 do 10 000 GB."
    )
    field.fill("5")
    page.get_by_role("button", name="Dalej").click()
    expect(page.locator("dt:text-is('Pamięć podglądów:') + dd")).to_have_text(
        "limit 5 GB"
    )
    page.get_by_role("button", name="Zapisz ustawienia").click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()

    assert served.settings().preview_cache_limit_gb == 5
    page.goto(f"{served.base}/?view=setup&step=mode")
    expect(page.get_by_label("Limit pamięci podglądów (GB)")).to_have_value("5")
    expect(page.locator(".cache-usage")).to_contain_text("z 5 GB")
    tab.assert_clean()


def test_no_csp_violations_previews(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """Thumbnails, legends, layers, a point cloud and archive members obey the CSP."""
    store, served = served_store(serve, tab, tmp_path)
    visit_every_kind(tab.page, served, store)
    tab.assert_clean()


def test_offline_previews_make_no_external_requests(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """Offline, previews and the settings ask nothing outside the server."""
    store, served = served_store(serve, tab, tmp_path)
    page = tab.page
    visit_every_kind(page, served, store)
    page.goto(f"{served.base}/?view=setup&step=mode")
    expect(page.locator(".cache-usage")).to_contain_text("Zajęte teraz:")

    assert tab.foreign_requests(served.base) == []
    images = [url for url in tab.requests if "/preview.png" in url]
    assert images and all(url.startswith(f"{served.base}/api/v1/") for url in images)
    tab.assert_clean()
