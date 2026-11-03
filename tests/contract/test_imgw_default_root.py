"""The adapter reports the store root IMGWTools uses when a call names none.

The root comes from ``imgwtools.store_root()``, which gives the layer of the
settings that chose it (``IMGW_ROOT``, the same key in ``.env``, ``[imgw] root``
of ``nogat.toml``, else ``<data_dir>/imgw``, DEV-19.2), so these tests set those
layers themselves (the canary of ``tests/conftest.py`` points all of them at an
empty tree) and pin the report to what IMGWTools' own writers leave.
"""

import json
from pathlib import Path

import imgwtools
import pytest

from archiwista.adapter.imgw import load
from archiwista.adapter.imgw.adapter import ImgwAdapter
from archiwista.sources import DefaultRoot, DefaultRootAdapter, SourceContext


@pytest.fixture
def adapter(tmp_path: Path) -> ImgwAdapter:
    """IMGW adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "imgw"))
    assert isinstance(created, ImgwAdapter)
    return created


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give ``NOGAT_DATA_DIR`` alone: a data directory with no root of its own."""
    monkeypatch.delenv("IMGW_ROOT")
    monkeypatch.delenv("IMGW_DATA_DIR")
    monkeypatch.setenv("NOGAT_DATA_DIR", str(tmp_path / "nogat"))
    return tmp_path / "nogat"


def test_default_root_is_a_capability_of_the_adapter(adapter: ImgwAdapter) -> None:
    """The wizard and the doctor find it by the protocol, not by the class."""
    assert isinstance(adapter, DefaultRootAdapter)


def test_default_root_variable_names_a_marked_store(
    adapter: ImgwAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``IMGW_ROOT`` on a store that IMGWTools initialised is a store to offer."""
    # Arrange
    root = tmp_path / "store"
    imgwtools.init_store(root)
    monkeypatch.setenv("IMGW_ROOT", str(root))

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(root, "env", "IMGW_ROOT", True, True)


def test_default_root_without_settings_lies_under_the_data_directory(
    adapter: ImgwAdapter, data_dir: Path
) -> None:
    """Nothing but ``NOGAT_DATA_DIR``: ``<data_dir>/imgw``, which is not there."""
    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(data_dir / "imgw", "default", None, False, False)
    assert not data_dir.exists()


def test_default_root_directory_is_marked_by_imgw_init_store_only(
    adapter: ImgwAdapter, data_dir: Path
) -> None:
    """A directory is not a store before ``init_store`` wrote the marker into it."""
    # Arrange
    (data_dir / "imgw").mkdir(parents=True)

    # Act
    before = adapter.default_root()
    imgwtools.init_store(data_dir / "imgw")
    after = adapter.default_root()

    # Assert
    assert (before.exists, before.marked) == (True, False)
    assert (after.exists, after.marked) == (True, True)


def test_default_root_of_the_settings_file_names_its_table(
    adapter: ImgwAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[imgw] root`` of ``nogat.toml`` is reported as the file's."""
    # Arrange
    chosen = tmp_path / "chosen"
    settings = tmp_path / "nogat.toml"
    settings.write_text(f"[imgw]\nroot = {json.dumps(str(chosen))}\n", "utf-8")
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))
    monkeypatch.delenv("IMGW_ROOT")

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(chosen, "file", "[imgw]", False, False)


def test_default_root_of_a_dotenv_file_is_told_from_the_environment(
    adapter: ImgwAdapter, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IMGWTools also reads ``IMGW_ROOT`` from ``.env``: its own layer."""
    # Arrange
    chosen = tmp_path / "chosen"
    (tmp_path / ".env").write_text(f"IMGW_ROOT={chosen}\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("IMGW_ROOT")

    # Act
    found = adapter.default_root()

    # Assert
    assert found == DefaultRoot(chosen, "dotenv", "IMGW_ROOT", False, False)
