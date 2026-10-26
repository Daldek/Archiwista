"""The shell in Chromium on a real server (plan v0.1, step 10a).

A session from the one-time token of the address, the instruction without a
session, the first-run wizard, offline mode with MapLibre's worker and the
packaged glyphs under the CSP, every ES module loading without errors (the
syntax check without Node.js), and in Chromium and Firefox an interface
upgraded on the same address reaching the next visit, view modules included.
"""

import os
import re
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from playwright.sync_api import Browser, Page, expect

import archiwista.web
from archiwista.config import AppSettings, ConfigStore, StoreConfig
from tests.fixtures.browser import Served, Tab
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.make_store import make_store

WEB_DIR = Path(archiwista.web.__file__).resolve().parent
# The map view's panel, a module the view imports once the page has loaded.
PANEL_MODULE = "src/map/panel.js"
# A file this old stays fresh by heuristic for a tenth of its age (three
# days): a browser would reuse it without asking, were it not ``no-cache``.
MONTH_S = 30 * 24 * 3600
GLYPHS = "/static/vendor/glyphs/noto-sans-regular/"
# A map like a map view's: a polygon and a label whose letters need three
# glyph ranges (Latin-1, Latin Extended-A for „Ł” and „ź”, punctuation „–”).
DRAW_MAP = """
async () => {
  const { GLYPHS, GLYPH_FONT, loadMapLibre } = await import("/static/src/maplibre.js");
  const maplibre = await loadMapLibre();
  const box = document.createElement("div");
  box.style.cssText = "position:fixed;left:0;top:0;width:480px;height:320px";
  document.body.append(box);
  const map = new maplibre.Map({
    container: box,
    attributionControl: false,
    center: [19.95, 50.05],
    zoom: 10,
    style: {
      version: 8,
      glyphs: GLYPHS,
      sources: {
        area: {
          type: "geojson",
          data: {
            type: "Feature",
            properties: { name: "Łódź – N-34-130" },
            geometry: {
              type: "Polygon",
              coordinates: [
                [[19.9, 50.0], [20.0, 50.0], [20.0, 50.1], [19.9, 50.1], [19.9, 50.0]],
              ],
            },
          },
        },
      },
      layers: [
        { id: "background", type: "background", paint: { "background-color": "#eee" } },
        { id: "fill", type: "fill", source: "area", paint: { "fill-color": "#46e" } },
        {
          id: "label",
          type: "symbol",
          source: "area",
          layout: { "text-field": ["get", "name"], "text-font": [GLYPH_FONT] },
        },
      ],
    },
  });
  await new Promise((resolve, reject) => {
    map.once("idle", resolve);
    map.once("error", (event) => reject(event.error));
  });
  const labels = map.queryRenderedFeatures({ layers: ["label"] }).length;
  map.remove();
  box.remove();
  return { version: maplibre.getVersion(), labels };
}
"""
IMPORT_ALL = """
async (paths) => {
  const results = await Promise.allSettled(
    paths.map((path) => import(`/static/${path}`)),
  );
  return results.flatMap((result, index) =>
    result.status === "rejected" ? [`${paths[index]}: ${result.reason}`] : []);
}
"""

Serve = Callable[..., Served]


def open_shell(page: Page, url: str) -> None:
    """Open an address and wait for the shell of a started session."""
    page.goto(url)
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def open_map_view(page: Page, served: Served) -> None:
    """Open the map view with a new session, in one page load."""
    fragment = urlsplit(served.token_url()).fragment
    page.goto(f"{served.base}/?view=map#{fragment}")


def zespol(root: Path) -> StoreConfig:
    """Return the generated store as the ``zespol`` store."""
    return StoreConfig(id="zespol", name="Zespół", kartograf=root, kind="local")


def interface_copy(directory: Path, build: str, modified: float) -> Path:
    """Copy the interface, dated ``modified``; its panel marks the page ``build``."""
    shutil.copytree(WEB_DIR, directory)
    panel = directory / PANEL_MODULE
    mark = f'\ndocument.documentElement.dataset.build = "{build}";\n'
    panel.write_text(panel.read_text("utf-8") + mark, "utf-8")
    for path in directory.rglob("*"):
        os.utime(path, (modified, modified))
    return directory


