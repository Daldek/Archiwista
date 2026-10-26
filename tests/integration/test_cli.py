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

import numpy as np
import pytest
import rasterio
from rasterio.windows import Window

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.index import IndexWriter, ManifestStamp, own_file_id
from archiwista.reader import add_read_commands
from archiwista.security import redeem_one_time_token
from archiwista.sources import ProjectInfo
from tests.fixtures import api_store
from tests.fixtures.api_session import Api, Caller, running_api
from tests.fixtures.api_store import ServedStore, served_store
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.index_data import PRODUCER, ROOT, STORE
from tests.fixtures.layer_store import (
    AREA_SHEET,
    PRODUCT,
    ServedLayers,
    served_layer_store,
    sheet_polygon,
)
from tests.fixtures.local_server import local_paths
from tests.fixtures.own_data_api import OwnDataApi, own_data_api
from tests.fixtures.permissions import log_entries
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

    def __call__(self, *argv: str) -> object:
        self._capsys.readouterr()
        assert main([*argv, "--json"], paths=self._paths) == 0
        out = self._capsys.readouterr().out
        return json.loads(out) if out else None

    def refused(self, *argv: str) -> dict[str, Any]:
        """Run a command that is refused; return its error document."""
        self._capsys.readouterr()
        status = main([*argv, "--json"], paths=self._paths)
        captured = self._capsys.readouterr()
        return refusal(captured.out, captured.err, status)


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
    assert {entry.actor for entry in log_entries(api.state)} == {"local"}


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
    """A refused command reports the API's problem and exits with its code."""
    # Arrange
    cli = _Cli(api, capsys)
    local: Caller = api.session(LOCAL_OWNER)

    # Act
    printed = cli.refused(*argv)
    answered = local.request(method, path, json=body)

    # Assert
    assert_same_error(printed, answered.json())


