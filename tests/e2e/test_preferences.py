"""Each person's preferences in the interface, in Chromium and Firefox.

Plan v0.4, step T11. A real ``archiwista serve`` in team mode over TLS with an
IMGWTools fixture store: two people keep different path aliases in „Moje
ścieżki…” of the account menu, and „Kopiuj ścieżkę pliku” of one station's
series file gives each the path as their own computer has it, the server's
path still offered beside it. The basemap chosen on the map and the year
type chosen on the station card follow a person into a second browser
context, and not into a colleague's. Playwright cannot let Firefox read the
clipboard, so in both engines the page's writes to it are recorded instead.
With ``ARCHIWISTA_SCREENSHOTS=<directory>`` Chromium keeps „Moje ścieżki” as
``09-moje-sciezki.png`` (``docs/reports/v0.4-screenshots/``).
"""

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import Locator, Page, expect

from archiwista.config import AppSettings, BasemapConfig
from tests.fixtures.browser import Tab
from tests.fixtures.station_browser import (
    STORE,
    api,
    query_of,
    station_settings,
    wait_indexed,
)
from tests.fixtures.team_pages import answered, shot, signed_in
from tests.fixtures.team_server import TeamServed, add_person
from tests.fixtures.tile_server import tile_server

TeamServe = Callable[..., TeamServed]
TeamTab = Callable[..., Tab]
Stores = Callable[[str], Path]

MAREK = "marek"
KASIA = "kasia"
PEOPLE = {
    MAREK: ("Marek Lis", "wiosla-na-Dunajcu-7"),
    KASIA: ("Kasia Wrona", "szum-Sanu-pod-Lesko"),
}
DAILY = "pl.imgw.hydro_daily"
PROVIDER = "IMGW-PIB"
RABA = "149190310"  # Raba Górna: located, with a daily series file
SAVE = "PUT /api/v1/preferences"
MENU = "#account-panel"
FIRST_BASEMAP = "Kafle testowe"
SECOND_BASEMAP = "Kafle drugie"
# Keeps what the page copies: Firefox's clipboard cannot be read in a test.
RECORD_COPIES = """
window.__copies = [];
navigator.clipboard.writeText = (text) => {
  window.__copies.push(text);
  return Promise.resolve();
};
"""


def serve_people(team_serve: TeamServe, base: AppSettings) -> TeamServed:
    """Start a team server with the settings ``base``; add marek and kasia."""
    served = team_serve(base)
    for account, (name, password) in PEOPLE.items():
        add_person(served.paths, account, password, name=name)
    return served


def person(team_tab: TeamTab, served: TeamServed, account: str) -> Tab:
    """Sign a person in, in a context of their own; wait for the store's index."""
    tab = team_tab()
    tab.page.add_init_script(RECORD_COPIES)
    signed_in(tab.page, served.origin, account, PEOPLE[account][1])
    wait_indexed(tab.page)
    return tab


def card_address(served: TeamServed) -> str:
    """Return the address of Raba Górna's card, its „Pochodzenie”, over the map."""
    station = f"{STORE}/{PROVIDER}/{RABA}"
    query = urlencode({"view": "map", "station": station, "station_tab": "origin"})
    return f"{served.origin}/?{query}"


def card_of(page: Page) -> Locator:
    """Return the station card of Raba Górna."""
    return page.get_by_role("dialog", name="Raba Górna")


def pressed_year_type(page: Page) -> Locator:
    """Return the pressed button of the card's switch „Lata”."""
    switch = card_of(page).get_by_role("group", name="Lata", exact=True)
    return switch.locator("button[aria-pressed='true']")


def keep_paths(page: Page, aliases: list[tuple[str, str]], screenshot: str = "") -> int:
    """Save path aliases in „Moje ścieżki…”; return the status of the save.

    ``screenshot`` names the picture of the saved window (Chromium, when
    ``ARCHIWISTA_SCREENSHOTS`` asks for one).
    """
    page.get_by_role("button", name=re.compile(r"^Konto: ")).click()
    page.locator(MENU).get_by_role("button", name="Moje ścieżki…").click()
    window = page.get_by_role("dialog", name="Moje ścieżki")
    expect(window.get_by_text("Brak ścieżek")).to_be_visible()
    for number, (server, personal) in enumerate(aliases, start=1):
        window.get_by_role("button", name="Dodaj").click()
        field = window.get_by_label(f"Na serwerze, ścieżka {number}", exact=True)
        expect(field).to_be_focused()
        field.fill(server)
        window.get_by_label(f"U mnie, ścieżka {number}", exact=True).fill(personal)
    status = answered(page, SAVE, window.get_by_role("button", name="Zapisz").click)
    expect(window.get_by_role("status")).to_have_text("Zapisano.")
    if screenshot:
        shot(page, screenshot)
    window.get_by_role("button", name="Zamknij").click()
    expect(window).to_have_count(0)
    return status


