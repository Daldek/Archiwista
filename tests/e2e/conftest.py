"""Fixtures of the interface tests: real servers and watched Chromium tabs.

``serve(settings)`` starts ``archiwista serve`` over the test directory, the
settings saved first (none: a first run); ``tab`` is a fresh browser
context (its own cookies) with a recording page. Chromium is installed once
with ``.venv/bin/python -m playwright install chromium``.
"""

from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import pytest
from playwright.sync_api import Browser, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from archiwista.config import AppSettings, ConfigStore
from archiwista.sources.registry import load_registry
from tests.fixtures.browser import VIEWPORT, Served, Tab
from tests.fixtures.local_server import local_paths, serving


@pytest.fixture(scope="session")
def chromium() -> Iterator[Browser]:
    """Yield one headless Chromium for the whole run."""
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except PlaywrightError as error:
            pytest.fail(
                "Chromium for Playwright is missing; install it with "
                f"`.venv/bin/python -m playwright install chromium` ({error})"
            )
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


@pytest.fixture
def tab(chromium: Browser) -> Iterator[Tab]:
    """Yield a recording page in a fresh context (Polish locale, Warsaw time)."""
    context = chromium.new_context(
        viewport=VIEWPORT, locale="pl-PL", timezone_id="Europe/Warsaw"
    )
    recorded = Tab(context.new_page())
    recorded.watch()
    yield recorded
    context.close()
