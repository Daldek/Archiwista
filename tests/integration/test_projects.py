"""Projects found in project directories and read through the Kartograf adapter.

Each test indexes the synthetic store of step 4, then runs ``scan_projects``
over its project directories (``brak-wersji``: a pinned version that does
not exist, ``inny-magazyn``: another store, ``zepsuty``: an invalid
manifest, ``projekt-NN``: regular, odd ones also pin an older version).
"""

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from archiwista.adapter.kartograf.adapter import KartografAdapter
from archiwista.auth import ALL_PROJECTS
from archiwista.config import StoreConfig
from archiwista.errors import PathOutsideRootError
from archiwista.index import IndexQueries, IndexWriter, scan_projects
from archiwista.messages import message
from archiwista.services import project_detail, project_status, store_summary
from archiwista.sources import ProjectInfo, SourceContext
from archiwista.sources.registry import load_registry
from tests.fixtures.make_store import (
    MANIFEST_NAME,
    MIN_SLOTS,
    StoreManifest,
    make_store,
)

STORE = "zespol"


class _CountingAdapter(KartografAdapter):
    """The Kartograf adapter recording which project directories it read."""

    def __init__(self, context: SourceContext) -> None:
        super().__init__(context, supported_versions="*")
        self.reads: list[str] = []

    def project_status(self, path: Path) -> ProjectInfo:
        self.reads.append(path.name)
        return super().project_status(path)


@pytest.fixture
def store(tmp_path: Path) -> StoreManifest:
    """Return a fresh synthetic store: tests change its project directories."""
    return make_store(tmp_path / "store", slots=MIN_SLOTS, seed=1)


@pytest.fixture
def adapter(tmp_path: Path) -> _CountingAdapter:
    """Return the Kartograf adapter, counting the projects it reads."""
    return _CountingAdapter(SourceContext(cache_dir=tmp_path / "cache"))


@pytest.fixture
def index(
    tmp_path: Path, store: StoreManifest, adapter: _CountingAdapter
) -> Iterator[tuple[IndexWriter, IndexQueries]]:
    """Writer and queries of an index holding one full pass of the store."""
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


def _write_manifest(directory: Path, root: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    document = {"schema": "kartograf-project/1", "root": root, "tasks": []}
    (directory / MANIFEST_NAME).write_text(json.dumps(document), encoding="utf-8")


def test_scan_projects_links_pins_to_indexed_versions(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Tasks keep their commands; an older pinned version shows on the card."""
    # Arrange
    writer, queries = index
    expected = store.project("projekt-01")
    older = next(t for t in expected.tasks if t.name == "archiwum").pins[0]

    # Act
    summary = scan_projects(
        adapter,
        writer,
        project_dirs=[store.projects_dir],
        stores=[_config(store.root)],
    )
    detail = project_detail(queries, "projekt-01", visible=ALL_PROJECTS)
    card = queries.slot(STORE, older.path, visible=ALL_PROJECTS)

    # Assert
    assert summary.found == len(store.projects)
    assert summary.read == len(store.projects)
    assert detail is not None
    assert detail.project.store == STORE
    assert [(t.task_id, t.command) for t in detail.tasks] == [
        (t.name, t.command) for t in expected.tasks
    ]
    assert detail.tasks[0].options == {
        "product": "nmt",
        "sheet": expected.tasks[0].pins[0].unit,
        "resolution": "1m",
        "vertical_crs": "EVRF2007",
    }
    assert {(p.task, p.version, p.state, p.is_current) for p in detail.pins} == {
        (task.name, pin.version, "ok", pin.current)
        for task in expected.tasks
        for pin in task.pins
    }
    assert detail.problems == ()
    assert card is not None
    old = next(v for v in card.versions if v.path == older.version)
    assert not old.is_current
    assert ("projekt-01", "archiwum") in {
        (p.project_key, p.task) for p in old.pinned_by
    }


def test_scan_projects_rereads_only_new_changed_or_unresolved_manifests(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Unchanged manifests are not read again; a changed one is re-read."""
    # Arrange
    writer, queries = index
    stores = [_config(store.root)]
    scan_projects(adapter, writer, project_dirs=[store.projects_dir], stores=stores)
    manifest = store.projects_dir / "projekt-01" / MANIFEST_NAME
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["tasks"] = [t for t in document["tasks"] if t["name"] != "plan"]

    # Act
    adapter.reads.clear()
    unchanged = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores
    )
    first_reads = sorted(adapter.reads)
    manifest.write_text(json.dumps(document), encoding="utf-8")
    adapter.reads.clear()
    changed = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores
    )
    detail = project_detail(queries, "projekt-01", visible=ALL_PROJECTS)

    # Assert
    # The invalid manifest and the one naming an unconfigured store stay
    # unresolved, so they are read on every pass.
    assert first_reads == ["inny-magazyn", "zepsuty"]
    assert unchanged.unchanged == len(store.projects) - 2
    assert sorted(adapter.reads) == ["inny-magazyn", "projekt-01", "zepsuty"]
    assert changed.read == 3
    assert detail is not None
    assert "plan" not in [t.task_id for t in detail.tasks]


