"""Logging of the command line and the server: one handler on standard error (DEV-12).

The package creates loggers with ``logging.getLogger(__name__)`` and never
configures a handler; the command line does, here, once per run. The level is
``debug`` for ``--verbose``, ``error`` for ``--quiet``, else the value of
``ARCHIWISTA_LOG_LEVEL``, else ``warning`` (DEV-12.2). Logs and progress go to
standard error, never to standard output (AGI-3.2), and never hold a secret or
a credential-bearing address (DEV-12.3).
"""

import logging
import os
import sys
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final, TextIO

ENV_LOG_LEVEL: Final = "ARCHIWISTA_LOG_LEVEL"
LOG_LEVELS: Final[Mapping[str, int]] = MappingProxyType(
    {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }
)
DEFAULT_LOG_LEVEL: Final = "warning"
_LOGGER_NAME: Final = "archiwista"
_FORMAT: Final = "%(levelname)s %(name)s: %(message)s"


class InvalidLogLevelError(ValueError):
    """``ARCHIWISTA_LOG_LEVEL`` names no level.

    Attributes
    ----------
    value : str
        What the variable holds.
    """

    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


def resolve_log_level(
    *, verbose: bool, quiet: bool, environ: Mapping[str, str] | None = None
) -> str:
    """Return the name of the log level a command runs with.

    Parameters
    ----------
    verbose, quiet : bool
        ``--verbose`` and ``--quiet``; the command line refuses both at once.
    environ : Mapping[str, str] or None, optional
        The environment for ``ARCHIWISTA_LOG_LEVEL``; the process's own when
        omitted.

    Returns
    -------
    str
        A key of ``LOG_LEVELS``: ``debug`` for ``--verbose``, ``error`` for
        ``--quiet``, else the variable (any case), else ``warning``.

    Raises
    ------
    InvalidLogLevelError
        The variable is set and names no level.
    """
    if verbose:
        return "debug"
    if quiet:
        return "error"
    value = (os.environ if environ is None else environ).get(ENV_LOG_LEVEL, "")
    name = value.strip().lower()
    if not name:
        return DEFAULT_LOG_LEVEL
    if name not in LOG_LEVELS:
        raise InvalidLogLevelError(value)
    return name


def process_log_level(default: str, environ: Mapping[str, str] | None = None) -> int:
    """Return the level of a process that has no command line, e.g. a worker.

    Parameters
    ----------
    default : str
        A key of ``LOG_LEVELS``, used when the variable is unset or invalid
        (the command that started the process already refused an invalid one).
    environ : Mapping[str, str] or None, optional
        The environment; the process's own when omitted.
    """
    env = os.environ if environ is None else environ
    return LOG_LEVELS.get(
        env.get(ENV_LOG_LEVEL, "").strip().lower(), LOG_LEVELS[default]
    )


def configure_logging(level: str, stream: TextIO | None = None) -> None:
    """Send the logs of the package to ``stream`` at ``level``.

    Calling it again replaces the handler and the level, so a process that
    runs the command line several times (tests) keeps one handler.

    Parameters
    ----------
    level : str
        A key of ``LOG_LEVELS``.
    stream : TextIO or None, optional
        Where the lines go; standard error when omitted.
    """
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(LOG_LEVELS[level])
    # The command line owns the output: a record reaches one handler only.
    logger.propagate = False
