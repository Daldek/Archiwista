"""The level of the log: options, variable and default (DEV-12.2)."""

import io
import logging

import pytest

from archiwista.logs import (
    DEFAULT_LOG_LEVEL,
    ENV_LOG_LEVEL,
    InvalidLogLevelError,
    configure_logging,
    process_log_level,
    resolve_log_level,
)


def test_log_level_without_options_or_variable_is_warning() -> None:
    """Nothing asked for: warnings and errors only."""
    assert resolve_log_level(verbose=False, quiet=False, environ={}) == "warning"
    assert DEFAULT_LOG_LEVEL == "warning"


@pytest.mark.parametrize(
    ("verbose", "quiet", "environ", "expected"),
    [
        (True, False, {}, "debug"),
        (False, True, {}, "error"),
        (False, False, {ENV_LOG_LEVEL: "info"}, "info"),
        (False, False, {ENV_LOG_LEVEL: " DEBUG "}, "debug"),
        (False, False, {ENV_LOG_LEVEL: ""}, "warning"),
        # The option of this run beats the variable of the environment.
        (True, False, {ENV_LOG_LEVEL: "error"}, "debug"),
        (False, True, {ENV_LOG_LEVEL: "debug"}, "error"),
    ],
)
def test_log_level_option_beats_variable_beats_default(
    verbose: bool, quiet: bool, environ: dict[str, str], expected: str
) -> None:
    """``--verbose`` and ``--quiet`` first, then the variable, then the default."""
    assert resolve_log_level(verbose=verbose, quiet=quiet, environ=environ) == expected


def test_log_level_variable_naming_no_level_is_refused_with_its_value() -> None:
    """A mistyped variable is an error, not a silent default."""
    with pytest.raises(InvalidLogLevelError) as refused:
        resolve_log_level(verbose=False, quiet=False, environ={ENV_LOG_LEVEL: "loud"})

    assert refused.value.value == "loud"


def test_process_log_level_reads_the_variable_or_keeps_the_default() -> None:
    """A worker takes the variable when it is valid; a bad one never stops it."""
    assert process_log_level("info", {ENV_LOG_LEVEL: "debug"}) == logging.DEBUG
    assert process_log_level("info", {}) == logging.INFO
    assert process_log_level("warning", {ENV_LOG_LEVEL: "loud"}) == logging.WARNING


def test_configure_logging_writes_the_chosen_levels_to_the_stream() -> None:
    """The package's loggers write at the level and to the stream; one handler."""
    # Arrange
    stream = io.StringIO()
    configure_logging("debug", stream)
    configure_logging("warning", stream)
    logger = logging.getLogger("archiwista.logs_test")

    # Act
    logger.debug("hidden")
    logger.warning("shown")

    # Assert
    assert stream.getvalue() == "WARNING archiwista.logs_test: shown\n"
    assert len(logging.getLogger("archiwista").handlers) == 1
