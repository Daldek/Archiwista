"""Discovery of Archiwista's project files (A-ADR-049, plan P2 commit 2).

A project is a directory holding ``archiwista-project.json``; a producer's
manifest alone makes none. Each test writes project files below a project
directory beside an empty marked Kartograf store and runs ``scan_projects``
over a fresh index: invalid and newer files are listed with their problem, a
file linked out of the project directory is never read, an unchanged file is
not read again, a removed file removes its project, and the area the file
names is read into the index's areas only while its bytes are the ones
written.
"""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import kartograf
import pytest

from archiwista.auth import ALL_PROJECTS
from archiwista.config import StoreConfig
from archiwista.index import IndexQueries, IndexWriter, ProjectRef, scan_projects
from archiwista.index.projects import ProjectScanSummary
from archiwista.index.types import AreaRecord
from archiwista.projects import (
    PROJECT_FILE,
    ProjectDocument,
    StoreRoot,
    change_project_file,
    read_project_json,
    write_area_file,
)
from archiwista.sources import GeoAdapter
from archiwista.sources.registry import load_registry

STORE = "zespol"
CREATED = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
# About 7 km × 11 km near Kraków.
AREA = AreaRecord(
    id="0123456789abcdef",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[19.0, 50.0], [19.1, 50.0], [19.1, 50.1], [19.0, 50.1], [19.0, 50.0]]
        ],
    },
    created_at=CREATED,
    area_km2=79.5,
    countries=("PL",),
    name="Kraków",
)


@dataclass
class Place:
    """A marked store, a project directory and an index that knows the store."""

    root: Path
    projects: Path
    writer: IndexWriter
    queries: IndexQueries
    geo: GeoAdapter | None = None

    def scan(self) -> ProjectScanSummary:
        """Run discovery over the project directory."""
        config = StoreConfig(id=STORE, name=STORE, kartograf=self.root, kind="local")
        return scan_projects(
            self.writer, project_dirs=[self.projects], stores=[config], geo=self.geo
        )

    def listed(self) -> dict[str, ProjectRef]:
        """Return the indexed projects by the name of their directory."""
        return {
            Path(ref.path).name: ref
            for ref in self.queries.projects(visible=ALL_PROJECTS)
        }


@pytest.fixture
def place(tmp_path: Path) -> Iterator[Place]:
    """Give an empty marked store and an empty project directory."""
    root = tmp_path / "nas" / "kartograf"
    kartograf.init_store(root)
    projects = tmp_path / "nas" / "projekty"
    projects.mkdir()
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores({STORE: {"kartograf": root}})
        yield Place(root, projects, writer, queries)


def _write(place: Place, name: str, *, area: AreaRecord | None = None) -> Path:
    """Write a project file naming the store; return its directory."""
    directory = place.projects / name
    directory.mkdir(parents=True, exist_ok=True)
    change_project_file(
        directory,
        create=ProjectDocument(
            name=name,
            description="",
            created_at=CREATED,
            created_by="local",
            area=None if area is None else write_area_file(directory, area),
            stores=(StoreRoot("kartograf", str(place.root)),),
        ),
    )
    return directory


