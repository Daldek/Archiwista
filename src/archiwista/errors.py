"""Errors shared by producer adapters and application services.

Every error is an ``ArchiwistaError`` that carries one ``code`` of the shared
error registry (``archiwista._errors``, generated from the Nogat registry,
ERR-1), a ``message``, JSON-compatible ``details`` and an optional ``hint``.
Each class selects a default ``code`` and a default ``reason``, the finer
cause that ERR-1 keeps in ``details["reason"]``. The HTTP API and the command
line report them alike (``archiwista.api.errors``, ``archiwista.error_document``).
A message and a hint are catalog texts (``archiwista.messages``): they stay
translatable, so each interface renders them in the language of its reader.
"""

import copy
from collections.abc import Mapping
from typing import Any, ClassVar

from archiwista._errors import BY_CODE
from archiwista.sources.types import SourceState

# Producer packages whose own errors have a reason of their own.
PRODUCER_REASONS: Mapping[str, str] = {
    "kartograf": "kartograf_error",
    "imgwtools": "imgwtools_error",
}


class ArchiwistaError(Exception):
    """Base error: a registry ``code``, a message, ``details`` and a ``hint``.

    Parameters
    ----------
    message : str, optional
        Description for the user, a catalog text (`archiwista.messages.message`).
    code : str or None, optional
        Registry code; the class default (``default_code``) when omitted.
    reason : str or None, optional
        Finer cause, stored as ``details["reason"]`` (ERR-1); the class
        default (``default_reason``) when omitted.
    details : Mapping[str, object] or None, optional
        JSON-compatible context, copied.
    hint : str or None, optional
        One line telling how to fix the call.

    Attributes
    ----------
    default_code : str
        Registry code of the class.
    default_reason : str or None
        Reason of the class, if it has one.
    code : str
        Registry code of the instance.
    message : str
        The message, also ``str(error)`` (the catalog text itself, not a copy).
    details : dict[str, Any]
        Context; ``details["reason"]`` holds the reason.
    hint : str or None
        The hint, if any.

    Raises
    ------
    ValueError
        If ``code`` is not in the registry.
    """

    default_code: ClassVar[str] = "internal_error"
    default_reason: ClassVar[str | None] = None

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        reason: str | None = None,
        details: Mapping[str, object] | None = None,
        hint: str | None = None,
    ) -> None:
        resolved = self.default_code if code is None else code
        if resolved not in BY_CODE:
            raise ValueError(f"unknown error code {resolved!r}")
        super().__init__(message)
        self.code = resolved
        self.message = message
        self.details: dict[str, Any] = copy.deepcopy(dict(details or {}))
        chosen = self.default_reason if reason is None else reason
        if chosen is not None:
            self.details["reason"] = chosen
        self.hint = hint

    def __str__(self) -> str:
        """Return the message itself, so that a catalog text stays translatable."""
        return self.message

    @property
    def exit_code(self) -> int | None:
        """Int or None: the command-line exit code of ``code`` (ERR §2)."""
        return BY_CODE[self.code].exit_code

    @property
    def http_status(self) -> int | None:
        """Int or None: the HTTP status of ``code`` (ERR §2)."""
        return BY_CODE[self.code].http_status


class SourceStateError(ArchiwistaError):
    """A producer source cannot serve a request in its current state.

    Default code ``missing_dependency``: the plugin is not installed or does
    not fit.

    Parameters
    ----------
    message : str
        Description for the user.
    state : SourceState or None, optional
        State of the producer plugin when the plugin itself is the cause.
    code, reason : str or None, optional
        Registry code and reason instead of the class defaults.
    """

    default_code = "missing_dependency"
    default_reason = "source_unavailable"

    def __init__(
        self,
        message: str,
        *,
        state: SourceState | None = None,
        code: str | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message, code=code, reason=reason)
        self.state = state


class SourceUnavailableError(SourceStateError):
    """Producer package or configured store cannot be reached.

    Without a plugin state the store itself cannot be read: the code is then
    ``store_unavailable`` (reason ``store_unreadable``).
    """

    def __init__(self, message: str, *, state: SourceState | None = None) -> None:
        if state is None:
            super().__init__(
                message, code="store_unavailable", reason="store_unreadable"
            )
        else:
            super().__init__(message, state=state)


class SourceIncompatibleError(SourceStateError):
    """Producer version or store schema is unsupported."""

    default_reason = "source_incompatible"


class ProducerError(ArchiwistaError):
    """A producer library rejected an operation; its own message is kept.

    Default code ``data_error``; the reason is ``<package>_error``.

    Parameters
    ----------
    package : str
        Producer package that raised, e.g. ``"kartograf"``.
    exception : str
        Class name of the producer's exception, e.g. ``"ValidationError"``.
    message : str
        The producer's message, unchanged.
    """

    default_code = "data_error"

    def __init__(self, package: str, exception: str, message: str) -> None:
        super().__init__(
            message,
            reason=PRODUCER_REASONS.get(package, "producer_error"),
            details={package: {"exception": exception, "message": message}},
        )
        self.package = package
        self.exception = exception


