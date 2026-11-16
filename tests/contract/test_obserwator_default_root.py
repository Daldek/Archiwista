"""The adapter reports the roots Obserwator uses when a call names none.

Obserwator keeps a store in two roots (its ADR-017), and each comes from
``obserwator.store_root(kind=...)``, which gives the layer of the settings that
chose it: for the raw root ``OBSERWATOR_RAW_ROOT``, the same key in ``.env``,
``[obserwator] raw_root`` of ``nogat.toml``, else ``<data_dir>/obserwator-raw``;
for the data root ``OBSERWATOR_ROOT``, ``[obserwator] root``, else
``<data_dir>/obserwator`` (DEV-19.2). ``default_root`` reports the raw root and
``default_data_root`` the data root, so these tests set those layers
themselves (the canary of ``tests/conftest.py`` points all of them at an empty
tree) and pin each report to what Obserwator's own writers leave.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import obserwator
import pytest

from archiwista.adapter.obserwator import load
from archiwista.adapter.obserwator.adapter import ObserwatorAdapter
from archiwista.sources import (
    DataRootAdapter,
    DefaultRoot,
    DefaultRootAdapter,
    SourceContext,
)


@dataclass(frozen=True)
class Kind:
    """What names Obserwator's default root of a kind, and the adapter's report.

    ``variable`` and ``key`` are the setting of the root in the environment and
    in ``[obserwator]`` of ``nogat.toml``, ``directory`` its default below the
    data directory.
    """

    name: Literal["raw", "data"]
    variable: str
    key: str
    directory: str
    report: Callable[[ObserwatorAdapter], DefaultRoot]


RAW = Kind(
    "raw",
    "OBSERWATOR_RAW_ROOT",
    "raw_root",
    "obserwator-raw",
    ObserwatorAdapter.default_root,
)
DATA = Kind(
    "data",
    "OBSERWATOR_ROOT",
    "root",
    "obserwator",
    ObserwatorAdapter.default_data_root,
)
KINDS = [RAW, DATA]


def _name(kind: Kind) -> str:
    return kind.name


@pytest.fixture
def adapter(tmp_path: Path) -> ObserwatorAdapter:
    """Obserwator adapter created by its entry-point factory."""
    created = load(SourceContext(cache_dir=tmp_path / "cache" / "obserwator"))
    assert isinstance(created, ObserwatorAdapter)
    return created


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give ``NOGAT_DATA_DIR`` alone: a data directory with no root of its own."""
    for variable in (RAW.variable, DATA.variable, "OBSERWATOR_DATA_DIR"):
        monkeypatch.delenv(variable)
    monkeypatch.setenv("NOGAT_DATA_DIR", str(tmp_path / "nogat"))
    return tmp_path / "nogat"


def test_default_roots_are_capabilities_of_the_adapter(
    adapter: ObserwatorAdapter,
) -> None:
    """The wizard and the doctor find both by the protocols, not by the class."""
    assert isinstance(adapter, DefaultRootAdapter)
    assert isinstance(adapter, DataRootAdapter)


@pytest.mark.parametrize("kind", KINDS, ids=_name)
def test_default_root_variable_names_a_marked_root(
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
) -> None:
    """The variable of a kind on a root Obserwator initialised so is one to offer."""
    # Arrange
    root = tmp_path / "root"
    obserwator.init_store(root, kind=kind.name)
    monkeypatch.setenv(kind.variable, str(root))

    # Act
    found = kind.report(adapter)

    # Assert
    assert found == DefaultRoot(root, "env", kind.variable, True, True)


@pytest.mark.parametrize("kind", KINDS, ids=_name)
def test_default_root_without_settings_lies_under_the_data_directory(
    adapter: ObserwatorAdapter, data_dir: Path, kind: Kind
) -> None:
    """Nothing but ``NOGAT_DATA_DIR``: its directory of the kind, which is not there."""
    # Act
    found = kind.report(adapter)

    # Assert
    assert found == DefaultRoot(
        data_dir / kind.directory, "default", None, False, False
    )
    assert not data_dir.exists()


@pytest.mark.parametrize("kind", KINDS, ids=_name)
def test_default_root_directory_is_marked_by_obserwator_init_store_only(
    adapter: ObserwatorAdapter, data_dir: Path, kind: Kind
) -> None:
    """A directory is no root before ``init_store`` of its kind wrote the marker."""
    # Arrange
    root = data_dir / kind.directory
    root.mkdir(parents=True)

    # Act
    before = kind.report(adapter)
    obserwator.init_store(root, kind=kind.name)
    after = kind.report(adapter)

    # Assert
    assert (before.exists, before.marked) == (True, False)
    assert (after.exists, after.marked) == (True, True)


@pytest.mark.parametrize(("kind", "other"), [(RAW, DATA), (DATA, RAW)], ids=_name)
def test_default_root_holding_the_other_kinds_marker_is_not_marked(
    adapter: ObserwatorAdapter, data_dir: Path, kind: Kind, other: Kind
) -> None:
    """A root of the other kind at the default directory is no root to offer."""
    # Arrange
    root = data_dir / kind.directory
    obserwator.init_store(root, kind=other.name)

    # Act
    found = kind.report(adapter)

    # Assert
    assert (found.exists, found.marked) == (True, False)


@pytest.mark.parametrize("kind", KINDS, ids=_name)
def test_default_root_of_the_settings_file_names_its_table(
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
) -> None:
    """The key of a kind in ``[obserwator]`` of ``nogat.toml`` is the file's."""
    # Arrange
    chosen = tmp_path / "chosen"
    settings = tmp_path / "nogat.toml"
    line = f"{kind.key} = {json.dumps(str(chosen))}"
    settings.write_text(f"[obserwator]\n{line}\n", "utf-8")
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))
    monkeypatch.delenv(kind.variable)

    # Act
    found = kind.report(adapter)

    # Assert
    assert found == DefaultRoot(chosen, "file", "[obserwator]", False, False)


@pytest.mark.parametrize("kind", KINDS, ids=_name)
def test_default_root_of_a_dotenv_file_is_told_from_the_environment(
    adapter: ObserwatorAdapter,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
) -> None:
    """Obserwator also reads the variable of a kind from ``.env``: its own layer."""
    # Arrange
    chosen = tmp_path / "chosen"
    (tmp_path / ".env").write_text(f"{kind.variable}={chosen}\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(kind.variable)

    # Act
    found = kind.report(adapter)

    # Assert
    assert found == DefaultRoot(chosen, "dotenv", kind.variable, False, False)