def test_scan_projects_pin_without_version_is_a_visible_problem(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A pinned version missing from the store shows in the project and store."""
    # Arrange
    writer, queries = index
    config = _config(store.root)
    pin = store.project("brak-wersji").tasks[0].pins[0]

    # Act
    scan_projects(adapter, writer, project_dirs=[store.projects_dir], stores=[config])
    detail = project_detail(queries, "brak-wersji", visible=ALL_PROJECTS)
    summary = store_summary(queries, config, visible=ALL_PROJECTS)

    # Assert
    assert detail is not None
    assert [(p.version, p.state) for p in detail.pins] == [(pin.version, "missing")]
    assert detail.project.missing_pins == 1
    assert [(p.code, p.path, p.task) for p in detail.problems] == [
        ("missing_pin", pin.version, "teren")
    ]
    assert "project download teren" in detail.problems[0].instruction
    missing = [p for p in summary.problems if p.code == "missing_pin"]
    assert [(p.project, p.path) for p in missing] == [("brak-wersji", pin.version)]


def test_scan_projects_invalid_manifest_stays_visible_until_fixed(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """An invalid manifest is listed with the producer's message, then heals."""
    # Arrange
    writer, queries = index
    stores = [_config(store.root)]
    manifest = store.projects_dir / "zepsuty" / MANIFEST_NAME

    # Act
    broken = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores
    )
    listed = {p.key: p for p in queries.projects(visible=ALL_PROJECTS)}["zepsuty"]
    detail = project_detail(queries, "zepsuty", visible=ALL_PROJECTS)
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            "elevation fly", "elevation download"
        ),
        encoding="utf-8",
    )
    scan_projects(adapter, writer, project_dirs=[store.projects_dir], stores=stores)
    healed = project_detail(queries, "zepsuty", visible=ALL_PROJECTS)

    # Assert
    assert broken.invalid == 1
    assert listed.problem is not None
    assert "elevation fly" in listed.problem
    assert detail is not None
    assert [p.code for p in detail.problems] == ["invalid_manifest"]
    assert listed.problem in detail.problems[0].message
    assert healed is not None
    assert healed.problems == ()
    assert healed.project.store == STORE
    assert [t.task_id for t in healed.tasks] == ["teren"]