def copy_file_path(page: Page, served: TeamServed) -> str:
    """Press „Kopiuj ścieżkę pliku” on Raba Górna's card; return what it copied."""
    page.goto(card_address(served))
    button = page.get_by_role("button", name="Kopiuj ścieżkę pliku", exact=True)
    action = card_of(page).locator(".copy-action").filter(has=button)
    action.get_by_role("button").click()
    expect(action.get_by_role("status")).to_have_text("Skopiowano")
    copies: list[str] = page.evaluate("window.__copies")
    return copies[-1]


def card_paths(page: Page) -> dict[str, Any]:
    """Return the copy path of Raba Górna's daily series file, as the API gives it."""
    query = urlencode({"store": STORE, "provider": PROVIDER})
    paths: dict[str, Any] = api(page, f"/stations/{RABA}?{query}")["paths"][DAILY]
    return paths


def test_two_people_copy_one_file_as_their_own_computers_have_it(
    team_serve: TeamServe, team_tab: TeamTab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Marek's and Kasia's aliases give each their own path; the server's stays."""
    # Arrange
    served = serve_people(
        team_serve, station_settings(imgw_store("complete"), tmp_path)
    )
    root = tmp_path / "imgw"
    marek = person(team_tab, served, MAREK)
    kasia = person(team_tab, served, KASIA)
    server_path = card_paths(marek.page)["local"]
    parts = PurePosixPath(server_path).relative_to(root).parts

    # Act
    saved = (
        keep_paths(marek.page, [(f"{root}/", "Y:\\")], screenshot="09-moje-sciezki"),
        keep_paths(kasia.page, [(str(tmp_path), "/home/kasia/nas")]),
    )
    marek_copied = copy_file_path(marek.page, served)
    origin = card_of(marek.page).locator(".sc-file")
    expect(origin.locator("code.path").first).to_have_text(marek_copied)
    expect(
        origin.get_by_role("button", name=f"Kopiuj: {server_path}", exact=True)
    ).to_be_visible()
    kasia_copied = copy_file_path(kasia.page, served)

    # Assert
    assert saved == (200, 200)
    assert marek_copied == "Y:\\" + "\\".join(parts)
    assert kasia_copied == "/home/kasia/nas/imgw/" + "/".join(parts)
    assert card_paths(marek.page)["personal"] == marek_copied
    assert card_paths(kasia.page)["personal"] == kasia_copied
    marek.assert_clean()
    kasia.assert_clean()


def test_the_basemap_and_the_year_type_follow_a_person_not_a_colleague(
    team_serve: TeamServe, team_tab: TeamTab, imgw_store: Stores, tmp_path: Path
) -> None:
    """Marek's choices come back in his second context; Kasia keeps the defaults."""
    with tile_server() as tiles:
        # Arrange
        basemaps = (
            BasemapConfig(name=FIRST_BASEMAP, url=tiles.template, attribution="© A"),
            BasemapConfig(
                name=SECOND_BASEMAP,
                url=f"{tiles.origin}/planet/{{z}}/{{x}}/{{y}}.png",
                attribution="© B",
            ),
        )
        settings = station_settings(imgw_store("complete"), tmp_path)
        served = serve_people(
            team_serve,
            settings.model_copy(update={"offline": False, "basemaps": basemaps}),
        )
        first = person(team_tab, served, MAREK)
        page = first.page
        page.goto(f"{served.origin}/?view=map")
        basemap = page.get_by_label("Podkład")
        expect(basemap).to_have_value(FIRST_BASEMAP)

        def choose_second() -> None:
            basemap.select_option(SECOND_BASEMAP)

        # Act
        chosen = answered(page, SAVE, choose_second)
        page.goto(card_address(served))
        calendar = card_of(page).get_by_role("button", name="kalendarzowe", exact=True)
        switched = answered(page, SAVE, calendar.click)
        second = person(team_tab, served, MAREK)
        kasia = person(team_tab, served, KASIA)
        for tab in (second, kasia):
            tab.page.goto(f"{served.origin}/?view=map")
        expect(second.page.get_by_label("Podkład")).to_have_value(SECOND_BASEMAP)
        expect(kasia.page.get_by_label("Podkład")).to_have_value(FIRST_BASEMAP)
        for tab in (second, kasia):
            tab.page.goto(card_address(served))

        # Assert
        assert (chosen, switched) == (200, 200)
        expect(pressed_year_type(second.page)).to_have_text("kalendarzowe")
        expect(pressed_year_type(kasia.page)).to_have_text("hydrologiczne")
        assert "year_type" not in query_of(second.page)
        first.assert_clean()
        second.assert_clean()
        kasia.assert_clean()
