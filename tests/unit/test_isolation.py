"""The tests run as on a computer without settings of the producers (M4).

``tests/conftest.py`` points the settings and every default directory of
Kartograf and IMGWTools at a canary tree and fails the test after which anything
lies there: a call that writes without a store root of its own would otherwise
put files into the default root of whoever runs the tests (Decision 1 of the
plan of 2026-10-25).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import kartograf
import pytest
from kartograf.testing import PL_SEGMENT, build_fixture_store, build_project

from archiwista.adapter.kartograf import load
from archiwista.sources import SourceContext
from tests.fixtures.isolation import Canary, isolated_producers

IMGW_DIRECTORIES = (
    "IMGW_ROOT",
    "IMGW_DATA_DIR",
    "IMGW_CACHE_DIR",
    "IMGW_REFERENCE_DIR",
)


def test_isolation_every_test_meets_the_producers_without_settings() -> None:
    """A test that asks for nothing finds an empty settings file and no default root."""
    # Act
    report = kartograf.get_config()

    # Assert
    assert report.config_file.source == "NOGAT_CONFIG"
    assert (report.config_file.exists, report.config_file.error) == (True, None)
    assert (report.store.source, report.store.name) == ("env", "KARTOGRAF_ROOT")
    assert report.store.exists is False
    assert report.keys["lang"].value == "pl"


def test_isolation_replaces_the_settings_of_the_developer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Variables and a file of the developer lose against the canary, and return."""
    # Arrange: a developer who has set up both producers, shared and own variables
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    (theirs / "nogat.toml").write_text(
        f'[kartograf]\nroot = "{theirs / "from-file"}"\nlang = "en"\n', encoding="utf-8"
    )
    monkeypatch.setenv("NOGAT_CONFIG", str(theirs / "nogat.toml"))
    for producer in ("NOGAT", "KARTOGRAF", "IMGW"):
        monkeypatch.setenv(f"{producer}_DATA_DIR", str(theirs / f"{producer}-data"))
        monkeypatch.setenv(f"{producer}_CACHE_DIR", str(theirs / f"{producer}-cache"))
        monkeypatch.setenv(f"{producer}_LANG", "en")
    monkeypatch.setenv("KARTOGRAF_ROOT", str(theirs / "kartograf"))
    monkeypatch.setenv("IMGW_ROOT", str(theirs / "imgw"))
    monkeypatch.setenv("IMGW_REFERENCE_DIR", str(theirs / "reference"))

    # Act
    with isolated_producers(tmp_path / "work") as canary:
        inside = kartograf.get_config()
        imgw = {name: Path(os.environ[name]) for name in IMGW_DIRECTORIES}
        imgw_language = os.environ["IMGW_LANG"]
    outside = kartograf.get_config()

    # Assert
    assert inside.config_file.path == canary.settings_file
    assert inside.store.root == canary.kartograf_root
    assert inside.keys["data_dir"].value == canary.data_dir
    assert inside.keys["cache_dir"].value == canary.cache_dir
    assert inside.keys["lang"].value == "pl"
    assert all(path.is_relative_to(canary.base) for path in imgw.values())
    assert imgw_language == "pl"
    assert outside.store.root == theirs / "kartograf"
    assert outside.keys["lang"].value == "en"


def test_isolation_adapter_reads_leave_the_canary_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a store and a project through the adapter writes into no default root."""
    # Arrange: the variables name other places, a store and a project wait to be read
    elsewhere = tmp_path / "elsewhere"
    for name in ("KARTOGRAF_ROOT", "IMGW_ROOT", "NOGAT_DATA_DIR", "NOGAT_CACHE_DIR"):
        monkeypatch.setenv(name, str(elsewhere / name))
    built = build_fixture_store(tmp_path / "store")
    project = build_project(tmp_path / "projects" / "projekt", built)
    adapter = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))

    # Act
    with isolated_producers(tmp_path / "work") as canary:
        state = adapter.probe(built.root)
        entry = next(
            e
            for e in adapter.iter_entries(built.root)
            if e.kind == "version" and e.segment == PL_SEGMENT
        )
        meta = adapter.read_meta(entry)
        outline = adapter.footprint(entry)
        info = adapter.read_project(project)
        checked = adapter.project_status(project)
        appeared = canary.appeared()

    # Assert: the reads happened, and nothing came of them in a default place
    assert state.status == "available"
    assert meta.relative_path == entry.relative_path
    assert outline.location == "footprint"
    assert info.tasks and checked.status == "ok"
    assert appeared == []
    assert not elsewhere.exists()


def test_isolation_write_without_a_store_root_fails_and_empties_the_tree(
    tmp_path: Path,
) -> None:
    """``init_store()`` without a root marks Kartograf's default root: it fails."""
    # Act
    with (
        pytest.raises(pytest.fail.Exception) as failed,
        isolated_producers(tmp_path / "work") as canary,
    ):
        kartograf.init_store()

    # Assert
    assert "kartograf/kartograf-store.json" in str(failed.value)
    assert "pass root=" in str(failed.value)
    assert canary.appeared() == []


def test_isolation_child_processes_inherit_it(producer_canary: Canary) -> None:
    """The producer's command line, started by a test, reads the same canary."""
    # Act
    done = subprocess.run(
        [sys.executable, "-m", "kartograf", "config", "show", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert done.returncode == 0, done.stderr
    report = json.loads(done.stdout)["result"]
    assert report["store"]["root"] == str(producer_canary.kartograf_root)
    assert report["config_file"]["error"] is None
