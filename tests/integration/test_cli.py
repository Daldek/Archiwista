"""The command line next to the HTTP API: the same models over the same data.

``archiwista … --json`` must print exactly what the matching route answers,
refusals included, so scripts and agents can use either (A-ADR-029, step
12).
"""

import argparse
import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.index import IndexWriter, ManifestStamp
from archiwista.reader import add_read_commands
from archiwista.security import redeem_one_time_token
from archiwista.sources import ProjectInfo
from tests.fixtures import api_store
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.api_store import ServedStore, served_store
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.local_server import local_paths
from tests.fixtures.preview_api import (
    PreviewApi,
    decoded_png,
    entry_of,
    preview_api,
    version_url,
)

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")
KRAKOW = "19.9,50.0,20.0,50.05"


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


# Read commands over a scanned store (step 12).


@pytest.fixture(scope="module")
def served(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedStore]:
    """Serve one scanned store for the read commands."""
    with served_store(tmp_path_factory.mktemp("cli")) as found:
        yield found


class _Reader:
    """Run a read command with ``--json`` and the HTTP route it mirrors."""

    def __init__(self, served: ServedStore, capsys: pytest.CaptureFixture[str]):
        self._served = served
        self._capsys = capsys

    def cli(self, *argv: str, status: int = 0) -> Any:
        self._capsys.readouterr()
        code = main(
            [*argv, "--json"],
            registry=self._served.registry,
            paths=self._served.api.paths,
        )
        captured = self._capsys.readouterr()
        assert code == status, captured.err
        return json.loads(captured.out)

    def http(self, path: str, status: int = 200) -> Any:
        response = self._served.owner.request("GET", path)
        assert response.status_code == status, response.text
        return response.json()


def _search_argv(params: dict[str, str]) -> list[str]:
    """Return ``search`` arguments of ``/slots`` parameters (``q`` positional)."""
    argv = ["search"]
    if "q" in params:
        argv.append(params["q"])
    argv += [
        f"--{name.replace('_', '-')}={value}"
        for name, value in params.items()
        if name != "q"
    ]
    return argv


def test_search_options_match_slots_parameters(served: ServedStore) -> None:
    """``search`` has exactly one option per ``/slots`` parameter, of its name."""
    # Arrange
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command")
    add_read_commands(commands)
    document = served.owner.request("GET", "/openapi.json").json()
    parameters = {
        item["name"] for item in document["paths"]["/api/v1/slots"]["get"]["parameters"]
    }

    # Act
    search = parser.parse_args(["search"])
    options = {
        action.dest: action.option_strings
        for action in commands.choices["search"]._actions
        if action.dest not in {"help", "json"}
    }

    # Assert
    assert set(options) == parameters
    assert options.pop("q") == []  # the positional QUERY
    for name, strings in options.items():
        assert strings == [f"--{name.replace('_', '-')}"]
        assert getattr(search, name) is None  # the model's default applies


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"versions": "all", "limit": "7"},
        {"product": "nmt", "years": "2019-2021", "versions": "all", "limit": "4"},
        {"q": "nmt", "status": "ok", "limit": "5"},
        {"location": "none", "store": "zespol"},
        {"bbox": KRAKOW, "location": "with", "limit": "3"},
        {"versions": "noncurrent_unpinned", "limit": "200"},
    ],
)
def test_search_cli_equals_http(
    served: ServedStore, capsys: pytest.CaptureFixture[str], params: dict[str, str]
) -> None:
    """Every page of a query, followed by its cursor, is the same on both doors."""
    # Arrange
    run = _Reader(served, capsys)
    pages: list[tuple[Any, Any]] = []
    cursor: dict[str, str] = {}

    # Act
    while len(pages) < 20:
        query = {**params, **cursor}
        pair = (run.cli(*_search_argv(query)), run.http(f"/slots?{urlencode(query)}"))
        pages.append(pair)
        if pair[1]["next_cursor"] is None:
            break
        cursor = {"cursor": pair[1]["next_cursor"]}

    # Assert
    assert pages[-1][1]["next_cursor"] is None
    for from_cli, from_http in pages:
        assert from_cli == from_http
    assert any(page["items"] for _, page in pages) or params.get("location")


@pytest.mark.parametrize(
    "params",
    [
        {"limit": "201"},
        {"limit": "dużo"},
        {"years": "2022-2020"},
        {"years": "rok"},
        {"store": "brak"},
        {"bbox": "1,2,3"},
        {"product": "nmt", "cursor": "obcy"},
    ],
)
def test_search_cli_refusal_equals_http_problem(
    served: ServedStore, capsys: pytest.CaptureFixture[str], params: dict[str, str]
) -> None:
    """Invalid options print the route's ``422`` problem and exit with status 1."""
    # Arrange
    run = _Reader(served, capsys)

    # Act
    printed = run.cli(*_search_argv(params), status=1)
    answered = run.http(f"/slots?{urlencode(params)}", status=422)

    # Assert
    assert printed == answered
    assert printed["code"] == "validation_error"


