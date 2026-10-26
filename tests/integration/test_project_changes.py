"""Changes of a project's manifest through its producer (plan of 2026-10-25, A7).

``services.projects.create_project``, ``add_project_task`` and
``remove_project_task`` with the real Kartograf adapter, offline, over a marked
Kartograf store and a project directory: the manifest is the one Kartograf's own
calls write for the same arguments, Kartograf's refusals keep its text and
option, the index shows a change at once, and a project lies only where a scan
finds it. Every test also runs under the canary of the producers' default roots.
"""

import json
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kartograf
import pytest

from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER, Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings, StoreConfig
from archiwista.errors import (
    CommandRequestError,
    NotFoundError,
    PathOutsideRootError,
    PermissionDeniedError,
    ProducerError,
    SourceUnavailableError,
    UnsupportedError,
)
from archiwista.index import IndexQueries, IndexWriter, initialize, scan_projects
from archiwista.index.projects import MAX_PROJECT_DEPTH
from archiwista.services import projects as changes
from archiwista.sources.registry import SourceRegistry, load_registry
from archiwista.state import StateStore, Visibility
from tests.fixtures.availability import register_standin
from tests.fixtures.network import no_network
from tests.fixtures.permissions import (
    MANAGES,
    SEES,
    VISIBILITY_VALUES,
    WHO,
    Who,
    add_people,
    principal,
    share,
)

STORE = "zespol"
MANIFEST = "kartograf-project.json"
TASK = "teren"
COMMAND = "elevation download"
# A box of 1 km² in PL-1992 cut into 1:10 000 sheets: checked without network.
OPTIONS: dict[str, Any] = {
    "product": "nmt",
    "country": "pl",
    "bbox": [500000, 250000, 501000, 251000],
    "bbox_crs": "EPSG:2180",
    "sheet_system": "1992",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
    "year": 2023,
}


@dataclass(frozen=True)
class Place:
    """A marked store, a project directory, the index and the people."""

    root: Path
    projects: Path
    settings: AppSettings
    index: Path
    registry: SourceRegistry
    state: StateStore
    authorizer: Authorizer

    def create(self, name: str, *, actor: Principal = LOCAL_OWNER) -> str:
        """Create the project ``projects/<name>`` of Kartograf; return its key."""
        return changes.create_project(
            self.registry,
            self.settings,
            self.index,
            self.authorizer,
            producer="kartograf",
            path=str(self.projects / name),
            store=STORE,
            actor=actor,
        )

    def add(
        self,
        key: str,
        options: dict[str, Any],
        *,
        actor: Principal = LOCAL_OWNER,
        name: str = TASK,
    ) -> str:
        """Add the task ``name`` of ``elevation download`` to a project."""
        with IndexQueries(self.index) as queries:
            return changes.add_project_task(
                self.registry,
                self.settings,
                queries,
                self.index,
                self.authorizer,
                key,
                name=name,
                command=COMMAND,
                options=options,
                producer=None,
                actor=actor,
                visible=self.authorizer.visible_projects(actor),
            )

    def remove(self, key: str, *, actor: Principal = LOCAL_OWNER) -> str:
        """Remove the task ``TASK`` of a project."""
        with IndexQueries(self.index) as queries:
            return changes.remove_project_task(
                self.registry,
                self.settings,
                queries,
                self.index,
                self.authorizer,
                key,
                name=TASK,
                actor=actor,
                visible=self.authorizer.visible_projects(actor),
            )


def _place(tmp_path: Path, **aliases: str) -> Place:
    root = tmp_path / "nas" / "kartograf"
    kartograf.init_store(root)
    projects = tmp_path / "nas" / "projekty"
    projects.mkdir()
    config = StoreConfig(
        id=STORE, name="Zespół", kartograf=root, kind="share", path_aliases=aliases
    )
    settings = AppSettings(stores=(config,), project_dirs=(projects,))
    index = tmp_path / "data" / "index.sqlite"
    initialize(index)
    with IndexWriter(index) as writer:
        writer.sync_stores({STORE: config.roots()})
    state = StateStore(tmp_path / "data" / "state.sqlite")
    add_people(state)
    return Place(
        root=root,
        projects=projects,
        settings=settings,
        index=index,
        registry=load_registry(cache_dir=tmp_path / "cache"),
        state=state,
        authorizer=Authorizer(state, lambda: settings),
    )


