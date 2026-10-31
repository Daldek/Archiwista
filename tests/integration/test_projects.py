"""The store fixture's project files found in its project directory and indexed.

Each test indexes the synthetic store of step 4, then runs ``scan_projects``
over its project directories (``brak-wersji``: a pinned version that does
not exist, ``inny-magazyn``: another store, ``zepsuty``: a file breaking a
rule, ``projekt-NN``: regular, odd ones also pin an older version in a local
group). ``project_directory`` refuses a project that left the project
directories since the scan.
"""

import json
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from archiwista.adapter.kartograf.adapter import KartografAdapter
from archiwista.auth import ALL_PROJECTS
from archiwista.config import AppSettings, StoreConfig
from archiwista.errors import PathOutsideRootError
from archiwista.index import IndexQueries, IndexWriter, ProjectRef, scan_projects
from archiwista.index.projects import ProjectScanSummary
from archiwista.projects import (
    PROJECT_FILE,
    ProjectDocument,
    StoreRoot,
    change_project_file,
)
from archiwista.services import project_detail, store_summary
from archiwista.services.projects import project_directory
from archiwista.sources import SourceContext
from tests.fixtures.make_store import MIN_SLOTS, StoreManifest, make_store

STORE = "zespol"


@pytest.fixture
def store(tmp_path: Path) -> StoreManifest:
    """Return a fresh synthetic store: tests change its project directories."""
    return make_store(tmp_path / "store", slots=MIN_SLOTS, seed=1)


@pytest.fixture
def index(
    tmp_path: Path, store: StoreManifest
) -> Iterator[tuple[IndexWriter, IndexQueries]]:
    """Writer and queries of an index holding one full pass of the store."""
    adapter = KartografAdapter(
        SourceContext(cache_dir=tmp_path / "cache"), supported_versions="*"
    )
    path = tmp_path / "index.sqlite"
    with IndexWriter(path) as writer, IndexQueries(path) as queries:
        writer.sync_stores({STORE: {"kartograf": store.root}})
        writer.write_segments(
            STORE,
            "kartograf",
            [adapter.describe_segment(name) for name in adapter.segments(store.root)],
        )
        writer.begin_pass(STORE, "kartograf", full=True)
        writer.write_entries(adapter.iter_entries(store.root))
        writer.finish_pass()
        yield writer, queries


def _config(root: Path, store_id: str = STORE, **aliases: str) -> StoreConfig:
    return StoreConfig(
        id=store_id,
        name=store_id,
        kartograf=root,
        kind="local",
        path_aliases=dict(aliases),
    )


def _scan(
    writer: IndexWriter, projects: Path, *stores: StoreConfig
) -> ProjectScanSummary:
    return scan_projects(writer, project_dirs=[projects], stores=stores, geo=None)


def _write_project(directory: Path, root: str) -> None:
    """Write a project file of the store ``root`` (as the file writes it)."""
    directory.mkdir(parents=True, exist_ok=True)
    change_project_file(
        directory,
        create=ProjectDocument(
            name=directory.name,
            description="",
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            created_by="local",
            stores=(StoreRoot("kartograf", root),),
        ),
    )


def _by_name(queries: IndexQueries) -> dict[str, ProjectRef]:
    return {p.name: p for p in queries.projects(visible=ALL_PROJECTS)}


