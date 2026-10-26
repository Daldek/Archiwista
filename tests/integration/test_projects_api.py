"""Projects created and changed over HTTP and by commands (plan of 2026-10-25, A7).

``POST /projects``, ``POST /projects/{project}/tasks`` and ``DELETE
/projects/{project}/tasks/{name}`` with the real Kartograf adapter, offline,
over a marked Kartograf store and a project directory; ``archiwista
project-init``, ``project-add``, ``project-remove`` and ``project-status``
print the routes' models and refuse with the routes' problems. The service
behind both is ``tests/integration/test_project_changes.py``.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

import kartograf
import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.messages import message
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.network import no_network
from tests.fixtures.permissions import Who, add_people, principal, share

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
TASK_BODY: dict[str, Any] = {"name": TASK, "command": COMMAND, "options": OPTIONS}


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return an installation with a marked Kartograf store and a project directory."""
    root = tmp_path / "nas" / "kartograf"
    kartograf.init_store(root)
    _projects(tmp_path).mkdir()
    created = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    store = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="share")
    ConfigStore(created.config_file).save(
        AppSettings(stores=(store,), project_dirs=(_projects(tmp_path),))
    )
    initialize(created.index_file)
    with IndexWriter(created.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
    return created


def _projects(tmp_path: Path) -> Path:
    """Return the project directory of the settings."""
    return tmp_path / "nas" / "projekty"


@contextmanager
def _api(paths: AppPaths) -> Iterator[Api]:
    """Serve the API with the producers' plugins and the people of the tests."""
    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        add_people(api.state)
        yield api


def _cli(capsys: pytest.CaptureFixture[str], paths: AppPaths, *argv: str) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    status = main(
        [*argv, "--json"],
        registry=load_registry(cache_dir=paths.cache_dir),
        paths=paths,
    )
    captured = capsys.readouterr()
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, status)


def _project_body(directory: Path, **changed: str) -> dict[str, str]:
    """Return the body of ``POST /projects`` of a Kartograf project in ``directory``."""
    return {"producer": "kartograf", "path": str(directory), "store": STORE, **changed}


def _manifest(directory: Path) -> Any:
    return json.loads((directory / MANIFEST).read_text(encoding="utf-8"))


def test_a_project_is_created_and_its_tasks_changed_over_http(
    paths: AppPaths, tmp_path: Path
) -> None:
    """`201` with `Location`; every answer is the card the project then has.

    Kartograf writes the manifest; nothing reaches the network.
    """
    directory = _projects(tmp_path) / "raba"
    with _api(paths) as api, no_network() as attempts:
        owner = api.session(LOCAL_OWNER)

        # Act
        created = owner.request("POST", "/projects", json=_project_body(directory))
        key = created.json()["project"]
        new = owner.request("GET", f"/projects/{key}").json()
        added = owner.request("POST", f"/projects/{key}/tasks", json=TASK_BODY)
        with_task = owner.request("GET", f"/projects/{key}").json()
        written = _manifest(directory)
        removed = owner.request("DELETE", f"/projects/{key}/tasks/{TASK}")
        without = owner.request("GET", f"/projects/{key}").json()

    # Assert
    assert created.status_code == 201, created.text
    assert created.headers["location"] == f"/api/v1/projects/{key}"
    assert created.json() == new
    assert [(m["producer"], m["store"]) for m in new["manifests"]] == [
        ("kartograf", STORE)
    ]
    assert new["tasks"] == []
    assert added.status_code == 201, added.text
    assert added.json() == with_task
    assert [
        (task["producer"], task["task"], task["command"]) for task in with_task["tasks"]
    ] == [("kartograf", TASK, COMMAND)]
    assert with_task["tasks"][0]["options"] == written["tasks"][0]["options"]
    assert removed.status_code == 200, removed.text
    assert removed.json() == without
    assert without["tasks"] == []
    assert _manifest(directory)["tasks"] == []
    assert attempts == []


