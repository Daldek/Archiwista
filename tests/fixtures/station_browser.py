"""IMGWTools fixture stores behind a real ``archiwista serve`` (plan I8).

The station views show the stations of a copy of a store of
``imgwtools.testing``: ``complete`` has one located water gauge (Raba Górna,
on the Raba) and one located precipitation post (Warszawa) beside stations
without a position; ``complete_pl_cz`` adds the stations of ČHMÚ. The server
is offline. Helpers start a session, read the API in the interface's
language (Polish labels), find where a position of the map lies on the
screen (MapLibre draws Web Mercator with 512 px tiles around the centre and
zoom the address holds) and where the days of a chart's plot lie, to select
them by dragging.
"""

import math
import shutil
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, StoreConfig
from tests.fixtures.browser import Served, Tab

STORE = "dane"
# Every station of the index: the box of `GET /map/stations` that frames none out.
WORLD = "-180,-85,180,85"
INDEX_TIMEOUT_S = 60.0
# The map is still when its address has not changed for this long.
STILL_S = 0.6
TILE_PX = 512
INDEXED = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  const answer = await fetch("/api/v1/health", { headers });
  if (!answer.ok) return false;
  const health = await answer.json();
  return health.stores.length > 0 && health.stores.every(
    (item) => item.state.indexed_at !== null && item.state.running_job === null,
  );
}"""
API_GET = """async (path) => {
  const headers = {
    "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf"),
    "Accept-Language": "pl",
  };
  const answer = await fetch(`/api/v1${path}`, { headers });
  return { status: answer.status, body: await answer.json() };
}"""


def station_settings(source: Path, base: Path) -> AppSettings:
    """Copy a fixture store under ``base``; return offline settings with it."""
    root = base / "imgw"
    shutil.copytree(source, root)
    store = StoreConfig(id=STORE, name="Dane IMGW", imgw=root, kind="local")
    return AppSettings(offline=True, stores=(store,))


def open_session(tab: Tab, served: Served) -> Page:
    """Start a session in the tab and wait until the store is indexed."""
    page = tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    wait_indexed(page)
    return page


def wait_indexed(page: Page) -> None:
    """Wait until every store of the page's server is indexed and no job runs."""
    deadline = time.monotonic() + INDEX_TIMEOUT_S
    while not page.evaluate(INDEXED):
        assert time.monotonic() < deadline, "the store was not indexed in time"
        page.wait_for_timeout(200)


def api(page: Page, path: str) -> Any:
    """Return the JSON answer of an API read with the page's session, in Polish."""
    answer: dict[str, Any] = page.evaluate(API_GET, path)
    assert answer["status"] == 200, answer
    return answer["body"]


def address(served: Served, **params: str) -> str:
    """Return an address of the interface."""
    return f"{served.base}/?{urlencode(params)}"


def query_of(page: Page) -> dict[str, str]:
    """Return the parameters of the page's address."""
    return dict(parse_qsl(urlsplit(page.url).query))


def wait_still(page: Page) -> None:
    """Wait until the map stopped: its address unchanged for ``STILL_S``.

    The address changes only when a move ends, so the wait starts after the
    longest animation of the map (600 ms).
    """
    page.wait_for_timeout(700)
    deadline = time.monotonic() + 20
    address = page.url
    since = time.monotonic()
    while time.monotonic() - since < STILL_S:
        assert time.monotonic() < deadline, "the map did not stop"
        page.wait_for_timeout(100)
        if page.url != address:
            address = page.url
            since = time.monotonic()


def mercator_lat(first: float, second: float) -> float:
    """Return the latitude halfway between two in Web Mercator (a cluster's)."""
    middle = (_mercator_y(first) + _mercator_y(second)) / 2
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * middle))))


def screen_point(page: Page, lon: float, lat: float) -> tuple[float, float]:
    """Return where a WGS84 position lies on the screen, from the address."""
    query = query_of(page)
    center_lon, center_lat = (float(value) for value in query["center"].split(","))
    size = TILE_PX * 2 ** float(query["zoom"])
    box = page.locator(".map-gl").bounding_box()
    assert box is not None
    x = (lon - center_lon) / 360 * size
    y = (_mercator_y(lat) - _mercator_y(center_lat)) * size
    return box["x"] + box["width"] / 2 + x, box["y"] + box["height"] / 2 + y


def hover_until(page: Page, point: tuple[float, float], shown: Locator) -> None:
    """Hover a point of the map until ``shown`` appears.

    The map draws a new answer a few frames after it arrives, and only a move
    of the pointer asks what lies under it.
    """
    deadline = time.monotonic() + 20
    step = 0
    while not shown.is_visible():
        assert time.monotonic() < deadline, f"nothing to hover at {point}"
        page.mouse.move(point[0] + step % 2, point[1])
        step += 1
        page.wait_for_timeout(150)


@dataclass(frozen=True)
class Frame:
    """A plot's range of days and where it lies: its svg on the screen, px."""

    first: date
    last: date
    svg_x: float
    left: float
    width: float
    y: float

    @property
    def days(self) -> int:
        """Return the days of the range."""
        return (self.last - self.first).days + 1

    def day_at(self, x: float) -> date:
        """Return the day under an x of the svg (its own coordinates)."""
        return self.first + timedelta(
            days=int((x - self.left) / self.width * self.days)
        )

    def screen_x(self, day: date) -> float:
        """Return the screen x of the middle of a day."""
        offset = (day - self.first).days + 0.5
        return self.svg_x + self.left + offset / self.days * self.width


def frame_of(plot: Locator) -> Frame:
    """Return the range and place of a chart's plot (``.sch-plot``)."""
    box = plot.locator("svg").bounding_box()
    assert box is not None
    return Frame(
        first=date.fromisoformat(plot.get_attribute("data-from") or ""),
        last=date.fromisoformat(plot.get_attribute("data-to") or ""),
        svg_x=box["x"],
        left=float(plot.get_attribute("data-left") or 0),
        width=float(plot.get_attribute("data-width") or 0),
        y=box["y"] + 100,
    )


def drag(page: Page, frame: Frame, first: date, last: date) -> None:
    """Select the days from ``first`` to ``last`` by dragging over the plot."""
    start, end = frame.screen_x(first), frame.screen_x(last)
    page.mouse.move(start, frame.y)
    page.mouse.down()
    page.mouse.move((start + end) / 2, frame.y)
    page.mouse.move(end, frame.y)
    page.mouse.up()


def _mercator_y(lat: float) -> float:
    """Return a latitude's place from the top of the Web Mercator world, 0 to 1."""
    phi = math.radians(lat)
    return (1 - math.log(math.tan(math.pi / 4 + phi / 2)) / math.pi) / 2
