"""Project visibility in index queries and services (A-ADR-029, SPEC 10.2).

One project, ``Raba``, pins an older version of a sheet and a version the
store no longer has. For every visibility and identity, each query and
service that names projects or follows their pins must agree with the
matrix; reports counting projects count it whoever looks.
"""

from pathlib import Path

import pytest

from archiwista.auth import ProjectVisibility, access_key
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings, StoreConfig
from archiwista.index import IndexQueries, IndexWriter, MapQuery, SlotQuery
from archiwista.services import project_detail, store_summary
from archiwista.state import StateStore, Visibility
from tests.fixtures.index_data import (
    NMT,
    ROOT,
    STORE,
    box,
    indexed_project,
    link,
    pin,
    sha,
    slot_path,
    version,
    version_path,
    write_pass,
)
from tests.fixtures.permissions import (
    SEES,
    VISIBILITY_VALUES,
    WHO,
    Who,
    add_people,
    principal,
    share,
)

SHEET = slot_path(NMT, "M-34-1-A")
CONFIG = StoreConfig(id=STORE, name="Zespół", kartograf=Path(ROOT), kind="local")
PROJECT_DIR = Path("/projekty/raba")
GONE = version_path(SHEET, "2010-01-01_1", sha(9))
VIEW = (17.0, 49.0, 20.0, 52.0)


def _index_with_raba(writer: IndexWriter) -> str:
    """Index a sheet whose older version Raba pins; Raba also pins a gone one."""
    current = version(SHEET, "2024-05-01_1", 1)
    older = version(SHEET, "2016-06-01_1", 2)
    write_pass(
        writer,
        [current, older, link(SHEET, current)],
        footprints={
            entry.relative_path.as_posix(): box(18.0, 50.0, 18.5, 50.3)
            for entry in (current, older)
        },
    )
    pins = (pin(older.relative_path, sha(2)), pin(GONE, sha(9)))
    indexed_project(writer, PROJECT_DIR, "Raba", store=STORE, pins=pins)
    return older.relative_path.as_posix()


def _seen(state: StateStore, who: Who, **settings: object) -> ProjectVisibility:
    current = AppSettings.model_validate(settings)
    return Authorizer(state, lambda: current).visible_projects(principal(state, who))


@pytest.mark.parametrize("who", WHO)
@pytest.mark.parametrize("visibility", VISIBILITY_VALUES)
def test_visibility_matrix_in_queries_and_services(
    tmp_path: Path,
    index: tuple[IndexWriter, IndexQueries],
    visibility: Visibility,
    who: Who,
) -> None:
    """Lists, cards, the pinned filter, the map and the store report agree."""
    # Arrange
    writer, queries = index
    older = _index_with_raba(writer)
    state = StateStore(tmp_path / "state.sqlite")
    add_people(state)
    share(state, access_key(PROJECT_DIR), visibility)
    visible = _seen(state, who)
    sees = who in SEES[visibility]
    names = ("Raba",) if sees else ()

    # Act
    listed = [ref.key for ref in queries.projects(visible=visible)]
    record = queries.project("raba", visible=visible)
    detail = project_detail(queries, "raba", visible=visible)
    pinned = queries.slots(SlotQuery(versions="pinned"), visible=visible)
    every = queries.slots(SlotQuery(versions="all"), visible=visible)
    card = queries.slot(STORE, SHEET, visible=visible)
    found = queries.version(STORE, older, visible=visible)
    drawn = queries.footprints(MapQuery(bbox=VIEW, versions="pinned"), visible=visible)
    problems = queries.pin_problems(STORE, visible=visible)
    summary = store_summary(queries, CONFIG, visible=visible)
    unpinned = queries.slots(SlotQuery(versions="noncurrent_unpinned"), visible=visible)

    # Assert
    assert listed == (["raba"] if sees else [])
    assert (record is not None, detail is not None) == (sees, sees)
    assert [row.version.path for row in pinned.items if row.version] == (
        [older] if sees else []
    )
    assert drawn.total == (1 if sees else 0)
    row = next(row for row in every.items if row.version and row.version.path == older)
    assert row.version is not None
    assert tuple(pin.project for pin in row.version.pinned_by) == names
    assert card is not None
    on_card = next(item for item in card.versions if item.path == older)
    assert tuple(pin.project for pin in on_card.pinned_by) == names
    assert found is not None
    assert tuple(pin.project for pin in found.summary.pinned_by) == names
    assert [pin.version for pin in problems] == ([GONE] if sees else [])
    assert [ref.key for ref in summary.projects] == (["raba"] if sees else [])
    assert {problem.code for problem in summary.problems} == (
        {"missing_pin"} if sees else set()
    )
    # Counts cover every project: Raba's pin keeps the older version in use.
    assert unpinned.items == ()
    assert summary.unused.versions == 0


@pytest.mark.parametrize(
    ("default", "seen_by"),
    [("public", set(WHO)), ("private", {"admin"})],
)
def test_project_without_entry_follows_default_in_queries(
    tmp_path: Path,
    index: tuple[IndexWriter, IndexQueries],
    default: str,
    seen_by: set[str],
) -> None:
    """A scanned project nobody shared yet uses ``default_project_visibility``."""
    # Arrange
    writer, queries = index
    _index_with_raba(writer)
    state = StateStore(tmp_path / "state.sqlite")
    add_people(state)

    # Act
    seeing = {
        who
        for who in WHO
        if queries.projects(
            visible=_seen(state, who, default_project_visibility=default)
        )
    }

    # Assert
    assert seeing == seen_by
