"""Previews through the API: MapLibre tiles and ``blob:`` images under the CSP.

Plan v0.2, decision 3: preview images and tiles come from ``/api/v1`` with
the ``X-Archiwista-CSRF`` header like every API request. MapLibre 6 adds it
in ``transformRequest`` and fetches raster tiles with ``fetch``, so
``connect-src 'self'`` is enough; an ``<img>`` shows a fetched image as a
``blob:`` address (``img-src blob:``). The test server answers with the
v0.1 policy of ``csp_header`` (offline: nothing but the server itself) and
refuses a tile or an image without the header.
"""

import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

import archiwista.web
from archiwista.config import AppSettings
from archiwista.security import CSRF_HEADER, csp_header
from tests.fixtures.browser import Tab
from tests.fixtures.tile_server import grey_png

TOKEN = "csrf-token-of-the-page"
THUMBNAIL_PX = 64
MAPLIBRE_DIR = Path(archiwista.web.__file__).parent / "vendor" / "maplibre-gl"
PAGE = f"""<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<title>Kafle podglądu</title>
<link rel="stylesheet" href="/vendor/maplibre-gl/maplibre-gl.css">
<link rel="stylesheet" href="/probe.css">
<script type="module" src="/probe.js"></script>
</head>
<body data-csrf="{TOKEN}"><div id="map"></div><img id="thumb" alt=""></body>
</html>
"""
STYLE = "#map { width: 512px; height: 512px; }\n"
# The page's module: a raster source of preview tiles and one blob: image.
PROBE = f"""
import {{ Map }} from "/vendor/maplibre-gl/maplibre-gl.mjs";

const token = document.body.dataset.csrf;
const headers = {{ "{CSRF_HEADER}": token }};
window.__mapErrors = [];

function sameOrigin(url) {{
  return new URL(url, location.href).origin === location.origin;
}}

const map = new Map({{
  container: "map",
  style: {{
    version: 8,
    sources: {{
      preview: {{
        type: "raster",
        tiles: [`${{location.origin}}/api/v1/previews/tiles/{{z}}/{{x}}/{{y}}.png`],
        tileSize: 256,
      }},
    }},
    layers: [{{ id: "preview", type: "raster", source: "preview" }}],
  }},
  center: [18.589, 49.759],
  zoom: 12,
  attributionControl: false,
  transformRequest: (url, resourceType) =>
    resourceType === "Tile" && sameOrigin(url) ? {{ url, headers }} : undefined,
}});
map.on("error", (event) => {{
  window.__mapErrors.push(String(event.error?.message ?? event));
}});
map.on("idle", () => {{
  if (map.isSourceLoaded("preview") && map.areTilesLoaded()) {{
    document.body.dataset.tiles = "loaded";
  }}
}});

const response = await fetch("/api/v1/previews/thumbnail.png", {{ headers }});
const image = document.getElementById("thumb");
image.src = URL.createObjectURL(await response.blob());
await image.decode();
window.__thumbnail = {{
  status: response.status,
  width: image.naturalWidth,
  scheme: new URL(image.src).protocol,
}};
document.body.dataset.thumbnail = "ready";
"""
_STATIC = {
    "/": (PAGE.encode("utf-8"), "text/html; charset=utf-8"),
    "/probe.css": (STYLE.encode("utf-8"), "text/css; charset=utf-8"),
    "/probe.js": (PROBE.encode("utf-8"), "text/javascript; charset=utf-8"),
}
_VENDOR_TYPES = {".mjs": "text/javascript; charset=utf-8", ".css": "text/css"}


@dataclass
class PreviewServer:
    """A server of preview tiles and images and the API requests it got."""

    base: str
    api_requests: list[tuple[str, str | None]] = field(default_factory=list)


@contextmanager
def preview_server() -> Iterator[PreviewServer]:
    """Serve the page, MapLibre and previews with the v0.1 CSP on 127.0.0.1."""
    policy = csp_header(AppSettings(offline=True))
    tile, thumbnail = grey_png(), grey_png(THUMBNAIL_PX)
    requests: list[tuple[str, str | None]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path.startswith("/api/v1/previews/"):
                header = self.headers.get(CSRF_HEADER)
                requests.append((path, header))
                image = thumbnail if path.endswith("/thumbnail.png") else tile
                if header != TOKEN:
                    self._answer(403, b"", "text/plain")
                else:
                    self._answer(200, image, "image/png")
            elif path in _STATIC:
                self._answer(200, *_STATIC[path])
            elif path.startswith("/vendor/maplibre-gl/"):
                found = MAPLIBRE_DIR / path.rsplit("/", 1)[1]
                kind = _VENDOR_TYPES.get(found.suffix)
                if kind is None or not found.is_file():
                    self._answer(404, b"", "text/plain")
                else:
                    self._answer(200, found.read_bytes(), kind)
            else:
                self._answer(404, b"", "text/plain")

        def _answer(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Security-Policy", policy)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Keep the test output quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield PreviewServer(base=base, api_requests=requests)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def served() -> Iterator[PreviewServer]:
    """Yield a running preview server."""
    with preview_server() as running:
        yield running


def _status(url: str) -> int:
    """Status of a request without the CSRF header."""
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return int(answer.status)
    except urllib.error.HTTPError as error:
        # The error holds the answer's body open; unclosed it warns (ResourceWarning).
        with error:
            return int(error.code)


def _loaded(page: Page) -> None:
    """Wait until the map's tiles and the image are shown (no eval: the CSP)."""
    body = page.locator("body")
    expect(body).to_have_attribute("data-tiles", "loaded", timeout=30_000)
    expect(body).to_have_attribute("data-thumbnail", "ready", timeout=30_000)


def test_maplibre_raster_tiles_carry_csrf_header(
    served: PreviewServer, tab: Tab
) -> None:
    """Every tile and the image carry the header; nothing breaks the CSP."""
    # Arrange
    refused = _status(f"{served.base}/api/v1/previews/thumbnail.png")

    # Act
    tab.page.goto(served.base + "/")
    _loaded(tab.page)

    # Assert
    assert refused == 403
    tiles = [item for item in served.api_requests if "/tiles/" in item[0]]
    assert tiles
    assert {header for _, header in tiles} == {TOKEN}
    assert ("/api/v1/previews/thumbnail.png", TOKEN) in served.api_requests
    assert tab.page.evaluate("window.__mapErrors") == []
    assert tab.page.evaluate("window.__thumbnail") == {
        "status": 200,
        "width": THUMBNAIL_PX,
        "scheme": "blob:",
    }
    assert tab.foreign_requests(served.base) == []
    tab.assert_clean()
