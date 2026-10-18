"""Consumer-facing checks for the initial command-line entry point."""

import os
import stat
from pathlib import Path

import pytest

from archiwista.cli import main
from tests.fixtures.local_server import local_paths


def test_cli_help_exits_successfully_in_polish(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Help is usable before any later command implementations are added."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "przeglądarka lokalnego magazynu" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "posix", reason="POSIX modes")
def test_cli_local_data_closed_to_other_accounts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What a command writes locally only its user reads, whatever the umask was."""
    os.umask(0o022)
    paths = local_paths(tmp_path)

    status = main(["token", "--port", "8090"], paths=paths)

    capsys.readouterr()
    written = [paths.data_dir, *paths.data_dir.rglob("*")]
    assert status == 0
    assert paths.index_file in written
    assert stat.S_IMODE(paths.data_dir.stat().st_mode) == 0o700
    assert {
        str(path.relative_to(tmp_path)): stat.S_IMODE(path.stat().st_mode) & 0o077
        for path in written
    } == {str(path.relative_to(tmp_path)): 0 for path in written}
