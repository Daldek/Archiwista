"""Obserwator's commands through the adapter's capability (plan 2026-11-05, P1).

The catalog, the reading and writing of a call and the check of its options
are Obserwator's own answers, offline. The plan of a call and its run go to
Obserwator's real ``check_command`` and ``run_command`` with its HTTP layer
stood in for (``tests/fixtures/obserwator_http.py``, as Obserwator's own
tests do): an initialised empty store is planned, the plan is run and writes
versions, a plan whose source changed meanwhile fails as ``stale_plan``, a
narrowed plan fetches only what it keeps, and an interrupt leaves no part of
a version. The places of plan positions and of files are compared with the
versions Obserwator wrote, so a change of its store layout fails here.
"""

import json
from dataclasses import replace
from pathlib import Path

import obserwator
import pytest
from obserwator import init_store, iter_store

from archiwista.adapter.obserwator import load
from archiwista.adapter.obserwator.actions import BESIDE_OPTIONS, STORE_COMMANDS
from archiwista.adapter.obserwator.adapter import ObserwatorAdapter
from archiwista.errors import ProducerError, UnsupportedError
from archiwista.messages import language
from archiwista.sources import (
    ActionAdapter,
    ActionProgress,
    AreaCommandAdapter,
    AvailabilityNotice,
    CommandCall,
    ScanScope,
    SourceContext,
)
from tests.fixtures.network import no_network
from tests.fixtures.obserwator_http import standin_source

HYDRO = "pl.imgw.hydro_daily"
SYNC = {"datasets": [HYDRO], "years": [2023, 2024]}
SLOT_2023 = "archives/versions/dane_hydrologiczne/dobowe/2023/codz_2023"
SLOT_2024 = "archives/versions/dane_hydrologiczne/dobowe/2024/codz_2024"
SERIES = "series/versions/hydro_daily"
CATALOG = "stations/versions"


@pytest.fixture
def adapter(tmp_path: Path) -> ObserwatorAdapter:
    """Create the adapter with its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "obserwator"))
    assert isinstance(created, ObserwatorAdapter)
    return created


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Return an empty Obserwator store (its marker only)."""
    store = tmp_path / "store"
    init_store(store)
    return store


def _versions(root: Path) -> list[str]:
    """Return the versions Obserwator's own scan sees, below the root."""
    return sorted(
        Path(entry.version).relative_to(root).as_posix()
        for entry in iter_store(root)
        if entry.kind != "problem" and entry.version is not None
    )


def _problems(root: Path) -> list[str]:
    return [
        str(entry.problem_code) for entry in iter_store(root) if entry.kind == "problem"
    ]


def test_obserwator_adapter_capabilities_commands_and_no_area(
    adapter: ObserwatorAdapter,
) -> None:
    """The adapter offers the commands that write the store and refuses areas."""
    assert isinstance(adapter, ActionAdapter)
    assert isinstance(adapter, AreaCommandAdapter)
    assert adapter.availability_products() == ()


def test_obserwator_catalog_store_commands_in_order_offline(
    adapter: ObserwatorAdapter,
) -> None:
    """The catalog is the store-writing commands of ``data_commands``, offline."""
    names = [command.name for command in obserwator.data_commands()]

    with no_network() as attempts:
        commands = adapter.commands()

    assert attempts == []
    assert tuple(command.command for command in commands) == STORE_COMMANDS
    assert [names.index(name) for name in STORE_COMMANDS] == sorted(
        names.index(name) for name in STORE_COMMANDS
    )
    for command in commands:
        assert command.producer == "obserwator"
        assert command.store and command.check and not command.read_only
        assert not {option.name for option in command.options} & BESIDE_OPTIONS


def test_obserwator_catalog_language_of_the_call(adapter: ObserwatorAdapter) -> None:
    """Summaries and option descriptions follow the call's language."""
    schema = obserwator.command_schema("store sync", lang="pl")
    polish = schema["commands"][0]  # type: ignore[index]

    with language("pl"):
        sync = adapter.commands()[0]
    with language("en"):
        english = adapter.commands()[0]

    assert sync.summary == polish["summary"]
    assert sync.summary != english.summary
    datasets = next(option for option in sync.options if option.name == "datasets")
    assert datasets.type == "array" and datasets.items == "string"
    assert HYDRO in {choice.value for choice in datasets.choices}


def test_obserwator_parse_format_round_trip_examples(
    adapter: ObserwatorAdapter,
) -> None:
    """Every example line reads back as the call it formats to; the root goes beside."""
    for command in adapter.commands():
        for line in command.examples:
            call = adapter.parse(line)
            again = adapter.parse(adapter.format(call))

            assert call.command == command.command
            assert "root" not in call.options and call.run["root"]
            assert (again.command, dict(again.options)) == (
                call.command,
                dict(call.options),
            )


