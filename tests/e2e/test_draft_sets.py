"""A set in the making („zestaw w budowie”), in Chromium and Firefox (plan A2).

The stand-in producer serves the store ``pomiary`` online (as in
``test_plan_window.py``) and the local owner has the project ``raba``.
„Nowy zestaw w budowie…” on the project's card makes an empty set: its badge
says „w budowie” and „Zamknij zestaw” is disabled with „Zestaw jest pusty.”.
The plan windows of two rows (2023, one line; 2022, three lines) download
into it through „Zestaw w budowie” and say „Dodano do zestawu w budowie …”;
the card lists the four calls and their pins. „Zamknij zestaw” closes it:
when, by whom and the start of the digest the project file holds. „Przepnij”
of the closed set is disabled with its reason and the API refuses the re-pin
(``409 set_closed``); „Otwórz do edycji” asks its question and opens it again.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from archiwista.projects import PROJECT_FILE
from tests.e2e.test_acceptance_v03 import call, card_group, standin_workers
from tests.e2e.test_plan_window import (
    ROW_STATIONS,
    WAIT_S,
    check_at_source,
    open_area,
    open_plan,
    serve_store,
)
from tests.fixtures.browser import Served, Tab

Serve = Callable[..., Served]

SET = "Wodowskaz 2022–2023"
EMPTY = "Zestaw jest pusty."
CLOSED = "Zestaw jest zamknięty: otwórz go do edycji, aby go przepiąć."
REOPEN_QUESTION = (
    f"Otworzyć zestaw „{SET}” do edycji? Programy, które czytają tylko zamknięte"
    " zestawy (Hydrograf), odmówią go do ponownego zamknięcia."
)
# „zamknięty {data} · {kto}” of a set the local owner closed.
CLOSED_BY_OWNER = re.compile(
    r"zamknięty \d{4}\.\d{2}\.\d{2} \d{2}:\d{2} · właściciel lokalny"
)


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in; the server's workers give it the store's directory."""
    return standin_workers(monkeypatch)


def written_set(directory: Path) -> dict[str, Any]:
    """Return the set ``SET`` as the project file in ``directory`` holds it."""
    data = json.loads((directory / PROJECT_FILE).read_text(encoding="utf-8"))
    found: dict[str, Any] = next(g for g in data["groups"] if g["name"] == SET)
    return found


def pin_into_set(page: Page, row: Locator, positions: str, button: str) -> Locator:
    """Download a row's plan into the open set ``SET``; return its window."""
    dialog = open_plan(page, row, positions)
    dialog.get_by_role("checkbox", name="Dodaj do projektu").check()
    dialog.get_by_role("radio", name="Zestaw w budowie").check()
    expect(dialog.get_by_role("combobox", name="Zestaw w budowie")).to_have_value(SET)
    dialog.get_by_role("button", name=button).click()
    return dialog


