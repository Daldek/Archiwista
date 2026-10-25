"""Producers' commands through the service of every interface (plan 2026-10-25, A1).

The stand-in producer (``tests/fixtures/action_source``) is registered the way
production plugins are, by an entry point on ``sys.path``. It takes the store
root among the options of a call, as IMGWTools does, and records every call
with the options it received (``standin_producer.CALLS``). The routes of
``/api/v1/commands`` and ``archiwista commands`` run over the installed
Kartograf under the socket guard (``tests/fixtures/network.py``).
"""

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import kartograf
import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.errors import (
    ArchiwistaError,
    CommandRequestError,
    NotFoundError,
    PathOutsideRootError,
    SourceUnavailableError,
    UnsupportedError,
)
from archiwista.services.commands import (
    list_commands,
    parse_command,
    validate_command,
)
from archiwista.sources import CommandCall
from archiwista.sources.registry import PluginRegistry, load_registry
from tests.fixtures.api_session import Caller, assert_problem, running_api
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.local_server import local_paths
from tests.fixtures.missing_package import hide_packages
from tests.fixtures.network import no_network

FIXTURES = Path(__file__).parents[1] / "fixtures"
FIXTURE_MODULES = (
    "standin_source_plugin",
    "standin_producer",
    "external_source_plugin",
    "external_producer",
)
STATION = {"station": " 150160180 ", "kind": "HYDRO"}
# A complete call of a store command (the example of ``elevation download``).
DOWNLOAD = "elevation download"
NMT = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2-4",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}
LINE = (
    "kartograf elevation download --product nmt --sheet N-34-130-D-d-2-4"
    " --resolution 1m --vertical-crs EVRF2007 --root ./data"
)


class _StandinStore(StoreConfig):
    """A store of the stand-in: the settings know only the producers' directories."""

    def roots(self) -> dict[str, Path]:
        """Return the stand-in's directory: the one given as Kartograf's."""
        return {"standin": super().roots()["kartograf"]}


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in (and the second source); return its producer library."""
    for name in FIXTURE_MODULES:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.syspath_prepend(str(FIXTURES / "second_source"))
    monkeypatch.syspath_prepend(str(FIXTURES / "action_source"))
    return importlib.import_module("standin_producer")


def _settings(tmp_path: Path) -> AppSettings:
    """Return the stand-in's store ``pomiary`` and the Kartograf store ``zespol``."""
    (tmp_path / "pomiary").mkdir()
    (tmp_path / "zespol").mkdir()
    return AppSettings(
        stores=(
            _StandinStore(
                id="pomiary",
                name="Pomiary",
                kartograf=tmp_path / "pomiary",
                kind="local",
            ),
            StoreConfig(
                id="zespol", name="Zespół", kartograf=tmp_path / "zespol", kind="local"
            ),
        )
    )


def test_validate_gives_the_producer_the_configured_store_as_its_root(
    tmp_path: Path, standin: ModuleType
) -> None:
    """The stand-in reads the root among its options; the answer leaves it out."""
    registry = load_registry(cache_dir=tmp_path / "cache")
    settings = _settings(tmp_path)

    checked = validate_command(
        registry,
        settings,
        CommandCall("standin", "series fetch", STATION),
        store="pomiary",
    )
    received = standin.CALLS

    assert checked == CommandCall(
        "standin", "series fetch", {"station": "150160180", "kind": "hydro"}
    )
    root = str(tmp_path / "pomiary")
    assert received == [("validate_command", "series fetch", {**STATION, "root": root})]


@pytest.mark.parametrize(
    ("call", "store", "kind", "reason"),
    [
        (
            CommandCall("standin", "series fetch", {**STATION, "area": "/etc/passwd"}),
            "pomiary",
            PathOutsideRootError,
            "path_outside_root",
        ),
        (
            CommandCall("standin", "series fetch", STATION),
            None,
            CommandRequestError,
            "store_required",
        ),
        (
            CommandCall("standin", "series fetch", STATION),
            "brak",
            NotFoundError,
            None,
        ),
        (
            CommandCall("standin", "series fetch", STATION),
            "zespol",
            CommandRequestError,
            "store_without_producer",
        ),
        (
            CommandCall("standin", "series_fetch", STATION),
            "pomiary",
            CommandRequestError,
            "unknown_command",
        ),
    ],
    ids=["path", "no_store", "unknown_store", "foreign_store", "unknown_command"],
)
def test_validate_refuses_what_archiwista_adds_before_the_producer_sees_it(
    tmp_path: Path,
    standin: ModuleType,
    call: CommandCall,
    store: str | None,
    kind: type[ArchiwistaError],
    reason: str | None,
) -> None:
    """A path, a missing or foreign store and an unknown command never reach it."""
    registry = load_registry(cache_dir=tmp_path / "cache")

    with pytest.raises(kind) as refused:
        validate_command(registry, _settings(tmp_path), call, store=store)

    assert refused.value.details.get("reason") == reason
    assert standin.CALLS == []


