"""A phone held upright, from the first load, in Chromium's mobile emulation.

An iPhone's browser (WebKit, whichever app) zooms the page in when a field
whose text is smaller than 16 px takes the focus, and keeps that zoom after
the field: the shell opened after the sign-in form wider than the screen,
its bottom navigation overflowing until a rotation reset the zoom. So on a
phone every field has 16 px text, and each view opens within the width of
the screen with all of the navigation on it; a computer's fields keep the
size of the text around them. The phone is Chromium's emulation: Firefox has
none, and WebKit is not among the engines of these tests (``ENGINES``).
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, ViewportSize, expect

from tests.e2e.test_map import offline_settings, wait_indexed
from tests.e2e.test_projects_view import served_store
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import make_store
from tests.fixtures.team_pages import expect_shell, fill_sign_in, open_sign_in, sign_in
from tests.fixtures.team_server import ADMIN_ACCOUNT, ADMIN_PASSWORD, TeamServed

Serve = Callable[..., Served]
TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]

# An iPhone 15 upright (Playwright's „iPhone 15”: the page below the browser's bars).
PHONE: ViewportSize = {"width": 393, "height": 659}
# Smallest text of a field that iOS does not zoom in on when it takes the focus.
LEGIBLE_PX = 16
# The shown fields one types or chooses in (a closed bottom sheet's are hidden),
# with the size of their text.
FIELDS = """
() => [...document.querySelectorAll("input, select, textarea")]
  .filter((field) => field.checkVisibility({ visibilityProperty: true })
    && !["checkbox", "radio", "range", "hidden"].includes(field.type))
  .map((field) => ({
    field: field.labels?.[0]?.textContent.trim()
      || field.getAttribute("aria-label") || field.name,
    px: parseFloat(getComputedStyle(field).fontSize),
  }))
"""
# How far the page reaches past the window, and the views of the navigation outside it.
WIDTH = """
() => ({
  overflow: document.documentElement.scrollWidth - innerWidth,
  outside: [...document.querySelectorAll('nav[aria-label="Widoki"] a')]
    .filter((item) => {
      const box = item.getBoundingClientRect();
      return box.width === 0 || box.left < 0 || box.right > innerWidth;
    })
    .map((item) => item.textContent.trim()),
})
"""
# What shows each view has opened at its address.
VIEWS: dict[str, Callable[[Page], Locator]] = {
    "map": lambda page: page.get_by_role("button", name="Wybór", exact=True),
    "catalog": lambda page: page.get_by_role("grid", name="Lista plików katalogu"),
    "projects": lambda page: page.locator(".projects-table"),
}


@pytest.fixture
def phone(chromium: Browser) -> Iterator[Callable[[], Tab]]:
    """Yield ``phone()``: a recording page of an emulated phone held upright."""
    contexts = []

    def new() -> Tab:
        context = chromium.new_context(
            viewport=PHONE,
            device_scale_factor=3,
            is_mobile=True,
            has_touch=True,
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            ignore_https_errors=True,
        )
        contexts.append(context)
        recorded = Tab(context.new_page())
        recorded.watch()
        return recorded

    yield new
    for context in contexts:
        context.close()


def small_fields(page: Page) -> list[dict[str, Any]]:
    """Return the shown fields whose text iOS zooms in on."""
    fields: list[dict[str, Any]] = page.evaluate(FIELDS)
    return [field for field in fields if field["px"] < LEGIBLE_PX]


def assert_fits(page: Page) -> None:
    """Assert the page is no wider than the window and shows all its views."""
    assert page.evaluate(WIDTH) == {"overflow": 0, "outside": []}


@pytest.mark.parametrize("view", list(VIEWS))
def test_each_view_opens_on_a_phone_within_its_width(
    serve: Serve, phone: Callable[[], Tab], tmp_path: Path, view: str
) -> None:
    """Opened at its address upright, a view fits the screen; no field needs a zoom."""
    _, served = served_store(serve, tmp_path)
    tab = phone()
    page = tab.page
    page.goto(served.token_url())
    wait_indexed(page)

    page.goto(f"{served.base}/?view={view}")
    expect(VIEWS[view](page)).to_be_visible()

    assert_fits(page)
    if view == "catalog":
        expect(page.get_by_role("searchbox")).to_be_visible()
    assert small_fields(page) == []
    tab.assert_clean()


def test_a_phone_signs_in_and_opens_the_map_within_its_width(
    team_serve: TeamServe, phone: Callable[[], Tab], tmp_path: Path
) -> None:
    """The sign-in fields need no zoom; then the map and its panel fit the screen."""
    store = make_store(tmp_path / "store", slots=24, seed=7)
    served = team_serve(offline_settings(store))
    tab = phone()
    page = tab.page
    panel = page.get_by_role("complementary", name="Wybór")

    open_sign_in(page, served.origin)
    sign_in_small = small_fields(page)
    fill_sign_in(page, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    sign_in(page)
    expect_shell(page)
    page.get_by_role("button", name="Wybór", exact=True).click()
    expect(panel).to_be_visible()

    assert sign_in_small == []
    assert page.evaluate(FIELDS) != []
    assert small_fields(page) == []
    assert_fits(page)
    tab.assert_clean()


def test_a_computer_keeps_its_fields_at_the_size_of_its_text(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """In a computer's window a sign-in field's text is the form's, not a phone's."""
    served = team_serve()
    page = team_tab().page

    open_sign_in(page, served.origin)
    sizes = page.get_by_label("Konto").evaluate(
        "(field) => [field.form, field].map((node) => getComputedStyle(node).fontSize)"
    )

    assert sizes[0] == sizes[1] != f"{LEGIBLE_PX}px"