def test_scan_projects_unknown_store_matches_once_configured(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A project of an unconfigured store says so; adding the store links it."""
    # Arrange
    writer, queries = index
    other = store.base / "other-data"
    stores = [_config(store.root), _config(other, "inny")]

    # Act
    first = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores[:1]
    )
    unknown = project_detail(queries, "inny-magazyn", visible=ALL_PROJECTS)
    writer.sync_stores({s.id: s.roots() for s in stores})
    scan_projects(adapter, writer, project_dirs=[store.projects_dir], stores=stores)
    known = project_detail(queries, "inny-magazyn", visible=ALL_PROJECTS)

    # Assert
    assert first.unknown_store == 1
    assert unknown is not None
    assert unknown.project.store is None
    assert unknown.project.store_dir == str(other)
    assert [p.code for p in unknown.problems] == ["unknown_store"]
    assert str(other) in unknown.problems[0].message
    assert known is not None
    assert known.project.store == "inny"
    assert known.problems == ()
    assert [p.key for p in queries.projects(store="inny", visible=ALL_PROJECTS)] == [
        "inny-magazyn"
    ]


def test_scan_projects_discovery_depth_and_skipped_directories(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """Depth ≤ 4 below a project directory; no hidden, ``.git`` or store dirs."""
    # Arrange
    writer, queries = index
    top = store.base
    output = str(store.root)
    _write_manifest(top / "a" / "b" / "c" / "deep4", output)
    _write_manifest(top / "a" / "b" / "c" / "d" / "deep5", output)
    _write_manifest(top / ".git" / "w-git", output)
    _write_manifest(top / ".ukryty" / "ukryty", output)
    _write_manifest(store.root / "w-magazynie", output)

    # Act
    scan_projects(adapter, writer, project_dirs=[top], stores=[_config(store.root)])
    names = {p.name for p in queries.projects(visible=ALL_PROJECTS)}

    # Assert
    assert "deep4" in names
    assert names.isdisjoint({"deep5", "w-git", "ukryty", "w-magazynie"})
    assert {p.name for p in store.projects} <= names


def test_scan_projects_never_reads_manifest_leaving_project_dir(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
) -> None:
    """A manifest symlinked outside stays visible as invalid and is never read."""
    # Arrange
    writer, queries = index
    outside = tmp_path / "outside"
    _write_manifest(outside, "../data")
    planted = store.projects_dir / "obcy" / MANIFEST_NAME
    planted.parent.mkdir()
    planted.symlink_to(outside / MANIFEST_NAME)
    inner = store.projects_dir / "dowiazany" / MANIFEST_NAME
    inner.parent.mkdir()
    inner.symlink_to(store.projects_dir / "projekt-01" / MANIFEST_NAME)

    # Act
    summary = scan_projects(
        adapter,
        writer,
        project_dirs=[store.projects_dir],
        stores=[_config(store.root)],
    )
    listed = {p.key: p for p in queries.projects(visible=ALL_PROJECTS)}

    # Assert
    assert "obcy" not in adapter.reads
    assert listed["obcy"].problem == message("ref.path_outside_root", path=planted)
    assert listed["dowiazany"].problem is None
    assert "dowiazany" in adapter.reads
    assert summary.invalid == 1 + sum(not p.valid for p in store.projects)


def test_scan_projects_removes_gone_manifests_but_keeps_unreachable_dirs(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
) -> None:
    """A deleted manifest drops its project; a disconnected directory keeps all."""
    # Arrange
    writer, queries = index
    stores = [_config(store.root)]
    scan_projects(adapter, writer, project_dirs=[store.projects_dir], stores=stores)
    shutil.rmtree(store.projects_dir / "brak-wersji")

    # Act
    after_delete = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores
    )
    store.projects_dir.rename(store.base / "odlaczony")
    disconnected = scan_projects(
        adapter, writer, project_dirs=[store.projects_dir], stores=stores
    )

    # Assert
    assert after_delete.removed == 1
    assert disconnected.removed == 0
    assert disconnected.unreadable_dirs == (str(store.projects_dir),)
    assert len(queries.projects(visible=ALL_PROJECTS)) == len(store.projects) - 1


def test_scan_projects_matches_store_through_path_alias(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
) -> None:
    """A store written as another computer's path matches through its alias."""
    # Arrange
    writer, queries = index
    windows = r"Z:\kartograf\data"
    posix = "/Volumes/nas/kartograf/data"
    projects = tmp_path / "projekty"
    _write_manifest(projects / "z-windows", windows)
    _write_manifest(projects / "z-maca", posix)
    config = StoreConfig(
        id=STORE,
        name=STORE,
        kartograf=store.root,
        kind="local",
        path_aliases={f"{store.root}/": "Z:\\kartograf\\data\\"},
    )
    mac = config.model_copy(
        update={"path_aliases": {**config.path_aliases, f"{store.root}/": posix}}
    )

    # Act
    scan_projects(adapter, writer, project_dirs=[projects], stores=[config])
    windows_store = {p.name: p.store for p in queries.projects(visible=ALL_PROJECTS)}[
        "z-windows"
    ]
    scan_projects(adapter, writer, project_dirs=[projects], stores=[mac])
    mac_store = {p.name: p.store for p in queries.projects(visible=ALL_PROJECTS)}[
        "z-maca"
    ]

    # Assert
    assert windows_store == STORE
    assert mac_store == STORE


def test_project_status_asks_the_producer_now(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
) -> None:
    """The live status sees a pinned file removed after the last scan."""
    # Arrange
    writer, queries = index
    scan_projects(
        adapter,
        writer,
        project_dirs=[store.projects_dir],
        stores=[_config(store.root)],
    )
    older = next(t for t in store.project("projekt-01").tasks if t.name == "archiwum")
    (store.root / older.pins[0].version).unlink()
    registry = load_registry(cache_dir=tmp_path / "registry")

    # Act
    live = project_status(
        queries,
        registry,
        "projekt-01",
        visible=ALL_PROJECTS,
        project_dirs=[store.projects_dir],
    )
    unknown = project_status(
        queries,
        registry,
        "nie-ma",
        visible=ALL_PROJECTS,
        project_dirs=[store.projects_dir],
    )

    # Assert
    assert live is not None
    assert {t.task_id: t.status for t in live.tasks} == {
        "teren": "ok",
        "archiwum": "missing",
        "pokrycie": "ok",
        "plan": "not_downloaded",
    }
    assert unknown is None


@pytest.mark.parametrize("planted", ["directory", "manifest"])
def test_project_status_refuses_project_leaving_project_dirs(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
    planted: str,
) -> None:
    """A project directory or manifest symlinked outside is refused unread."""
    # Arrange
    writer, queries = index
    scan_projects(
        adapter,
        writer,
        project_dirs=[store.projects_dir],
        stores=[_config(store.root)],
    )
    project = store.base / store.project("projekt-01").path
    outside = tmp_path / "outside" / project.name
    shutil.copytree(project, outside)
    if planted == "directory":
        shutil.rmtree(project)
        project.symlink_to(outside, target_is_directory=True)
    else:
        (project / MANIFEST_NAME).unlink()
        (project / MANIFEST_NAME).symlink_to(outside / MANIFEST_NAME)
    registry = load_registry(cache_dir=tmp_path / "registry")

    # Act
    with pytest.raises(PathOutsideRootError) as refused:
        project_status(
            queries,
            registry,
            "projekt-01",
            visible=ALL_PROJECTS,
            project_dirs=[store.projects_dir],
        )

    # Assert
    assert str(project.relative_to(store.projects_dir)) in str(refused.value)


def test_project_status_refuses_project_outside_configured_dirs(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
) -> None:
    """A project indexed below a directory no longer configured is refused."""
    # Arrange
    writer, queries = index
    scan_projects(
        adapter,
        writer,
        project_dirs=[store.projects_dir],
        stores=[_config(store.root)],
    )
    registry = load_registry(cache_dir=tmp_path / "registry")
    other = tmp_path / "inne-projekty"
    other.mkdir()

    # Act / Assert
    with pytest.raises(PathOutsideRootError):
        project_status(
            queries,
            registry,
            "projekt-01",
            visible=ALL_PROJECTS,
            project_dirs=[other],
        )


def test_project_status_accepts_symlinked_project_dirs_root(
    store: StoreManifest,
    adapter: _CountingAdapter,
    index: tuple[IndexWriter, IndexQueries],
    tmp_path: Path,
) -> None:
    """A configured project directory that is itself a symlink keeps working."""
    # Arrange
    writer, queries = index
    # Beside the real one, so the manifests' relative store paths still match.
    alias = store.base / "projekty-alias"
    alias.symlink_to(store.projects_dir, target_is_directory=True)
    scan_projects(adapter, writer, project_dirs=[alias], stores=[_config(store.root)])
    registry = load_registry(cache_dir=tmp_path / "registry")

    # Act
    live = project_status(
        queries, registry, "projekt-01", visible=ALL_PROJECTS, project_dirs=[alias]
    )

    # Assert
    assert live is not None and live.problem is None
    assert {t.status for t in live.tasks} <= {"ok", "not_downloaded"}