def test_a_missing_producer_refuses_only_its_own_commands(
    tmp_path: Path, standin: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Kartograf the stand-in's catalog and calls still answer."""
    hide_packages(monkeypatch, "kartograf")
    registry = load_registry(cache_dir=tmp_path / "cache")

    listed = list_commands(registry)
    parsed = parse_command(registry, "standin", "standin stations list --kind meteo")
    with pytest.raises(SourceUnavailableError) as missing:
        parse_command(registry, "kartograf", "kartograf sheet parse --sheet N-34")
    with pytest.raises(UnsupportedError) as without:
        list_commands(registry, producer="external")

    assert [(info.producer, info.command) for info in listed] == [
        ("standin", "series fetch"),
        ("standin", "stations list"),
    ]
    assert parsed == CommandCall("standin", "stations list", {"kind": "meteo"})
    assert (missing.value.code, missing.value.details["reason"]) == (
        "missing_dependency",
        "source_unavailable",
    )
    assert without.value.details["reason"] == "no_commands"


def _kartograf_paths(tmp_path: Path) -> AppPaths:
    """Return local paths whose settings name the Kartograf store ``zespol``."""
    paths = local_paths(tmp_path)
    root = tmp_path / "zespol"
    root.mkdir()
    store = StoreConfig(id="zespol", name="Zespół", kartograf=root, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(store,)))
    return paths


def _answer(response: httpx.Response) -> Any:
    """Return the JSON of a successful answer."""
    assert response.status_code == 200, response.text
    return response.json()


def _parse(owner: Caller, producer: str, line: str) -> Any:
    """Return the call ``POST /commands/parse`` reads from ``line``."""
    body = {"producer": producer, "line": line}
    return _answer(owner.request("POST", "/commands/parse", json=body))


def test_commands_api_lists_kartograf_and_reads_every_example_back_offline(
    tmp_path: Path,
) -> None:
    """The ids are ``kartograf commands list``'s; a line's call survives JSON."""
    # Arrange
    paths = _kartograf_paths(tmp_path)
    listed = [row.name for row in kartograf.list_commands().commands]

    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        with no_network() as attempts:
            # Act
            catalog = _answer(owner.request("GET", "/commands"))
            examples = [line for item in catalog["items"] for line in item["examples"]]
            calls = [_parse(owner, "kartograf", line) for line in examples]
            lines = [
                _answer(owner.request("POST", "/commands/format", json=call))["line"]
                for call in calls
            ]
            read_back = [_parse(owner, "kartograf", line) for line in lines]

    # Assert
    assert [item["command"] for item in catalog["items"]] == listed
    assert {item["producer"] for item in catalog["items"]} == {"kartograf"}
    assert {call["command"] for call in calls} == set(listed)
    assert read_back == calls
    assert attempts == []


def test_commands_api_refuses_an_invalid_year_with_kartograf_own_text(
    tmp_path: Path,
) -> None:
    """``400`` with ``details.option`` ``year``, the text and hint in the language."""
    # Arrange
    paths = _kartograf_paths(tmp_path)
    options = {**NMT, "year": 1800}
    with pytest.raises(kartograf.ValidationError) as own:
        kartograf.validate_command(DOWNLOAD, options, root=tmp_path / "zespol")
    polish = kartograf.error_report(
        own.value, command=DOWNLOAD, given=options, lang="pl"
    )
    body = {"producer": "kartograf", "command": DOWNLOAD, "store": "zespol"}

    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        with no_network() as attempts:
            # Act
            refused = owner.request(
                "POST", "/commands/validate", json={**body, "options": options}
            )
            in_polish = owner.request(
                "POST",
                "/commands/validate",
                json={**body, "options": options},
                accept_language="pl",
            )
            valid = owner.request(
                "POST", "/commands/validate", json={**body, "options": NMT}
            )

    # Assert
    assert_problem(refused, 400, "validation_error", "kartograf_error")
    assert refused.json()["detail"] == own.value.localized("en")
    assert refused.json()["details"]["option"] == "year"
    assert (in_polish.json()["detail"], in_polish.json()["hint"]) == (
        polish.message,
        polish.hint,
    )
    assert _answer(valid) == {
        "producer": "kartograf",
        "command": DOWNLOAD,
        "options": NMT,
        "run": {},
    }
    assert attempts == []


