"""Consumer-facing checks for ``archiwista doctor`` diagnostics."""

import socket
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from archiwista.cli import main
from archiwista.config import AppPaths, AppSettings, ConfigStore, StoreConfig
from archiwista.doctor import is_port_available, run_doctor
from archiwista.sources import SourceAdapter, SourceState
from archiwista.sources.registry import source_error

KARTOGRAF = SourceState(
    producer="kartograf",
    status="available",
    package_version="0.8.0",
    supported_versions=">=0.8.0,<0.9",
    schemas=("kartograf-meta/1", "kartograf-project/1"),
)


@dataclass
class FakeRegistry:
    """Plugin registry with fixed states; probes mirror the plugin state."""

    source_states: tuple[SourceState, ...] = (KARTOGRAF,)
    failing: dict[Path, SourceState] = field(default_factory=dict)

    def producers(self) -> tuple[str, ...]:
        """Return the producers of the configured states."""
        return tuple(state.producer for state in self.source_states)

    def states(self) -> tuple[SourceState, ...]:
        """Return the configured plugin states."""
        return self.source_states

    def state(self, producer: str) -> SourceState:
        """Return a producer's configured state (``not_installed`` if none)."""
        found = (s for s in self.source_states if s.producer == producer)
        return next(found, SourceState(producer=producer, status="not_installed"))

    def adapter(self, producer: str) -> SourceAdapter:
        """Refuse every producer: the doctor never reads a store."""
        raise source_error(self.state(producer))

    def probe(self, producer: str, root: Path) -> SourceState:
        """Return the plugin state, or a listed root's own failure."""
        state = self.state(producer)
        if state.status != "available":
            return state
        return self.failing.get(root, replace(state, store=str(root)))


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    """Place configuration and local data inside the test directory."""
    return AppPaths(
        config_file=tmp_path / "config" / "config.toml",
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    """Create a Kartograf store directory with one file."""
    root = tmp_path / "nas" / "kartograf"
    (root / "nmt").mkdir(parents=True)
    (root / "nmt" / "a.txt").write_text("x", encoding="utf-8")
    return root


def configure(paths: AppPaths, root: Path, **values: object) -> None:
    """Write settings with one store at ``root``."""
    store = StoreConfig(id="zespol", name="Zespół", kartograf=root, kind="share")
    settings = AppSettings(stores=(store,)).model_copy(update=values)
    ConfigStore(paths.config_file).save(settings)


def run_cli(
    paths: AppPaths, registry: FakeRegistry, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    """Run ``archiwista doctor`` and return its exit status and output."""
    status = main(["doctor"], registry=registry, paths=paths)
    return status, capsys.readouterr().out


def tree(root: Path) -> list[str]:
    """Return every path under ``root``."""
    return sorted(str(path.relative_to(root)) for path in root.rglob("*"))


def test_doctor_healthy_store_exits_zero_and_writes_nothing(
    tmp_path: Path,
    paths: AppPaths,
    store_root: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Diagnostics only read: no file appears in the store or local data."""
    projects = tmp_path / "projekty"
    projects.mkdir()
    configure(paths, store_root, project_dirs=(projects,))
    before = tree(tmp_path)

    status, out = run_cli(paths, FakeRegistry(), capsys)

    assert status == 0
    assert tree(tmp_path) == before
    assert "[OK] Wtyczka kartograf: wersja 0.8.0" in out
    assert "Magazyn „zespol” (kartograf, udział sieciowy)" in out
    assert "Wynik: błędy 0" in out


def test_doctor_disconnected_store_explains_fix_and_fails(
    tmp_path: Path, paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unplugged share is an error with a Polish repair hint."""
    configure(paths, tmp_path / "unplugged")

    status, out = run_cli(paths, FakeRegistry(), capsys)

    assert status == 1
    assert "[BŁĄD] Katalog kartograf magazynu „zespol” nie istnieje" in out
    assert "Naprawa: podłącz udział albo popraw ścieżkę magazynu" in out
    assert not (tmp_path / "unplugged").exists()


def test_doctor_missing_plugin_shows_install_command(
    paths: AppPaths, store_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A store whose producer is not installed fails with a pip command."""
    configure(paths, store_root)
    registry = FakeRegistry(
        source_states=(
            SourceState(
                producer="kartograf",
                status="not_installed",
                detail="No module named 'kartograf'",
            ),
        )
    )

    status, out = run_cli(paths, registry, capsys)

    assert status == 1
    assert "[BŁĄD] Wtyczka kartograf: pakiet producenta nie jest zainstalowany" in out
    assert 'pip install "kartograf<0.9,>=0.8.0"' in out


def test_doctor_unregistered_plugin_for_store_fails(
    paths: AppPaths, store_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A store whose producer has no entry point is not reported as healthy."""
    configure(paths, store_root)

    status, out = run_cli(paths, FakeRegistry(source_states=()), capsys)

    assert status == 1
    assert "Wtyczka kartograf nie jest zarejestrowana" in out


def test_doctor_wrong_version_shows_installed_supported_and_fix(
    paths: AppPaths, store_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An incompatible producer names both versions and how to install."""
    configure(paths, store_root)
    registry = FakeRegistry(
        source_states=(
            replace(
                KARTOGRAF,
                status="incompatible",
                package_version="0.7.2",
                detail="version outside range",
            ),
        )
    )

    status, out = run_cli(paths, registry, capsys)

    assert status == 1
    assert "zainstalowana wersja 0.7.2 jest niezgodna (wspierane >=0.8.0,<0.9" in out
    assert 'Naprawa: zainstaluj zgodną wersję: pip install "kartograf' in out


def test_doctor_optional_plugin_missing_is_only_a_warning(
    paths: AppPaths, store_root: Path
) -> None:
    """A producer no store uses does not fail the diagnostics."""
    configure(paths, store_root)
    imgw = SourceState(producer="imgw", status="not_installed")

    report = run_doctor(
        paths,
        FakeRegistry(source_states=(KARTOGRAF, imgw)),
        port_available=lambda port: True,
    )

    assert report.errors == 0
    assert any(
        check.level == "warning" and 'pip install "archiwista[imgw]"' in str(check.fix)
        for check in report.checks
    )


def test_doctor_invalid_config_is_an_error(
    paths: AppPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """A broken settings file is reported instead of crashing the command."""
    paths.config_file.parent.mkdir(parents=True)
    paths.config_file.write_text("port = 1\n", encoding="utf-8")

    status, out = run_cli(paths, FakeRegistry(), capsys)

    assert status == 1
    assert "Niepoprawne ustawienie „port”" in out
    assert "Naprawa: popraw plik konfiguracji" in out


def test_doctor_without_config_warns_but_passes(paths: AppPaths) -> None:
    """A fresh installation points at the setup wizard without failing."""
    report = run_doctor(paths, FakeRegistry(), port_available=lambda port: True)

    assert report.errors == 0
    assert report.warnings == 2
    assert not paths.config_file.exists()
    assert not paths.data_dir.exists()


def test_doctor_busy_port_is_a_warning(paths: AppPaths, store_root: Path) -> None:
    """A port in use (possibly by a running server) is reported, not fatal."""
    configure(paths, store_root, port=8123)

    report = run_doctor(paths, FakeRegistry(), port_available=lambda port: False)

    assert report.errors == 0
    assert [check.message for check in report.checks if check.level == "warning"] == [
        "Port 8123 na 127.0.0.1 jest zajęty (może działać już Archiwista)"
    ]


def test_doctor_is_port_available_detects_listener() -> None:
    """A listening socket makes its port unavailable to the server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]

        assert is_port_available(port) is False
