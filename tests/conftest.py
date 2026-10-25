"""Shared test fixtures for Archiwista test suites."""

import logging
import os
import signal
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def interruptible_session() -> Iterator[None]:
    """Run the session with the default SIGINT handling of a foreground run.

    A run started in the background of a non-interactive shell (``cmd &``, a
    script, an agent) ignores SIGINT, and every process the tests start
    inherits that. A job worker is then deaf to the supervisor's interrupt
    until it has imported its modules and installed its handler, so stopping
    a server just after the scheduler started a job waits for the whole run
    of the worker: seconds under load, more than ``serving`` allows. The
    session therefore takes SIGINT back; started processes get the default
    disposition at exec.
    """
    ignored = signal.getsignal(signal.SIGINT) == signal.SIG_IGN
    if ignored:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    yield
    if ignored:
        signal.signal(signal.SIGINT, signal.SIG_IGN)


@pytest.fixture(autouse=True)
def isolate_package_logger() -> Iterator[None]:
    """Undo the handler and level a command puts on the package logger (DEV-12.1)."""
    logger = logging.getLogger("archiwista")
    handlers, level, propagate = list(logger.handlers), logger.level, logger.propagate
    yield
    logger.handlers[:] = handlers
    logger.setLevel(level)
    logger.propagate = propagate


@pytest.fixture(autouse=True)
def restore_umask() -> Iterator[None]:
    """Give every test the umask it started with (``archiwista`` sets 077)."""
    mask = os.umask(0o022)
    os.umask(mask)
    yield
    os.umask(mask)
