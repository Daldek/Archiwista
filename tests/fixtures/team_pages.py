"""Pages of a team server in the interface tests: signing in, the shell, a session.

``open_sign_in``, ``fill_sign_in`` and ``sign_in`` drive the sign-in page,
``signed_in`` signs a person in up to the shell, ``answered`` returns the
status of the API request a press sends, ``read_session`` the page's
session as the API tells it, ``come_back`` asks the server at once as a
person returning to the tab does, and ``shot`` keeps a Chromium screenshot
for a report when ``ARCHIWISTA_SCREENSHOTS`` names a directory.
"""

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Response, expect

SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
LOGIN = "POST /api/v1/session/login"
# The one text of a session that ended under the page (views/login.js).
LOST = "Sesja wygasła albo została zakończona. Zaloguj się ponownie."
_READ_SESSION = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  return (await fetch("/api/v1/session", { headers })).json();
}"""
_COME_BACK = "document.dispatchEvent(new Event('visibilitychange'))"


def shot(page: Page, name: str) -> None:
    """Keep a Chromium screenshot when ``ARCHIWISTA_SCREENSHOTS`` is set."""
    directory = os.environ.get(SCREENSHOTS)
    browser = page.context.browser
    if directory and browser is not None and browser.browser_type.name == "chromium":
        Path(directory).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(directory) / f"{name}.png"))


def open_sign_in(page: Page, origin: str) -> None:
    """Open the team server and wait for its sign-in page."""
    page.goto(f"{origin}/")
    expect(page.get_by_role("heading", name="Logowanie")).to_be_visible()


def fill_sign_in(page: Page, account: str, password: str) -> None:
    """Type an account and a password into the sign-in page."""
    page.get_by_label("Konto").fill(account)
    page.get_by_label("Hasło", exact=True).fill(password)


def answered(page: Page, request: str, press: Callable[[], None]) -> int:
    """Press something that sends ``request`` (``"PUT /path"``); return its status."""
    method, path = request.split(" ")

    def matches(response: Response) -> bool:
        return response.request.method == method and response.url.endswith(path)

    with page.expect_response(matches) as answer:
        press()
    return answer.value.status


def sign_in(page: Page) -> int:
    """Press „Zaloguj”; return the status of the sign-in's answer."""
    button = page.get_by_role("button", name="Zaloguj", exact=True)
    return answered(page, LOGIN, button.click)


def expect_shell(page: Page) -> None:
    """Wait for the shell of a started session."""
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def signed_in(page: Page, origin: str, account: str, password: str) -> None:
    """Sign ``account`` in with ``password`` and wait for the shell."""
    open_sign_in(page, origin)
    fill_sign_in(page, account, password)
    sign_in(page)
    expect_shell(page)


def read_session(page: Page) -> dict[str, Any]:
    """Return the page's session as ``GET /session`` answers it."""
    state: dict[str, Any] = page.evaluate(_READ_SESSION)
    return state


def come_back(page: Page) -> None:
    """Act as a person returning to the tab: the shell asks the server at once."""
    page.evaluate(_COME_BACK)