@pytest.fixture
def place(tmp_path: Path) -> Place:
    """Give a store without path aliases: manifests name it by its absolute path."""
    return _place(tmp_path)


def _manifest(directory: Path) -> Any:
    return json.loads((directory / MANIFEST).read_text(encoding="utf-8"))


def _library_options() -> dict[str, Any]:
    """Return ``OPTIONS`` as Kartograf's library takes them: the box is one ``BBox``."""
    arguments = {k: v for k, v in OPTIONS.items() if k not in ("bbox", "bbox_crs")}
    x0, y0, x1, y1 = OPTIONS["bbox"]
    return {**arguments, "bbox": kartograf.BBox(x0, y0, x1, y1, OPTIONS["bbox_crs"])}


@pytest.mark.parametrize("aliased", [False, True])
def test_a_project_and_its_task_are_written_as_kartografs_own_calls_write_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, aliased: bool
) -> None:
    """The store is relative with path aliases, absolute without; never the default.

    Kartograf's own project lies as far from the store, so its relative root
    reads the same; nothing reaches the network, and the index shows the project
    with its task and store at once.
    """
    place = _place(tmp_path, **({"/mnt/nas/": "Z:\\"} if aliased else {}))
    own = tmp_path / "nas" / "own" / "raba"

    with no_network() as attempts:
        key = place.create("raba")
        place.add(key, OPTIONS)
        monkeypatch.chdir(tmp_path / "nas")
        kartograf.init_project(own, root="kartograf" if aliased else place.root)
        kartograf.add_project_task(
            own, name=TASK, command=COMMAND, options=_library_options()
        )

    written = _manifest(place.projects / "raba")
    assert attempts == []
    assert written == _manifest(own)
    assert written["root"] == ("../../kartograf" if aliased else str(place.root))
    with IndexQueries(place.index) as queries:
        record = queries.project(key, visible=ALL_PROJECTS)
    assert record is not None
    assert [(m.store, m.status) for m in record.project.manifests] == [
        (STORE, "not_downloaded")
    ]
    assert [(task.task_id, task.command) for task in record.tasks] == [(TASK, COMMAND)]
    assert dict(record.tasks[0].options) == written["tasks"][0]["options"]


def test_removing_a_task_writes_kartografs_manifest_and_keeps_the_store(
    place: Place,
) -> None:
    """The task goes from the manifest and the index; the store is untouched."""
    key = place.create("raba")
    place.add(key, OPTIONS)
    before = sorted(path.name for path in place.root.iterdir())
    own = place.projects / "own"
    kartograf.init_project(own, root=place.root)

    assert place.remove(key) == key

    assert _manifest(place.projects / "raba") == _manifest(own)
    assert sorted(path.name for path in place.root.iterdir()) == before
    with IndexQueries(place.index) as queries:
        record = queries.project(key, visible=ALL_PROJECTS)
    assert record is not None and record.tasks == ()


def test_an_invalid_option_is_kartografs_refusal_with_its_option(place: Place) -> None:
    """Kartograf's text is kept and its option is ``details.option``."""
    key = place.create("raba")
    asked = {**OPTIONS, "year": 1800}
    with pytest.raises(kartograf.KartografError) as own:
        kartograf.validate_command(COMMAND, asked, root=place.root)
    before = _manifest(place.projects / "raba")

    with pytest.raises(ProducerError) as refused:
        place.add(key, asked)

    assert refused.value.code == "validation_error"
    assert refused.value.details["option"] == "year"
    assert refused.value.message == kartograf.error_report(own.value).message
    assert _manifest(place.projects / "raba") == before


@pytest.mark.parametrize(
    ("name", "option"), [("Teren 1", "name"), (TASK, "name")], ids=["invalid", "taken"]
)
def test_kartograf_refuses_a_name_it_does_not_take(
    place: Place, name: str, option: str
) -> None:
    """An invalid or taken task name is Kartograf's refusal of ``name``."""
    key = place.create("raba")
    place.add(key, OPTIONS)
    before = _manifest(place.projects / "raba")

    with pytest.raises(ProducerError) as refused:
        place.add(key, OPTIONS, name=name)

    assert refused.value.details["option"] == option
    assert _manifest(place.projects / "raba") == before