def test_admin_cli_taken_id_is_a_conflict(
    api: Api, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adding an existing group again is ``409 conflict`` on both doors."""
    # Arrange
    cli = _Cli(api, capsys)
    local = api.session(LOCAL_OWNER)
    cli("groups", "add", "hydro")

    # Act
    printed = cli.refused("groups", "add", "hydro")
    answered = local.request("POST", "/groups", json={"id": "hydro"})

    # Assert
    assert answered.status_code == 409
    assert_same_error(printed, answered.json())
    assert printed["exit_code"] == 4


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

    def cli(self, *argv: str) -> Any:
        self._capsys.readouterr()
        code = main(
            [*argv, "--json"],
            registry=self._served.registry,
            paths=self._served.api.paths,
        )
        captured = self._capsys.readouterr()
        assert code == 0, captured.err
        return json.loads(captured.out)

    def refused(self, *argv: str) -> dict[str, Any]:
        """Run a command that is refused; return its error document."""
        self._capsys.readouterr()
        code = main(
            [*argv, "--json"],
            registry=self._served.registry,
            paths=self._served.api.paths,
        )
        captured = self._capsys.readouterr()
        return refusal(captured.out, captured.err, code)

    def http(
        self, path: str, status: int = 200, *, accept_language: str | None = None
    ) -> Any:
        response = self._served.owner.request(
            "GET", path, accept_language=accept_language
        )
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
    """Invalid options give the route's ``400`` problem; the command exits 2."""
    # Arrange
    run = _Reader(served, capsys)

    # Act
    printed = run.refused(*_search_argv(params))
    answered = run.http(f"/slots?{urlencode(params)}", status=400)

    # Assert
    assert_same_error(printed, answered)
    assert (printed["code"], printed["exit_code"]) == ("validation_error", 2)


def test_search_cursor_of_another_query_refused(
    served: ServedStore, capsys: pytest.CaptureFixture[str]
) -> None:
    """A cursor is bound to its query on both doors."""
    # Arrange
    run = _Reader(served, capsys)
    cursor = run.cli("search", "--limit=3")["next_cursor"]

    # Act
    printed = run.refused("search", "--product=nmt", f"--cursor={cursor}")
    answered = run.http(f"/slots?product=nmt&cursor={cursor}", status=400)

    # Assert
    assert_same_error(printed, answered)


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
    missing = run.refused("entry", store, "nie/ma.tif")

    # Assert
    assert entry == run.http(f"/stores/{store}/slots/{slot}")
    assert entry["versions"]
    path = entry["current"]
    assert version == run.http(f"/stores/{store}/versions/{path}")
    expected = run.http(f"/stores/{store}/slots/nie/ma.tif", status=404)
    assert_same_error(missing, expected)
    assert (missing["code"], missing["exit_code"]) == ("not_found", 3)
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
    document = refusal(refused[1], refused[2], refused[0])
    assert (document["code"], refused[0]) == ("validation_error", 2)
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
    assert second.json()["code"] == "unauthorized"
    assert second.json()["details"]["reason"] == "session_required"
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
    unknown = run.refused("compare", a, missing)
    malformed = run.refused("compare", "plik.tif", b)
    capsys.readouterr()
    code = main(["compare", a, b], registry=served.registry, paths=served.api.paths)
    text = capsys.readouterr().out

    # Assert
    assert compared == run.http("/compare?" + urlencode({"a": a, "b": b}))
    expected = run.http("/compare?" + urlencode({"a": a, "b": missing}), status=404)
    assert_same_error(unknown, expected)
    assert unknown["exit_code"] == 3
    expected = run.http("/compare?" + urlencode({"a": "plik.tif", "b": b}), status=400)
    assert_same_error(malformed, expected)
    assert (malformed["code"], malformed["details"]["reason"]) == (
        "validation_error",
        "invalid_ref",
    )
    # The text is for a person, in Polish; the model of ``--json`` is English.
    polish = run.http("/compare?" + urlencode({"a": a, "b": b}), accept_language="pl")
    differs = [row for row in polish["rows"] if row["differs"]]
    assert code == 0 and differs
    assert f"* {differs[0]['label']}: " in text
    assert f"A: {polish['a']['title']} ({a})" in text


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
    """Run ``archiwista preview … --json``; a refusal gives its error document."""
    capsys.readouterr()
    code = main(["preview", *argv, "--json"], paths=previews.api.paths)
    captured = capsys.readouterr()
    assert code == status, captured.err
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, code)


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
    unknown = _preview(previews, capsys, _ref("nie/ma.tif"), status=3)
    malformed = _preview(previews, capsys, "version:Zespol:plik.tif", status=2)
    small = _preview(previews, capsys, _ref(raster), "--size", "77", status=2)
    unstyled = _preview(
        previews,
        capsys,
        _ref(raster),
        "--style",
        "nieznany",
        "--output",
        str(output),
        status=2,
    )
    refused = _preview(
        previews, capsys, _ref(document), "--output", str(output), status=15
    )

    # Assert
    for path, printed in zip(paths, described, strict=True):
        assert printed == previews.get(version_url(path)).json()
    assert before["state"] == "needs_build"
    assert built == previews.get(version_url(sheet)).json()
    assert built["state"] == "ready"
    assert_same_error(unknown, previews.get(version_url("nie/ma.tif")).json())
    assert unknown["code"] == "not_found"
    assert_same_error(
        malformed,
        previews.get("/api/v1/stores/Zespol/versions/plik.tif/preview").json(),
    )
    assert malformed["details"]["reason"] == "invalid_ref"
    assert_same_error(
        small, previews.get(version_url(raster, "preview.png?size=77")).json()
    )
    assert_same_error(
        unstyled,
        previews.get(version_url(raster, "preview.png?style=nieznany")).json(),
    )
    assert_same_error(
        refused, previews.get(version_url(document, "preview.png")).json()
    )
    assert (refused["code"], refused["details"]["reason"]) == (
        "unsupported",
        "preview_unavailable",
    )
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


# Own data of projects (plan v0.2, step 9).


def _own(
    served: OwnDataApi,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    status: int = 0,
) -> Any:
    """Run ``archiwista … --json``; a refusal gives its error document."""
    capsys.readouterr()
    code = main([*argv, "--json"], paths=served.paths)
    captured = capsys.readouterr()
    assert code == status, captured.err
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, code)