def test_the_commands_print_what_the_routes_answer(
    paths: AppPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--json` is the route's model; a relative directory is the current one's."""
    monkeypatch.chdir(_projects(tmp_path))
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        created = _cli(
            capsys, paths, "project-init", "kartograf", "raba", "--store", STORE
        )
        key = created["project"]
        new = owner.request("GET", f"/projects/{key}").json()
        options = json.dumps(OPTIONS)
        added = _cli(
            capsys, paths, "project-add", key, TASK, COMMAND, "--options", options
        )
        with_task = owner.request("GET", f"/projects/{key}").json()
        status = _cli(capsys, paths, "project-status", key)
        checked = owner.request("GET", f"/projects/{key}/status").json()
        removed = _cli(capsys, paths, "project-remove", key, TASK)
        without = owner.request("GET", f"/projects/{key}").json()

    # Assert
    assert (_projects(tmp_path) / "raba" / MANIFEST).is_file()
    assert created == new
    assert added == with_task
    assert [task["task"] for task in added["tasks"]] == [TASK]
    assert _unclocked(status) == _unclocked(checked)
    assert [
        (manifest["producer"], [task["task"] for task in manifest["tasks"]])
        for manifest in status["manifests"]
    ] == [("kartograf", [TASK])]
    assert removed == without
    assert removed["tasks"] == []


def _unclocked(status: dict[str, Any]) -> dict[str, Any]:
    """Return a project's status without the times its producers checked it."""
    manifests = [{**item, "checked_at": None} for item in status["manifests"]]
    return {**status, "manifests": manifests}


@pytest.mark.parametrize("token", ["startup", "agent"])
@pytest.mark.parametrize(
    ("who", "status"),
    [("owner", None), ("listed", 403), ("other", 404), ("admin", None)],
)
def test_a_task_is_changed_by_the_owner_or_an_administrator(
    paths: AppPaths,
    tmp_path: Path,
    who: Who,
    status: int | None,
    token: Literal["startup", "agent"],
) -> None:
    """Shared with listed people: they see it but may not change it (`403`).

    A person it is not shared with does not see it (`404`, as an unknown
    project); the owner and an administrator, also through an agent, change it.
    """
    # Arrange
    directory = _projects(tmp_path) / "raba"
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)
        key = owner.request("POST", "/projects", json=_project_body(directory))
        project = key.json()["project"]
        owner.request("POST", f"/projects/{project}/tasks", json=TASK_BODY)
        share(api.state, access_key(directory), "users")
        person = api.session(principal(api.state, who), token=token)

        # Act
        added = person.request(
            "POST", f"/projects/{project}/tasks", json={**TASK_BODY, "name": "drugi"}
        )
        removed = person.request("DELETE", f"/projects/{project}/tasks/{TASK}")

    # Assert
    names = [task["name"] for task in _manifest(directory)["tasks"]]
    if status is None:
        assert (added.status_code, removed.status_code) == (201, 200), added.text
        assert names == ["drugi"]
        return
    code = {403: "forbidden", 404: "not_found"}[status]
    assert_problem(added, status, code)
    assert_problem(removed, status, code)
    assert names == [TASK]


def _refused(
    case: str, tmp_path: Path, project: str
) -> tuple[str, str, dict[str, Any] | None, list[str]]:
    """Return a refused request: method, path, body, and the same command."""
    projects = _projects(tmp_path)
    created: dict[str, Callable[[Path], dict[str, str]]] = {
        "outside": lambda place: _project_body(tmp_path / "obcy"),
        "hidden": lambda place: _project_body(place / ".ukryty" / "raba"),
        "unknown_store": lambda place: _project_body(place / "nowy", store="nieznany"),
        "producer_without_projects": lambda place: _project_body(
            place / "nowy", producer="standin"
        ),
    }
    if case in created:
        body = created[case](projects)
        argv = [
            "project-init",
            body["producer"],
            body["path"],
            "--store",
            body["store"],
        ]
        return "POST", "/projects", body, argv
    tasks = {
        "invalid_year": {
            **TASK_BODY,
            "name": "drugi",
            "options": {**OPTIONS, "year": 1800},
        },
        "file_path": {
            **TASK_BODY,
            "name": "drugi",
            "options": {**OPTIONS, "geometry": "/etc/obszar.gpkg"},
        },
        "empty_name": {**TASK_BODY, "name": ""},
        "unknown_project": {**TASK_BODY, "name": "drugi"},
    }
    if case in tasks:
        task = tasks[case]
        key = "nieznany" if case == "unknown_project" else project
        argv = ["project-add", key, task["name"], task["command"]]
        argv += ["--options", json.dumps(task["options"])]
        return "POST", f"/projects/{key}/tasks", task, argv
    assert case == "unknown_task"
    return (
        "DELETE",
        f"/projects/{project}/tasks/brak",
        None,
        [
            "project-remove",
            project,
            "brak",
        ],
    )


@pytest.mark.parametrize(
    ("case", "status", "code", "reason", "option"),
    [
        ("outside", 403, "forbidden", "path_outside_root", "path"),
        ("hidden", 400, "validation_error", "project_not_discoverable", "path"),
        ("unknown_store", 404, "not_found", None, None),
        ("producer_without_projects", 422, "unsupported", "no_project_actions", None),
        ("invalid_year", 400, "validation_error", None, "year"),
        ("file_path", 403, "forbidden", "path_outside_root", "geometry"),
        ("empty_name", 400, "validation_error", "invalid_request", None),
        ("unknown_project", 404, "not_found", None, None),
        ("unknown_task", 400, "validation_error", None, "name"),
    ],
)
def test_a_refusal_is_the_same_by_the_api_and_the_command(
    paths: AppPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    status: int,
    code: str,
    reason: str | None,
    option: str | None,
) -> None:
    """The command's error document says what the route's problem says.

    Nothing is written: the project keeps its one task and no other directory
    is made.
    """
    # Arrange
    register_standin(monkeypatch)
    directory = _projects(tmp_path) / "raba"
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)
        project = owner.request("POST", "/projects", json=_project_body(directory))
        key = project.json()["project"]
        owner.request("POST", f"/projects/{key}/tasks", json=TASK_BODY)
        before = _manifest(directory)
        method, path, body, argv = _refused(case, tmp_path, key)

        # Act
        refused = owner.request(method, path, json=body)
        printed = _cli(capsys, paths, *argv)

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    if option is not None:
        assert refused.json()["details"]["option"] == option
    assert _manifest(directory) == before
    assert sorted(path.name for path in _projects(tmp_path).iterdir()) == ["raba"]
    assert not (tmp_path / "obcy").exists()


def test_a_refusal_is_explained_in_polish_on_request(
    paths: AppPaths, tmp_path: Path
) -> None:
    """`Accept-Language: pl` gives the Polish text of the catalog."""
    directory = _projects(tmp_path) / ".ukryty" / "raba"
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        refused = owner.request(
            "POST", "/projects", json=_project_body(directory), accept_language="pl"
        )

    # Assert
    assert_problem(refused, 400, "validation_error", "project_not_discoverable")
    assert refused.headers["content-language"] == "pl"
    assert refused.json()["detail"] == str(
        message("project.not_discoverable", "pl", path=directory, depth=4)
    )


def test_openapi_documents_creating_a_project_and_changing_its_tasks(
    paths: AppPaths,
) -> None:
    """The card is the answer of all three; refusals are problems, `422` too."""
    with _api(paths) as api:
        document = api.session(LOCAL_OWNER).request("GET", "/openapi.json").json()

    operations = {
        ("create_project", "201"): document["paths"]["/api/v1/projects"]["post"],
        ("add_project_task", "201"): document["paths"][
            "/api/v1/projects/{project}/tasks"
        ]["post"],
        ("remove_project_task", "200"): document["paths"][
            "/api/v1/projects/{project}/tasks/{name}"
        ]["delete"],
    }
    schemas = document["components"]["schemas"]
    for (name, success), operation in operations.items():
        responses = operation["responses"]
        assert operation["operationId"] == name
        assert responses[success]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ProjectCard"
        }
        assert {status for status in responses if int(status) >= 400} >= {
            "400",
            "401",
            "403",
            "404",
            "422",
            "503",
        }
        for status, response in responses.items():
            if int(status) >= 400:
                assert list(response["content"]) == ["application/problem+json"]
    bodies = [
        operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        for (name, _), operation in operations.items()
        if name != "remove_project_task"
    ]
    assert bodies == [
        "#/components/schemas/ProjectRequest",
        "#/components/schemas/TaskRequest",
    ]
    for model in ("ProjectRequest", "TaskRequest"):
        assert schemas[model]["examples"]
        assert schemas[model]["additionalProperties"] is False
