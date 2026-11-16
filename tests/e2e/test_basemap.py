"""The vector basemap in Chromium on a real server (feedback before v0.2).

The default basemap is OpenFreeMap's vector tiles drawn in Archiwista's own
grey style. A local tile server on another origin stands in for it: its
TileJSON and tiles load within the page's CSP and without a ``Referer``,
labels take the Polish name in the packaged glyphs, the attribution is the
configured text and not the TileJSON's HTML, and a label in a script the
glyphs lack is still drawn, without a map failure.
"""

import json
import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import expect

from archiwista.config import AppSettings, BasemapConfig, StoreConfig
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import make_store
from tests.fixtures.tile_server import TILEJSON_PATH, tile_server

Serve = Callable[..., Served]
GLYPHS = "/static/vendor/glyphs/noto-sans-regular/"
# Latin Extended-A („ń”, „ł”), Cyrillic, Georgian (not packaged).
POLISH, CYRILLIC, GEORGIAN = "256-511", "1024-1279", "4096-4351"
WAIT_S = 30


def test_vector_basemap_within_csp_with_polish_names(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """TileJSON and tiles of another origin load in the CSP; labels are Polish."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    with tile_server() as tiles:
        basemap = BasemapConfig(
            name="Wektor testowy",
            kind="vector",
            url=tiles.tilejson,
            attribution="© Kafle testowe",
        )
        served = serve(
            AppSettings(
                offline=False,
                basemaps=(basemap,),
                stores=(
                    StoreConfig(
                        id="zespol", name="Zespół", kartograf=store.root, kind="local"
                    ),
                ),
                project_dirs=(store.projects_dir,),
            )
        )

        def glyphs(part: str) -> str:
            return f"{served.base}{GLYPHS}{part}.pbf"

        page = tab.page
        page.goto(served.token_url())
        expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
        document = page.goto(f"{served.base}/?view=map&center=19.0,52.0&zoom=6")
        expect(page.get_by_text("© Kafle testowe")).to_be_attached()
        deadline = time.monotonic() + WAIT_S
        while not {glyphs(POLISH), glyphs(GEORGIAN)} <= set(tab.requests):
            assert time.monotonic() < deadline, "the basemap's labels were not laid out"
            page.wait_for_timeout(100)
        page.wait_for_timeout(500)
        requested = list(tiles.requests)

    assert document is not None
    policy = document.headers["content-security-policy"]
    assert f"connect-src 'self' {tiles.origin};" in policy
    assert requested[0].path == TILEJSON_PATH
    assert tiles.tiles()
    assert {request.referer for request in requested} == {None}
    assert {request.origin for request in requested} <= {served.base, None}
    assert all(
        url.startswith(f"{tiles.origin}/") for url in tab.foreign_requests(served.base)
    )
    # „Lwów” of name:pl, not the local „Львів”.
    assert glyphs(CYRILLIC) not in tab.requests
    expect(page.get_by_text("Obca atrybucja")).to_have_count(0)
    expect(page.locator(".map-failure")).to_have_count(0)
    expect(page.get_by_text("Podkład nie odpowiada")).to_have_count(0)
    expect(page.get_by_label("Podkład")).to_have_value("Wektor testowy")
    tab.assert_clean()


def test_vector_basemap_rejects_tiles_outside_tilejson_origin(
    serve: Serve, tab: Tab, tmp_path: Path
) -> None:
    """A mismatched TileJSON shows a note without requesting CSP-blocked tiles."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    with tile_server() as tiles:
        served = serve(
            AppSettings(
                offline=False,
                basemaps=(
                    BasemapConfig(
                        name="Wektor testowy", kind="vector", url=tiles.tilejson
                    ),
                ),
                stores=(
                    StoreConfig(
                        id="zespol", name="Zespół", kartograf=store.root, kind="local"
                    ),
                ),
                project_dirs=(store.projects_dir,),
            )
        )
        page = tab.page
        foreign = "https://other.example.invalid/planet/{z}/{x}/{y}.pbf"
        tilejson = {
            "tilejson": "3.0.0",
            "tiles": [f"{tiles.origin}/planet/{{z}}/{{x}}/{{y}}.pbf", foreign],
        }
        page.route(
            tiles.tilejson,
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
                body=json.dumps(tilejson),
            ),
        )
        page.goto(served.token_url())
        expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
        page.goto(f"{served.base}/?view=map&center=19.0,52.0&zoom=6")
        expect(page.get_by_text("Podkład nie odpowiada", exact=False)).to_be_visible()
        expect(page.get_by_label("Podkład")).to_have_value("Wektor testowy")
        expect(page.locator(".maplibregl-canvas")).to_be_visible()
        assert tiles.tiles() == []
        assert all("other.example.invalid" not in url for url in tab.requests)
        tab.assert_clean()
