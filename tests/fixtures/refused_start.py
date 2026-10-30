"""Children that cannot start, as every limited child on macOS did.

``refuse_starts`` replaces the ``child_limits`` a module starts its children
with: while ``RefusedStarts.on``, each child fails between fork and exec as
``setrlimit(RLIMIT_AS)`` failed on macOS (``EINVAL``), so ``subprocess.Popen``
raises ``SubprocessError``. With ``on`` false the next child starts as usual.
"""

import errno
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest


def _refuse_limit() -> None:
    raise OSError(errno.EINVAL, "Invalid argument")


class RefusedStarts:
    """``child_limits`` whose children fail before they run while ``on``."""

    def __init__(self, limits: Callable[[int | None], dict[str, Any]]) -> None:
        self.on = True
        self._limits = limits

    def __call__(self, memory_bytes: int | None = None) -> dict[str, Any]:
        """Return the ``Popen`` arguments of a child, refused while ``on``."""
        found = self._limits(memory_bytes)
        if self.on:
            found["preexec_fn"] = _refuse_limit
        return found


def refuse_starts(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> RefusedStarts:
    """Refuse the children ``module`` starts until the switch is turned off."""
    refused = RefusedStarts(module.child_limits)
    monkeypatch.setattr(module, "child_limits", refused)
    return refused
