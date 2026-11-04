"""The adapter reports the store root Obserwator uses when a call names none.

The root comes from ``obserwator.store_root()``, which gives the layer of the
settings that chose it (``OBSERWATOR_ROOT``, the same key in ``.env``,
``[obserwator] root`` of ``nogat.toml``, else ``<data_dir>/obserwator``, DEV-19.2),
so these tests set those layers themselves (the canary of ``tests/conftest.py``
points all of them at an empty tree) and pin the report to what Obserwator's own
writers leave.
"""

import json
from pathlib import Path

import obserwator
import pytest

from archiwista.adapter.obserwator import load
from archiwista.adapter.obserwator.adapter import ObserwatorAdapter
from archiwista.sources import DefaultRoot, DefaultRootAdapter, SourceContext


@pytest.fixture
def adapter(tmp_path: Path) -> ObserwatorAdapter:
    """Obserwator adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "obserwator"))
    assert isinstance(created, ObserwatorAdapter)
    return created


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give ``NOGAT_DATA_DIR`` alone: a data directory with no root of its own."""
    monkeypatch.delenv("OBSERWATOR_ROOT")
    monkeypatch.delenv("OBSERWATOR_DATA_DIR")
    monkeypatch.setenv("NOGAT_DATA_DIR", str(tmp_path / "nogat"))
    return tmp_path / "nogat"


def test_default_root_is_a_capability_of_the_adapter(
    adapter: ObserwatorAdapter,
) -> None:
    """The wizard and the doctor find it by the protocol, not by the class."""
    assert isinstance(adapter, DefaultRootAdapter)


def test_default_root_variable_names_a_marked_store(
    adapter: ObserwatorAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``OBSERWATOR_ROOT`` on a store Obserwator initialised is a store to offer."""
    # Arrange
    root = tmp_path / "store"
    obserwator.init_store(root)
    monkeypatch.setenv("OBSERWATOR_ROOT", str(root))

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(root, "env", "OBSERWATOR_ROOT", True, True)


def test_default_root_without_settings_lies_under_the_data_directory(
    adapter: ObserwatorAdapter, data_dir: Path
) -> None:
    """Nothing but ``NOGAT_DATA_DIR``: ``<data_dir>/obserwator``, which is not there."""
    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(data_dir / "obserwator", "default", None, False, False)
    assert not data_dir.exists()


def test_default_root_directory_is_marked_by_obserwator_init_store_only(
    adapter: ObserwatorAdapter, data_dir: Path
) -> None:
    """A directory is not a store before ``init_store`` wrote the marker into it."""
    # Arrange
    (data_dir / "obserwator").mkdir(parents=True)

    # Act
    before = adapter.default_root()
    obserwator.init_store(data_dir / "obserwator")
    after = adapter.default_root()

    # Assert
    assert (before.exists, before.marked) == (True, False)
    assert (after.exists, after.marked) == (True, True)


def test_default_root_of_the_settings_file_names_its_table(
    adapter: ObserwatorAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[obserwator] root`` of ``nogat.toml`` is reported as the file's."""
    # Arrange
    chosen = tmp_path / "chosen"
    settings = tmp_path / "nogat.toml"
    settings.write_text(f"[obserwator]\nroot = {json.dumps(str(chosen))}\n", "utf-8")
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))
    monkeypatch.delenv("OBSERWATOR_ROOT")

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(chosen, "file", "[obserwator]", False, False)


def test_default_root_of_a_dotenv_file_is_told_from_the_environment(
    adapter: ObserwatorAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Obserwator also reads ``OBSERWATOR_ROOT`` from ``.env``: its own layer."""
    # Arrange
    chosen = tmp_path / "chosen"
    (tmp_path / ".env").write_text(f"OBSERWATOR_ROOT={chosen}\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OBSERWATOR_ROOT")

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(chosen, "dotenv", "OBSERWATOR_ROOT", False, False)
