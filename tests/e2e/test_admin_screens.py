"""The administrators' „Konta” and „Grupy” on a team server, in Chromium and Firefox.

Plan v0.4, step T6. A real ``archiwista serve`` in team mode over TLS: the
administrator anna creates kasia and gives her a temporary password, which
kasia changes at her first sign-in in a second browser; the role „zapis do
magazynu” counts from kasia's next request, and disabling kasia ends her
session. Anna makes the group hydro with kasia, adds herself and removes it;
kasia's groups follow at her next request. A person without ``admin`` has
neither „Konta”, „Grupy” nor „Dziennik”, and their routes answer ``403``,
while „Zadania” is there for everyone; the last
administrator can neither be disabled nor lose the role, said at the
control. With ``ARCHIWISTA_SCREENSHOTS=<directory>`` Chromium keeps
screenshots there (``docs/reports/v0.4-screenshots/``).
"""

import re
from collections.abc import Callable

from playwright.sync_api import Page, expect

from tests.fixtures.browser import Tab
from tests.fixtures.team_pages import (
    LOST,
    come_back,
    expect_shell,
    fill_sign_in,
    open_sign_in,
    read_session,
    shot,
    sign_in,
    signed_in,
)
from tests.fixtures.team_server import (
    ADMIN_ACCOUNT,
    ADMIN_PASSWORD,
    TeamServed,
    add_person,
)

TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]

KASIA = "kasia"
KASIA_PASSWORD = "wiosla-na-Dunajcu-7"
LAST_ADMIN = (
    "Konto „anna” jest ostatnim administratorem zespołu, który może się zalogować:"
    " najpierw nadaj rolę admin innemu włączonemu kontu, które może się zalogować"
    " (hasłem albo przez serwer pośredniczący)."
)
# The status of an API request (``/api/v1/…``) sent with the page's session.
STATUS = """async (path) => {
  const headers = { "X-Archiwista-CSRF": sessionStorage.getItem("archiwista_csrf") };
  return (await fetch(path, { headers })).status;
}"""


def open_accounts(page: Page) -> None:
    """Open „Konta” from the navigation."""
    page.get_by_role("link", name="Konta").click()
    expect(page.get_by_role("heading", name="Konta")).to_be_visible()


def open_groups(page: Page) -> None:
    """Open „Grupy” from the navigation."""
    page.get_by_role("link", name="Grupy").click()
    expect(page.get_by_role("heading", name="Grupy")).to_be_visible()


