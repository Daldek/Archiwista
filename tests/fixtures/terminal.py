"""A pseudo-terminal as a child's standard output, as a person's shell gives it.

``archiwista serve`` prints its one-time address only on a terminal
(``isatty``): a test that runs the real program as a person starts it gives it
``Terminal.child`` as standard output and reads what it printed with
``Terminal.wait_for``. Leaving the ``with`` block closes both ends.
"""

import os
import pty
import re
import select
import subprocess
import time
from pathlib import Path
from types import TracebackType
from typing import Any, Self


class Terminal:
    """A pseudo-terminal: ``child`` for the process, the other end for the test.

    Parameters
    ----------
    copy : Path
        File that gets everything the child printed, for a failure to show.
    """

    def __init__(self, copy: Path) -> None:
        self._reader, self.child = pty.openpty()
        self._copy = copy
        self._printed = ""
        self._open = [self._reader, self.child]

    def __enter__(self) -> Self:
        """Return the terminal for a ``with`` block."""
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close both ends that are still open."""
        for descriptor in self._open:
            os.close(descriptor)
        self._open.clear()

    def started(self) -> None:
        """Close this process's copy of the child's end once the child has it."""
        os.close(self.child)
        self._open.remove(self.child)

    def wait_for(
        self,
        pattern: re.Pattern[str],
        process: "subprocess.Popen[Any]",
        timeout_s: float,
        errors: Path,
    ) -> re.Match[str]:
        """Read what ``process`` prints until ``pattern`` appears in it.

        Fails with the text of ``errors`` (its standard error) when the
        process ends first or ``timeout_s`` passes.
        """
        deadline = time.monotonic() + timeout_s
        while (found := pattern.search(self._printed)) is None:
            assert process.poll() is None, errors.read_text("utf-8")
            assert time.monotonic() < deadline, errors.read_text("utf-8")
            ready, _, _ = select.select([self._reader], [], [], 0.1)
            if not ready:
                continue
            try:
                chunk = os.read(self._reader, 4096).decode("utf-8", "replace")
            except OSError:  # the child closed its end: it is ending
                continue
            self._printed += chunk
            with self._copy.open("a", encoding="utf-8") as copy:
                copy.write(chunk)
        return found
