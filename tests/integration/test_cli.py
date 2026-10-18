"""The command line next to the HTTP API: the same models over the same data.

``archiwista … --json`` must print exactly what the matching route answers,
refusals included, so scripts and agents can use either (A-ADR-029, step
12).
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.index import IndexWriter, ManifestStamp
from archiwista.sources import ProjectInfo
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths


@pytest.fixture
def api(tmp_path: Path) -> Iterator[Api]:
    """Serve an index with the project ``raba`` and an empty state database."""
    paths = local_paths(tmp_path)
    with running_api(paths) as served:
        with IndexWriter(paths.index_file) as writer:
            writer.sync_stores({STORE: {PRODUCER: ROOT}})
            project = ProjectInfo(PRODUCER, ROOT, Path("/projekty/raba"), "Raba")
            writer.write_project(project, store=STORE, stamp=ManifestStamp(1, 1))
        yield served


class _Cli:
    """Run ``archiwista`` with ``--json`` over the served data."""

    def __init__(self, api: Api, capsys: pytest.CaptureFixture[str]) -> None:
        self._paths = api.paths
        self._capsys = capsys

    def __call__(self, *argv: str, status: int = 0) -> object:
        self._capsys.readouterr()
        assert main([*argv, "--json"], paths=self._paths) == status
        out = self._capsys.readouterr().out
        return json.loads(out) if out else None


def _item(listing: object, key: str) -> object:
    assert isinstance(listing, dict)
    return next(item for item in listing["items"] if item["id"] == key)


def test_admin_cli_json_equals_http(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    """Accounts, groups and sharing read the same through either door."""
    # Arrange
    cli = _Cli(api, capsys)
    local = api.session(LOCAL_OWNER)

    def get(path: str) -> object:
        return local.request("GET", path).json()

    # Act
    pairs: list[tuple[object, object]] = []
    added = cli("users", "add", "anna.nowak", "--name", "Anna Nowak", "--role", "admin")
    pairs.append((added, _item(get("/users"), "anna.nowak")))
    posted = local.request("POST", "/users", json={"id": "jan", "name": "Jan"})
    pairs.append((_item(cli("users", "list"), "jan"), posted.json()))
    pairs.append(
        (cli("users", "roles", "jan", "store_writer"), _item(get("/users"), "jan"))
    )
    group = cli("groups", "add", "hydro", "--name", "Hydrologia", "--member", "jan")
    pairs.append((group, _item(get("/groups"), "hydro")))
    members = local.request(
        "PUT", "/groups/hydro/members", json={"members": ["anna.nowak", "jan"]}
    )
    pairs.append((_item(cli("groups", "list"), "hydro"), members.json()))
    shown = cli("share", "raba")
    pairs.append((shown, get("/projects/raba/access")))
    shared = cli(
        "share", "raba", "--visibility", "group", "--group", "hydro", "--owner", "jan"
    )
    pairs.append((shared, get("/projects/raba/access")))
    put = local.request(
        "PUT", "/projects/raba/access", json={"visibility": "users", "users": ["jan"]}
    )
    pairs.append((cli("share", "raba"), put.json()))
    pairs.append((cli("users", "list"), get("/users")))
    pairs.append((cli("groups", "list"), get("/groups")))
    removed = cli("users", "remove", "anna.nowak")
    pairs.append((cli("users", "list"), get("/users")))
    pairs.append((cli("groups", "list"), get("/groups")))

    # Assert
    for from_cli, from_http in pairs:
        assert from_cli == from_http
    assert removed is None
    assert {change.actor for change in api.state.changes()} == {"local"}


@pytest.mark.parametrize(
    ("argv", "method", "path", "body"),
    [
        (("users", "add", "local"), "POST", "/users", {"id": "local"}),
        (
            ("users", "roles", "nikt", "admin"),
            "PATCH",
            "/users/nikt",
            {"roles": ["admin"]},
        ),
        (
            ("groups", "members", "nic", "nikt"),
            "PUT",
            "/groups/nic/members",
            {"members": ["nikt"]},
        ),
        (("share", "nie-ma"), "GET", "/projects/nie-ma/access", None),
        (
            ("share", "raba", "--visibility", "users"),
            "PUT",
            "/projects/raba/access",
            {"visibility": "users"},
        ),
    ],
)
def test_admin_cli_refusal_equals_http_problem(
    api: Api,
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    method: str,
    path: str,
    body: object,
) -> None:
    """A refused command prints the API's problem and exits with status 1."""
    # Arrange
    cli = _Cli(api, capsys)
    local: Caller = api.session(LOCAL_OWNER)

    # Act
    printed = cli(*argv, status=1)
    answered = local.request(method, path, json=body)

    # Assert
    assert printed == answered.json()


def test_admin_cli_taken_id_is_a_conflict(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adding an existing group again is ``409 conflict`` on both doors."""
    # Arrange
    cli = _Cli(api, capsys)
    local = api.session(LOCAL_OWNER)
    cli("groups", "add", "hydro")

    # Act
    printed = cli("groups", "add", "hydro", status=1)
    answered = local.request("POST", "/groups", json={"id": "hydro"})

    # Assert
    assert answered.status_code == 409
    assert printed == answered.json()
