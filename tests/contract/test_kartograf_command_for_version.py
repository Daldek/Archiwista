"""The call of a stored Kartograf version (A-ADR-049 D-10, Kartograf KB-6).

The adapter reads the version's sidecar with ``read_sidecar`` and rebuilds the
call with ``command_for_file``, offline: the call of each version of
``kartograf.testing``'s store selects that version's data year again, and
``format`` writes a line that ``parse`` reads back into the same call. A
version whose call Kartograf cannot rebuild (``soil hsg``) is
``UnsupportedError`` with Kartograf's own text and the reason
``command_not_rebuildable``; a missing sidecar is Kartograf's ``data_error``.
"""

import json
from pathlib import Path

import kartograf
import pytest
from kartograf.testing import FixtureStore, build_fixture_store, make_sidecar

from archiwista.adapter.kartograf import load
from archiwista.errors import ProducerError, UnsupportedError
from archiwista.sources import (
    ActionAdapter,
    CommandCall,
    SourceContext,
    VersionCommandAdapter,
)
from tests.fixtures.network import no_network


@pytest.fixture
def adapter(tmp_path: Path) -> VersionCommandAdapter:
    """Kartograf's adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache"))
    assert isinstance(created, VersionCommandAdapter)
    return created


@pytest.fixture
def built(tmp_path: Path) -> FixtureStore:
    """Kartograf's fixture store."""
    return build_fixture_store(tmp_path / "data")


def test_command_for_version_of_each_sheet_version_reads_back_to_itself(
    adapter: VersionCommandAdapter, built: FixtureStore
) -> None:
    """The call names the version's data year; its line parses back to it."""
    # Arrange
    assert isinstance(adapter, ActionAdapter)
    versions = [
        version.path.relative_to(built.root).as_posix()
        for item in built.files
        for version in item.versions
    ]

    # Act
    with no_network() as attempts:
        calls = {
            path: adapter.command_for_version(path, root=built.root)
            for path in versions
        }

    # Assert
    assert attempts == []
    first = calls[versions[0]]
    assert (first.producer, first.command, dict(first.run)) == (
        "kartograf",
        "elevation download",
        {},
    )
    assert first.options["sheet"] == "N-34-130-D-d-2-4"
    assert first.options["year"] == 2022
    for call in calls.values():
        rooted = CommandCall(
            call.producer, call.command, call.options, {"root": str(built.root)}
        )
        line = adapter.format(rooted)
        assert adapter.parse(line) == rooted
        assert "--root" not in adapter.format(call)


def test_command_for_version_refuses_soil_hsg_with_kartografs_text(
    adapter: VersionCommandAdapter, tmp_path: Path
) -> None:
    """A derived version: ``unsupported``, ``command_not_rebuildable``, its text."""
    # Arrange
    root = tmp_path / "store"
    version = "hsg/global_soilgrids_250m/versions/2026-01-01_aa/hsg.tif"
    document = make_sidecar()
    document["product"] = "hsg"
    sidecar = root / f"{version}.meta.json"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(kartograf.CommandNotRebuildableError) as kartografs:
        kartograf.command_for_file(kartograf.read_sidecar(sidecar))
    expected = str(kartografs.value)

    # Act
    with pytest.raises(UnsupportedError) as raised:
        adapter.command_for_version(version, root=root)

    # Assert
    error = raised.value
    assert (error.code, error.details["reason"]) == (
        "unsupported",
        "command_not_rebuildable",
    )
    assert error.message == expected
    assert (error.details["producer"], error.details["version"]) == (
        "kartograf",
        version,
    )
    assert error.details["family"] == "hsg"


def test_command_for_version_without_a_sidecar_is_kartografs_data_error(
    adapter: VersionCommandAdapter, tmp_path: Path
) -> None:
    """No sidecar: ``ProducerError`` with Kartograf's code, not ``unsupported``."""
    with pytest.raises(ProducerError) as raised:
        adapter.command_for_version("nmt/x/versions/a/N.asc", root=tmp_path)

    assert raised.value.code == "data_error"
