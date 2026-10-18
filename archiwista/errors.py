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


class IndexQueryError(ArchiwistaError):
    """A query of the local index has invalid parameters.

    The message is Polish and names the parameter (cursor, limit, years,
    area or view); the HTTP API answers ``422 validation_error``.
    """


class PermissionDeniedError(ArchiwistaError):
    """The principal may not perform an action (A-ADR-029).

    The message is Polish and says what is missing; the HTTP API answers
    ``403 permission_denied``. A project the principal does not see is
    ``NotFoundError`` instead, so that its existence stays hidden.
    """


class NotFoundError(ArchiwistaError):
    """An account, a group or a project is unknown or not visible (``404``)."""


class ConflictError(ArchiwistaError):
    """A change conflicts with the current state, e.g. a taken id (``409``)."""


class InvalidChangeError(ArchiwistaError):
    """A requested change is invalid (``422 validation_error``).

    For example unknown people or groups, entries that do not fit the
    project's visibility, or a reserved account id; the message is Polish.
    """


class StateError(ArchiwistaError):
    """The state database cannot be used or restored.

    For example a database written by a newer Archiwista, or a backup
    imported into a database that is not empty; the message is Polish.
    """


class JobConflictError(ConflictError):
    """Another job already writes the store's index (``409 conflict``).

    Parameters
    ----------
    message : str
        Polish description naming the job in the way.
    job_id, kind, state : str
        That job, for the problem's ``job`` member.
    """

    def __init__(self, message: str, *, job_id: str, kind: str, state: str) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.kind = kind
        self.state = state


class OfflineModeError(ArchiwistaError):
    """An action needs the network while offline mode is on (``409 offline_mode``)."""


class AreaTooLargeError(ArchiwistaError):
    """An area file is over its size limit (``413 area_too_large``).

    The body is over 50 MB, or an archive declares more than 200 MB once
    unpacked; the message is Polish and gives the size and the limit.
    """


class AreaUnreadableError(ArchiwistaError):
    """An area file cannot be read (``422 area_unreadable``).

    For example an unknown format, an archive member leaving its directory,
    a missing CRS, no polygon, or a read killed after its time limit; the
    message is Polish.

    Parameters
    ----------
    message : str
        Polish description of what is wrong with the file.
    layers : tuple[str, ...], optional
        Layers to choose from when the file has several (``layer=``).
    """

    def __init__(self, message: str, *, layers: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.layers = layers


class AreaTooComplexError(ArchiwistaError):
    """An area has more vertices than allowed (``422 area_too_complex``).

    Archiwista never simplifies an area silently; the message is Polish and
    gives the count and the limit.
    """
