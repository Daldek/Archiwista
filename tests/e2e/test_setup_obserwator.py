"""The Obserwator directory in the first-run wizard and the settings (plan I2).

SPEC 5.8: the field "Katalog Obserwatora" is offered while the source
``obserwator`` is available or the store already has an Obserwator directory;
without the package a first run shows no such field, and a directory saved earlier
stays in the settings.
"""

import re
from collections.abc import Callable
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from archiwista.config import AppSettings, StoreConfig
from tests.fixtures.browser import Served, Tab
from tests.fixtures.make_store import make_store
from tests.fixtures.missing_package import hide_packages

Serve = Callable[..., Served]


def open_shell(page: Page, url: str) -> None:
    """Open an address and wait for the shell of a started session."""
    page.goto(url)
    expect(page.get_by_role("navigation", name="Widoki")).to_be_visible()


def to_save_step(page: Page) -> None:
    """Walk from the stores step to the last one, which saves."""
    for _ in range(3):
        page.get_by_role("button", name="Dalej").click()


def test_wizard_saves_a_store_of_only_an_obserwator_directory(
    serve: Serve, tab: Tab, obserwator_store: Callable[[str], Path]
) -> None:
    """One of the two directories is enough, and the scheduler indexes the store."""
    # Arrange
    pytest.importorskip("obserwator")
    root = obserwator_store("complete")
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    expect(page.get_by_role("heading", name="Pierwsze uruchomienie")).to_be_visible()
    obserwator = page.get_by_label("Katalog Obserwatora")
    expect(obserwator).to_be_visible()
    page.get_by_label("Nazwa", exact=True).fill("Dane IMGW")

    # Act
    page.get_by_role("button", name="Dalej").click()
    refused = page.get_by_text(
        "Wpisz pełną ścieżkę katalogu Kartografa albo katalogu Obserwatora."
    )
    expect(refused).to_be_visible()
    obserwator.fill(str(root))
    to_save_step(page)
    summary = page.locator(".summary-store")
    expect(summary).to_contain_text("Obserwator:")
    expect(summary).to_contain_text(str(root))
    expect(summary).not_to_contain_text("Kartograf:")
    page.get_by_role("button", name="Zapisz i zindeksuj").click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()
    expect(page.get_by_text("Magazyn „Dane IMGW” zindeksowany")).to_be_visible(
        timeout=60_000
    )

    # Assert
    (store,) = served.settings().stores
    assert (store.kartograf, store.obserwator) == (None, root)
    tab.assert_clean()


def test_wizard_offers_no_obserwator_field_without_the_source(
    serve: Serve, tab: Tab, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A first run without Obserwator asks for Kartograf's directory only."""
    # Arrange
    hide_packages(monkeypatch, "obserwator")
    served = serve()
    page = tab.page
    open_shell(page, served.token_url())
    expect(page.get_by_role("heading", name="Pierwsze uruchomienie")).to_be_visible()

    # Act
    page.get_by_label("Nazwa", exact=True).fill("Zespół")
    page.get_by_role("button", name="Dalej").click()

    # Assert
    expect(page.get_by_label("Katalog Kartografa")).to_have_attribute(
        "aria-invalid", "true"
    )
    expect(page.get_by_text("Wpisz pełną ścieżkę katalogu Kartografa.")).to_be_visible()
    expect(page.get_by_label("Katalog Obserwatora")).to_have_count(0)
    expect(page.locator(".source.bad")).to_contain_text("obserwator")
    tab.assert_clean()


def test_wizard_keeps_a_saved_obserwator_directory_while_its_source_is_missing(
    serve: Serve, tab: Tab, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The saved directory is shown, and saving the form does not drop it."""
    # Arrange
    store = make_store(tmp_path / "store", slots=24, seed=7)
    obserwator = tmp_path / "obserwator"
    obserwator.mkdir()
    saved = AppSettings(
        offline=True,
        stores=(
            StoreConfig(
                id="zespol",
                name="Zespół",
                kartograf=store.root,
                obserwator=obserwator,
                kind="local",
            ),
        ),
    )
    hide_packages(monkeypatch, "obserwator")
    served = serve(saved)
    page = tab.page
    open_shell(page, served.token_url())
    page.goto(f"{served.base}/?view=setup")
    expect(page.get_by_role("heading", name="Ustawienia")).to_be_visible()

    # Act
    field = page.get_by_label("Katalog Obserwatora")
    expect(field).to_have_value(str(obserwator))
    expect(page.locator(".source.bad")).to_contain_text("obserwator")
    to_save_step(page)
    page.get_by_role("button", name=re.compile("Zapisz ustawienia")).click()
    expect(page.get_by_text("Zapisano ustawienia.")).to_be_visible()

    # Assert
    assert served.settings() == saved
    tab.assert_clean()
