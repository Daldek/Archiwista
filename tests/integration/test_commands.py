"""Producers' commands through the service of every interface (plan 2026-10-25, A1).

The stand-in producer (``tests/fixtures/action_source``) is registered the way
production plugins are, by an entry point on ``sys.path``. It takes the store
root among the options of a call, as IMGWTools does, and records every call
with the options it received (``standin_producer.CALLS``).
"""

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

from archiwista.config import AppSettings, StoreConfig
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
from archiwista.sources.registry import load_registry
from tests.fixtures.missing_package import hide_packages

FIXTURES = Path(__file__).parents[1] / "fixtures"
FIXTURE_MODULES = (
    "standin_source_plugin",
    "standin_producer",
    "external_source_plugin",
    "external_producer",
)
STATION = {"station": " 150160180 ", "kind": "HYDRO"}


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