def test_a_file_path_option_never_reaches_kartograf(place: Place) -> None:
    """Kartograf would open a geometry file in this process: it is refused first."""
    key = place.create("raba")

    with pytest.raises(PathOutsideRootError) as refused:
        place.add(key, {**OPTIONS, "geometry": "/etc/obszar.gpkg"})

    assert refused.value.details["option"] == "geometry"
    assert _manifest(place.projects / "raba")["tasks"] == []


def test_an_existing_project_is_refused_and_left_as_it_is(place: Place) -> None:
    """Kartograf refuses a second manifest in one directory."""
    key = place.create("raba")
    place.add(key, OPTIONS)
    before = _manifest(place.projects / "raba")

    with pytest.raises(ProducerError):
        place.create("raba")

    assert _manifest(place.projects / "raba") == before


def test_a_new_project_is_the_project_a_scan_finds(place: Place) -> None:
    """Four levels below a project directory: the next scan keeps it as it is."""
    assert MAX_PROJECT_DEPTH == 4
    key = place.create("a/b/c/raba")
    place.add(key, OPTIONS)

    with IndexWriter(place.index) as writer:
        summary = scan_projects(
            place.registry.adapter("kartograf"),
            writer,
            project_dirs=place.settings.project_dirs,
            stores=place.settings.stores,
        )

    assert (summary.found, summary.unchanged, summary.removed) == (1, 1, 0)
    with IndexQueries(place.index) as queries:
        listed = queries.projects(visible=ALL_PROJECTS)
    assert [
        (item.key, [m.store for m in item.manifests], item.tasks) for item in listed
    ] == [(key, [STORE], 1)]


@pytest.mark.parametrize("relative", ["a/b/c/d/raba", ".ukryty/raba"])
def test_a_project_a_scan_would_not_find_is_refused(
    place: Place, relative: str
) -> None:
    """Deeper than four levels, or in a hidden directory: no manifest is made."""
    with pytest.raises(CommandRequestError) as refused:
        place.create(relative)

    assert refused.value.details == {
        "reason": "project_not_discoverable",
        "option": "path",
    }
    assert not (place.projects / relative).exists()


def test_a_project_never_lies_in_a_store(tmp_path: Path) -> None:
    """A store inside the project directory is no place of a project."""
    place = _place(tmp_path)
    inner = place.projects / "magazyn"
    kartograf.init_store(inner)
    config = StoreConfig(id="drugi", name="Drugi", kartograf=inner, kind="local")
    settings = place.settings.model_copy(
        update={"stores": (*place.settings.stores, config)}
    )
    moved = Place(**{**vars(place), "settings": settings})

    with pytest.raises(CommandRequestError) as refused:
        moved.create("magazyn/raba")

    assert refused.value.details["reason"] == "project_not_discoverable"
    assert not (inner / "raba").exists()


@pytest.mark.parametrize(
    "asked",
    [
        lambda place: "raba",
        lambda place: str(place.projects.parent / "obcy"),
        lambda place: f"{place.projects}/../obcy",
    ],
    ids=["relative", "beside", "dot-dot"],
)
def test_a_project_outside_the_project_directories_is_refused(
    place: Place, asked: Callable[[Place], str]
) -> None:
    """A relative path and a path outside every project directory are refused."""
    path = asked(place)

    with pytest.raises(PathOutsideRootError) as refused:
        changes.create_project(
            place.registry,
            place.settings,
            place.index,
            place.authorizer,
            producer="kartograf",
            path=path,
            store=STORE,
            actor=LOCAL_OWNER,
        )

    assert refused.value.details == {"reason": "path_outside_root", "option": "path"}
    assert not (place.projects.parent / "obcy").exists()


def test_a_symbolic_link_out_of_the_project_directory_is_refused(
    place: Place, tmp_path: Path
) -> None:
    """A link below the project directory may not lead the manifest elsewhere."""
    outside = tmp_path / "obcy"
    outside.mkdir()
    (place.projects / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathOutsideRootError):
        place.create("link/raba")

    assert list(outside.iterdir()) == []


def test_a_store_that_cannot_be_read_now_gets_no_project(place: Place) -> None:
    """A disconnected share: no manifest, no store directory made in its place."""
    place.root.rename(place.root.with_name("odlaczony"))

    with pytest.raises(SourceUnavailableError) as refused:
        place.create("raba")

    assert refused.value.code == "store_unavailable"
    assert not place.root.exists()
    assert not (place.projects / "raba").exists()


