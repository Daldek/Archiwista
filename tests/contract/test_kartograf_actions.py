"""Kartograf's commands through the adapter's action capability (plan 2026-10-25, A1).

The catalog, the reading of a line, the check of a call and the line of a call
run against the installed Kartograf, as every test does, under the canary of
the producers' default roots (``tests/conftest.py``). Kartograf's
``kartograf-commands/1`` gives the commands and their example lines.
"""

from pathlib import Path

import kartograf
import pytest

import archiwista.adapter.kartograf.actions as actions_module
from archiwista.adapter.kartograf import load
from archiwista.errors import ProducerError
from archiwista.sources import ActionAdapter, SourceContext
from tests.fixtures.network import no_network

# A complete call of a store command (the example of ``elevation download``).
NMT = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2-4",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}


@pytest.fixture
def adapter(tmp_path: Path) -> ActionAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, ActionAdapter)
    return created


def test_catalog_holds_every_command_of_kartograf_in_its_order(
    adapter: ActionAdapter,
) -> None:
    """The ids are those of ``kartograf commands list``, in its order."""
    listed = [row.name for row in kartograf.list_commands().commands]

    commands = adapter.commands()

    assert [info.command for info in commands] == listed
    assert {info.producer for info in commands} == {"kartograf"}


def test_options_of_a_call_leave_the_store_and_the_flags_of_a_run_out(
    adapter: ActionAdapter,
) -> None:
    """A download takes its store by name; its run flags are no options of a call."""
    commands = {info.command: info for info in adapter.commands()}

    download = commands["elevation download"]
    parse = commands["sheet parse"]

    names = {option.name for option in download.options}
    assert {"product", "sheet", "year", "geometry"} <= names
    assert not names & {"root", "output_dir", "check", "update", "plan", "workers"}
    assert (download.store, download.check, download.writes) == (True, True, "add")
    assert (parse.store, parse.check, parse.read_only) == (False, False, True)
    geometry = next(option for option in download.options if option.name == "geometry")
    assert (geometry.path_role, geometry.group) == ("input", "area")


def test_every_example_line_reads_back_into_its_call_without_the_network(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """``parse`` reads the line ``format`` writes into the same call; nothing connects.

    Kartograf writes the canonical line of a call. The examples are complete
    calls, so each also passes ``validate`` (with a store root for a store
    command).
    """
    root = tmp_path / "store"

    with no_network() as attempts:
        catalog = adapter.commands()
        calls = [adapter.parse(line) for info in catalog for line in info.examples]
        read_back = [adapter.parse(adapter.format(call)) for call in calls]
        stores = {info.command: info.store for info in catalog}
        for call in calls:
            adapter.validate(
                call.command, call.options, root=root if stores[call.command] else None
            )

    assert read_back == calls
    assert {call.command for call in calls} == set(stores)
    assert attempts == []


def test_an_invalid_year_is_refused_with_its_option_and_kartograf_text(
    adapter: ActionAdapter, tmp_path: Path
) -> None:
    """Kartograf's text is kept, its option becomes ``details.option``."""
    options = {**NMT, "year": 1800}
    with pytest.raises(kartograf.ValidationError) as own:
        kartograf.validate_command("elevation download", options, root=tmp_path)

    with pytest.raises(ProducerError) as refused:
        adapter.validate("elevation download", options, root=tmp_path)

    error = refused.value
    assert (error.code, error.http_status) == ("validation_error", 400)
    assert error.message == own.value.localized("en")
    assert error.details["option"] == "year"
    assert error.details["reason"] == "kartograf_error"
    assert error.details["kartograf"]["reason"] == "invalid_input"


def test_validate_names_the_store_root_of_a_store_command_only(
    adapter: ActionAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartograf gets ``root=`` for a download, none for a command without a store.

    A download without its root never reaches Kartograf, whose default root
    would stand in (Decision 1 of the plan).
    """
    received: list[tuple[str, dict[str, object]]] = []

    def recording(command: str, options: object, **kwargs: object) -> None:
        received.append((command, kwargs))
        kartograf.validate_command(command, options, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(actions_module, "validate_command", recording)
    root = tmp_path / "store"

    adapter.validate("elevation download", NMT, root=root)
    adapter.validate("sheet parse", {"sheet": "N-34-130-D-d-2-4"}, root=root)
    with pytest.raises(ValueError, match="works on a store"):
        adapter.validate("elevation download", NMT, root=None)

    assert received == [("elevation download", {"root": root}), ("sheet parse", {})]