def test_obserwator_format_names_the_root_beside_the_options(
    adapter: ObserwatorAdapter,
) -> None:
    """A store root of ``run`` becomes ``--root``; Archiwista's own flags go."""
    call = CommandCall(
        "obserwator", "store sync", SYNC, {"root": "/data/obserwator", "upgrade": True}
    )

    line = adapter.format(call)

    assert line.startswith("obserwator store sync --root /data/obserwator")
    assert "--upgrade" not in line


def test_obserwator_validate_errors_with_the_option_offline(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A refusal keeps Obserwator's code and names the option; nothing is asked."""
    with no_network() as attempts, pytest.raises(ProducerError) as missing:
        adapter.validate("store sync", {"datasets": [HYDRO]}, root=root)
    with pytest.raises(ProducerError) as unknown:
        adapter.validate("store teleport", {}, root=root)

    assert attempts == []
    assert missing.value.code == "validation_error"
    assert missing.value.details["option"] == "years"
    assert unknown.value.code == "validation_error"


def test_obserwator_validate_store_command_needs_root(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A store command without its root never reaches Obserwator's default root."""
    with pytest.raises(ValueError, match="give its root"):
        adapter.validate("store sync", SYNC, root=None)

    assert adapter.validate("store sync", SYNC, root=root) == SYNC


def test_obserwator_check_plans_missing_archives_and_series(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """The plan of an empty store: both archives and the series are missing."""
    notices: list[AvailabilityNotice] = []

    with standin_source() as source:
        plan = adapter.check("store sync", SYNC, root=root, on_notice=notices.append)

    assert (plan.producer, plan.command, plan.schema) == (
        "obserwator",
        "store sync",
        "obserwator-plan/1",
    )
    assert [(entry.path, entry.status) for entry in plan.entries] == [
        (SLOT_2023, "missing"),
        (SLOT_2024, "missing"),
        (SERIES, "missing"),
    ]
    assert plan.ok and plan.size_bytes and plan.size_bytes > 0
    assert plan.document["schema"] == "obserwator-plan/1"
    assert source.files() == []
    assert _versions(root) == []


def test_obserwator_run_of_a_plan_writes_versions_at_its_places(
    adapter: ObserwatorAdapter, root: Path, tmp_path: Path
) -> None:
    """A run of the plan writes each version at the place its position named."""
    events: list[ActionProgress] = []
    with standin_source():
        plan = adapter.check("store sync", SYNC, root=root)
        result = adapter.run(
            "store sync", SYNC, root=root, plan=plan, on_progress=events.append
        )

    assert result.status == "ok" and not result.failed
    places = {file.path for file in result.files}
    assert places == {entry.path for entry in plan.entries}
    assert {file.version_path for file in result.files} == set(_versions(root)) - {
        version for version in _versions(root) if version.startswith("stations")
    }
    for file in result.files:
        assert file.status == "new"
        assert file.version_path and file.version_path.startswith(f"{file.path}/")
        assert (root / file.version_path).is_file()
    assert events and events[-1].current == events[-1].total
    assert list((tmp_path / "cache" / "obserwator").glob("*")) == []


def test_obserwator_run_of_a_stale_plan_fails_the_position(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A source changed since the plan: the position fails as ``stale_plan``."""
    with standin_source() as source:
        plan = adapter.check("store sync", SYNC, root=root)
        source.etags["dane_hydrologiczne/dobowe/2024/codz_2024.zip"] = '"changed"'
        result = adapter.run("store sync", SYNC, root=root, plan=plan)

    stale = [item for item in result.items if item.reason == "stale_plan"]
    assert [item.id for item in stale] == [
        "archive:pl.imgw.hydro_daily:2024/codz_2024.zip"
    ]
    assert stale[0].code == "conflict" and stale[0].status == "failed"
    assert result.status == "partial"


def test_obserwator_narrow_keeps_only_the_claimed_archives(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A narrowed plan's run fetches only the archives it keeps."""
    with standin_source() as source:
        plan = adapter.check("store sync", SYNC, root=root)
        narrowed = adapter.narrow(plan, [SLOT_2024, SERIES])
        result = adapter.run("store sync", SYNC, root=root, plan=narrowed)

    assert [entry.path for entry in narrowed.entries] == [SLOT_2024, SERIES]
    assert source.files() == ["dane_hydrologiczne/dobowe/2024/codz_2024.zip"]
    assert SLOT_2023 not in {file.path for file in result.files}


def test_obserwator_narrow_refuses_another_producers_plan(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A document that is no ``obserwator-plan/1`` is refused."""
    with standin_source():
        plan = adapter.check("store sync", SYNC, root=root)
    other = replace(plan, document={"schema": "kartograf-plan/1"})

    with pytest.raises(ValueError, match="no plan of Obserwator"):
        adapter.narrow(other, [])


def test_obserwator_run_interrupted_leaves_no_part_of_a_version(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """An interrupt goes through; the store holds whole versions only."""
    with standin_source() as source:
        plan = adapter.check("store sync", SYNC, root=root)
        source.interrupt_after = 1
        with pytest.raises(KeyboardInterrupt):
            adapter.run("store sync", SYNC, root=root, plan=plan)

    assert _problems(root) == []
    assert _versions(root) == [f"{SLOT_2023}/2026-10-17_d6b138ff/codz_2023.zip"]


def test_obserwator_run_again_without_plan_is_unchanged(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A run without a plan keeps what is current: every file ``unchanged``."""
    with standin_source():
        adapter.run("store sync", SYNC, root=root)
        again = adapter.run("store sync", SYNC, root=root, upgrade=True)
        plan = adapter.check("store sync", SYNC, root=root)

    assert {file.status for file in again.files} == {"unchanged"}
    assert {entry.status for entry in plan.entries} == {"current"}
    assert plan.todo == ()
    assert {entry.local_label for entry in plan.entries[:2]} == {"2026-10-17"}


def test_obserwator_catalog_and_series_at_their_places(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """The catalog's and the series' positions name where their versions lie."""
    with standin_source():
        adapter.run("store sync", {**SYNC, "series": False}, root=root)
        series_plan = adapter.check("series build", {"dataset": HYDRO}, root=root)
        series = adapter.run("series build", {"dataset": HYDRO}, root=root)
        catalog_plan = adapter.check("store catalog", {}, root=root)
        catalog = adapter.run("store catalog", {}, root=root)

    assert {entry.path for entry in series_plan.entries} == {
        SERIES,
        SLOT_2023,
        SLOT_2024,
    }
    assert [entry.status for entry in series_plan.entries if entry.path != SERIES] == [
        "current",
        "current",
    ]
    assert [file.path for file in series.files] == [SERIES]
    assert CATALOG in {entry.path for entry in catalog_plan.entries}
    assert [file.path for file in catalog.files] == [CATALOG]
    assert [item.id for item in catalog.items] == [CATALOG]


def test_obserwator_version_call_runs_again(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """The call of a version a run wrote is a command of the catalog."""
    with standin_source():
        result = adapter.run("store sync", SYNC, root=root)
    names = {command.command for command in adapter.commands()}

    for file in result.files:
        assert file.version_path is not None
        call = adapter.command_for_version(file.version_path, root=root)
        assert call.command in names
        adapter.validate(call.command, call.options, root=root)


def test_obserwator_scope_is_the_whole_store(adapter: ObserwatorAdapter) -> None:
    """Every slot is read again by a scan of the whole store."""
    assert adapter.scope(SLOT_2024) == ScanScope()
    assert adapter.scope(SERIES) == ScanScope()
    for wrong in ("/abs/x", "x", "../archives/y", "kartograf/nmt"):
        with pytest.raises(ValueError):
            adapter.scope(wrong)


def test_obserwator_with_area_refuses_no_area_option(
    adapter: ObserwatorAdapter, tmp_path: Path
) -> None:
    """IMGW-PIB's archives are national files: no area narrows a download."""
    call = CommandCall("obserwator", "store sync", SYNC)

    with pytest.raises(UnsupportedError) as refused:
        adapter.with_area(
            call, area_file=tmp_path / "a.geojson", geometry={}, countries=("PL",)
        )
    with pytest.raises(UnsupportedError) as availability:
        adapter.availability("hydro", area_file=tmp_path / "a.geojson", countries=())

    assert refused.value.details["reason"] == "no_area_option"
    assert availability.value.details["reason"] == "no_availability"


def test_obserwator_check_of_a_command_without_plan_is_unsupported(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """A command outside the catalog has no plan of a store (``no_plan``)."""
    with pytest.raises(UnsupportedError) as refused:
        adapter.check("store info", {}, root=root)

    assert refused.value.details["reason"] == "no_plan"


@pytest.mark.live
def test_obserwator_live_store_sync_of_one_year(
    adapter: ObserwatorAdapter, root: Path
) -> None:
    """IMGW-PIB's real ``pl.imgw.hydro_daily`` 2024: plan, run, files, series.

    Downloads about 2 MB from danepubliczne.imgw.pl; run deliberately with
    ``-m live``.
    """
    call = {"datasets": [HYDRO], "years": [2024]}

    plan = adapter.check("store sync", call, root=root)
    result = adapter.run("store sync", call, root=root, plan=plan)

    assert result.status == "ok", json.dumps([item.message for item in result.failed])
    assert {file.path for file in result.files} == {SLOT_2024, SERIES}