def test_fragment_token_starts_session_and_is_removed_from_url(
    serve: Serve, tab: Tab, chromium: Browser
) -> None:
    """The token of ``#token=`` becomes a session and leaves the address at once."""
    served = serve()
    url = served.token_url()
    token = url.partition("#token=")[2]

    open_shell(tab.page, url)
    address = tab.page.url
    cookies = {cookie["name"]: cookie for cookie in tab.page.context.cookies()}
    tab.page.reload()
    expect(tab.page.get_by_text("Sesja: właściciel lokalny")).to_be_visible()
    other = chromium.new_context()
    replay = other.new_page()
    replay.goto(url)

    assert token not in address
    assert urlsplit(address).fragment == ""
    assert cookies["archiwista_session"]["httpOnly"] is True
    assert cookies["archiwista_session"]["sameSite"] == "Strict"
    # The CSRF token stays in the tab (sessionStorage), never in a cookie.
    assert "archiwista_csrf" not in cookies
    assert tab.page.evaluate("() => sessionStorage.getItem('archiwista_csrf')")
    expect(replay.get_by_role("heading", name="Wymagana sesja")).to_be_visible()
    expect(
        replay.get_by_text("Token jest nieznany, wygasł albo został już użyty")
    ).to_be_visible()
    other.close()
    tab.assert_clean()


def test_no_session_shows_instruction(serve: Serve, tab: Tab) -> None:
    """Without a session — or once it is gone — the page says how to open one."""
    served = serve()

    tab.page.goto(served.base + "/")
    expect(tab.page.get_by_role("heading", name="Wymagana sesja")).to_be_visible()
    expect(tab.page.get_by_text("Ta karta nie zna tokenu sesji")).to_be_visible()
    expect(tab.page.get_by_text("Otwórz adres z terminala")).to_be_visible()
    expect(tab.page.get_by_text("archiwista token", exact=True)).to_be_visible()
    open_shell(tab.page, served.token_url())
    tab.page.context.clear_cookies()
    tab.page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")

    expect(
        tab.page.get_by_text("Sesja wygasła albo serwer został uruchomiony ponownie.")
    ).to_be_visible()
    expect(tab.page.get_by_role("navigation", name="Widoki")).to_have_count(0)
    tab.assert_clean()


