"""Fixtures of the interface tests: real servers and watched browser tabs.

``serve(settings)`` starts ``archiwista serve`` over the test directory, the
settings saved first (none: a first run); ``tab`` is a fresh Chromium context
(its own cookies) with a recording page, and ``engine_tab`` the same in
Chromium and then in Firefox, for what depends on the browser engine.
``team_serve(**team)`` starts a team server over TLS, and ``team_tab()``
opens one person's browser of it, in each engine. The browsers are
installed once with ``.venv/bin/python -m playwright install chromium
firefox``.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Playwright, expect, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from archiwista.auth import passwords
from archiwista.config import AppSettings, ConfigStore
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import EXPECT_TIMEOUT_MS, VIEWPORT, Served, Tab
from tests.fixtures.local_server import local_paths, serving
from tests.fixtures.team_server import (
    TeamServed,
    cheap_hasher,
    team_serving,
    team_site,
)

ENGINES = ("chromium", "firefox")


@pytest.fixture(scope="package")
def playwright() -> Iterator[Playwright]:
    """Yield Playwright for the interface tests.

    Playwright's sync API keeps its event loop running in the main thread,
    so it stops with the last test of this package: later tests of the run
    call ``asyncio.run`` (the CLI's commands) in that thread.

    Expectations (``expect``) wait up to ``EXPECT_TIMEOUT_MS``.
    """
    with sync_playwright() as running:
        expect.set_options(timeout=EXPECT_TIMEOUT_MS)
        yield running
        expect.set_options(timeout=None)


def launch(playwright: Playwright, engine: str) -> Browser:
    """Start a headless browser of ``engine``; fail saying how to install it."""
    try:
        browser: Browser = getattr(playwright, engine).launch()
    except PlaywrightError as error:
        pytest.fail(
            f"{engine} for Playwright is missing; install it with "
            f"`.venv/bin/python -m playwright install {engine}` ({error})"
        )
    return browser


@pytest.fixture(scope="package")
def chromium(playwright: Playwright) -> Iterator[Browser]:
    """Yield one headless Chromium for the interface tests."""
    browser = launch(playwright, "chromium")
    yield browser
    browser.close()


@pytest.fixture(scope="package")
def firefox(playwright: Playwright) -> Iterator[Browser]:
    """Yield one headless Firefox for the tests that run in both engines."""
    browser = launch(playwright, "firefox")
    yield browser
    browser.close()


@pytest.fixture
def serve(tmp_path: Path) -> Iterator[Callable[..., Served]]:
    """Start a server over ``tmp_path``: ``serve(settings=None)``."""
    with ExitStack() as stack:

        def start(settings: AppSettings | None = None) -> Served:
            paths = local_paths(tmp_path)
            if settings is not None:
                ConfigStore(paths.config_file).save(settings)
            registry = load_registry(cache_dir=paths.cache_dir)
            server, _ = stack.enter_context(serving(paths, registry=registry))
            return Served(server, paths)

        yield start


def recording_tab(browser: Browser) -> Iterator[Tab]:
    """Yield a recording page in a fresh context (Polish locale, Warsaw time)."""
    context = browser.new_context(
        viewport=VIEWPORT, locale="pl-PL", timezone_id="Europe/Warsaw"
    )
    recorded = Tab(context.new_page())
    recorded.watch()
    yield recorded
    context.close()


@pytest.fixture
def tab(chromium: Browser) -> Iterator[Tab]:
    """Yield a recording Chromium page in a fresh context."""
    yield from recording_tab(chromium)


@pytest.fixture(params=ENGINES)
def engine_tab(request: pytest.FixtureRequest) -> Iterator[Tab]:
    """Yield a recording page in a fresh context, in each engine of ``ENGINES``."""
    browser: Browser = request.getfixturevalue(request.param)
    yield from recording_tab(browser)


@pytest.fixture
def team_serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., TeamServed]]:
    """Start a team server over TLS over ``tmp_path``: ``team_serve(**team)``.

    ``team`` adds values of the table ``[team]``. The administrator
    ``ADMIN_ACCOUNT`` exists; passwords are hashed at the lowest cost.
    """
    monkeypatch.setattr(passwords, "HASHER", cheap_hasher())
    with ExitStack() as stack:

        def start(**team: object) -> TeamServed:
            paths = local_paths(tmp_path)
            site = team_site(tmp_path / "tls")
            served = team_serving(paths, site, admin=True, **team)
            server, _ = stack.enter_context(served)
            return TeamServed(server, paths, site.origin)

        yield start


@pytest.fixture(params=ENGINES)
def team_tab(request: pytest.FixtureRequest) -> Iterator[Callable[..., Tab]]:
    """Yield ``team_tab(headers=None)``: a person's recording page of a team server.

    Each call opens a fresh context (its own cookies) of one engine of
    ``ENGINES`` that accepts the server's test certificate; ``headers`` go
    with every request (a reverse proxy's header naming the person).
    """
    browser: Browser = request.getfixturevalue(request.param)
    with ExitStack() as contexts:

        def new(headers: dict[str, str] | None = None) -> Tab:
            context = browser.new_context(
                viewport=VIEWPORT,
                locale="pl-PL",
                timezone_id="Europe/Warsaw",
                ignore_https_errors=True,
                extra_http_headers=headers,
            )
            contexts.callback(context.close)
            recorded = Tab(context.new_page())
            recorded.watch()
            return recorded

        yield new
