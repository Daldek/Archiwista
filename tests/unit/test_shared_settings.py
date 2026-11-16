"""``nogat.toml``, the settings shared with the Nogat tools (A-ADR-053, A-ADR-054).

Every test runs with ``NOGAT_CONFIG`` naming an empty file (``tests/conftest.py``),
so each one writes the file it needs, or removes the variable to find the file in
the user configuration directory of a temporary home.
"""

import sys
from pathlib import Path

import pytest

from archiwista.config import AppPaths, own_folder_conflict
from archiwista.shared_settings import SharedSettings

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="the XDG directories of platformdirs on Linux"
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give a home whose XDG directories lie in ``tmp_path``, without NOGAT_CONFIG."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.delenv("NOGAT_CONFIG")
    return tmp_path


def _nogat_toml(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_app_paths_default_keeps_the_platform_directories_without_nogat_toml(
    home: Path,
) -> None:
    """No file: data and caches stay in Archiwista's own platform directory."""
    # Act
    shared = SharedSettings.read()
    paths = AppPaths.default(shared)

    # Assert
    assert shared.path == home / "xdg-config" / "nogat" / "nogat.toml"
    assert (shared.exists, shared.problem, dict(shared.values)) == (False, None, {})
    assert paths.config_file == home / "xdg-config" / "archiwista" / "config.toml"
    assert paths.data_dir == home / "xdg-data" / "archiwista"
    assert paths.previews_dir == home / "xdg-data" / "archiwista" / "previews"
    assert paths.cache_dir == home / "xdg-data" / "archiwista" / "cache"
    assert shared.language == "pl"


def test_app_paths_default_takes_the_directories_of_nogat_toml(home: Path) -> None:
    """``data_dir`` and ``cache_dir`` give ``<dir>/archiwista``; config.toml stays."""
    # Arrange
    _nogat_toml(
        home / "xdg-config" / "nogat" / "nogat.toml",
        '[nogat]\ndata_dir = "~/nogat-data"\ncache_dir = "/var/cache/nogat"\n',
    )

    # Act
    paths = AppPaths.default()

    # Assert
    data = home / "home" / "nogat-data" / "archiwista"
    assert paths.config_file == home / "xdg-config" / "archiwista" / "config.toml"
    assert (paths.index_file, paths.state_file, paths.jobs_dir) == (
        data / "index.sqlite",
        data / "state.sqlite",
        data / "jobs",
    )
    assert paths.previews_dir == Path("/var/cache/nogat/archiwista/previews")
    assert paths.cache_dir == Path("/var/cache/nogat/archiwista/cache")
    assert paths.own_dirs == (data, paths.cache_dir, paths.previews_dir)


def test_shared_settings_read_takes_archiwista_table_before_nogat_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[archiwista]`` wins key by key; ``[nogat]`` fills the rest (DEV-18.1)."""
    # Arrange
    settings = _nogat_toml(
        tmp_path / "elsewhere.toml",
        "[nogat]\n"
        'data_dir = "/srv/nogat"\ncache_dir = "/srv/cache"\nlang = "pl"\n'
        "[archiwista]\n"
        'data_dir = "/srv/archiwista-only"\nlang = "EN"\n'
        "[kartograf]\n"
        'root = "relative is not ours"\n',
    )
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))

    # Act
    shared = SharedSettings.read()

    # Assert
    assert (shared.path, shared.named, shared.problem) == (settings, True, None)
    assert {key: (value.value, value.name) for key, value in shared.values.items()} == {
        "data_dir": ("/srv/archiwista-only", "[archiwista] data_dir"),
        "cache_dir": ("/srv/cache", "[nogat] cache_dir"),
        "lang": ("en", "[archiwista] lang"),
    }
    assert shared.language == "en"


def test_shared_settings_read_takes_the_first_gui_table_whole_in_its_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``[archiwista.gui]`` replaces ``[nogat.gui]`` whole; the file's order stays."""
    # Arrange
    settings = _nogat_toml(
        tmp_path / "nogat.toml",
        "[nogat.gui]\n"
        'hydrolog = "http://127.0.0.1:8070/"\n'
        'hydrograf = "http://127.0.0.1:8080/"\n'
        "[archiwista.gui]\n"
        'obserwator = " /obserwator/ "\n'
        'archiwista = "https://archiwista.example/"\n',
    )
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))

    # Act
    shared = SharedSettings.read()

    # Assert
    assert shared.problem is None
    assert shared.gui is not None
    assert (shared.gui.name, list(shared.gui.addresses.items())) == (
        "[archiwista] gui",
        [("obserwator", "/obserwator/"), ("archiwista", "https://archiwista.example/")],
    )


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"[nogat\n", "is not valid TOML"),
        (b'[nogat]\ndata_dir = "/x\xff"\n', "is not UTF-8 text"),
        (b"nogat = 3\n", "[nogat] of the settings file"),
        (b'[archiwista]\ndata_dir = "relative/dir"\n', "data_dir of [archiwista]"),
        (b"[nogat]\ncache_dir = 7\n", "cache_dir of [nogat]"),
        (b'[nogat]\nlang = "de"\n', "lang of [nogat]"),
        (b'[nogat]\ngui = "http://127.0.0.1:8070/"\n', "gui of [nogat]"),
        (b"[nogat.gui]\nhydrolog = 8070\n", "hydrolog of [nogat.gui]"),
        (b'[archiwista.gui]\nhydrolog = " "\n', "hydrolog of [archiwista.gui]"),
    ],
)
def test_shared_settings_read_gives_no_value_from_a_file_it_cannot_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes, expected: str
) -> None:
    """A broken file or value is a problem and moves nothing (the CLI refuses it)."""
    # Arrange
    settings = tmp_path / "nogat.toml"
    settings.write_bytes(content)
    monkeypatch.setenv("NOGAT_CONFIG", str(settings))

    # Act
    shared = SharedSettings.read()

    # Assert
    assert shared.problem is not None
    assert expected in shared.problem.localized("en")
    assert dict(shared.values) == {}
    assert shared.gui is None
    assert shared.language == "pl"


def test_shared_settings_read_refuses_a_missing_file_named_by_the_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``NOGAT_CONFIG`` naming nothing is a mistake; an absent default file is not."""
    # Arrange
    monkeypatch.setenv("NOGAT_CONFIG", str(tmp_path / "typo.toml"))

    # Act
    shared = SharedSettings.read()

    # Assert
    assert shared.problem is not None
    assert "NOGAT_CONFIG" in shared.problem.localized("en")
    assert not shared.exists


def test_own_folder_conflict_refuses_a_folder_holding_caches_kept_apart(
    tmp_path: Path,
) -> None:
    """With ``cache_dir`` the caches lie apart; no project's folder may hold them."""
    # Arrange
    paths = AppPaths(
        config_file=tmp_path / "config.toml",
        data_dir=tmp_path / "data" / "archiwista",
        cache_home=tmp_path / "shared" / "cache" / "archiwista",
    )

    # Act
    holding = own_folder_conflict(
        tmp_path / "shared", stores=(), app_data=paths.own_dirs, others=()
    )
    beside = own_folder_conflict(
        tmp_path / "shared" / "project-data",
        stores=(),
        app_data=paths.own_dirs,
        others=(),
    )

    # Assert
    assert holding == ("inside_app_data", paths.cache_dir)
    assert beside is None