def _count_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the directory of each project file discovery reads from now on."""
    reads: list[str] = []

    def counted(directory: Path) -> dict[str, Any]:
        reads.append(directory.name)
        return read_project_json(directory)

    monkeypatch.setattr("archiwista.index.projects.read_project_json", counted)
    return reads


def _edit(directory: Path, **members: Any) -> None:
    """Change members of a project file by hand, as another program might."""
    path = directory / PROJECT_FILE
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(members)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_discovery_reads_the_project_file_only(place: Place) -> None:
    """A directory with another JSON file alone is no project; the file is."""
    # Arrange
    other = place.projects / "inny-plik"
    other.mkdir(parents=True)
    (other / "project.json").write_text('{"name": "inny"}', encoding="utf-8")
    _write(place, "raba")

    # Act
    summary = place.scan()
    listed = place.listed()

    # Assert
    assert (summary.found, summary.read, summary.invalid) == (1, 1, 0)
    assert list(listed) == ["raba"]
    raba = listed["raba"]
    assert (raba.state, raba.problem) == ("ok", None)
    assert [(s.producer, s.root, s.store) for s in raba.stores] == [
        ("kartograf", str(place.root), STORE)
    ]


def test_discovery_lists_invalid_and_newer_files_with_their_problem(
    place: Place,
) -> None:
    """A rule broken or a newer schema: listed by the directory, not used."""
    # Arrange
    _edit(_write(place, "zepsuty"), name="")
    _edit(_write(place, "nowszy"), schema="archiwista-project/2", name="Nowszy")

    # Act
    summary = place.scan()
    listed = place.listed()

    # Assert
    assert summary.invalid == 2
    broken, newer = listed["zepsuty"], listed["nowszy"]
    assert (broken.name, broken.state, broken.problem) == (
        "zepsuty",
        "invalid",
        "invalid_project_file",
    )
    assert broken.problem_detail is not None
    assert broken.problem_detail["pointer"] == "/name"
    assert (newer.name, newer.state, newer.problem) == (
        "Nowszy",
        "unsupported_schema",
        "unsupported_project_schema",
    )
    assert (broken.stores, newer.stores, broken.groups) == ((), (), 0)


def test_discovery_never_reads_a_file_linked_out_of_the_project_directory(
    place: Place, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A link out is ``path_outside_root`` unread; a link inside is read."""
    # Arrange
    outside = tmp_path / "poza"
    outside.mkdir()
    change_project_file(
        outside,
        create=ProjectDocument("Obcy", "", CREATED, "local"),
    )
    planted = place.projects / "obcy"
    planted.mkdir()
    (planted / PROJECT_FILE).symlink_to(outside / PROJECT_FILE)
    inner = place.projects / "dowiazany"
    inner.mkdir()
    (inner / PROJECT_FILE).symlink_to(_write(place, "raba") / PROJECT_FILE)
    reads = _count_reads(monkeypatch)

    # Act
    place.scan()
    listed = place.listed()

    # Assert
    assert sorted(reads) == ["dowiazany", "raba"]
    obcy = listed["obcy"]
    assert (obcy.name, obcy.state, obcy.problem) == (
        "obcy",
        "invalid",
        "invalid_project_file",
    )
    assert obcy.problem_detail == {"pointer": "", "rule": "path_outside_root"}
    assert listed["dowiazany"].state == "ok"


def test_discovery_reads_again_only_a_changed_file_and_drops_a_removed_one(
    place: Place, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stamp (size, modification time) decides; a removed file is gone."""
    # Arrange
    raba = _write(place, "raba")
    wisla = _write(place, "wisla")
    place.scan()
    reads = _count_reads(monkeypatch)

    # Act
    unchanged = place.scan()
    unchanged_reads = list(reads)
    _edit(raba, description="Zlewnia Raby")
    (wisla / PROJECT_FILE).unlink()
    changed = place.scan()
    listed = place.listed()

    # Assert
    assert (unchanged.unchanged, unchanged.read, unchanged_reads) == (2, 0, [])
    assert (changed.read, changed.removed, reads) == (1, 1, ["raba"])
    assert list(listed) == ["raba"]
    assert listed["raba"].description == "Zlewnia Raby"


def test_discovery_reads_the_area_into_the_index_unless_its_file_changed(
    place: Place, tmp_path: Path
) -> None:
    """The area file kept is an area of the index; a changed one is not used."""
    # Arrange
    adapter = load_registry(cache_dir=tmp_path / "cache").adapter("kartograf")
    assert isinstance(adapter, GeoAdapter)
    place.geo = adapter
    _write(place, "raba", area=AREA)
    changed = _write(place, "wisla", area=AREA)
    area_file = changed / "obszary" / f"{AREA.id}.geojson"
    area_file.write_text(area_file.read_text(encoding="utf-8") + "\n", "utf-8")

    # Act
    place.scan()
    listed = place.listed()

    # Assert
    kept, refused = listed["raba"].area, listed["wisla"].area
    assert kept is not None and refused is not None
    assert (kept.path, kept.state) == (f"obszary/{AREA.id}.geojson", "ok")
    assert kept.area_id is not None
    stored = place.queries.area(kept.area_id)
    assert stored is not None
    assert (stored.source, stored.name, stored.countries) == ("file", "raba", ("PL",))
    assert (refused.state, refused.area_id) == ("changed", None)