def test_own_data_cli_equals_http(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``files``, ``file``, ``snapshot`` and ``own-scan --json`` are the routes'.

    Each answer is compared with the route's at the same moment, refusals
    included; jobs as ``GET /jobs/{job}`` shows them once they ended. After a
    working file is edited, ``own-scan`` makes ``file`` show ``changed``.
    """
    with own_data_api(tmp_path) as served:
        # Arrange
        first, owner = served.first, served.owner
        raster = first.folder.file("tif_2180").path
        vector = first.folder.file("gpkg_layers").path
        files = f"/projects/{first.key}/files"

        def http(method: str, path: str, **body: Any) -> Any:
            return owner.request(method, path, **body).json()

        def job(answer: Any) -> Any:
            return http("GET", f"/jobs/{answer['id']}")

        # Act
        listed = (_own(served, capsys, "files", first.key), http("GET", files))
        query = ("--q", "kanalizacja", "--state", "unsnapshotted", "--limit", "1")
        filtered = (
            _own(served, capsys, "files", first.key, *query),
            http("GET", f"{files}?q=kanalizacja&state=unsnapshotted&limit=1"),
        )
        bad_state = (
            _own(served, capsys, "files", first.key, "--state", "zly", status=2),
            http("GET", f"{files}?state=zly"),
        )
        by_path = _own(served, capsys, "file", first.key, raster)
        by_id = _own(served, capsys, "file", first.key, own_file_id(raster))
        card = http("GET", first.url(raster))
        no_project = (
            _own(served, capsys, "file", "nie-ma", raster, status=3),
            http("GET", f"/projects/nie-ma/files/{own_file_id(raster)}"),
        )
        plan = (
            _own(served, capsys, "snapshot", first.key, raster, "--plan"),
            http("GET", first.url(raster, "snapshot-plan")),
        )
        argv = ("snapshot", first.key, raster, "--note", "przed zmianą")
        snapshot = _own(served, capsys, *argv)
        snapshot_job = job(snapshot)
        snapshotted = (
            _own(served, capsys, "file", first.key, raster),
            http("GET", first.url(raster)),
        )
        (first.root / vector).unlink()
        blocked = (
            _own(served, capsys, "snapshot", first.key, vector, status=4),
            http("POST", first.url(vector, "snapshots"), json={"note": ""}),
        )
        with rasterio.open(first.root / raster, "r+") as edited:
            pixel = np.full((1, 1), 999.0, dtype=np.float32)
            edited.write(pixel, 1, window=Window(0, 0, 1, 1))
        scan = _own(served, capsys, "own-scan", "--project", first.key)
        scan_job = job(scan)
        changed = (
            _own(served, capsys, "file", first.key, raster),
            http("GET", first.url(raster)),
        )
        every = _own(served, capsys, "own-scan")
        every_job = job(every)
        projects = http("GET", "/projects")["items"]
        unknown = (
            _own(served, capsys, "own-scan", "--project", "nie-ma", status=3),
            http("POST", "/projects/nie-ma/scan"),
        )

    # Assert
    for printed, answered in (listed, filtered):
        assert printed == answered
    for printed, answered in (bad_state, no_project, blocked, unknown):
        assert_same_error(printed, answered)
    assert [item["path"] for item in filtered[0]["items"]] == [vector]
    assert bad_state[0]["code"] == "validation_error"
    assert by_path == by_id == card
    assert card["preview"] is not None
    assert no_project[0]["code"] == "not_found"
    # Free space is read anew for each answer: anything writing to the disk
    # meanwhile changes it.
    assert {**plan[0], "free_bytes": None} == {**plan[1], "free_bytes": None}
    assert plan[0]["blocked"] is None and plan[0]["file"] == raster
    assert snapshot == snapshot_job
    assert snapshot["kind"] == "snapshot" and snapshot["state"] == "succeeded"
    assert snapshot["params"]["note"] == "przed zmianą"
    assert snapshot["result"]["status"] == "created"
    label = snapshot["result"]["label"]
    assert snapshotted[0] == snapshotted[1]
    assert [item["label"] for item in snapshotted[0]["snapshots"]] == [label]
    assert snapshotted[0]["change"] == "unchanged"
    assert blocked[0]["code"] == "conflict"
    assert blocked[0]["details"]["reason"] == "snapshot_blocked"
    assert blocked[0]["details"]["blocked_by"] == "file_missing"
    assert scan == scan_job
    assert (scan["kind"], scan["state"]) == ("own_scan", "succeeded")
    assert scan["params"] == {"project": first.key}
    assert scan["result"]["projects"] == 1
    assert (scan["result"]["changed"], scan["result"]["missing"]) == (1, 1)
    assert changed[0] == changed[1]
    assert changed[0]["change"] == "changed"
    assert changed[0]["last_snapshot"]["label"] == label
    assert every == every_job
    assert (every["params"], every["state"]) == ({}, "succeeded")
    assert every["result"]["projects"] == len(projects) > 2
    assert unknown[0]["code"] == "not_found"


# Layers (plan v0.2, step 11).


@pytest.fixture(scope="module")
def layers(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServedLayers]:
    """Serve the store of a product's years and campaigns for ``layers``."""
    with served_layer_store(tmp_path_factory.mktemp("cli-layers")) as found:
        yield found


_LAYERS_STORE = ("--store", api_store.STORE, "--product", PRODUCT)


def _layers(
    layers: ServedLayers,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
    status: int = 0,
) -> Any:
    """Run ``archiwista layers … --json``; a refusal gives its error document."""
    capsys.readouterr()
    command = ["layers", *_LAYERS_STORE, *argv, "--json"]
    code = main(command, paths=layers.api.api.paths)
    captured = capsys.readouterr()
    assert code == status, captured.err
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, code)