class PathOutsideRootError(ArchiwistaError):
    """A requested path escapes its configured store or project root."""

    default_code = "forbidden"
    default_reason = "path_outside_root"


class SnapshotError(ArchiwistaError):
    """An own-data snapshot could not be made consistently."""

    default_code = "io_error"
    default_reason = "snapshot_failed"


class SnapshotBlockedError(SnapshotError):
    """A snapshot may not be made now (``conflict``, reason ``snapshot_blocked``).

    ``reason`` is ``folder_invalid`` (the data folder breaks the rules of
    plan v0.2 decision 8), ``read_only_folder``, ``insufficient_space`` or
    ``file_missing``, also ``details["blocked_by"]``; the message says what
    to do.
    """

    default_code = "conflict"
    default_reason = "snapshot_blocked"

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message, details={"blocked_by": reason})
        self.reason = reason


class SnapshotFailedError(SnapshotError):
    """A snapshot was not published; its ``reason`` says why.

    The reasons are ``inconsistent_copy`` (the file kept changing while it was
    copied), ``checksum_mismatch`` (written bytes differ from those read),
    ``integrity_failed`` (the SQLite copy fails ``PRAGMA integrity_check``) and
    ``target_exists`` (another process published the label first); the code
    follows from the reason (``_CODES``).
    """

    _CODES: ClassVar[Mapping[str, str]] = {
        "inconsistent_copy": "conflict",
        "target_exists": "conflict",
        "checksum_mismatch": "data_error",
        "integrity_failed": "data_error",
    }

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(
            message, code=self._CODES.get(reason, self.default_code), reason=reason
        )


class InconsistentReadError(ArchiwistaError):
    """An own-data file changed while it was read or copied (decision 8).

    A SQLite file read in place differs before and after the read, or the
    copy of a file with its ``-wal`` did not hold in any attempt. A later
    read gives a consistent result. The message is English and never
    contains the path.
    """

    default_code = "conflict"
    default_reason = "inconsistent_read"


class OwnReaderError(ArchiwistaError):
    """The own-data reader process did not start or answered out of turn.

    The process (``archiwista.owndata.reader``) ended or stayed silent before
    it was ready, e.g. without the GDAL bindings it imports; no file can be
    read until that is fixed.
    """

    default_code = "missing_dependency"
    default_reason = "own_reader_failed"


class IndexQueryError(ArchiwistaError):
    """A query of the local index has invalid parameters.

    The message names the parameter (cursor, limit, years,
    area or view); the HTTP API answers ``400 validation_error``.
    """

    default_code = "validation_error"


class PermissionDeniedError(ArchiwistaError):
    """The principal may not perform an action (A-ADR-029).

    The message says what is missing; the HTTP API answers
    ``403 forbidden`` with the reason ``permission_denied``. A project the
    principal does not see is ``NotFoundError`` instead, so that its
    existence stays hidden.
    """

    default_code = "forbidden"
    default_reason = "permission_denied"


class NotFoundError(ArchiwistaError):
    """An account, a group or a project is unknown or not visible (``404``)."""

    default_code = "not_found"


class ConflictError(ArchiwistaError):
    """A change conflicts with the current state, e.g. a taken id (``409``)."""

    default_code = "conflict"


class UnsupportedError(ArchiwistaError):
    """A request is valid but this combination is not supported (``422``).

    For example a link check of a store whose producer cannot confirm links;
    the message says why.
    """

    default_code = "unsupported"


class InvalidChangeError(ArchiwistaError):
    """A requested change is invalid (``400 validation_error``).

    For example unknown people or groups, entries that do not fit the
    project's visibility, or a reserved account id.
    """

    default_code = "validation_error"


class StateError(ArchiwistaError):
    """The state database cannot be used or restored.

    For example a database written by a newer Archiwista, or a backup
    imported into a database that is not empty.
    """

    default_code = "store_unavailable"
    default_reason = "state_database"


class JobConflictError(ConflictError):
    """Another job already writes the store's index (``409 conflict``).

    Parameters
    ----------
    message : str
        Description naming the job in the way.
    job_id, kind, state : str
        That job, for the problem's ``details["job"]``.
    """

    def __init__(self, message: str, *, job_id: str, kind: str, state: str) -> None:
        super().__init__(
            message, details={"job": {"id": job_id, "kind": kind, "state": state}}
        )
        self.job_id = job_id
        self.kind = kind
        self.state = state


class OfflineModeError(ArchiwistaError):
    """An action needs the network while offline mode is on (``409 conflict``)."""

    default_code = "conflict"
    default_reason = "offline_mode"


