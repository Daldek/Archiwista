"""Signing in to a team server, in Chromium and Firefox (plan v0.4, step T5).

A real ``archiwista serve`` in team mode over TLS (a test certificate
authority): the sign-in page with one message for every refused account, the
wait after five failures counted down, a temporary password changed before
the shell opens, a session ended elsewhere leading back to the sign-in, and
the company's sign-in through a trusted reverse proxy. With
``ARCHIWISTA_SCREENSHOTS=<directory>`` Chromium keeps screenshots there
(``docs/reports/v0.4-screenshots/``).
"""

import os
import re
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page, expect

from archiwista.auth import LOCAL_OWNER
from archiwista.auth.throttle import FREE_FAILURES
from archiwista.state import StateStore
from tests.fixtures.browser import Tab
from tests.fixtures.team_server import TeamServed, add_person

TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]

KASIA = "kasia"
KASIA_PASSWORD = "wiosla-na-Dunajcu-7"
WRONG_PASSWORD = "zle-haslo-kasi-123"
NEW_PASSWORD = "szum-Sanu-pod-Lesko"
PROXY_HEADER = "X-Remote-User"
SCREENSHOTS = "ARCHIWISTA_SCREENSHOTS"
LOGIN = "/api/v1/session/login"
PASSWORD = "/api/v1/session/password"
REFUSED = "Nieprawidłowe konto albo hasło."
WAITING = re.compile(r"^Zbyt wiele nieudanych prób: spróbuj ponownie za \d+ s\.$")
# The session of the page as the API tells it, read with the tab's CSRF token.
READ_SESSION = """async () => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  return (await fetch("/api/v1/session", { headers })).json();
}"""
# A person coming back to the tab: the shell asks the server at once.
COME_BACK = "document.dispatchEvent(new Event('visibilitychange'))"


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


def answered(page: Page, path: str, press: Callable[[], None]) -> int:
    """Press something that calls ``path`` of the API; return the answer's status."""
    with page.expect_response(lambda response: response.url.endswith(path)) as answer:
        press()
    return answer.value.status


def sign_in(page: Page) -> int:
    """Press „Zaloguj”; return the status of the sign-in's answer."""
    button = page.get_by_role("button", name="Zaloguj", exact=True)
    return answered(page, LOGIN, button.click)


