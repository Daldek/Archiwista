"""The index and the state database opened by processes at the same moment.

The first ``initialize`` switches a new database to WAL, writing its header;
SQLite refuses a process that read the header meanwhile at once, without the
busy timeout ("database is locked"). The server, the job workers and the
command line open both databases, so every one of them must open a new one
together with the others. Other processes are real ones
(``tests.fixtures.processes``).
"""

from contextlib import ExitStack
from pathlib import Path

import pytest

from tests.fixtures.processes import CHILD_TIMEOUT_S, spawn, start_together

# Processes initialising new databases together: before each one every
# process says "ready" and waits for a line on its standard input, so that all
# of them open the same new database at once; one database per argument
# after the module whose ``initialize`` opens it.
OPENING = """
import importlib, sys
from pathlib import Path

initialize = importlib.import_module(sys.argv[1]).initialize
for path in sys.argv[2:]:
    print("ready", flush=True)
    sys.stdin.readline()
    initialize(Path(path))
"""


@pytest.mark.parametrize(
    ("module", "name"),
    [("archiwista.index", "index.sqlite"), ("archiwista.state", "state.sqlite")],
)
def test_database_opened_by_processes_at_once(
    tmp_path: Path, module: str, name: str
) -> None:
    """Eight processes initialise each of five new databases together."""
    # Arrange
    paths = [tmp_path / f"round-{round_}" / name for round_ in range(5)]

    # Act
    with ExitStack() as stack:
        children = [spawn(stack, OPENING, module, *paths) for _ in range(8)]
        for _ in paths:
            if not start_together(children):
                break
        finished = [child.communicate(timeout=CHILD_TIMEOUT_S) for child in children]

    # Assert
    assert [child.returncode for child in children] == [0] * 8, finished