def test_an_administrator_creates_an_account_and_manages_it(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """A new account's temporary password, its role and its disabling, seen by kasia."""
    served = team_serve()
    admin = team_tab()
    person = team_tab()
    page = admin.page
    created = page.get_by_role("dialog", name="Nowe konto")
    card = page.get_by_role("dialog", name="Konto · kasia")
    row = page.get_by_role("row").filter(has_text="Kasia Wrona")
    signed_in(page, served.origin, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    open_accounts(page)

    page.get_by_role("button", name="Nowe konto").click()
    created.get_by_label("Konto").fill(KASIA)
    created.get_by_label("Nazwa").fill("Kasia Wrona")
    created.get_by_role("button", name="Utwórz konto").click()
    expect(card.get_by_text("Konto kasia utworzone.")).to_be_visible()
    card.get_by_role("button", name="Ustaw hasło tymczasowe").click()
    secret = card.locator(".admin-secret code")
    expect(secret).to_have_text(re.compile(r"^\S{12,}$"))
    expect(
        card.get_by_role("button", name="Kopiuj: hasło tymczasowe konta kasia")
    ).to_be_visible()
    temporary = secret.inner_text()
    shot(page, "04-konta")
    card.get_by_role("button", name="Zamknij").click()
    expect(row).to_contain_text("tymczasowe · do")
    open_sign_in(person.page, served.origin)
    fill_sign_in(person.page, KASIA, temporary)
    sign_in(person.page)
    person.page.get_by_label("Obecne hasło").fill(temporary)
    person.page.get_by_label("Nowe hasło", exact=True).fill(KASIA_PASSWORD)
    person.page.get_by_label("Powtórz nowe hasło").fill(KASIA_PASSWORD)
    person.page.get_by_role("button", name="Zmień hasło").click()
    expect_shell(person.page)
    before = read_session(person.page)
    page.get_by_role("button", name="Zarządzaj kontem kasia").click()
    card.get_by_label("zapis do magazynu").check()
    card.get_by_role("button", name="Zapisz role").click()
    expect(card.get_by_text("Role zapisane")).to_be_visible()
    after = read_session(person.page)
    card.get_by_role("button", name="Wyłącz").click()
    expect(card.get_by_role("button", name="Włącz")).to_be_visible()
    come_back(person.page)

    assert (before["store_write"], after["store_write"]) == (False, True)
    assert after["roles"] == ["store_writer"]
    expect(person.page.get_by_text(LOST)).to_be_visible()
    expect(row).to_contain_text("wyłączone")
    expect(person.page.get_by_role("link", name="Konta")).to_have_count(0)
    admin.assert_clean()
    person.assert_clean()


def test_an_administrator_makes_a_group_and_changes_its_members(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """Hydro with kasia, then anna too, then removed; kasia's groups follow."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD, name="Kasia Wrona")
    admin = team_tab()
    person = team_tab()
    page = admin.page
    created = page.get_by_role("dialog", name="Nowa grupa")
    members = page.get_by_role("dialog", name="Członkowie · hydro")
    removal = page.get_by_role("dialog", name="Usunąć grupę hydro?")
    row = page.get_by_role("row").filter(has_text="Dział hydrologii")
    signed_in(person.page, served.origin, KASIA, KASIA_PASSWORD)
    signed_in(page, served.origin, ADMIN_ACCOUNT, ADMIN_PASSWORD)
    open_groups(page)

    page.get_by_role("button", name="Nowa grupa").click()
    created.get_by_label("Grupa", exact=True).fill("hydro")
    created.get_by_label("Nazwa").fill("Dział hydrologii")
    created.get_by_label("Kasia Wrona (kasia)").check()
    created.get_by_role("button", name="Utwórz grupę").click()
    expect(row).to_contain_text("1: Kasia Wrona")
    joined = read_session(person.page)
    page.get_by_role("button", name="Członkowie grupy hydro").click()
    members.get_by_label(ADMIN_ACCOUNT, exact=True).check()
    shot(page, "05-grupy")
    members.get_by_role("button", name="Zapisz").click()
    expect(row).to_contain_text(f"2: {ADMIN_ACCOUNT}, Kasia Wrona")
    page.get_by_role("button", name="Usuń grupę hydro").click()
    removal.get_by_role("button", name="Usuń grupę").click()
    expect(row).to_have_count(0)
    left = read_session(person.page)

    assert joined["groups"] == ["hydro"]
    assert left["groups"] == []
    expect(page.get_by_text("Nie ma jeszcze żadnej grupy.")).to_be_visible()
    admin.assert_clean()
    person.assert_clean()


def test_without_admin_no_admin_views_and_the_last_administrator_stays(
    team_serve: TeamServe, team_tab: TeamTab
) -> None:
    """No „Konta”, „Grupy”, „Dziennik” nor their routes without admin; last stays."""
    served = team_serve()
    add_person(served.paths, KASIA, KASIA_PASSWORD)
    admin = team_tab()
    person = team_tab()
    page = admin.page
    card = page.get_by_role("dialog", name="Konto · anna")
    signed_in(person.page, served.origin, KASIA, KASIA_PASSWORD)
    signed_in(page, served.origin, ADMIN_ACCOUNT, ADMIN_PASSWORD)

    names = ("Konta", "Grupy", "Dziennik")
    links = [person.page.get_by_role("link", name=name) for name in names]
    expect(person.page.get_by_role("link", name="Ustawienia")).to_be_visible()
    expect(person.page.get_by_role("link", name="Zadania")).to_be_visible()
    for name in ("Zadania", *names):
        expect(page.get_by_role("link", name=name)).to_be_visible()
    statuses = [
        person.page.evaluate(STATUS, f"/api/v1/{path}")
        for path in ("users", "groups", "log")
    ]
    person.page.goto(f"{served.origin}/?view=accounts")
    expect(
        person.page.get_by_text("Zarządzanie kontami wymaga roli administratora.")
    ).to_be_visible()
    open_accounts(page)
    page.get_by_role("button", name="Zarządzaj kontem anna").click()
    card.get_by_role("button", name="Wyłącz").click()
    expect(card.get_by_text(LAST_ADMIN)).to_be_visible()
    card.get_by_label("administrator").uncheck()
    card.get_by_role("button", name="Zapisz role").click()

    assert statuses == [403, 403, 403]
    for link in links:
        expect(link).to_have_count(0)
    expect(card.get_by_text(LAST_ADMIN)).to_have_count(2)
    expect(card.get_by_role("button", name="Wyłącz")).to_be_visible()
    admin.assert_clean()
    person.assert_clean()
