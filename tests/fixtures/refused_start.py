"""Children that cannot start, as every limited child on macOS did.

``refuse_starts`` replaces the ``child_limits`` a module starts its children
with: while ``RefusedStarts.on``, each child is pointed at a program that does
not exist, so its ``exec`` fails and ``subprocess.Popen`` raises ``OSError``
in the parent. No Python code runs in the forked child: a ``preexec_fn`` that
raises (the macOS failure itself) makes the child unwind Python and, on macOS,
crash in PROJ's destructor. With ``on`` false the next child starts as usual.
"""

from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

# A program no test machine has; its ``exec`` fails with ``ENOENT``.
MISSING_PROGRAM = "/nonexistent/archiwista-refused-start"


class RefusedStarts:
    """``child_limits`` whose children fail before they run while ``on``."""

    def __init__(self, limits: Callable[[int | None], dict[str, Any]]) -> None:
        self.on = True
        self._limits = limits

    def __call__(self, memory_bytes: int | None = None) -> dict[str, Any]:
        """Return the ``Popen`` arguments of a child, refused while ``on``."""
        found = self._limits(memory_bytes)
        if self.on:
            found["executable"] = MISSING_PROGRAM
        return found


def refuse_starts(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> RefusedStarts:
    """Refuse the children ``module`` starts until the switch is turned off."""
    refused = RefusedStarts(module.child_limits)
    monkeypatch.setattr(module, "child_limits", refused)
    return refused
