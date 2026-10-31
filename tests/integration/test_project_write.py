"""Whether a session may change each project, as the API says (plan 2026-10-25, A11).

``project_write`` of ``GET /projects``, ``GET /projects/{project}`` and the
projects of ``GET /stores/{store}``, over a project file naming Kartograf's
fixture store (``kartograf.testing``) shared with the listed person: its
owner and an administrator may change it, the listed person sees it and may
not, another person does not see it. Each answer equals what a route that
changes a project decides (``PUT /projects/{project}/stores/{producer}``:
``403 permission_denied``, else past the permission to the next refusal),
for sessions and agent tokens, and a change of the project's owner shows at
the next request. ``archiwista projects`` and ``project`` act as the owner
of the installation, who changes every project.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pytest
from kartograf.testing import build_fixture_store

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.index.projects import record_project
from archiwista.projects import ProjectDocument, StoreRoot, change_project_file
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.permissions import (
    LISTED,
    WHO,
    Who,
    add_people,
    principal,
    share,
)

STORE = "zespol"
# Of a project its owner shares with the listed person: who may change it,
# and None for who does not see it.
WRITES: dict[Who, bool | None] = {
    "owner": True,
    "listed": False,
    "other": None,
    "admin": True,
}
# A change refused after the permission: the store has no IMGW directory.
PROBE = "/projects/{key}/stores/imgw"


@dataclass(frozen=True)
class Place:
    """An installation with a project of Kartograf's store recorded in its index."""

    paths: AppPaths
    directory: Path
    key: str


@pytest.fixture
def place(tmp_path: Path) -> Place:
    """Give a project of a configured store, recorded as a scan reads it."""
    built = build_fixture_store(tmp_path / "nas" / "kartograf")
    projects = tmp_path / "nas" / "projekty"
    directory = projects / "raba"
    directory.mkdir(parents=True)
    change_project_file(
        directory,
        create=ProjectDocument(
            name="raba",
            description="",
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            created_by="local",
            stores=(StoreRoot("kartograf", str(built.root)),),
        ),
    )
    config = StoreConfig(id=STORE, name="Zespół", kartograf=built.root, kind="local")
    settings = AppSettings(stores=(config,), project_dirs=(projects,))
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    ConfigStore(paths.config_file).save(settings)
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        key = record_project(writer, directory, stores=settings.stores, geo=None)
    return Place(paths, directory, key)


def _said(caller: Caller, key: str) -> dict[str, Any]:
    """Return what the list, the card and the store say of the project."""
    listed = caller.request("GET", "/projects").json()["items"]
    card = caller.request("GET", f"/projects/{key}")
    store = caller.request("GET", f"/stores/{STORE}").json()["projects"]
    return {
        "list": [item["project_write"] for item in listed if item["project"] == key],
        "card": card.json()["project_write"] if card.status_code == 200 else None,
        "store": [item["project_write"] for item in store if item["project"] == key],
    }


def _probe(caller: Caller, key: str) -> Any:
    """Ask for a change of the project that is refused after the permission."""
    return caller.request("PUT", PROBE.format(key=key), json={"store": STORE})


@pytest.mark.parametrize("token", ["startup", "agent"])
@pytest.mark.parametrize("who", WHO)
def test_project_write_says_what_a_change_of_the_project_meets(
    place: Place, who: Who, token: Literal["startup", "agent"]
) -> None:
    """The owner and an administrator may, the listed person may not, the rest see none.

    The change probed names a producer the store has no directory of, so a
    person past the permission meets that check (`400
    store_without_producer`) and nothing changes.
    """
    registry = load_registry(cache_dir=place.paths.cache_dir)
    with running_api(place.paths, registry) as api:
        add_people(api.state)
        share(api.state, access_key(place.directory), "users")
        person = api.session(principal(api.state, who), token=token)

        # Act
        said = _said(person, place.key)
        probe = _probe(person, place.key)

    # Assert
    writes = WRITES[who]
    if writes is None:
        assert said == {"list": [], "card": None, "store": []}
        assert_problem(probe, 404, "not_found")
        return
    assert said == {"list": [writes], "card": writes, "store": [writes]}
    if writes:
        assert_problem(probe, 400, "validation_error", "store_without_producer")
    else:
        assert_problem(probe, 403, "forbidden", "permission_denied")


def test_project_write_follows_the_owner_at_the_next_request(place: Place) -> None:
    """Made the owner, the listed person may change the project at once."""
    registry = load_registry(cache_dir=place.paths.cache_dir)
    with running_api(place.paths, registry) as api:
        add_people(api.state)
        share(api.state, access_key(place.directory), "users")
        listed = api.session(principal(api.state, "listed"))
        before = _said(listed, place.key)

        # Act
        api.state.set_project_access(
            access_key(place.directory),
            owner=LISTED,
            visibility="private",
            actor=LOCAL_OWNER,
        )
        after = _said(listed, place.key)
        probe = _probe(listed, place.key)

    # Assert
    assert before == {"list": [False], "card": False, "store": [False]}
    assert after == {"list": [True], "card": True, "store": [True]}
    assert_problem(probe, 400, "validation_error", "store_without_producer")


@pytest.mark.parametrize("command", ["projects", "project"])
def test_the_commands_print_the_owner_of_the_installation_may_change_it(
    place: Place, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    """`archiwista projects` and `project` act as the local owner, an administrator."""
    registry = load_registry(cache_dir=place.paths.cache_dir)
    argv = ["projects"] if command == "projects" else ["project", place.key]

    # Act
    status = main([*argv, "--json"], registry=registry, paths=place.paths)

    # Assert
    assert status == 0
    printed = json.loads(capsys.readouterr().out)
    items = printed["items"] if command == "projects" else [printed]
    assert [item["project_write"] for item in items] == [True]
