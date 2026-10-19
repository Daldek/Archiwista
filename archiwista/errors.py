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


class SnapshotBlockedError(SnapshotError):
    """A snapshot may not be made now (``409 snapshot_blocked`` with ``reason``).

    ``reason`` is ``folder_invalid`` (the data folder breaks the rules of
    plan v0.2 decision 8), ``read_only_folder``, ``insufficient_space`` or
    ``file_missing``; the message is Polish and says what to do.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class SnapshotFailedError(SnapshotError):
    """A snapshot was not published; ``code`` is the ``snapshot`` job's error.

    ``inconsistent_copy`` (the file kept changing while it was copied),
    ``checksum_mismatch`` (written bytes differ from those read),
    ``integrity_failed`` (the SQLite copy fails ``PRAGMA integrity_check``) or
    ``target_exists`` (another process published the label first). The
    message is Polish.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class InconsistentReadError(ArchiwistaError):
    """An own-data file changed while it was read or copied (decision 8).

    A SQLite file read in place differs before and after the read, or the
    copy of a file with its ``-wal`` did not hold in any attempt. A later
    read gives a consistent result. The message is English and never
    contains the path.
    """


class OwnReaderError(ArchiwistaError):
    """The own-data reader process did not start or answered out of turn.

    The process (``archiwista.owndata.reader``) ended or stayed silent before
    it was ready, e.g. without the GDAL bindings it imports; no file can be
    read until that is fixed.
    """


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


class FormatRefusedError(ArchiwistaError):
    """A file may not be opened as its format (preview reason ``unsupported_format``).

    Raised by ``archiwista.formats`` before GDAL opens anything: a format
    without that kind of reading, a wrong signature, a MapInfo table other
    than a native one, a path GDAL would split. The message is English and
    never contains the path.
    """


class PreviewBusyError(ArchiwistaError):
    """The render queue is full (``503 preview_busy`` with ``Retry-After``).

    Parameters
    ----------
    message : str
        Polish description.
    retry_after_s : int
        Seconds after which asking again is likely to succeed.
    """

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class PreviewTimeoutError(ArchiwistaError):
    """A render process ran past the time limit of its operation.

    ``504 preview_timeout``; the message is Polish. The process was killed,
    and the same request fails at once for 10 minutes (decision 3).
    """


class PreviewUnavailableError(ArchiwistaError):
    """A file has no preview of the kind asked for (``409 preview_unavailable``).

    Raised by renderers and by the render pool, never with a path in it.

    Parameters
    ----------
    reason : str
        Reason code (``PreviewReason``, e.g. ``no_crs``, ``unreadable``);
        its Polish description and fix are ``preview_reason_<code>`` and
        ``preview_fix_<code>`` of ``MESSAGES``.
    detail : str or None, optional
        English message of the library behind it, without paths.
    """

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class InvalidRefError(ArchiwistaError):
    """A reference to an object is not one (``422 invalid_ref``).

    References are ``version:<store>:<path>``, ``file:<project>:<path>`` and
    ``snapshot:<project>:<label>:<path>`` (decision 10); the message is
    Polish and quotes the reference.
    """


class OwnFileChangedError(ArchiwistaError):
    """An own-data working file changed since its scan (``409 own_file_changed``).

    Its preview would show content the index does not know (decision 8):
    the sizes and times of its files differ from what the last ``own_scan``
    recorded, before or after a render. The message is Polish and says to
    refresh the project's own data (``POST /projects/{project}/scan``).
    """


class PreviewParameterError(ArchiwistaError):
    """A parameter does not fit the file (``422 validation_error``).

    A style not among the file's styles, a layer it does not have: what the
    request model cannot know before the file's probe.

    Parameters
    ----------
    field : str
        Where the value came from, e.g. ``query.style``.
    message : str
        Polish description naming the value and what is allowed.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class PreviewNotReadyError(ArchiwistaError):
    """A preview needs its build first (``409 preview_not_ready``).

    The map tiles of a file whose local COG is not in the preview cache yet
    (decision 6). The problem names the ``preview`` job building it, or says
    ``build_required`` when none does.

    Parameters
    ----------
    message : str
        Polish description.
    job_id, kind, state : str or None, optional
        The job building the preview, if any.
    """

    def __init__(
        self,
        message: str,
        *,
        job_id: str | None = None,
        kind: str | None = None,
        state: str | None = None,
    ) -> None:
        super().__init__(message)
        self.job_id = job_id
        self.kind = kind
        self.state = state
