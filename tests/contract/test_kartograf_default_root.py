"""The adapter reports the store root Kartograf uses when a call names none (M5).

The root comes from ``kartograf.get_config()``, which gives the layer of the
settings that chose it (``KARTOGRAF_ROOT``, ``[kartograf] root`` of
``nogat.toml``, else ``<data_dir>/kartograf``, DEV-19.2), so these tests set
those layers themselves (the canary of ``tests/conftest.py`` points all of them
at an empty tree) and pin the report to what Kartograf's own writers leave.
"""

import json
from pathlib import Path

import kartograf
import pytest
from kartograf.testing import build_fixture_store

from archiwista.adapter.kartograf import load
from archiwista.adapter.kartograf.adapter import KartografAdapter
from archiwista.sources import DefaultRoot, DefaultRootAdapter, SourceContext


@pytest.fixture
def adapter(tmp_path: Path) -> KartografAdapter:
    """Kartograf adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "kartograf"))
    assert isinstance(created, KartografAdapter)
    return created


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give ``NOGAT_DATA_DIR`` alone: a data directory with no root of its own."""
    monkeypatch.delenv("KARTOGRAF_ROOT")
    monkeypatch.delenv("KARTOGRAF_DATA_DIR")
    monkeypatch.setenv("NOGAT_DATA_DIR", str(tmp_path / "nogat"))
    return tmp_path / "nogat"


def test_default_root_is_a_capability_of_the_adapter(
    adapter: KartografAdapter,
) -> None:
    """The wizard and the doctor find it by the protocol, not by the class."""
    assert isinstance(adapter, DefaultRootAdapter)


def test_default_root_variable_names_a_marked_store(
    adapter: KartografAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``KARTOGRAF_ROOT`` on a store that Kartograf built is a store to offer."""
    # Arrange
    built = build_fixture_store(tmp_path / "store")
    monkeypatch.setenv("KARTOGRAF_ROOT", str(built.root))

    # Act
    root = adapter.default_root()

    # Assert
    assert root == DefaultRoot(built.root, "env", "KARTOGRAF_ROOT", True, True)


def test_default_root_without_settings_lies_under_the_data_directory(
    adapter: KartografAdapter, data_dir: Path
) -> None:
    """Nothing but ``NOGAT_DATA_DIR``: ``<data_dir>/kartograf``, which is not there."""
    # Act
    root = adapter.default_root()

    # Assert
    assert root == DefaultRoot(data_dir / "kartograf", "default", None, False, False)
    assert not data_dir.exists()


def test_default_root_directory_is_marked_by_kartograf_init_store_only(
    adapter: KartografAdapter, data_dir: Path
) -> None:
    """A directory is not a store before ``init_store`` wrote the marker into it."""
    # Arrange
    (data_dir / "kartograf").mkdir(parents=True)

    # Act
    before = adapter.default_root()
    kartograf.init_store(data_dir / "kartograf")
    after = adapter.default_root()

    # Assert
    assert (before.exists, before.marked) == (True, False)
    assert (after.exists, after.marked) == (True, True)


def test_default_root_of_the_settings_file_names_its_table(
    adapter: KartografAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[kartograf] root`` of ``nogat.toml`` is reported as the file's."""
    # Arrange
    chosen = tmp_path / "chosen"
    settings = tmp_path / "nogat.toml"
    settings.write_text(f"[kartograf]\nroot = {json.dumps(str(chosen))}\n", "utf-8")
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))
    monkeypatch.delenv("KARTOGRAF_ROOT")

    # Act
    root = adapter.default_root()

    # Assert
    assert root == DefaultRoot(chosen, "file", "[kartograf]", False, False)
