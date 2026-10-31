"""The call of a stored version over HTTP and the command line (A-ADR-049 D-10).

``GET /stores/{store}/versions/{version}/command`` and ``archiwista
version-command`` answer alike over a store of the stand-in producer
(``tests/fixtures/action_source``), which gives the call of a file from its
path and refuses its ``derived`` files. The producer is asked once per
version: the index keeps its answer (``version_calls``), the refusal too.
"""

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from archiwista.auth import LOCAL_OWNER
from archiwista.cli import main
from archiwista.config import AppPaths, ConfigStore
from archiwista.index import IndexWriter, initialize, scan_store
from archiwista.sources.registry import PluginRegistry, load_registry
from tests.fixtures.actions import (
    STORE,
    action_paths,
    standin_in_settings,
    store_root,
)
from tests.fixtures.api_session import assert_problem, running_api
from tests.fixtures.availability import register_standin
from tests.fixtures.cli_errors import assert_same_error, refusal
from tests.fixtures.network import no_network

STATION = "150160180"
FETCHED = f"hydro/{STATION}/2023.csv"
DERIVED = f"derived/{STATION}/opad.csv"


@pytest.fixture
def standin(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Register the stand-in with each store's directory; return its producer."""
    producer = register_standin(monkeypatch)
    standin_in_settings(monkeypatch)
    return producer


def _indexed(tmp_path: Path) -> tuple[AppPaths, PluginRegistry]:
    """Return an installation whose index holds a fetched and a derived file."""
    paths = action_paths(tmp_path)
    for version in (FETCHED, DERIVED):
        place = store_root(tmp_path) / version
        place.parent.mkdir(parents=True)
        place.write_text(f"{STATION},{version},2023-12-31\n", encoding="utf-8")
    registry = load_registry(cache_dir=paths.cache_dir)
    settings = ConfigStore(paths.config_file).load()
    config = settings.store(STORE)
    assert config is not None
    initialize(paths.index_file)
    with IndexWriter(paths.index_file) as writer:
        writer.sync_stores({STORE: config.roots()})
        scan_store(registry.adapter("standin"), writer, settings, STORE, mode="full")
    return paths, registry


def _cli(
    capsys: pytest.CaptureFixture[str],
    paths: AppPaths,
    registry: PluginRegistry,
    version: str,
    *,
    status: int = 0,
) -> Any:
    """Run ``archiwista version-command … --json``; a refusal gives its document."""
    capsys.readouterr()
    code = main(
        ["version-command", STORE, version, "--json"], registry=registry, paths=paths
    )
    captured = capsys.readouterr()
    assert code == status, captured.err
    if status == 0:
        return json.loads(captured.out)
    return refusal(captured.out, captured.err, code)


def _asked(producer: ModuleType) -> list[str]:
    """Return the versions the producer was asked the call of, in order."""
    return [path for name, path, _ in producer.CALLS if name == "command_for_version"]


def test_version_command_route_equals_the_command_and_asks_the_producer_once(
    tmp_path: Path, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """The call without the root, its line with it; the second answer is the index's."""
    # Arrange
    paths, registry = _indexed(tmp_path)
    root = store_root(tmp_path)

    with running_api(paths, registry) as api, no_network() as attempts:
        owner = api.session(LOCAL_OWNER)
        # Act
        served = owner.request("GET", f"/stores/{STORE}/versions/{FETCHED}/command")
        printed = _cli(capsys, paths, registry, FETCHED)
        unknown = owner.request("GET", f"/stores/{STORE}/versions/nic/a/b.csv/command")

    # Assert
    assert served.status_code == 200, served.text
    assert served.json() == {
        "producer": "standin",
        "command": "series fetch",
        "options": {"station": STATION, "kind": "hydro"},
        "line": (
            f"standin series fetch --station {STATION} --kind hydro --root {root}"
        ),
    }
    assert printed == served.json()
    assert _asked(standin) == [FETCHED]
    assert_problem(unknown, 404, "not_found")
    assert attempts == []


def test_version_command_of_a_derived_file_is_the_producers_kept_refusal(
    tmp_path: Path, standin: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """``422 unsupported`` ``command_not_rebuildable`` with its text, asked once."""
    # Arrange
    paths, registry = _indexed(tmp_path)

    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        # Act
        served = owner.request("GET", f"/stores/{STORE}/versions/{DERIVED}/command")
        document = _cli(capsys, paths, registry, DERIVED, status=15)

    # Assert
    assert_problem(served, 422, "unsupported", "command_not_rebuildable")
    problem = served.json()
    assert problem["detail"] == (
        f"No command fetches the derived file {DERIVED} again: pin it as it is."
    )
    assert problem["details"]["version"] == DERIVED
    assert_same_error(document, problem)
    assert _asked(standin) == [DERIVED]


def test_version_command_of_a_producer_without_the_capability_is_no_commands(
    tmp_path: Path,
    standin: ModuleType,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``422 unsupported`` ``no_commands`` by both; the producer is never asked."""
    # Arrange
    paths, registry = _indexed(tmp_path)
    plugin = type(registry.adapter("standin"))
    monkeypatch.delattr(plugin, "command_for_version")

    with running_api(paths, registry) as api:
        owner = api.session(LOCAL_OWNER)
        # Act
        served = owner.request("GET", f"/stores/{STORE}/versions/{FETCHED}/command")
        document = _cli(capsys, paths, registry, FETCHED, status=15)

    # Assert
    assert_problem(served, 422, "unsupported", "no_commands")
    problem = served.json()
    assert_same_error(document, problem)
    assert _asked(standin) == []
