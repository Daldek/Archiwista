"""Shared test fixtures for Archiwista test suites."""

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def restore_umask() -> Iterator[None]:
    """Give every test the umask it started with (``archiwista`` sets 077)."""
    mask = os.umask(0o022)
    os.umask(mask)
    yield
    os.umask(mask)