def test_commands_api_without_kartograf_refuses_only_its_commands(
    tmp_path: Path, standin: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf's requests are ``503``, the stand-in's answer, ``external`` ``422``."""
    # Arrange
    hide_packages(monkeypatch, "kartograf")
    paths = local_paths(tmp_path)
    sheet = {"producer": "kartograf", "command": "sheet parse", "options": {}}
    stations = {"producer": "standin", "command": "stations list"}
    line = {"producer": "kartograf", "line": "kartograf sheet parse --sheet N-34"}

    with running_api(paths, load_registry(cache_dir=paths.cache_dir)) as api:
        owner = api.session(LOCAL_OWNER)
        with no_network() as attempts:
            # Act
            listed = _answer(owner.request("GET", "/commands"))
            missing = [
                owner.request("GET", "/commands?producer=kartograf"),
                owner.request("POST", "/commands/parse", json=line),
                owner.request("POST", "/commands/validate", json=sheet),
                owner.request("POST", "/commands/format", json=sheet),
            ]
            parsed = _parse(owner, "standin", "standin stations list --kind meteo")
            checked = owner.request(
                "POST",
                "/commands/validate",
                json={**stations, "options": {"kind": " METEO "}},
            )
            written = owner.request("POST", "/commands/format", json=parsed)
            without = owner.request("GET", "/commands?producer=external")

    # Assert
    assert [(item["producer"], item["command"]) for item in listed["items"]] == [
        ("standin", "series fetch"),
        ("standin", "stations list"),
    ]
    for response in missing:
        assert_problem(response, 503, "missing_dependency", "source_unavailable")
    assert parsed == {**stations, "options": {"kind": "meteo"}, "run": {}}
    assert _answer(checked) == parsed
    assert _answer(written)["line"] == "standin stations list --kind meteo"
    assert_problem(without, 422, "unsupported", "no_commands")
    assert attempts == []


def _cli(
    capsys: pytest.CaptureFixture[str],
    paths: AppPaths,
    registry: PluginRegistry,
    *argv: str,
    status: int = 0,
) -> Any:
    """Run ``archiwista commands … --json``; a refusal gives its error document."""
    capsys.readouterr()
    code = main(["commands", *argv, "--json"], registry=registry, paths=paths)
    captured = capsys.readouterr()
    assert code == status, captured.err
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, code)


def test_commands_cli_json_equals_http(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``commands list|parse|validate|format --json`` are the routes, refusals too."""
    # Arrange
    paths = _kartograf_paths(tmp_path)
    registry = load_registry(cache_dir=paths.cache_dir)
    call = {"producer": "kartograf", "command": DOWNLOAD, "options": NMT}
    given = ("kartograf", DOWNLOAD, "--options")
    year = {**NMT, "year": 1800}
    geometry = {**NMT, "geometry": "/etc/passwd"}
    run = json.dumps({"root": "./data"})

    def cli(*argv: str, status: int = 0) -> Any:
        return _cli(capsys, paths, registry, *argv, status=status)

    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)

        def http(method: str, path: str, body: object = None) -> Any:
            return owner.request(method, path, json=body).json()

        with no_network() as attempts:
            # Act
            answers = [
                (cli("list"), http("GET", "/commands")),
                (
                    cli("parse", "kartograf", LINE),
                    http(
                        "POST",
                        "/commands/parse",
                        {"producer": "kartograf", "line": LINE},
                    ),
                ),
                (
                    cli("validate", *given, json.dumps(NMT), "--store", "zespol"),
                    http("POST", "/commands/validate", {**call, "store": "zespol"}),
                ),
                (
                    cli("format", *given, json.dumps(NMT), "--run", run),
                    http(
                        "POST", "/commands/format", {**call, "run": {"root": "./data"}}
                    ),
                ),
            ]
            refusals = [
                (
                    cli(
                        "validate",
                        *given,
                        json.dumps(year),
                        "--store",
                        "zespol",
                        status=2,
                    ),
                    http(
                        "POST",
                        "/commands/validate",
                        {**call, "options": year, "store": "zespol"},
                    ),
                ),
                (
                    cli(
                        "validate", *given, json.dumps(NMT), "--store", "brak", status=3
                    ),
                    http("POST", "/commands/validate", {**call, "store": "brak"}),
                ),
                (
                    cli(
                        "validate",
                        *given,
                        json.dumps(geometry),
                        "--store",
                        "zespol",
                        status=12,
                    ),
                    http(
                        "POST",
                        "/commands/validate",
                        {**call, "options": geometry, "store": "zespol"},
                    ),
                ),
                (
                    cli("list", "--producer", "imgw", status=15),
                    http("GET", "/commands?producer=imgw"),
                ),
            ]
            capsys.readouterr()
            argv = ["commands", "format", *given, json.dumps(NMT), "--run", run]
            text = (main(argv, registry=registry, paths=paths), capsys.readouterr())

    # Assert
    for printed, answered in answers:
        assert printed == answered
    for document, problem in refusals:
        assert_same_error(document, problem)
    assert [document["code"] for document, _ in refusals] == [
        "validation_error",
        "not_found",
        "forbidden",
        "unsupported",
    ]
    assert answers[3][0]["line"] == LINE
    assert (text[0], text[1].out) == (0, f"{LINE}\n")
    assert attempts == []
