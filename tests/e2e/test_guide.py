"""„Instrukcja”: the user guide at ``/instrukcja``, in Chromium and Firefox.

A real ``archiwista serve`` shows „Instrukcja” in the top bar, which opens the
guide in a new tab: every picture of it loads and nothing breaks the CSP, its
slides are 16:9 inside a computer's window, and at a phone's width the link is
an icon inside the top bar and the guide one column without sideways scrolling.
A team server serves the guide before anyone signs in, as it serves the sign-in
page, and its signed-in top bar leads there too.
"""

from collections.abc import Callable
from urllib.parse import urlsplit

from playwright.sync_api import Locator, Page, ViewportSize, expect

from tests.fixtures.browser import CSP_WATCH, Served, Tab
from tests.fixtures.team_pages import signed_in
from tests.fixtures.team_server import ADMIN_ACCOUNT, ADMIN_PASSWORD, TeamServed

GUIDE = "/instrukcja"
PHONE: ViewportSize = {"width": 390, "height": 844}
# The pictures of the page that did not load: their addresses.
BROKEN = """() => [...document.images]
  .filter((image) => !image.complete || image.naturalWidth === 0)
  .map((image) => image.getAttribute("src"))"""
# The sizes of the guide's slides, as drawn.
SLIDES = """() => [...document.querySelectorAll("main > section")].map((slide) => {
  const box = slide.getBoundingClientRect();
  return [box.width, box.height];
})"""
OVERFLOW = "() => document.documentElement.scrollWidth - innerWidth"


def guide_link(page: Page) -> Locator:
    """Return „Instrukcja” of the page's top bar."""
    return page.get_by_role("banner").get_by_role("link", name="Instrukcja")


def open_guide(page: Page) -> Page:
    """Follow „Instrukcja” of the top bar; return the guide's tab once it has loaded."""
    with page.context.expect_page() as opened:
        guide_link(page).click()
    guide = opened.value
    guide.wait_for_load_state("load")
    return guide


def assert_guide_loaded(guide: Page) -> None:
    """Check the guide is there with every picture and no CSP violation."""
    assert urlsplit(guide.url).path == GUIDE
    expect(guide.get_by_role("heading", level=1)).to_have_text("Archiwista")
    assert guide.evaluate("() => document.images.length") > 0
    assert guide.evaluate(BROKEN) == []
    assert guide.evaluate("window.__cspViolations") == []


def test_the_top_bar_opens_the_guide_with_its_pictures_on_a_computer_and_a_phone(
    serve: Callable[..., Served], engine_tab: Tab
) -> None:
    """A new tab with the guide; 16:9 slides; on a phone an icon and one column."""
    # Arrange
    served = serve()
    page = engine_tab.page
    # The new tab records CSP violations from its first byte, as the app's does.
    page.context.add_init_script(CSP_WATCH)
    page.goto(served.token_url())

    # Act
    guide = open_guide(page)

    # Assert
    assert_guide_loaded(guide)
    window = guide.viewport_size
    assert window is not None
    slides = guide.evaluate(SLIDES)
    assert slides
    for width, height in slides:
        assert abs(width / height - 16 / 9) < 0.01
        assert width <= window["width"] and height <= window["height"]

    # Act: a phone's width, the guide and the app.
    guide.set_viewport_size(PHONE)
    page.set_viewport_size(PHONE)

    # Assert
    assert guide.evaluate(OVERFLOW) == 0
    assert all(width <= PHONE["width"] for width, _ in guide.evaluate(SLIDES))
    box = guide_link(page).bounding_box()
    assert box is not None
    assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"]
    assert page.evaluate(OVERFLOW) == 0
    guide.close()
    engine_tab.assert_clean()


def test_a_team_server_serves_the_guide_before_and_after_signing_in(
    team_serve: Callable[..., TeamServed], team_tab: Callable[..., Tab]
) -> None:
    """Without a session the guide loads over TLS; signed in, the top bar opens it."""
    # Arrange
    served = team_serve()
    tab = team_tab()
    page = tab.page
    page.context.add_init_script(CSP_WATCH)

    # Act
    page.goto(f"{served.origin}{GUIDE}")
    page.wait_for_load_state("load")

    # Assert
    assert_guide_loaded(page)

    # Act
    signed_in(page, served.origin, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    guide = open_guide(page)

    # Assert
    assert_guide_loaded(guide)
    guide.close()
    tab.assert_clean()