def test_a_set_in_the_making_takes_two_plan_windows_is_closed_and_opened_again(
    serve: Serve, engine_tab: Tab, tmp_path: Path, standin: ModuleType
) -> None:
    """Empty draft → two plan windows into it → closed with its digest → opened."""
    # Arrange: the store online, the local owner's project, its card.
    tab = engine_tab
    projects = tmp_path / "projekty"
    projects.mkdir()
    served = serve_store(serve, tmp_path, projects=projects)
    page = tab.page
    page.goto(served.token_url())
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()
    tab.settle()
    created = call(page, "POST", "/projects", {"path": str(projects / "raba")})
    assert created["status"] == 201, created
    project = created["body"]["project"]
    tab.settle()
    page.goto(f"{served.base}/?view=projects&project={project}")
    panel = page.get_by_role("complementary", name="Projekt")

    # Act: an empty set in the making.
    panel.get_by_role("button", name="Nowy zestaw w budowie…").click()
    form = page.get_by_role("dialog", name="Nowy zestaw w budowie")
    form.get_by_label("Nazwa zestawu").fill(SET)
    form.get_by_role("button", name="Utwórz zestaw").click()

    # Assert: „w budowie”; closing it waits for a pin and says why.
    expect(form).to_be_hidden()
    expect(panel.locator(".pc-done")).to_have_text(
        f"Utworzono zestaw w budowie „{SET}”."
    )
    draft = card_group(panel, SET)
    expect(draft.locator(".pc-group-head")).to_contain_text("w budowie")
    close = draft.get_by_role("button", name=f"Zamknij zestaw {SET}")
    expect(close).to_be_disabled()
    expect(close).to_have_accessible_description(EMPTY)
    expect(panel.locator(".pc-why li").filter(has_text=EMPTY)).to_have_count(1)
    assert written_set(projects / "raba")["state"] == "open"

    # Act: the plan windows of 2023 and of 2022 download into it.
    tab.settle()
    rows = check_at_source(open_area(page, served, served.token_url()))
    first = pin_into_set(page, rows.nth(0), "4 pozycje", "Pobierz 2 pozycje i przypnij")
    expect(first).to_contain_text(
        f"Dodano do zestawu w budowie „{SET}”: 2 wersje.", timeout=WAIT_S * 1000
    )
    first.get_by_role("button", name="Zamknij").click()
    expect(first).to_be_hidden()
    second = pin_into_set(
        page, rows.nth(1), "12 pozycji", "Pobierz 6 pozycji i przypnij"
    )

    # Assert: the second window added to the same set.
    expect(second).to_contain_text(
        f"Dodano do zestawu w budowie „{SET}”: 6 wersji.", timeout=WAIT_S * 1000
    )
    second.get_by_role("button", name="Zamknij").click()
    expect(second).to_be_hidden()

    # Act: the project's card.
    tab.settle()
    page.goto(f"{served.base}/?view=projects&project={project}")
    built = card_group(panel, SET)
    built.get_by_role("button", name="i 1 więcej").click()

    # Assert: both windows' four lines and their eight pins, still open.
    commands = built.locator(".pc-cmd")
    expect(commands).to_have_count(4)
    for place, station in enumerate(("150160190", *ROW_STATIONS)):
        expect(commands.nth(place)).to_contain_text(station)
    expect(built.locator(".pc-pin")).to_have_count(8)
    expect(built.locator(".pc-group-head")).to_contain_text("w budowie")
    calls = written_set(projects / "raba")["origin"]["calls"]
    assert [call["options"]["station"] for call in calls] == [
        "150160190",
        *ROW_STATIONS,
    ]

    # Act
    close = built.get_by_role("button", name=f"Zamknij zestaw {SET}")
    expect(close).to_be_enabled()
    close.click()

    # Assert: closed now by the local owner, with the digest the file holds.
    expect(panel.locator(".pc-done")).to_have_text(f"Zamknięto zestaw „{SET}”.")
    head = built.locator(".pc-group-head")
    expect(head).to_contain_text(CLOSED_BY_OWNER)
    written = written_set(projects / "raba")
    assert (written["state"], written["closed_by"]) == ("closed", "local")
    digest = written["pins_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)
    expect(head.locator(".pc-digest")).to_have_text(digest[:12])
    expect(head.locator(".pc-digest")).to_have_attribute("title", digest)
    expect(built.get_by_role("button", name=re.compile("^Odepnij"))).to_have_count(0)

    # Assert: a closed set is not re-pinned; the button says why, the API refuses.
    repin = built.get_by_role("button", name=f"Przepnij zestaw {SET}")
    expect(repin).to_be_disabled()
    expect(repin).to_have_accessible_description(CLOSED)
    refused = call(
        page, "POST", f"/projects/{project}/jobs", {"kind": "repin", "groups": [SET]}
    )
    assert refused["status"] == 409, refused
    assert refused["body"]["details"]["reason"] == "set_closed"

    # Act: opened for editing, after its question.
    built.get_by_role("button", name=f"Otwórz do edycji zestaw {SET}").click()
    question = page.get_by_role("dialog", name="Otwórz do edycji")
    expect(question).to_contain_text(REOPEN_QUESTION)
    question.get_by_role("button", name="Otwórz do edycji").click()

    # Assert: in the making again, its closing gone from the file.
    expect(question).to_be_hidden()
    expect(panel.locator(".pc-done")).to_have_text(f"Otwarto do edycji zestaw „{SET}”.")
    expect(head).to_contain_text("w budowie")
    expect(head.locator(".pc-digest")).to_have_count(0)
    expect(built.get_by_role("button", name=f"Zamknij zestaw {SET}")).to_be_enabled()
    expect(built.get_by_role("button", name=f"Przepnij zestaw {SET}")).to_be_enabled()
    reopened = written_set(projects / "raba")
    assert reopened["state"] == "open"
    assert "pins_sha256" not in reopened
    tab.settle()
    tab.assert_clean()
