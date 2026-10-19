"""The ``project`` filter of ``GET /slots`` and ``GET /map/footprints``.

Two projects pin versions of the same store: ``Raba`` an older version of a
sheet and the current one of another, ``Odra`` a third version. With
``project`` the catalog and the map list exactly the versions the project
pins (on top of ``versions``); a project the session cannot see answers as
an unknown one, ``404`` (decision 8, "Granice widoczności").
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from archiwista.auth import access_key
from archiwista.index import IndexWriter, ManifestStamp
from archiwista.sources import ProjectInfo, ProjectPin, SourceEntry
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.index_data import (
    NMT,
    PRODUCER,
    ROOT,
    STORE,
    box,
    link,
    slot_path,
    version,
    write_pass,
)
from tests.fixtures.local_server import local_paths
from tests.fixtures.permissions import add_people, principal, share

SHEET_A = slot_path(NMT, "M-34-1-A")
SHEET_B = slot_path(NMT, "M-34-1-B")
RABA_DIR = Path("/projekty/raba")
VIEW = "17.0,49.0,20.0,52.0"
A_CURRENT = version(SHEET_A, "2024-05-01_1", 1)
A_OLDER = version(SHEET_A, "2016-06-01_1", 2)
B_CURRENT = version(SHEET_B, "2023-04-01_1", 3)
B_OLDER = version(SHEET_B, "2015-04-01_1", 4)


ROUTES = ["/slots?project={key}", f"/map/footprints?bbox={VIEW}&project={{key}}"]


def _path(entry: SourceEntry) -> str:
    return entry.relative_path.as_posix()


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve two sheets with two versions each; Raba and Odra pin some."""
    paths = local_paths(tmp_path)
    entries = [A_CURRENT, A_OLDER, B_CURRENT, B_OLDER]
    with running_api(paths) as served:
        with IndexWriter(paths.index_file) as writer:
            writer.sync_stores({STORE: {PRODUCER: ROOT}})
            write_pass(
                writer,
                [*entries, link(SHEET_A, A_CURRENT), link(SHEET_B, B_CURRENT)],
                footprints={
                    _path(entry): box(18.0, 50.0, 18.5, 50.3) for entry in entries
                },
            )
            for name, directory, pinned in (
                ("Raba", RABA_DIR, (A_OLDER, B_CURRENT)),
                ("Odra", Path("/projekty/odra"), (B_OLDER,)),
            ):
                pins = tuple(
                    ProjectPin(ROOT, entry.relative_path, None, "teren")
                    for entry in pinned
                )
                info = ProjectInfo(PRODUCER, ROOT, directory, name, pins=pins)
                writer.write_project(info, store=STORE, stamp=ManifestStamp(1, 1))
        add_people(served.state)
        yield served


def _versions(page: dict[str, Any]) -> list[str]:
    return sorted(row["version"]["path"] for row in page["items"] if row["version"])


@pytest.mark.parametrize(
    ("versions", "expected"),
    [
        ("all", [A_OLDER, B_CURRENT]),
        ("pinned", [A_OLDER, B_CURRENT]),
        ("current", [B_CURRENT]),
        ("noncurrent_unpinned", []),
    ],
)
def test_project_filter_lists_exactly_its_pinned_versions(
    api: Api, versions: str, expected: list[SourceEntry]
) -> None:
    """Catalog rows and map outlines: the project's pins the mode picks, only."""
    # Arrange
    owner = api.session(principal(api.state, "admin"))
    query = f"project=raba&versions={versions}"

    # Act
    page = owner.request("GET", f"/slots?{query}")
    drawn = owner.request("GET", f"/map/footprints?bbox={VIEW}&{query}")

    # Assert
    assert page.status_code == 200, page.text
    assert _versions(page.json()) == sorted(_path(entry) for entry in expected)
    assert page.json()["groups"]["footprint"] == len(expected)
    assert drawn.status_code == 200, drawn.text
    assert sorted(item["version"] for item in drawn.json()["items"]) == sorted(
        _path(entry) for entry in expected
    )


def test_project_filter_cursor_belongs_to_the_project(api: Api) -> None:
    """A page of one project continues only that project's query."""
    # Arrange
    owner = api.session(principal(api.state, "admin"))
    first = owner.request("GET", "/slots?project=raba&versions=all&limit=1").json()

    # Act
    following = owner.request(
        "GET", f"/slots?project=raba&versions=all&limit=1&cursor={first['next_cursor']}"
    )
    elsewhere = owner.request(
        "GET", f"/slots?project=odra&versions=all&limit=1&cursor={first['next_cursor']}"
    )

    # Assert
    assert _versions(first) + _versions(following.json()) == sorted(
        [_path(A_OLDER), _path(B_CURRENT)]
    )
    assert following.json()["next_cursor"] is None
    assert_problem(elsewhere, 422, "validation_error")


@pytest.mark.parametrize("route", ROUTES)
def test_hidden_and_unknown_project_filter_is_not_found(api: Api, route: str) -> None:
    """A private project of someone else answers like a missing one: 404."""
    # Arrange
    share(api.state, access_key(RABA_DIR), "private")
    other = api.session(principal(api.state, "other"))
    owner = api.session(principal(api.state, "owner"))

    # Act
    hidden = other.request("GET", route.format(key="raba"))
    missing = other.request("GET", route.format(key="nie-ma"))
    seen = owner.request("GET", route.format(key="raba"))

    # Assert
    assert_problem(hidden, 404, "not_found")
    assert_problem(missing, 404, "not_found")
    assert hidden.json()["detail"] == "Nie ma projektu „raba”."
    assert seen.status_code == 200, seen.text
