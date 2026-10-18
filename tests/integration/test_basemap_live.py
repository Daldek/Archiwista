"""The default basemap really serves tiles to Archiwista's browsers (plan step 10b).

The application sends ``Referrer-Policy: no-referrer``, so tile requests carry no
``Referer``. Some providers (tile.openstreetmap.org) then answer ``200`` with a
small "Access blocked" picture instead of the map; the default basemap must not.
"""

import urllib.request
from dataclasses import dataclass

import pytest

from archiwista.config import DEFAULT_BASEMAP

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
APP_REFERER = "http://127.0.0.1:8090/"
# A tile near Kraków.
TILE = {"z": 10, "x": 568, "y": 346}
MIN_TILE_BYTES = 10_000


@dataclass(frozen=True)
class Tile:
    """A fetched tile.

    Parameters
    ----------
    status : int
        HTTP status of the response.
    content_type : str
        ``Content-Type`` header of the response.
    body : bytes
        The image bytes.
    """

    status: int
    content_type: str
    body: bytes


def _fetch(url: str, referer: str | None) -> Tile:
    """Fetch a tile like a browser, optionally with a ``Referer``.

    Parameters
    ----------
    url : str
        Tile URL.
    referer : str or None
        Value of the ``Referer`` header; ``None`` sends no header.

    Returns
    -------
    Tile
        Status, content type and body of the response.
    """
    headers = {"User-Agent": USER_AGENT}
    if referer is not None:
        headers["Referer"] = referer
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return Tile(
            status=response.status,
            content_type=response.headers.get("Content-Type", ""),
            body=response.read(),
        )


@pytest.mark.live
def test_default_basemap_serves_tiles_without_referer() -> None:
    """Without a Referer the default basemap gives the same real tile as with one."""
    # Arrange
    url = DEFAULT_BASEMAP.url.format(**TILE)

    # Act
    anonymous = _fetch(url, referer=None)
    referred = _fetch(url, referer=APP_REFERER)

    # Assert
    assert anonymous.status == 200
    assert referred.status == 200
    assert anonymous.content_type.startswith("image/")
    assert referred.content_type.startswith("image/")
    assert anonymous.body == referred.body
    assert len(anonymous.body) > MIN_TILE_BYTES