def _layers_url(route: str, **params: str) -> str:
    """Return the address of ``/local-layers{route}`` with a query."""
    return f"/api/v1/local-layers{route}?{urlencode(params)}"


def test_layers_cli_equals_http(
    layers: ServedLayers, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``layers --json`` is ``GET /local-layers``, refusals and ``--thumbnail`` too.

    With an area once the server has built the layers' previews: the command
    submits no jobs, so it would name none while they run.
    """
    # Arrange
    served = layers.api
    created = served.owner.request(
        "POST", "/areas", json={"geometry": sheet_polygon(AREA_SHEET)}
    )
    area = created.json()["id"]
    query = {"store": api_store.STORE, "product": PRODUCT}
    for layer in served.get(_layers_url("", **query, area_id=area)).json()["layers"]:
        if layer["preview"]["job"] is not None:
            served.wait(layer["preview"]["job"]["id"])
    built = served.get(_layers_url("", **query, area_id=area)).json()
    key = built["layers"][0]["key"]
    output, refused = tmp_path / "warstwa.png", tmp_path / "brak.png"
    image = {**query, "area_id": area, "size": "256"}

    # Act
    whole = _layers(layers, capsys)
    by_campaign = _layers(layers, capsys, "--group", "campaign")
    shown = _layers(
        layers,
        capsys,
        "--area-id",
        area,
        "--thumbnail",
        key,
        "--output",
        str(output),
        "--size",
        "256",
    )
    unknown = _layers(layers, capsys, "--area-id", "nieznany", status=2)
    missing = _layers(
        layers,
        capsys,
        "--area-id",
        area,
        "--thumbnail",
        "nie:ma",
        "--output",
        str(refused),
        status=3,
    )
    capsys.readouterr()
    usage = main(["layers", *_LAYERS_STORE, "--thumbnail", key], paths=served.api.paths)
    usage_error = refusal(*capsys.readouterr(), usage)

    # Assert
    assert whole == served.get(_layers_url("", **query)).json()
    assert by_campaign == served.get(_layers_url("", **query, group="campaign")).json()
    assert shown == built
    assert all(layer["preview"]["job"] is None for layer in shown["layers"])
    thumbnail = served.get(_layers_url("/thumbnail.png", **image, layer=key))
    assert thumbnail.status_code == 200, thumbnail.text
    assert output.read_bytes() == thumbnail.content
    assert_same_error(
        unknown, served.get(_layers_url("", **query, area_id="nieznany")).json()
    )
    assert unknown["code"] == "validation_error"
    thumbnail_missing = _layers_url("/thumbnail.png", **image, layer="nie:ma")
    assert_same_error(missing, served.get(thumbnail_missing).json())
    assert missing["code"] == "not_found"
    assert (usage_error["code"], usage_error["details"]["reason"]) == (
        "validation_error",
        "usage",
    )
    assert not refused.exists()