def expect_shell(page: Page) -> None:
    """Wait for the shell of a started session."""
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def test_a_person_signs_in_and_every_refusal_has_one_message(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """A wrong password and an unknown account say the same; then kasia signs in."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD, name="Kasia Wrona")
    tab = team_tab()
    page = tab.page
    password = page.get_by_label("Hasło", exact=True)

    open_sign_in(page, served.origin)
    fill_sign_in(page, KASIA, WRONG_PASSWORD)
    page.get_by_role("button", name="Pokaż").click()
    expect(password).to_have_attribute("type", "text")
    page.get_by_role("button", name="Pokaż").click()
    expect(password).to_have_attribute("type", "password")
    wrong = sign_in(page)
    expect(page.get_by_role("alert")).to_have_text(REFUSED)
    fill_sign_in(page, "nikt", WRONG_PASSWORD)
    unknown = sign_in(page)
    expect(page.get_by_role("alert")).to_have_text(REFUSED)
    shot(page, "01-logowanie")
    fill_sign_in(page, " Kasia ", KASIA_PASSWORD)
    signed_in = sign_in(page)
    expect_shell(page)
    cookies = {cookie["name"]: cookie for cookie in page.context.cookies()}
    state = page.evaluate(READ_SESSION)

    assert (wrong, unknown, signed_in) == (401, 401, 200)
    expect(page.get_by_role("heading", name="Logowanie")).to_have_count(0)
    assert (state["actor"], state["method"]) == (KASIA, "password")
    cookie = cookies["__Host-archiwista_session"]
    assert (cookie["secure"], cookie["httpOnly"], cookie["sameSite"]) == (
        True,
        True,
        "Strict",
    )
    tab.assert_clean()


def test_five_failures_make_the_sign_in_wait_counted_down(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """After five failures the page counts the server's wait down, then signs in."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD)
    tab = team_tab()
    page = tab.page
    button = page.get_by_role("button", name="Zaloguj", exact=True)
    open_sign_in(page, served.origin)
    fill_sign_in(page, KASIA, WRONG_PASSWORD)

    statuses = [sign_in(page) for _ in range(FREE_FAILURES)]
    # The fifth failure makes the server wait a second and each further one
    # doubles the wait: the attempts go on until one comes within it.
    while statuses[-1] != 429 and len(statuses) < FREE_FAILURES + 4:
        statuses.append(sign_in(page))
    expect(page.get_by_role("alert")).to_have_text(WAITING)
    expect(button).to_be_disabled()
    expect(page.get_by_role("alert")).to_have_count(0)
    page.get_by_label("Hasło", exact=True).fill(KASIA_PASSWORD)
    signed_in = sign_in(page)
    expect_shell(page)

    assert statuses[:FREE_FAILURES] == [401] * FREE_FAILURES
    assert statuses[-1] == 429
    assert signed_in == 200
    tab.assert_clean()


def test_a_temporary_password_is_changed_before_the_shell_opens(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """The change form comes first; its refusals show at their fields."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD, temporary=True)
    tab = team_tab()
    page = tab.page
    current = page.get_by_label("Obecne hasło")
    new = page.get_by_label("Nowe hasło", exact=True)
    repeat = page.get_by_label("Powtórz nowe hasło")
    change = page.get_by_role("button", name="Zmień hasło")
    open_sign_in(page, served.origin)
    fill_sign_in(page, KASIA, KASIA_PASSWORD)

    signed_in = sign_in(page)
    expect(
        page.get_by_role("heading", name="Zmień hasło tymczasowe · kasia")
    ).to_be_visible()
    expect(page.get_by_role("navigation", name="Widoki")).to_have_count(0)
    current.fill(KASIA_PASSWORD)
    new.fill(NEW_PASSWORD)
    repeat.fill(f"{NEW_PASSWORD}!")
    expect(page.get_by_text("Powtórzone hasło różni się od nowego.")).to_be_visible()
    expect(change).to_be_disabled()
    new.fill("za-krotkie")
    repeat.fill("za-krotkie")
    short = answered(page, PASSWORD, change.click)
    expect(page.get_by_text("Hasło musi mieć co najmniej 12 znaków.")).to_be_visible()
    expect(new).to_have_attribute("aria-invalid", "true")
    shot(page, "02-zmiana-hasla")
    current.fill(WRONG_PASSWORD)
    new.fill(NEW_PASSWORD)
    repeat.fill(NEW_PASSWORD)
    wrong = answered(page, PASSWORD, change.click)
    expect(page.get_by_text("Obecne hasło jest nieprawidłowe.")).to_be_visible()
    expect(current).to_have_attribute("aria-invalid", "true")
    current.fill(KASIA_PASSWORD)
    changed = answered(page, PASSWORD, change.click)
    expect_shell(page)
    state = page.evaluate(READ_SESSION)

    assert (signed_in, short, wrong, changed) == (200, 400, 403, 200)
    assert state["password_change_required"] is False
    expect(current).to_have_count(0)
    tab.assert_clean()


def test_a_session_ended_elsewhere_leads_back_to_the_sign_in(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """Sessions ended at the terminal: the next request shows the sign-in."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD)
    tab = team_tab()
    page = tab.page
    open_sign_in(page, served.origin)
    fill_sign_in(page, KASIA, KASIA_PASSWORD)
    sign_in(page)
    expect_shell(page)

    StateStore(served.paths.state_file).revoke_sessions(KASIA, actor=LOCAL_OWNER)
    page.evaluate(COME_BACK)
    expect(page.get_by_role("heading", name="Logowanie")).to_be_visible()
    expect(
        page.get_by_text("Sesja wygasła albo została zakończona. Zaloguj się ponownie.")
    ).to_be_visible()
    fill_sign_in(page, KASIA, KASIA_PASSWORD)
    again = sign_in(page)
    expect_shell(page)

    assert again == 200
    assert page.evaluate("() => sessionStorage.getItem('archiwista_csrf')")
    tab.assert_clean()


def test_the_company_sign_in_through_a_trusted_proxy(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """With the proxy's header the page offers the company's sign-in; without, not."""
    served = team_serve(trusted_proxies=["127.0.0.1"], proxy_user_header=PROXY_HEADER)
    add_person(served.paths, KASIA, KASIA_PASSWORD)
    plain = team_tab()
    proxied = team_tab({PROXY_HEADER: "Kasia"})
    company = "Zaloguj kontem firmowym"
    open_sign_in(plain.page, served.origin)
    open_sign_in(proxied.page, served.origin)

    expect(plain.page.get_by_role("button", name=company)).to_have_count(0)
    proxied.page.get_by_role("button", name=company).click()
    expect_shell(proxied.page)
    state = proxied.page.evaluate(READ_SESSION)

    assert (state["actor"], state["method"]) == (KASIA, "proxy")
    plain.assert_clean()
    proxied.assert_clean()
