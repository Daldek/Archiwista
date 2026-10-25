"""Consumer-facing checks for the initial command-line entry point."""

import json
import logging
import os
import stat
from pathlib import Path

import pytest

from archiwista.cli import main
from archiwista.logs import ENV_LOG_LEVEL
from tests.fixtures.cli_errors import refusal
from tests.fixtures.local_server import NoSources, local_paths


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


def _logged_by_a_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    before: tuple[str, ...] = (),
    after: tuple[str, ...] = (),
) -> tuple[int, str, str]:
    """Run ``sources --json`` with options around it, then log at every level.

    The four log calls come after the command, as the logs of a long run do.

    Returns
    -------
    tuple[int, str, str]
        The exit status, what the command wrote to standard output and what
        reached standard error during the whole run.
    """
    status = main(
        [*before, "sources", "--json", *after],
        registry=NoSources(),
        paths=local_paths(tmp_path),
    )
    logger = logging.getLogger("archiwista.cli_test")
    logger.debug("a-debug")
    logger.info("a-info")
    logger.warning("a-warning")
    logger.error("an-error")
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_cli_logs_warnings_and_errors_to_stderr_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without options the logs are quiet, and standard output stays JSON."""
    status, out, err = _logged_by_a_command(tmp_path, capsys)

    assert status == 0
    assert json.loads(out) == {"items": []}
    assert err.splitlines() == [
        "WARNING archiwista.cli_test: a-warning",
        "ERROR archiwista.cli_test: an-error",
    ]


@pytest.mark.parametrize("where", ["before", "after"])
def test_cli_verbose_logs_debug_before_or_after_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    """``--verbose`` is valid on either side of the command name."""
    before, after = (("--verbose",), ()) if where == "before" else ((), ("--verbose",))

    status, out, err = _logged_by_a_command(
        tmp_path, capsys, before=before, after=after
    )

    assert status == 0
    assert json.loads(out) == {"items": []}
    assert err.splitlines() == [
        "DEBUG archiwista.cli_test: a-debug",
        "INFO archiwista.cli_test: a-info",
        "WARNING archiwista.cli_test: a-warning",
        "ERROR archiwista.cli_test: an-error",
    ]


def test_cli_quiet_logs_errors_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--quiet`` leaves the errors of the log."""
    _, _, err = _logged_by_a_command(tmp_path, capsys, after=("--quiet",))

    assert err.splitlines() == ["ERROR archiwista.cli_test: an-error"]


def test_cli_log_level_variable_sets_the_level_and_an_option_beats_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ARCHIWISTA_LOG_LEVEL`` applies unless the command line says otherwise."""
    monkeypatch.setenv(ENV_LOG_LEVEL, "info")

    _, _, from_variable = _logged_by_a_command(tmp_path, capsys)
    _, _, from_option = _logged_by_a_command(tmp_path, capsys, before=("--quiet",))

    assert from_variable.splitlines() == [
        "INFO archiwista.cli_test: a-info",
        "WARNING archiwista.cli_test: a-warning",
        "ERROR archiwista.cli_test: an-error",
    ]
    assert from_option.splitlines() == ["ERROR archiwista.cli_test: an-error"]


def test_cli_refuses_a_log_level_variable_that_names_no_level(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mistyped level is a ``validation_error`` that names the variable."""
    monkeypatch.setenv(ENV_LOG_LEVEL, "loud")

    status = main(["sources"], registry=NoSources(), paths=local_paths(tmp_path))

    captured = capsys.readouterr()
    document = refusal(captured.out, captured.err, status)
    assert document["code"] == "validation_error"
    assert document["details"] == {
        "reason": "invalid_log_level",
        "option": ENV_LOG_LEVEL,
        "value": "loud",
        "allowed": ["debug", "info", "warning", "error"],
    }


def test_cli_refuses_verbose_and_quiet_together_in_any_place(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The options exclude each other, also when one stands before the command."""
    with pytest.raises(SystemExit) as refused:
        main(
            ["--verbose", "sources", "--quiet"],
            registry=NoSources(),
            paths=local_paths(tmp_path),
        )

    captured = capsys.readouterr()
    assert refused.value.code == 2
    document = refusal(captured.out, captured.err, 2)
    assert document["code"] == "validation_error"
    assert document["details"] == {"reason": "usage"}
