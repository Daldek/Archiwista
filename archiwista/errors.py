"""Errors shared by producer adapters and application services."""

from archiwista.sources.types import SourceState


class ArchiwistaError(Exception):
    """Base error for Archiwista operations."""


class SourceStateError(ArchiwistaError):
    """A producer source cannot serve a request in its current state.

    Parameters
    ----------
    message : str
        Polish description for the user.
    state : SourceState or None, optional
        State of the producer plugin when the plugin itself is the cause.
    """

    def __init__(self, message: str, *, state: SourceState | None = None) -> None:
        super().__init__(message)
        self.state = state


class SourceUnavailableError(SourceStateError):
    """Producer package or configured store cannot be reached."""


class SourceIncompatibleError(SourceStateError):
    """Producer version or store schema is unsupported."""


class ProducerError(ArchiwistaError):
    """A producer library rejected an operation; its own message is kept.

    Parameters
    ----------
    package : str
        Producer package that raised, e.g. ``"kartograf"``.
    exception : str
        Class name of the producer's exception, e.g. ``"ValidationError"``.
    message : str
        The producer's message, unchanged.
    """

    def __init__(self, package: str, exception: str, message: str) -> None:
        super().__init__(message)
        self.package = package
        self.exception = exception
        self.message = message


class PathOutsideRootError(ArchiwistaError):
    """A requested path escapes its configured store or project root."""


class SnapshotError(ArchiwistaError):
    """An own-data snapshot could not be made consistently."""