def test_scan_projects_links_pins_to_indexed_versions(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """Groups keep their origin and pins; an older pinned version shows on the card."""
    # Arrange
    writer, queries = index
    expected = store.project("projekt-01")
    older = next(g for g in expected.groups if g.name == "archiwum").pins[0]

    # Act
    summary = _scan(writer, store.projects_dir, _config(store.root))
    detail = project_detail(queries, "projekt-01", visible=ALL_PROJECTS)
    card = queries.slot(STORE, older.path, visible=ALL_PROJECTS)

    # Assert
    assert summary.found == len(store.projects)
    assert summary.read == len(store.projects)
    assert detail is not None
    assert [(s.producer, s.store) for s in detail.project.stores] == [
        ("kartograf", STORE)
    ]
    assert [(g.name, g.origin) for g in detail.groups] == [
        (g.name, g.origin) for g in expected.groups
    ]
    teren = detail.groups[0]
    assert [call.options for call in teren.calls] == [
        {
            "product": "nmt",
            "sheet": expected.groups[0].pins[0].unit,
            "resolution": "1m",
            "vertical_crs": "EVRF2007",
        }
    ]
    assert {
        (g.name, p.version, p.state, p.is_current)
        for g in detail.groups
        for p in g.pins
    } == {
        (g.name, pin.version, "ok", pin.current)
        for g in expected.groups
        for pin in g.pins
    }
    assert detail.problems == ()
    assert card is not None
    old = next(v for v in card.versions if v.path == older.version)
    assert not old.is_current
    assert ("projekt-01", "archiwum") in {
        (p.project_key, p.group) for p in old.pinned_by
    }


def test_scan_projects_pin_without_version_is_a_visible_problem(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """A pinned version missing from the store shows in the project and store."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    pin = store.project("brak-wersji").groups[0].pins[0]

    # Act
    _scan(writer, store.projects_dir, config)
    detail = project_detail(queries, "brak-wersji", visible=ALL_PROJECTS)
    summary = store_summary(queries, config, visible=ALL_PROJECTS)

    # Assert
    assert detail is not None
    assert [(p.version, p.state) for g in detail.groups for p in g.pins] == [
        (pin.version, "missing")
    ]
    assert detail.project.missing_pins == 1
    assert [(p.code, p.path, p.group) for p in detail.problems] == [
        ("missing_pin", pin.version, "teren")
    ]
    assert "kartograf" in detail.problems[0].instruction
    missing = [p for p in summary.problems if p.code == "missing_pin"]
    assert [(p.project, p.path) for p in missing] == [("brak-wersji", pin.version)]


def test_scan_projects_invalid_file_stays_visible_until_fixed(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """A file breaking a rule is listed with the rule's pointer, then heals."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    path = store.projects_dir / "zepsuty" / PROJECT_FILE

    # Act
    broken = _scan(writer, store.projects_dir, config)
    listed = _by_name(queries)["zepsuty"]
    detail = project_detail(queries, "zepsuty", visible=ALL_PROJECTS)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["groups"][0]["name"] = "teren"
    path.write_text(json.dumps(data), encoding="utf-8")
    _scan(writer, store.projects_dir, config)
    healed = project_detail(queries, "zepsuty", visible=ALL_PROJECTS)

    # Assert
    assert broken.invalid == 1
    assert (listed.state, listed.problem) == ("invalid", "invalid_project_file")
    assert listed.problem_detail is not None
    assert listed.problem_detail["pointer"] == "/groups/0/name"
    assert detail is not None
    assert [p.code for p in detail.problems] == ["invalid_project_file"]
    assert "/groups/0/name" in detail.problems[0].message
    assert healed is not None
    assert healed.problems == ()
    assert [s.store for s in healed.project.stores] == [STORE]
    assert [g.name for g in healed.groups] == ["teren"]


def test_scan_projects_unknown_store_matches_once_configured(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """A project of an unconfigured store says so and is read on every pass."""
    # Arrange
    writer, queries = index
    other = store.base / "other-data"
    stores = [_config(store.root), _config(other, "inny")]

    # Act
    first = _scan(writer, store.projects_dir, stores[0])
    again = _scan(writer, store.projects_dir, stores[0])
    unknown = project_detail(queries, "inny-magazyn", visible=ALL_PROJECTS)
    writer.sync_stores({s.id: s.roots() for s in stores})
    _scan(writer, store.projects_dir, *stores)
    known = project_detail(queries, "inny-magazyn", visible=ALL_PROJECTS)

    # Assert
    assert first.unknown_store == 1
    assert again.read == 1
    assert unknown is not None
    assert [s.store for s in unknown.project.stores] == [None]
    assert [p.code for p in unknown.problems] == ["unknown_store"]
    assert unknown.project.stores[0].root in unknown.problems[0].message
    assert known is not None
    assert [s.store for s in known.project.stores] == ["inny"]
    assert known.problems == ()
    assert [p.key for p in queries.projects(store="inny", visible=ALL_PROJECTS)] == [
        "inny-magazyn"
    ]


def test_scan_projects_discovery_depth_and_skipped_directories(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """Depth ≤ 4 below a project directory; no hidden, ``.git`` or store dirs."""
    # Arrange
    writer, queries = index
    top = store.base
    root = str(store.root)
    _write_project(top / "a" / "b" / "c" / "deep4", root)
    _write_project(top / "a" / "b" / "c" / "d" / "deep5", root)
    _write_project(top / ".git" / "w-git", root)
    _write_project(top / ".ukryty" / "ukryty", root)
    _write_project(store.root / "w-magazynie", root)

    # Act
    _scan(writer, top, _config(store.root))
    names = set(_by_name(queries))

    # Assert
    assert "deep4" in names
    assert names.isdisjoint({"deep5", "w-git", "ukryty", "w-magazynie"})
    assert {p.name for p in store.projects if p.valid} <= names


def test_scan_projects_removes_gone_files_but_keeps_unreachable_dirs(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """A deleted project drops; a disconnected project directory keeps all."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    _scan(writer, store.projects_dir, config)
    shutil.rmtree(store.projects_dir / "brak-wersji")

    # Act
    after_delete = _scan(writer, store.projects_dir, config)
    store.projects_dir.rename(store.base / "odlaczony")
    disconnected = _scan(writer, store.projects_dir, config)

    # Assert
    assert after_delete.removed == 1
    assert disconnected.removed == 0
    assert disconnected.unreadable_dirs == (str(store.projects_dir),)
    assert len(queries.projects(visible=ALL_PROJECTS)) == len(store.projects) - 1


def test_scan_projects_matches_store_through_path_alias(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries], tmp_path: Path
) -> None:
    """A store written as another computer's path matches through its alias."""
    # Arrange
    writer, queries = index
    windows = r"Z:\kartograf\data"
    posix = "/Volumes/nas/kartograf/data"
    projects = tmp_path / "projekty"
    _write_project(projects / "z-windows", windows)
    _write_project(projects / "z-maca", posix)
    config = _config(store.root, **{f"{store.root}/": "Z:\\kartograf\\data\\"})
    mac = _config(store.root, **{f"{store.root}/": posix})

    # Act
    _scan(writer, projects, config)
    windows_store = [s.store for s in _by_name(queries)["z-windows"].stores]
    _scan(writer, projects, mac)
    mac_store = [s.store for s in _by_name(queries)["z-maca"].stores]

    # Assert
    assert windows_store == [STORE]
    assert mac_store == [STORE]


@pytest.mark.parametrize("planted", ["directory", "file"])
def test_project_directory_refuses_project_leaving_project_dirs(
    store: StoreManifest,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
    planted: str,
) -> None:
    """A project directory or file symlinked outside since the scan is refused."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    _scan(writer, store.projects_dir, config)
    record = queries.project("projekt-01", visible=ALL_PROJECTS)
    assert record is not None
    project = store.base / store.project("projekt-01").path
    outside = tmp_path / "outside" / project.name
    shutil.copytree(project, outside)
    if planted == "directory":
        shutil.rmtree(project)
        project.symlink_to(outside, target_is_directory=True)
    else:
        (project / PROJECT_FILE).unlink()
        (project / PROJECT_FILE).symlink_to(outside / PROJECT_FILE)
    settings = AppSettings(stores=(config,), project_dirs=(store.projects_dir,))

    # Act
    with pytest.raises(PathOutsideRootError) as refused:
        project_directory(record.project, settings)

    # Assert
    assert str(project.relative_to(store.projects_dir)) in str(refused.value)


def test_project_directory_refuses_project_outside_configured_dirs(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries], tmp_path: Path
) -> None:
    """A project indexed below a directory no longer configured is refused."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    _scan(writer, store.projects_dir, config)
    record = queries.project("projekt-01", visible=ALL_PROJECTS)
    assert record is not None
    other = tmp_path / "inne-projekty"
    other.mkdir()
    settings = AppSettings(stores=(config,), project_dirs=(other,))

    # Act / Assert
    with pytest.raises(PathOutsideRootError):
        project_directory(record.project, settings)


def test_project_directory_accepts_symlinked_project_dirs_root(
    store: StoreManifest, index: tuple[IndexWriter, IndexQueries]
) -> None:
    """A configured project directory that is itself a symlink keeps working."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    # Beside the real one, so the files' relative store paths still match.
    alias = store.base / "projekty-alias"
    alias.symlink_to(store.projects_dir, target_is_directory=True)
    _scan(writer, alias, config)
    record = queries.project("projekt-01", visible=ALL_PROJECTS)
    assert record is not None
    settings = AppSettings(stores=(config,), project_dirs=(alias,))

    # Act
    directory = project_directory(record.project, settings)

    # Assert
    assert directory == alias / "projekt-01"
    assert [s.store for s in record.project.stores] == [STORE]