def test_first_run_wizard_saves_settings(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """The wizard saves a store and project directory; the server then indexes it."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    expect(page.get_by_role("heading", name="Pierwsze uruchomienie")).to_be_visible()
    expect(
        page.get_by_text("Nie skonfigurowano jeszcze żadnego magazynu")
    ).to_be_visible()

    page.get_by_label("Nazwa", exact=True).fill("Zespół")
    page.get_by_label("Katalog Kartografa").fill(str(tmp_path / "missing"))
    page.get_by_role("button", name="Dalej").click()
    page.get_by_role("button", name="Dodaj katalog").click()
    page.get_by_label("Katalog projektów 1").fill(str(store.projects_dir))
    page.get_by_role("button", name="Dalej").click()
    page.get_by_role("button", name="Dalej").click()
    page.get_by_role("button", name="Zapisz i zindeksuj").click()
    field = page.get_by_label("Katalog Kartografa")
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(
        page.get_by_text("nie istnieje albo udział nie jest podłączony")
    ).to_be_visible()
    refused = served.settings()
    expect(page.get_by_label("Identyfikator")).to_have_value("zespol")
    field.fill(str(store.root))
    page.get_by_role("button", name=re.compile("Zapis$")).click()
    page.get_by_role("button", name="Zapisz i zindeksuj").click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()
    expect(page.get_by_text("Magazyn „Zespół” zindeksowany")).to_be_visible(
        timeout=60_000
    )
    saved = served.settings()

    assert refused.stores == ()
    assert saved.stores == (zespol(store.root),)
    assert saved.project_dirs == (store.projects_dir,)
    query = dict(parse_qsl(urlsplit(page.url).query))
    assert query == {"view": "setup", "step": "save", "saved": "1"}
    tab.assert_clean()


def test_first_run_wizard_offers_the_default_root_and_enters_it_on_a_click(
    serve: Serve, tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf's own store is offered under the empty field, entered by a click."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    monkeypatch.setenv("KARTOGRAF_ROOT", str(store.root))
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    field = page.get_by_label("Katalog Kartografa")
    offer = page.get_by_text("Kartograf zapisuje domyślnie w katalogu")
    use = page.get_by_role("button", name="Użyj tego katalogu")

    expect(offer).to_contain_text(str(store.root))
    expect(offer).to_contain_text("zmienna KARTOGRAF_ROOT")
    expect(field).to_have_value("")  # offered, not entered
    page.get_by_label("Nazwa", exact=True).fill("Zespół")
    use.click()
    expect(field).to_have_value(str(store.root))
    expect(use).to_have_count(0)  # it is entered: nothing left to offer
    for _ in range(3):
        page.get_by_role("button", name="Dalej").click()
    page.get_by_role("button", name="Zapisz i zindeksuj").click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()
    expect(page.get_by_text("Magazyn „Zespół” zindeksowany")).to_be_visible(
        timeout=60_000
    )

    assert served.settings().stores == (zespol(store.root),)
    tab.assert_clean()


def test_first_run_wizard_offers_both_default_roots_each_under_its_own_field(
    serve: Serve, tab: Tab, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf's and IMGWTools' stores are offered, each entered by its own click."""
    imgwtools = pytest.importorskip("imgwtools")
    store = make_store(tmp_path / "store", slots=24, seed=7)
    imgw_root = tmp_path / "imgw"
    imgwtools.init_store(imgw_root)
    monkeypatch.setenv("KARTOGRAF_ROOT", str(store.root))
    monkeypatch.setenv("IMGW_ROOT", str(imgw_root))
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    kartograf = page.get_by_label("Katalog Kartografa")
    imgw = page.get_by_label("Katalog IMGWTools")
    kartograf_offer = page.get_by_text("Kartograf zapisuje domyślnie w katalogu")
    imgw_offer = page.get_by_text("IMGWTools zapisuje domyślnie w katalogu")

    expect(kartograf_offer).to_contain_text(str(store.root))
    expect(imgw_offer).to_contain_text(str(imgw_root))
    expect(imgw_offer).to_contain_text("zmienna IMGW_ROOT")
    expect(imgw).to_have_value("")  # offered, not entered
    page.get_by_role("button", name="Użyj tego katalogu").nth(1).click()
    expect(imgw).to_have_value(str(imgw_root))
    expect(kartograf).to_have_value("")
    expect(imgw_offer).to_have_count(0)  # it is entered: nothing left to offer
    expect(kartograf_offer).to_have_count(1)
    tab.assert_clean()


@pytest.mark.parametrize("exists", [True, False], ids=["no-marker", "no-directory"])
def test_first_run_wizard_offers_no_default_root_that_is_no_store(
    serve: Serve,
    tab: Tab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exists: bool,
) -> None:
    """A default root without the marker, or that is not there, is not offered."""
    root = tmp_path / "kartograf"
    if exists:
        root.mkdir()
    monkeypatch.setenv("KARTOGRAF_ROOT", str(root))
    served = serve()
    page = tab.page
    with page.expect_response(re.compile(r"/api/v1/sources$")):
        open_shell(page, served.token_url())
    # Two frames after the answer, the page has drawn what it made of it.
    page.evaluate(
        "() => new Promise((done) => requestAnimationFrame(()"
        " => requestAnimationFrame(done)))"
    )

    expect(page.get_by_label("Katalog Kartografa")).to_be_visible()
    expect(page.get_by_role("button", name="Użyj tego katalogu")).to_have_count(0)
    assert root.exists() == exists  # looking at it created nothing
    tab.assert_clean()


def test_no_csp_violations_offline(serve: Serve, tab: Tab, tmp_path: Path) -> None:
    """Offline, the shell and MapLibre (worker, glyphs) stay within the CSP."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = serve(
        AppSettings(
            offline=True,
            stores=(zespol(store.root),),
            project_dirs=(store.projects_dir,),
        )
    )
    page = tab.page
    open_shell(page, served.token_url())
    document = page.goto(served.base + "/?view=setup")
    expect(page.get_by_role("heading", name="Ustawienia")).to_be_visible()
    for step in ("Projekty", "Zapis", "Tryb pracy"):
        page.get_by_role("button", name=re.compile(f"{step}$")).click()
        expect(page.locator("[aria-current=step]")).to_contain_text(step)
    expect(page.get_by_label("Tryb offline")).to_be_checked()
    page.goto(served.base + "/?view=nieznany")
    expect(page.get_by_text("Nie ma widoku „nieznany”.")).to_be_visible()

    drawn = page.evaluate(DRAW_MAP)

    assert document is not None
    policy = document.headers["content-security-policy"]
    assert "worker-src 'self';" in policy
    assert "http" not in policy
    assert drawn == {"version": "6.14.0", "labels": 1}
    assert {urlsplit(url).path for url in tab.workers} == {
        "/static/vendor/maplibre-gl/maplibre-gl-worker.mjs"
    }
    glyphs = {
        f"{served.base}{GLYPHS}{part}.pbf" for part in ("0-255", "256-511", "8192-8447")
    }
    assert glyphs <= set(tab.requests)
    assert tab.foreign_requests(served.base) == []
    tab.assert_clean()


def test_all_modules_load_without_errors(serve: Serve, tab: Tab) -> None:
    """Every module of src/ and every vendored module imports in Chromium."""
    served = serve()
    open_shell(tab.page, served.token_url())
    sources = sorted(
        path.relative_to(WEB_DIR).as_posix() for path in (WEB_DIR / "src").rglob("*.js")
    )
    vendored = sorted(
        path.relative_to(WEB_DIR).as_posix()
        for path in (WEB_DIR / "vendor").rglob("*.mjs")
        if not path.name.endswith("-worker.mjs")
    )

    failures = tab.page.evaluate(IMPORT_ALL, sources + vendored)

    assert {"src/main.js", "src/setup.js", "src/labels/index.js"} <= set(sources)
    assert "vendor/maplibre-gl/maplibre-gl.mjs" in vendored
    assert failures == []
    tab.assert_clean()


def test_an_upgraded_interface_reaches_the_next_visit(
    engine_tab: Tab, tmp_path: Path
) -> None:
    """After an upgrade on the same address the next visit runs the new modules.

    A view's modules are imported after the page has loaded, so not even a
    forced reload asks for them again: a browser that kept the previous
    build's by heuristic freshness went on showing its map panel (without
    „U źródła”) for days. Every file is ``no-cache``, so it asks each time.
    Each visit is one page load in a tab of its own in the same browser (one
    cache); the first tab closes before its server stops.
    """
    now = time.time()
    previous = interface_copy(tmp_path / "previous", "previous", now - MONTH_S)
    upgraded = interface_copy(tmp_path / "upgraded", "upgraded", now)
    paths = local_paths(tmp_path)
    ConfigStore(paths.config_file).save(AppSettings(offline=True))
    context = engine_tab.page.context

    with serving(paths, web_dir=previous) as (server, _):
        open_map_view(engine_tab.page, Served(server, paths))
        expect(engine_tab.page.locator("html")).to_have_attribute(
            "data-build", "previous"
        )
        engine_tab.assert_clean()
        engine_tab.page.close()
        port = server.port
    with serving(paths, port=port, web_dir=upgraded) as (server, _):
        again = Tab(context.new_page())
        again.watch()
        open_map_view(again.page, Served(server, paths))

        expect(again.page.locator("html")).to_have_attribute("data-build", "upgraded")
        again.assert_clean()
