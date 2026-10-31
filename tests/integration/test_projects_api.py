"""Projects created and changed over HTTP and by commands (A-ADR-049, plan P2).

``POST /projects``, ``PATCH /projects/{project}``, ``PUT …/area`` and ``PUT
…/stores/{producer}`` write Archiwista's project file over a marked
Kartograf store and a project directory; ``archiwista project-init``,
``project-edit``, ``project-area`` and ``project-store`` print the routes'
models and refuse with the routes' problems. Who may change a project
follows its sharing; a lock another change holds is ``409 project_locked``.
"""

import functools
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import kartograf
import pytest

from archiwista.auth import LOCAL_OWNER, access_key
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.index import IndexWriter, initialize
from archiwista.index.types import AreaRecord
from archiwista.messages import message
from archiwista.projects import (
    LOCK_NAME,
    LOCK_OWNER,
    PROJECT_FILE,
    change_project_file,
)
from archiwista.services import projects as project_service
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import Api, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.permissions import Who, add_people, principal, share

STORE = "zespol"
# About 7 km × 11 km near Kraków, an area of the index.
AREA = AreaRecord(
    id="0123456789abcdef",
    source="drawn",
    geometry={
        "type": "Polygon",
        "coordinates": [
            [[19.0, 50.0], [19.1, 50.0], [19.1, 50.1], [19.0, 50.1], [19.0, 50.0]]
        ],
    },
    created_at=datetime(2026, 10, 1, tzinfo=UTC),
    area_km2=79.5,
    countries=("PL",),
    name="Kraków",
)


def _projects(tmp_path: Path) -> Path:
    """Return the project directory of the settings."""
    return tmp_path / "nas" / "projekty"


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Return an installation with a marked Kartograf store and a project directory.

    The settings also name a project directory that does not exist
    (``brak``); the index keeps the area ``AREA``.
    """
    root = tmp_path / "nas" / "kartograf"
    kartograf.init_store(root)
    _projects(tmp_path).mkdir()
    created = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    store = StoreConfig(id=STORE, name="Zespół", kartograf=root, kind="share")
    ConfigStore(created.config_file).save(
        AppSettings(
            stores=(store,),
            project_dirs=(_projects(tmp_path), tmp_path / "nas" / "brak"),
        )
    )
    initialize(created.index_file)
    with IndexWriter(created.index_file) as writer:
        writer.sync_stores({STORE: store.roots()})
        writer.write_area(AREA)
    return created


@pytest.fixture(autouse=True)
def short_lock_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wait 0.2 s for a held lock instead of 5 s."""
    quick = functools.partial(change_project_file, wait_s=0.2)
    monkeypatch.setattr(project_service, "change_project_file", quick)


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


def _file(directory: Path) -> Any:
    return json.loads((directory / PROJECT_FILE).read_text(encoding="utf-8"))


def test_a_project_is_created_and_changed_over_http(
    paths: AppPaths, tmp_path: Path
) -> None:
    """`201` with `Location`; every answer is the card the project then has."""
    directory = _projects(tmp_path) / "raba"
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        created = owner.request(
            "POST",
            "/projects",
            json={"path": str(directory), "name": "Raba", "description": "Zlewnia"},
        )
        key = created.json()["project"]
        edited = owner.request(
            "PATCH", f"/projects/{key}", json={"description": "Zlewnia Raby"}
        )
        area = owner.request("PUT", f"/projects/{key}/area", json={"area_id": AREA.id})
        store = owner.request(
            "PUT", f"/projects/{key}/stores/kartograf", json={"store": STORE}
        )
        card = owner.request("GET", f"/projects/{key}").json()
        cleared = owner.request("PUT", f"/projects/{key}/area", json={"area_id": None})

    # Assert
    assert created.status_code == 201, created.text
    assert created.headers["location"] == f"/api/v1/projects/{key}"
    assert (key, created.json()["name"], created.json()["stores"]) == (
        "raba",
        "Raba",
        [],
    )
    assert edited.json()["description"] == "Zlewnia Raby"
    chosen = area.json()["area"]
    assert (chosen["path"], chosen["state"]) == (f"obszary/{AREA.id}.geojson", "ok")
    # The file's copy is read back into an area of the index of its own.
    assert chosen["area_id"] is not None
    root = str(tmp_path / "nas" / "kartograf")
    assert store.json()["stores"] == [
        {"producer": "kartograf", "root": root, "store": STORE}
    ]
    assert store.json() == card
    assert (cleared.status_code, cleared.json()["area"]) == (200, None)
    assert (directory / "obszary" / f"{AREA.id}.geojson").is_file()
    written = _file(directory)
    assert (written["schema"], written["name"], written["description"]) == (
        "archiwista-project/1",
        "Raba",
        "Zlewnia Raby",
    )
    assert written.get("area") is None