class AreaTooLargeError(ArchiwistaError):
    """An area file is over its size limit (``400 validation_error``).

    The body is over 50 MB, or an archive declares more than 200 MB once
    unpacked; the message gives the size and the limit.
    """

    default_code = "validation_error"
    default_reason = "area_too_large"


class AreaUnreadableError(ArchiwistaError):
    """An area file cannot be read (``data_error``, reason ``area_unreadable``).

    For example an unknown format, an archive member leaving its directory,
    a missing CRS, no polygon, or a read killed after its time limit; the
    message says why.

    Parameters
    ----------
    message : str
        Description of what is wrong with the file.
    layers : tuple[str, ...], optional
        Layers to choose from when the file has several (``layer=``).
    """

    default_code = "data_error"
    default_reason = "area_unreadable"

    def __init__(self, message: str, *, layers: tuple[str, ...] = ()) -> None:
        super().__init__(message, details={"layers": list(layers)} if layers else None)
        self.layers = layers


class AreaTooComplexError(ArchiwistaError):
    """An area has more vertices than allowed (``400 validation_error``).

    Archiwista never simplifies an area silently; the message gives the count
    and the limit.
    """

    default_code = "validation_error"
    default_reason = "area_too_complex"


class FormatRefusedError(ArchiwistaError):
    """A file may not be opened as its format (preview reason ``unsupported_format``).

    Raised by ``archiwista.formats`` before GDAL opens anything: a format
    without that kind of reading, a wrong signature, a MapInfo table other
    than a native one, a path GDAL would split. The message is English and
    never contains the path.
    """

    default_code = "unsupported"
    default_reason = "format_refused"


class PreviewBusyError(ArchiwistaError):
    """The render queue is full (``429 rate_limited`` with ``Retry-After``).

    Parameters
    ----------
    message : str
        Description of the full queue.
    retry_after_s : int
        Seconds after which asking again is likely to succeed.
    """

    default_code = "rate_limited"
    default_reason = "preview_busy"

    def __init__(self, message: str, *, retry_after_s: int) -> None:
        super().__init__(message, details={"retry_after_s": retry_after_s})
        self.retry_after_s = retry_after_s


class PreviewTimeoutError(ArchiwistaError):
    """A render process ran past the time limit of its operation.

    ``422 calculation_error``, reason ``preview_timeout``. The process was
    killed, and the same request fails at once for 10 minutes (decision 3).
    """

    default_code = "calculation_error"
    default_reason = "preview_timeout"


class PreviewUnavailableError(ArchiwistaError):
    """A file has no preview of the kind asked for (``422 unsupported``).

    Raised by renderers and by the render pool, never with a path in it.

    Parameters
    ----------
    reason : str
        Reason code (``PreviewReason``, e.g. ``no_crs``, ``unreadable``);
        its description and fix are ``preview.reason_<code>`` and
        ``preview.fix_<code>`` of the message catalog. The problem reports it
        as ``details["preview_reason"]``.
    detail : str or None, optional
        English message of the library behind it, without paths.
    """

    default_code = "unsupported"
    default_reason = "preview_unavailable"

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


class InvalidRefError(ArchiwistaError):
    """A reference to an object is not one (``400 validation_error``).

    References are ``version:<store>:<path>``, ``file:<project>:<path>`` and
    ``snapshot:<project>:<label>:<path>`` (decision 10); the message quotes the
    reference.
    """

    default_code = "validation_error"
    default_reason = "invalid_ref"


class OwnFileChangedError(ArchiwistaError):
    """An own-data working file changed since its scan (``409 conflict``).

    Its preview would show content the index does not know (decision 8):
    the sizes and times of its files differ from what the last ``own_scan``
    recorded, before or after a render. The message says to refresh the
    project's own data (``POST /projects/{project}/scan``).
    """

    default_code = "conflict"
    default_reason = "own_file_changed"


class PreviewParameterError(ArchiwistaError):
    """A parameter does not fit the file (``400 validation_error``).

    A style not among the file's styles, a layer it does not have: what the
    request model cannot know before the file's probe.

    Parameters
    ----------
    field : str
        Where the value came from, e.g. ``query.style``.
    message : str
        Description naming the value and what is allowed.
    """

    default_code = "validation_error"

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class PreviewNotReadyError(ArchiwistaError):
    """A preview needs its build first (``409 conflict``).

    The map tiles of a file whose local COG is not in the preview cache yet
    (decision 6). The problem names a visible ``preview`` job building it
    (``details["job"]``), reports ``building`` without an ID for a hidden
    job, or says ``build_required`` when none does.

    Parameters
    ----------
    message : str
        Description of what is not ready.
    job_id, kind, state : str or None, optional
        The job building the preview, if any.
    """

    default_code = "conflict"
    default_reason = "preview_not_ready"

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
