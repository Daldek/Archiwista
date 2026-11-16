"""Local databases opened by processes at the same moment.

The first process to open a new database switches it to WAL, writing its
header; SQLite refuses a process that read the header meanwhile at once,
without the busy timeout ("database is locked"). The server, the job workers
and the command line open the index and the state database, and those that
outline Kartograf's files the adapter's unit cache, so every one of them must
open a new one together with the others. Other processes are real ones
(``tests.fixtures.processes``).
"""

from contextlib import ExitStack
from pathlib import Path

import pytest

from tests.fixtures.processes import CHILD_TIMEOUT_S, spawn, start_together

# Processes opening new databases together: before each one every process
# says "ready" and waits for a line on its standard input, so that all of
# them open the same new database at once; one database per argument, opened
# by the ``open_database`` that the parameter of the test defines before.
TOGETHER = """
import sys
from pathlib import Path

for path in sys.argv[1:]:
    print("ready", flush=True)
    sys.stdin.readline()
    open_database(Path(path))
"""
# Kartograf's unit cache creates its file when it stores the first outline.
UNIT_CACHE = """
from kartograf import BBox
from archiwista.adapter.kartograf.unit_cache import UnitBBoxCache

def open_database(path):
    outline = BBox(560_000.0, 240_000.0, 580_000.0, 260_000.0, "EPSG:2180")
    UnitBBoxCache(path)[("teryt", "1465")] = outline
"""


@pytest.mark.parametrize(
    ("opening", "name"),
    [
        ("from archiwista.index import initialize as open_database", "index.sqlite"),
        ("from archiwista.state import initialize as open_database", "state.sqlite"),
        (UNIT_CACHE, "unit_bboxes.sqlite"),
    ],
    ids=["index", "state", "unit_cache"],
)
def test_database_opened_by_processes_at_once(
    tmp_path: Path, opening: str, name: str
) -> None:
    """Eight processes open each of five new databases together."""
    # Arrange
    paths = [tmp_path / f"round-{round_}" / name for round_ in range(5)]

    # Act
    with ExitStack() as stack:
        children = [spawn(stack, opening + TOGETHER, *paths) for _ in range(8)]
        for _ in paths:
            if not start_together(children):
                break
        finished = [child.communicate(timeout=CHILD_TIMEOUT_S) for child in children]

    # Assert
    assert [child.returncode for child in children] == [0] * 8, finished
