"""A producer's package that looks not installed to the plugin registry.

The registry judges a source by ``importlib.metadata.version`` of the producer's
package before it imports anything (``check_package``), so hiding the
distribution from that call makes the source ``not_installed`` while the
package stays importable. ``hide_packages`` does it in the test process and,
through ``MISSING_PACKAGES_ENV``, in the job workers of the job tests
(``tests.fixtures.job_worker``).
"""

import importlib.metadata
from collections.abc import Callable, Collection

import pytest

MISSING_PACKAGES_ENV = "ARCHIWISTA_TEST_MISSING_PACKAGES"


def hiding(names: Collection[str]) -> Callable[[str], str]:
    """Return ``importlib.metadata.version`` that does not know ``names``."""
    installed = importlib.metadata.version

    def version(name: str) -> str:
        if name in names:
            raise importlib.metadata.PackageNotFoundError(name)
        return installed(name)

    return version


def hide_packages(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    """Make the named distributions look not installed for the rest of the test.

    The job workers the test starts inherit the environment variable and hide
    them too; anything that loads the plugin registry afterwards sees the
    sources of these packages as ``not_installed``.
    """
    monkeypatch.setattr(importlib.metadata, "version", hiding(names))
    monkeypatch.setenv(MISSING_PACKAGES_ENV, ",".join(names))
