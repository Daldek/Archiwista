"""Consumer-facing checks for the initial command-line entry point."""

import pytest

from archiwista.cli import main


def test_cli_help_exits_successfully_in_polish(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Help is usable before any later command implementations are added."""
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])

    assert exit_info.value.code == 0
    assert "przeglądarka lokalnego magazynu" in capsys.readouterr().out


def test_cli_unknown_command_is_not_silently_accepted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unavailable operation fails instead of claiming to have run it."""
    with pytest.raises(SystemExit) as exit_info:
        main(["serve"])

    assert exit_info.value.code == 2
    assert "serve" in capsys.readouterr().err