def test_the_commands_print_what_the_routes_answer(
    paths: AppPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--json` is the route's model; a relative directory is the current one's."""
    monkeypatch.chdir(_projects(tmp_path))

    # Act
    created = _cli(capsys, paths, "project-init", "raba", "--description", "Z")
    key = created["project"]
    edited = _cli(capsys, paths, "project-edit", key, "--name", "Raba")
    area = _cli(capsys, paths, "project-area", key, "--area-id", AREA.id)
    store = _cli(capsys, paths, "project-store", key, "kartograf", "--store", STORE)
    with _api(paths) as api:
        card = api.session(LOCAL_OWNER).request("GET", f"/projects/{key}").json()
    cleared = _cli(capsys, paths, "project-area", key, "--clear")

    # Assert
    assert (key, created["path"]["local"]) == (
        "raba",
        str(_projects(tmp_path) / "raba"),
    )
    assert (created["description"], edited["name"]) == ("Z", "Raba")
    assert area["area"]["path"] == f"obszary/{AREA.id}.geojson"
    assert [item["store"] for item in store["stores"]] == [STORE]
    assert store == card
    assert cleared["area"] is None


@pytest.mark.parametrize("token", ["startup", "agent"])
@pytest.mark.parametrize(
    ("who", "status"),
    [("owner", None), ("listed", 403), ("other", 404), ("admin", None)],
)
def test_a_project_is_changed_by_the_owner_or_an_administrator(
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
        owner.request("POST", "/projects", json={"path": str(directory)})
        share(api.state, access_key(directory), "users")
        person = api.session(principal(api.state, who), token=token)

        # Act
        answers = [
            person.request("PATCH", "/projects/raba", json={"description": "D"}),
            person.request("PUT", "/projects/raba/area", json={"area_id": AREA.id}),
            person.request(
                "PUT", "/projects/raba/stores/kartograf", json={"store": STORE}
            ),
        ]

    # Assert
    written = _file(directory)
    if status is None:
        assert [answer.status_code for answer in answers] == [200, 200, 200]
        assert (written["description"], len(written["stores"])) == ("D", 1)
        return
    code = {403: "forbidden", 404: "not_found"}[status]
    for answer in answers:
        assert_problem(answer, status, code)
    assert (written["description"], written.get("area"), written["stores"]) == (
        "",
        None,
        [],
    )


def _hold_lock(directory: Path) -> None:
    """Hold the project's lock as another computer's change would."""
    lock = directory / LOCK_NAME
    lock.mkdir()
    (lock / LOCK_OWNER).write_text("nas_4242 2026-10-31T12:00:00Z\n", encoding="utf-8")


def _break(directory: Path) -> None:
    """Break a rule of the project file by hand."""
    data = _file(directory)
    data["name"] = ""
    (directory / PROJECT_FILE).write_text(json.dumps(data), encoding="utf-8")


# A refused request: method, path, body and the same command, by project key.
_REFUSED: dict[str, tuple[str, str, dict[str, Any], list[str]]] = {
    "outside": ("POST", "/projects", {"path": "{tmp}/obcy"}, ["project-init"]),
    "hidden": (
        "POST",
        "/projects",
        {"path": "{projects}/.ukryty/nowy"},
        ["project-init"],
    ),
    "dir_missing": ("POST", "/projects", {"path": "{tmp}/nas/brak/nowy"}, []),
    "unknown_area": (
        "POST",
        "/projects",
        {"path": "{projects}/nowy", "area_id": "brak"},
        [],
    ),
    "exists": ("POST", "/projects", {"path": "{projects}/raba"}, []),
    "empty_name": ("PATCH", "/projects/raba", {"name": ""}, []),
    "unknown_project": ("PATCH", "/projects/brak", {"description": "D"}, []),
    "unknown_store": ("PUT", "/projects/raba/stores/kartograf", {"store": "brak"}, []),
    "store_without_producer": (
        "PUT",
        "/projects/raba/stores/imgw",
        {"store": STORE},
        [],
    ),
    "locked": ("PATCH", "/projects/raba", {"description": "D"}, []),
    "invalid_file": ("PATCH", "/projects/raba", {"description": "D"}, []),
}


def _argv(method: str, path: str, body: dict[str, Any]) -> list[str]:
    """Return the command of a request of ``_REFUSED``."""
    if method == "POST":
        argv = ["project-init", body["path"]]
        if "area_id" in body:
            argv += ["--area-id", body["area_id"]]
        return argv
    key = path.split("/")[2]
    if method == "PATCH":
        options = [(f"--{name}", value) for name, value in body.items()]
        return ["project-edit", key, *[item for pair in options for item in pair]]
    producer = path.split("/")[-1]
    return ["project-store", key, producer, "--store", body["store"]]


@pytest.mark.parametrize(
    ("case", "status", "code", "reason"),
    [
        ("outside", 403, "forbidden", "path_outside_root"),
        ("hidden", 400, "validation_error", "project_not_discoverable"),
        ("dir_missing", 400, "validation_error", "project_dir_missing"),
        ("unknown_area", 404, "not_found", None),
        ("exists", 409, "conflict", "project_exists"),
        ("empty_name", 400, "validation_error", "invalid_request"),
        ("unknown_project", 404, "not_found", None),
        ("unknown_store", 404, "not_found", None),
        ("store_without_producer", 400, "validation_error", "store_without_producer"),
        ("locked", 409, "conflict", "project_locked"),
        ("invalid_file", 409, "conflict", "invalid_project_file"),
    ],
)
def test_a_refusal_is_the_same_by_the_api_and_the_command(
    paths: AppPaths,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
    status: int,
    code: str,
    reason: str | None,
) -> None:
    """The command's error document says what the route's problem says.

    Nothing is written: the project file stays as it was and no other
    directory is made.
    """
    # Arrange
    directory = _projects(tmp_path) / "raba"
    method, path, template, _ = _REFUSED[case]
    places = {"tmp": str(tmp_path), "projects": str(_projects(tmp_path))}
    body = {
        name: value.format(**places) if isinstance(value, str) else value
        for name, value in template.items()
    }
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)
        created = owner.request("POST", "/projects", json={"path": str(directory)})
        assert created.status_code == 201, created.text
        if case == "locked":
            _hold_lock(directory)
        if case == "invalid_file":
            _break(directory)
        before = (directory / PROJECT_FILE).read_bytes()

        # Act
        refused = owner.request(method, path, json=body)
        printed = _cli(capsys, paths, *_argv(method, path, body))

    # Assert
    assert_problem(refused, status, code, reason)
    assert_same_error(printed, refused.json())
    assert (directory / PROJECT_FILE).read_bytes() == before
    assert sorted(item.name for item in _projects(tmp_path).iterdir()) == ["raba"]
    assert not (tmp_path / "obcy").exists()
    if case == "locked":
        assert refused.json()["details"]["lock"] == str(directory / LOCK_NAME)
        assert refused.json()["details"]["owner"] == "nas_4242"


def test_a_project_directory_that_cannot_be_written_is_an_io_error(
    paths: AppPaths, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`500 io_error` (`project_file_write_failed`) by the route and the command."""
    projects = _projects(tmp_path)
    body = {"path": str(projects / "raba")}
    projects.chmod(0o555)
    try:
        with _api(paths) as api:
            # Act
            refused = api.session(LOCAL_OWNER).request("POST", "/projects", json=body)
            printed = _cli(capsys, paths, "project-init", body["path"])
    finally:
        projects.chmod(0o755)

    # Assert
    assert_problem(refused, 500, "io_error", "project_file_write_failed")
    assert_same_error(printed, refused.json())


def test_a_refusal_is_explained_in_polish_on_request(
    paths: AppPaths, tmp_path: Path
) -> None:
    """`Accept-Language: pl` gives the Polish text of the catalog."""
    directory = _projects(tmp_path) / ".ukryty" / "raba"
    with _api(paths) as api:
        owner = api.session(LOCAL_OWNER)

        # Act
        refused = owner.request(
            "POST", "/projects", json={"path": str(directory)}, accept_language="pl"
        )

    # Assert
    assert_problem(refused, 400, "validation_error", "project_not_discoverable")
    assert refused.headers["content-language"] == "pl"
    assert refused.json()["detail"] == str(
        message("project.not_discoverable", "pl", path=directory, depth=4)
    )


def test_openapi_documents_creating_and_changing_a_project(paths: AppPaths) -> None:
    """The card answers all four; refusals are problems, `409` and `500` too."""
    with _api(paths) as api:
        document = api.session(LOCAL_OWNER).request("GET", "/openapi.json").json()

    routes = document["paths"]
    operations = {
        ("create_project", "201", "ProjectRequest"): routes["/api/v1/projects"]["post"],
        ("update_project", "200", "ProjectChange"): routes[
            "/api/v1/projects/{project}"
        ]["patch"],
        ("set_project_area", "200", "AreaChoice"): routes[
            "/api/v1/projects/{project}/area"
        ]["put"],
        ("set_project_store", "200", "StoreChoice"): routes[
            "/api/v1/projects/{project}/stores/{producer}"
        ]["put"],
    }
    schemas = document["components"]["schemas"]
    for (name, success, model), operation in operations.items():
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
            "409",
            "500",
        }
        for status, response in responses.items():
            if int(status) >= 400:
                assert list(response["content"]) == ["application/problem+json"]
        body = operation["requestBody"]["content"]["application/json"]["schema"]
        assert body == {"$ref": f"#/components/schemas/{model}"}
        assert schemas[model]["examples"]
        assert schemas[model]["additionalProperties"] is False
    assert "project_locked" in str(
        operations[("update_project", "200", "ProjectChange")]["responses"]["409"]
    )
