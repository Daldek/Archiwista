"""End-to-end ``archiwista doctor`` with the installed plugin registry."""

import os
import subprocess
import sys
from pathlib import Path

from tests.fixtures.isolation import Canary


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
