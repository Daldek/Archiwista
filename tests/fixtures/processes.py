"""Child processes running the repository's code, started together.

A child is ``python -c`` with the repository on ``PYTHONPATH``. A script
that should act at the same moment as the others prints "ready" and waits
for a line on its standard input; ``start_together`` gives that line to all
of them once every one is ready.
"""

import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHILD_TIMEOUT_S = 60.0


def child_env() -> dict[str, str]:
    """Return the environment of a child importing the repository's code."""
    paths = [str(REPO_ROOT), os.environ.get("PYTHONPATH", "")]
    return {**os.environ, "PYTHONPATH": os.pathsep.join(path for path in paths if path)}


def spawn(stack: ExitStack, script: str, *args: object) -> subprocess.Popen[str]:
    """Start a child with pipes; leaving ``stack`` kills it, so a hang fails."""
    child = stack.enter_context(
        subprocess.Popen(
            [sys.executable, "-c", script, *(str(arg) for arg in args)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=child_env(),
        )
    )
    stack.callback(child.kill)
    return child


def start_together(children: list[subprocess.Popen[str]]) -> bool:
    """Wait for "ready" from every child, then give each its line to go on.

    Returns ``False``, writing nothing, when a child ended instead: its return
    code and standard error say why, where a write would raise
    ``BrokenPipeError``.
    """
    lines = []
    for child in children:
        assert child.stdout is not None
        lines.append(child.stdout.readline())
    if lines != ["ready\n"] * len(children):
        return False
    for child in children:
        assert child.stdin is not None
        child.stdin.write("go\n")
        child.stdin.flush()
    return True
