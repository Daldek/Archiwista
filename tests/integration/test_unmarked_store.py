"""A Kartograf store without its marker is refused wherever one is read (ADR-031).

``make_store`` marks what it writes. The tests take the marker away, as the
store of a Kartograf 0.8.0-dev has none, and look at what a person meets: a
scan job that fails with the reason and the command, the settings that refuse
the directory with the same text, and the doctor that prints the fix.
"""

from pathlib import Path

import pytest
from kartograf.testing import build_fixture_store

from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.messages import message
from archiwista.sources.markers import STORE_MARKERS
from archiwista.sources.registry import load_registry
from tests.fixtures.api_session import assert_problem
from tests.fixtures.api_store import served_store
from tests.fixtures.jobs import STORE, jobs_env

MARKER = STORE_MARKERS["kartograf"]

pytestmark = pytest.mark.filterwarnings("ignore:Dataset has no geotransform")


def _unmarked_store(directory: Path) -> Path:
    """Build a small store and take its marker away, as an older store has none."""
    root = build_fixture_store(directory).root
    (root / MARKER).unlink()
    return root


def test_unmarked_store_scan_job_fails_with_the_reason_and_the_fix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The job ends ``store_unavailable`` and names the command; the index is empty."""
    with jobs_env(tmp_path, monkeypatch) as env:
        # Arrange
        root = env.store.root
        (root / MARKER).unlink()

        # Act
        record = env.run("scan", mode="full")
        state = env.state()
        indexed = env.rows()

    # Assert
    assert record.state == "failed"
    assert record.error is not None
    assert (record.error.code, record.error.reason) == (
        "store_unavailable",
        "no_marker",
    )
    assert message("source.no_marker", marker=MARKER) in record.error.detail
    assert record.error.hint == message("fix.store_init", path=str(root))
    assert (state.status, state.stale) == ("unavailable", True)
    assert indexed == []


def test_unmarked_store_in_the_settings_is_refused_with_the_same_text(
    tmp_path: Path,
) -> None:
    """``PUT /settings`` answers 400 at the field with the reason and the command."""
    with served_store(tmp_path) as served:
        # Arrange
        current = served.owner.request("GET", "/settings").json()
        unmarked = _unmarked_store(tmp_path / "older")
        changed = {
            **current,
            "stores": [{**current["stores"][0], "kartograf": str(unmarked)}],
        }

        # Act
        refused = served.owner.request("PUT", "/settings", json=changed)

    # Assert
    assert_problem(refused, 400, "validation_error")
    problems = refused.json()["details"]["problems"]
    assert [(p["code"], p["field"], p["reason"]) for p in problems] == [
        ("source_incompatible", "stores[0].kartograf", "no_marker")
    ]
    assert problems[0]["message"].endswith(message("source.no_marker", marker=MARKER))
    assert problems[0]["hint"] == message("fix.store_init", path=str(unmarked))


def test_doctor_prints_the_command_that_marks_an_unmarked_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``archiwista doctor`` fails the store and prints the command as the fix."""
    # Arrange
    unmarked = _unmarked_store(tmp_path / "older")
    paths = AppPaths(
        config_file=tmp_path / "config" / "config.toml", data_dir=tmp_path / "data"
    )
    store = StoreConfig(id=STORE, name="Zespół", kartograf=unmarked, kind="local")
    ConfigStore(paths.config_file).save(AppSettings(stores=(store,)))
    registry = load_registry(cache_dir=paths.cache_dir)

    # Act
    status = main(["doctor"], registry=registry, paths=paths)

    # Assert
    out = capsys.readouterr().out
    assert status == 10
    assert f"[BŁĄD] Katalog kartograf magazynu „{STORE}” nie jest zgodnym" in out
    assert f"nie ma pliku {MARKER}" in out
    assert f"Naprawa: uruchom raz: kartograf store init --root {unmarked}" in out