@pytest.mark.parametrize(
    ("store", "error", "reason"),
    [
        ("nieznany", NotFoundError, None),
        ("imgw", CommandRequestError, "store_without_producer"),
    ],
)
def test_the_store_is_a_configured_store_of_the_producer(
    place: Place, tmp_path: Path, store: str, error: type[Exception], reason: str | None
) -> None:
    """A store that is not configured or has no Kartograf directory is refused."""
    other = StoreConfig(id="imgw", name="IMGW", imgw=tmp_path / "imgw", kind="local")
    settings = place.settings.model_copy(
        update={"stores": (*place.settings.stores, other)}
    )

    with pytest.raises(error) as refused:
        changes.create_project(
            place.registry,
            settings,
            place.index,
            place.authorizer,
            producer="kartograf",
            path=str(place.projects / "raba"),
            store=store,
            actor=LOCAL_OWNER,
        )

    if reason is not None:
        assert isinstance(refused.value, CommandRequestError)
        assert refused.value.details["reason"] == reason
    assert not (place.projects / "raba").exists()


def test_a_producer_that_changes_no_projects_is_unsupported(
    place: Place, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stand-in offers its commands, not the changes of its projects."""
    register_standin(monkeypatch)
    registry = load_registry(cache_dir=tmp_path / "standin-cache")

    with pytest.raises(UnsupportedError) as refused:
        changes.create_project(
            registry,
            place.settings,
            place.index,
            place.authorizer,
            producer="standin",
            path=str(place.projects / "raba"),
            store=STORE,
            actor=LOCAL_OWNER,
        )

    assert refused.value.details["reason"] == "no_project_actions"
    assert not (place.projects / "raba").exists()


def test_only_an_administrator_creates_a_project(place: Place) -> None:
    """A new project has no owner yet: ``project.write`` is an administrator's."""
    with pytest.raises(PermissionDeniedError):
        place.create("raba", actor=principal(place.state, "owner"))
    assert not (place.projects / "raba").exists()

    place.create("raba", actor=principal(place.state, "admin"))
    assert (place.projects / "raba" / MANIFEST).is_file()


@pytest.fixture(params=VISIBILITY_VALUES)
def shared(
    request: pytest.FixtureRequest, place: Place
) -> Iterator[tuple[str, Visibility]]:
    """Give a project with a task, shared with ``olga`` as its owner."""
    key = place.create("raba")
    place.add(key, OPTIONS)
    with IndexQueries(place.index) as queries:
        record = queries.project(key, visible=ALL_PROJECTS)
    assert record is not None
    share(place.state, record.project.access_key, request.param)
    yield key, request.param


@pytest.mark.parametrize("who", WHO)
def test_a_task_is_changed_by_the_owner_or_an_administrator(
    place: Place, shared: tuple[str, Visibility], who: Who
) -> None:
    """A hidden project is unknown (404); one seen but not owned is refused (403)."""
    key, visibility = shared
    actor = principal(place.state, who)
    before = _manifest(place.projects / "raba")
    expected: type[Exception] | None = None
    if who not in SEES[visibility]:
        expected = NotFoundError
    elif who not in MANAGES:
        expected = PermissionDeniedError

    if expected is None:
        place.remove(key, actor=actor)
        place.add(key, OPTIONS, actor=actor)
        assert _manifest(place.projects / "raba") == before
        return
    with pytest.raises(expected):
        place.remove(key, actor=actor)
    with pytest.raises(expected):
        place.add(key, OPTIONS, actor=actor, name="drugi")
    assert _manifest(place.projects / "raba") == before


def test_a_project_left_through_a_link_after_its_scan_is_not_changed(
    place: Place, tmp_path: Path
) -> None:
    """A project directory replaced by a link out of the project directories."""
    key = place.create("raba")
    moved = tmp_path / "obcy"
    os.rename(place.projects / "raba", moved)
    (place.projects / "raba").symlink_to(moved, target_is_directory=True)

    with pytest.raises(PathOutsideRootError):
        place.add(key, OPTIONS)

    assert _manifest(moved)["tasks"] == []
