"""End-to-end ``archiwista doctor`` with the installed plugin registry."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from archiwista.config import AppSettings, ConfigStore, TeamSettings
from tests.fixtures.isolation import Canary
from tests.fixtures.team_server import team_tls


def _doctor(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Run ``archiwista doctor`` as a fresh installation would, under ``tmp_path``."""
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from archiwista.cli import main; raise SystemExit(main())",
            "doctor",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_doctor_cli_reports_installed_kartograf_plugin(tmp_path: Path) -> None:
    """A fresh installation finds both entry points and passes, installed or not."""
    result = _doctor(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] Wtyczka kartograf: wersja 0.8.0" in result.stdout
    assert "] Wtyczka imgw: " in result.stdout
    assert not (tmp_path / "config").exists()


def test_doctor_cli_names_the_default_store_root_of_kartograf(
    tmp_path: Path, producer_canary: Canary
) -> None:
    """The root Kartograf would use, and the variable that gave it, are printed."""
    result = _doctor(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "[OK] Wtyczka kartograf: domyślny katalog główny magazynu"
        f" {producer_canary.kartograf_root} (zmienna KARTOGRAF_ROOT; nie istnieje)"
    ) in result.stdout
    assert producer_canary.appeared() == []


def test_doctor_cli_names_the_default_store_root_of_imgw(
    tmp_path: Path, producer_canary: Canary
) -> None:
    """The root IMGWTools would use, and the variable that gave it, are printed."""
    pytest.importorskip("imgwtools")

    result = _doctor(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "[OK] Wtyczka imgw: domyślny katalog główny magazynu"
        f" {producer_canary.imgw_root} (zmienna IMGW_ROOT; nie istnieje)"
    ) in result.stdout
    assert producer_canary.appeared() == []


def _configure(tmp_path: Path, team: TeamSettings) -> None:
    """Write the settings file ``_doctor`` reads, with the table ``[team]``."""
    config = ConfigStore(tmp_path / "config" / "archiwista" / "config.toml")
    config.save(AppSettings(team=team))


def test_doctor_cli_reports_team_mode(tmp_path: Path) -> None:
    """The origin, the TLS pair, a key others may read, and the trusted proxies."""
    tls = team_tls(tmp_path / "tls")
    tls.key.chmod(0o644)
    team = TeamSettings(
        enabled=True,
        origin="https://archiwista.firma.local",
        tls_cert=tls.cert,
        tls_key=tls.key,
        trusted_proxies=("127.0.0.1", "10.0.0.0/24"),
    )
    _configure(tmp_path, team)

    result = _doctor(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    assert "[OK] Tryb zespołu: ludzie otwierają https://archiwista.firma.local" in lines
    assert (
        f"[OK] Tryb zespołu: TLS w serwerze, certyfikat {tls.cert} i klucz {tls.key}"
        " wczytują się jako para"
    ) in lines
    assert (
        f"[UWAGA] Klucz TLS {tls.key} jest dostępny dla innych kont tego komputera"
        " (uprawnienia 0644)"
    ) in lines
    assert (
        f"    Naprawa: chmod 600 {tls.key} (do odczytu tylko przez konto serwera)"
        in (lines)
    )
    assert (
        "[OK] Tryb zespołu: zaufane serwery pośredniczące 127.0.0.1, 10.0.0.0/24"
        in lines
    )


def test_doctor_cli_reports_team_mode_without_tls_as_an_error(tmp_path: Path) -> None:
    """Neither TLS files nor a trusted proxy: the error serve would refuse with."""
    _configure(
        tmp_path, TeamSettings(enabled=True, origin="https://archiwista.firma.local")
    )

    result = _doctor(tmp_path)

    assert result.returncode == 10, result.stdout + result.stderr
    assert "[BŁĄD] Tryb zespołu wymaga TLS" in result.stdout
    assert "Tryb zespołu: zaufane serwery" not in result.stdout