def test_search_cursor_of_another_query_refused(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cursor is bound to its query on both doors."""
    # Arrange
    run = _Reader(served, capsys)
    cursor = run.cli("search", "--limit=3")["next_cursor"]

    # Act
    printed = run.cli("search", "--product=nmt", f"--cursor={cursor}", status=1)
    answered = run.http(f"/slots?product=nmt&cursor={cursor}", status=422)

    # Assert
    assert printed == answered


def test_status_json_equals_health(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """``status --json`` is ``GET /health``; ``sources --json`` is ``/sources``."""
    # Arrange
    run = _Reader(served, capsys)

    # Act
    status = run.cli("status")
    health = run.http("/health")
    sources = run.cli("sources")

    # Assert
    assert status == health
    assert status["stores"][0]["state"]["slots"] > 0
    assert sources == run.http("/sources")


def test_status_shows_last_full_scan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``/health``, ``status --json`` and ``status`` show the last full scan."""
    # Arrange
    full_at = datetime.fromisoformat("2026-10-18T03:14:07+00:00")
    with served_store(tmp_path, slots=17) as served:
        run = _Reader(served, capsys)
        before = run.cli("status")["stores"][0]["state"]["full_scan_at"]
        with sqlite3.connect(served.api.paths.index_file) as connection:
            connection.execute(
                "INSERT INTO jobs (id, kind, actor, actor_kind, store, params,"
                " state, created_at, finished_at) VALUES ('j1', 'scan',"
                " 'scheduler', 'scheduler', ?, '{\"mode\": \"full\"}',"
                " 'succeeded', '2026-10-18T03:00:00+00:00', ?)",
                (api_store.STORE, full_at.isoformat()),
            )
        connection.close()

        # Act
        status = run.cli("status")
        health = run.http("/health")
        capsys.readouterr()
        code = main(["status"], registry=served.registry, paths=served.api.paths)
        text = capsys.readouterr().out

    # Assert
    shown = status["stores"][0]["state"]["full_scan_at"]
    assert before is None
    assert status == health
    assert datetime.fromisoformat(shown) == full_at
    stamp = full_at.astimezone().strftime("%Y-%m-%d %H:%M")
    assert code == 0 and f"ostatni pełny skan: {stamp}." in text


def test_entry_json_equals_slot_card(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """File, version and project cards are the routes' models; unknown is 404."""
    # Arrange
    run = _Reader(served, capsys)
    store = api_store.STORE
    slot = run.http("/slots?versions=all&limit=1")["items"][0]["slot"]
    projects = run.http("/projects")
    project = projects["items"][0]["project"]

    # Act
    entry = run.cli("entry", store, slot)
    version = run.cli("version", store, entry["current"])
    missing = run.cli("entry", store, "nie/ma.tif", status=1)

    # Assert
    assert entry == run.http(f"/stores/{store}/slots/{slot}")
    assert entry["versions"]
    path = entry["current"]
    assert version == run.http(f"/stores/{store}/versions/{path}")
    assert missing == run.http(f"/stores/{store}/slots/nie/ma.tif", status=404)
    assert missing["code"] == "not_found"
    assert run.cli("projects") == projects
    assert run.cli("projects", "--store", store) == run.http(f"/projects?store={store}")
    assert run.cli("project", project) == run.http(f"/projects/{project}")


def test_read_commands_text_for_people(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without ``--json`` the commands print Polish text, problems on stderr."""
    # Arrange
    paths = served.api.paths

    def text(*argv: str) -> tuple[int, str, str]:
        capsys.readouterr()
        code = main(list(argv), registry=served.registry, paths=paths)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    # Act
    status = text("status")
    page = text("search", "--limit=2")
    refused = text("search", "--limit=0")

    # Assert
    assert status[0] == 0 and "Magazyn „zespol”" in status[1]
    assert "ostatni pełny skan: brak." in status[1]
    assert page[0] == 0 and "Następna strona: --cursor " in page[1]
    assert refused[0] == 1 and refused[1] == ""
    assert "query.limit" in refused[2]


def test_token_is_one_time_and_expires(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """``token --json`` gives one session to an agent, for five minutes only."""
    # Arrange
    run = _Reader(served, capsys)
    client = served.api.client

    # Act
    issued = run.cli("token")
    first = client.post("/api/v1/session", json={"token": issued["token"]})
    client.cookies.clear()
    second = client.post("/api/v1/session", json={"token": issued["token"]})
    late = run.cli("token")
    expires_at = datetime.fromisoformat(late["expires_at"])
    expired = redeem_one_time_token(
        served.api.paths.index_file,
        late["token"],
        now=expires_at,
    )
    in_time = redeem_one_time_token(
        served.api.paths.index_file,
        late["token"],
        now=expires_at - timedelta(seconds=1),
    )

    # Assert
    assert issued["url"].startswith("http://127.0.0.1:")
    assert issued["url"].endswith(f"/#token={issued['token']}")
    assert first.status_code == 200 and first.json()["actor"] == "local"
    assert second.status_code == 401
    assert second.json()["code"] == "session_required"
    assert expired is None and in_time is not None
    assert in_time.principal_id == "local"


def test_compare_cli_equals_http(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """``compare --json`` is ``GET /compare``, refusals too; text marks differences."""
    # Arrange
    run = _Reader(served, capsys)
    slots: dict[str, list[str]] = {}
    for item in run.http("/slots?versions=all&limit=200")["items"]:
        slots.setdefault(item["slot"], []).append(item["version"]["ref"])
    a, b = next(refs for refs in slots.values() if len(refs) > 1)[:2]
    missing = f"version:{api_store.STORE}:nie/ma.tif"

    # Act
    compared = run.cli("compare", a, b)
    unknown = run.cli("compare", a, missing, status=1)
    malformed = run.cli("compare", "plik.tif", b, status=1)
    capsys.readouterr()
    code = main(["compare", a, b], registry=served.registry, paths=served.api.paths)
    text = capsys.readouterr().out

    # Assert
    assert compared == run.http("/compare?" + urlencode({"a": a, "b": b}))
    assert unknown == run.http(
        "/compare?" + urlencode({"a": a, "b": missing}), status=404
    )
    assert malformed == run.http(
        "/compare?" + urlencode({"a": "plik.tif", "b": b}), status=422
    )
    assert malformed["code"] == "invalid_ref"
    differs = [row for row in compared["rows"] if row["differs"]]
    assert code == 0 and differs
    assert f"* {differs[0]['label']}: " in text
    assert f"A: {compared['a']['title']} ({a})" in text


# Previews (plan v0.2, step 6).


@pytest.fixture(scope="module")
def previews(tmp_path_factory: pytest.TempPathFactory) -> Iterator[PreviewApi]:
    """Serve a generated store with render processes and jobs for ``preview``."""
    with preview_api(tmp_path_factory.mktemp("cli-previews")) as found:
        yield found


def _preview(
    previews: PreviewApi,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    status: int = 0,
) -> Any:
    """Run ``archiwista preview … --json`` over the served store's data."""
    capsys.readouterr()
    code = main(["preview", *argv, "--json"], paths=previews.api.paths)
    captured = capsys.readouterr()
    assert code == status, captured.err
    return json.loads(captured.out)


def _ref(path: str) -> str:
    return f"version:{api_store.STORE}:{path}"


def test_preview_cli_equals_http(
    previews: PreviewApi, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``preview --json`` is ``GET …/preview``, after ``--build`` and refusals too."""
    # Arrange
    store = previews.store
    paths = [
        entry_of(store, family).path
        for family in ("tif_sheet", "gpkg_teryt", "zip_ku", "pdf_map", "laz_tile")
    ]
    raster, document = paths[0], paths[3]
    sheet = entry_of(store, "asc_sheet", "regular").path
    before = previews.get(version_url(sheet)).json()
    output = tmp_path / "miniatura.png"

    # Act
    described = [_preview(previews, capsys, _ref(path)) for path in paths]
    built = _preview(previews, capsys, _ref(sheet), "--build")
    unknown = _preview(previews, capsys, _ref("nie/ma.tif"), status=1)
    malformed = _preview(previews, capsys, "version:Zespol:plik.tif", status=1)
    small = _preview(previews, capsys, _ref(raster), "--size", "77", status=1)
    unstyled = _preview(
        previews,
        capsys,
        _ref(raster),
        "--style",
        "nieznany",
        "--output",
        str(output),
        status=1,
    )
    refused = _preview(
        previews, capsys, _ref(document), "--output", str(output), status=1
    )

    # Assert
    for path, printed in zip(paths, described, strict=True):
        assert printed == previews.get(version_url(path)).json()
    assert before["state"] == "needs_build"
    assert built == previews.get(version_url(sheet)).json()
    assert built["state"] == "ready"
    assert unknown == previews.get(version_url("nie/ma.tif")).json()
    assert unknown["code"] == "not_found"
    assert (
        malformed
        == previews.get("/api/v1/stores/Zespol/versions/plik.tif/preview").json()
    )
    assert malformed["code"] == "invalid_ref"
    assert small == previews.get(version_url(raster, "preview.png?size=77")).json()
    assert (
        unstyled
        == previews.get(version_url(raster, "preview.png?style=nieznany")).json()
    )
    assert refused == previews.get(version_url(document, "preview.png")).json()
    assert refused["code"] == "preview_unavailable"
    assert not output.exists()


def test_preview_output_writes_png(
    previews: PreviewApi, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``--output`` writes the thumbnail into the cache the server answers from."""
    # Arrange
    path = entry_of(previews.store, "tif_oblique").path
    output = tmp_path / "miniatura.png"

    # Act
    printed = _preview(
        previews, capsys, _ref(path), "--output", str(output), "--size", "256"
    )
    rendered = previews.pool.stats().rendered
    answered = previews.get(version_url(path, "preview.png?size=256"))
    described = previews.get(version_url(path))

    # Assert
    assert printed == described.json()
    assert answered.status_code == 200
    assert output.read_bytes() == answered.content
    assert 0 < max(decoded_png(answered.content).shape[1:]) <= 256
    assert previews.pool.stats().rendered == rendered
