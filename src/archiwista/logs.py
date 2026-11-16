"""Logging of the command line, the server and its worker processes (DEV-12).

The package creates loggers with ``logging.getLogger(__name__)`` and never
configures a handler; the command line does, here, once per run. The level is
``debug`` for ``--verbose``, ``error`` for ``--quiet``, else the value of
``ARCHIWISTA_LOG_LEVEL``, else ``warning`` (DEV-12.2). Logs and progress go to
standard error, never to standard output (AGI-3.2), and never hold a secret or
a credential-bearing address (DEV-12.3).

``archiwista serve`` keeps Nogat's logs (DEV-12.4 to DEV-12.9, A-ADR-057) with
the module ``archiwista.nogat_logging``, Nogat's reference copied byte for byte:
``server_log`` writes ``nogat-log/1`` records to ``AppPaths.logs_dir``. While
the server serves (``server_logging``) the package's handler on standard error
is set aside, so its records reach the root logger, where the server's log
keeps those of ``warning`` and above as app records; standard error then gets
only the lifecycle records and the errors reduced to their type, whatever the
level the command line asked for (DEV-12.7). A job or render process
(``log_to_server``) writes its warnings and errors as app records to the same
directory; only the server deletes old files.
"""

import io
import logging
import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from typing import Final, TextIO

from archiwista.nogat_logging import ServerLog
from archiwista.shared_settings import TOOL

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


def server_log(directory: Path, *, stream: TextIO | None = None) -> ServerLog:
    """Return the logs of Archiwista's server in ``directory`` (DEV-12.6).

    Parameters
    ----------
    directory : Path
        ``AppPaths.logs_dir``; created when first written.
    stream : TextIO or None, optional
        Where the lifecycle records and the reduced errors go; standard error
        when omitted.
    """
    return ServerLog(TOOL, version(TOOL), directory, stream=stream)


@contextmanager
def server_logging(log: ServerLog, settings: Mapping[str, object]) -> Iterator[None]:
    """Log the server through ``log`` while the block runs (DEV-12.4 to DEV-12.9).

    The package's handler of ``configure_logging`` is set aside and its level
    left to the root logger, then ``log`` starts: the lifecycle record
    ``start`` with ``settings``, the app records of ``warning`` and above of
    every logger, the deletion of the files 14 days old. When the block ends
    ``log`` stops (record ``stop``) and the package's handler, level and
    propagation come back.

    Parameters
    ----------
    log : ServerLog
        The server's logs (``server_log``).
    settings : Mapping of str to object
        The summary of the server's settings for the record ``start``; never a
        secret, a token or an address that carries one.
    """
    package = logging.getLogger(_LOGGER_NAME)
    handlers, level, propagate = (
        list(package.handlers),
        package.level,
        package.propagate,
    )
    for handler in handlers:
        package.removeHandler(handler)
    package.setLevel(logging.NOTSET)
    package.propagate = True
    log.start(settings)
    try:
        yield
    finally:
        log.stop()
        for handler in handlers:
            package.addHandler(handler)
        package.setLevel(level)
        package.propagate = propagate


def log_to_server(directory: Path) -> None:
    """Write this process's warnings and errors to the server's log as well.

    For a job or render process, which the server or a command starts with the
    directory of the server's logs (``AppPaths.logs_dir``): its records of
    ``warning`` and above become app records there (DEV-12.4), whatever the
    level of its own log on standard error, whose handlers keep that level
    and get no reduced record. The process never writes a lifecycle record
    nor deletes a file: only the server does (``server_logging``).

    Parameters
    ----------
    directory : Path
        The directory of the server's logs.
    """
    root = logging.getLogger()
    if root.level > logging.WARNING:
        for handler in root.handlers:
            handler.setLevel(max(handler.level, root.level))
        root.setLevel(logging.WARNING)
    root.addHandler(_ApplicationLog(server_log(directory, stream=_Discarded())))


class _ApplicationLog(logging.Handler):
    """Writes the records of ``warning`` and above as app records of a server log."""

    def __init__(self, log: ServerLog) -> None:
        super().__init__(logging.WARNING)
        self._log = log

    def emit(self, record: logging.LogRecord) -> None:
        """Write ``record`` with ``ServerLog.application``, the logger as its event."""
        try:
            info = record.exc_info
            error = None
            if info is not None and info[1] is not None:
                error = (type(info[1]), info[1], info[2])
            self._log.application(
                record.levelno, record.name, record.getMessage(), error
            )
        except Exception:
            self.handleError(record)


class _Discarded(io.StringIO):
    """A stream that keeps nothing, for the reduced errors of a worker's server log.

    A job process's standard error is the job's own log (``<jobs>/<id>.log``);
    the reduced form of an error belongs on the server's standard error only.
    """

    def write(self, text: str, /) -> int:
        """Drop ``text``; return its length as a write does."""
        return len(text)
