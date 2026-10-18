"""End-to-end ``archiwista doctor`` with the installed plugin registry."""

import os
import subprocess
import sys
from pathlib import Path


def test_doctor_cli_reports_installed_kartograf_plugin(tmp_path: Path) -> None:
    """A fresh installation finds the Kartograf entry point and passes."""
    env = {
        **os.environ,
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }

    result = subprocess.run(
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

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] Wtyczka kartograf: wersja 0.8.0" in result.stdout
    assert not (tmp_path / "config").exists()
