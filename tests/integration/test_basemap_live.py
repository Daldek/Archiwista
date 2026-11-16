"""The built-in basemaps really serve Archiwista's browsers (plan step 10b).

The application sends ``Referrer-Policy: no-referrer``, so tile requests carry no
``Referer``. Some providers (tile.openstreetmap.org) then answer ``200`` with a
small "Access blocked" picture instead of the map; the built-in basemaps must
not. MapLibre reads tiles and a TileJSON with ``fetch`` from the page's origin,
so they must allow it (CORS), and the vector tiles must lie on the TileJSON's
origin: the page's CSP allows no other.
"""

import gzip
import json
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest

from archiwista.config import DEFAULT_BASEMAPS, BasemapConfig, BasemapKind

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
APP_ORIGIN = "http://127.0.0.1:8090"
APP_REFERER = f"{APP_ORIGIN}/"
# A tile near Kraków.
TILE = {"z": 10, "x": 568, "y": 346}
MIN_TILE_BYTES = 10_000
# Source layers drawn by Archiwista's vector style (web/src/map/style.js).
STYLE_LAYERS = {
    "boundary",
    "landuse",
    "place",
    "transportation",
    "water",
    "water_name",
    "waterway",
}


@dataclass(frozen=True)
class Answer:
    """A fetched resource.

    Parameters
    ----------
    status : int
        HTTP status of the response.
    content_type : str
        ``Content-Type`` header of the response.
    allow_origin : str or None
        ``Access-Control-Allow-Origin`` header of the response.
    body : bytes
        The body, gzip already undone.
    """

    status: int
    content_type: str
    allow_origin: str | None
    body: bytes


def _fetch(url: str, referer: str | None) -> Answer:
    """Fetch like MapLibre in the page, optionally with a ``Referer``.

    Parameters
    ----------
    url : str
        Address of a tile or a TileJSON.
    referer : str or None
        Value of the ``Referer`` header; ``None`` sends no header.

    Returns
    -------
    Answer
        Status, content type, CORS header and body of the response.
    """
    headers = {"User-Agent": USER_AGENT, "Origin": APP_ORIGIN}
    if referer is not None:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        return Answer(
            status=response.status,
            content_type=response.headers.get("Content-Type", ""),
            allow_origin=response.headers.get("Access-Control-Allow-Origin"),
            body=gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body,
        )


def _built_in(kind: BasemapKind) -> BasemapConfig:
    """Return the built-in basemap of a kind."""
    return next(basemap for basemap in DEFAULT_BASEMAPS if basemap.kind == kind)


@pytest.mark.live
def test_vector_basemap_serves_tilejson_and_tiles_without_referer() -> None:
    """The TileJSON and its tiles answer without a Referer, on the TileJSON's origin."""
    # Arrange
    basemap = _built_in("vector")

    # Act
    tilejson = _fetch(basemap.url, referer=None)
    document = json.loads(tilejson.body)
    template = document["tiles"][0]
    anonymous = _fetch(template.format(**TILE), referer=None)
    referred = _fetch(template.format(**TILE), referer=APP_REFERER)

    # Assert
    assert tilejson.status == 200
    assert tilejson.allow_origin in ("*", APP_ORIGIN)
    assert {layer["id"] for layer in document["vector_layers"]} >= STYLE_LAYERS
    parts = urlsplit(template)
    assert f"{parts.scheme}://{parts.netloc}" == basemap.origin
    assert anonymous.status == 200
    assert referred.status == 200
    assert anonymous.allow_origin in ("*", APP_ORIGIN)
    assert anonymous.body == referred.body
    assert len(anonymous.body) > MIN_TILE_BYTES
    assert "Kraków".encode() in anonymous.body


@pytest.mark.live
def test_raster_basemap_serves_tiles_without_referer() -> None:
    """Without a Referer the built-in raster gives the same real tile as with one."""
    # Arrange
    url = _built_in("xyz").url.format(**TILE)

    # Act
    anonymous = _fetch(url, referer=None)
    referred = _fetch(url, referer=APP_REFERER)

    # Assert
    assert anonymous.status == 200
    assert referred.status == 200
    assert anonymous.content_type.startswith("image/")
    assert anonymous.allow_origin in ("*", APP_ORIGIN)
    assert anonymous.body == referred.body
    assert len(anonymous.body) > MIN_TILE_BYTES
