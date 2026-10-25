"""The error of a job that did not succeed (``GET /jobs/{id}``, the final event).

A job's error is described as the problem of a request is
(``archiwista.error_document``): a ``code`` of the shared error registry
(``archiwista._errors``, ERR §2), a Polish ``detail``, a ``hint`` when a fix is
known and the JSON ``details``, whose ``reason`` is the project's own cause
(ERR-1) and the rest the context (``blocked_by`` of a blocked snapshot,
``source`` of an unusable producer plugin). The worker reports an
``ArchiwistaError`` through that description, so the problem of a request and
the error of a job agree on one cause.

Jobs recorded before the registry codes (0.2.x) kept a code of their own
(``worker_crashed``, ``snapshot_blocked``, ``kartograf_error``…) and no
``details``. Such a row is read as the error it would be now (``from_json``):
the old code becomes the ``reason``, the registry code is the one in
``_JOB_CODES``, and the cause of a blocked snapshot moves to
``details["blocked_by"]``. The row itself is never rewritten, so the history
needs no migration; a stored error with a ``details`` member is a current one.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Self

from archiwista._errors import BY_CODE
from archiwista.error_document import describe
from archiwista.errors import ArchiwistaError
from archiwista.jobs.protocol import CODE_INTERNAL_ERROR, JsonObject

# The registry code and the reason that each job code of 0.2.x became; a
# registry code that is not here stays as it was, ``<package>_error`` (a
# producer's own error) is a ``data_error`` and any other code an
# ``internal_error`` that keeps the old code as its reason.
_JOB_CODES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "store_unavailable": ("store_unavailable", "store_unreadable"),
        "source_unavailable": ("missing_dependency", "source_unavailable"),
        "source_incompatible": ("missing_dependency", "source_incompatible"),
        "own_reader_failed": ("missing_dependency", "own_reader_failed"),
        "offline_mode": ("conflict", "offline_mode"),
        "snapshot_blocked": ("conflict", "snapshot_blocked"),
        "inconsistent_copy": ("conflict", "inconsistent_copy"),
        "target_exists": ("conflict", "target_exists"),
        "checksum_mismatch": ("data_error", "checksum_mismatch"),
        "integrity_failed": ("data_error", "integrity_failed"),
        "path_outside_root": ("forbidden", "path_outside_root"),
        "worker_crashed": (CODE_INTERNAL_ERROR, "worker_crashed"),
        "protocol_error": (CODE_INTERNAL_ERROR, "protocol_error"),
        "interrupted": ("cancelled", "interrupted"),
    }
)


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job did not succeed.

    Attributes
    ----------
    code : str
        Code of the shared error registry (ERR §2).
    detail : str
        Polish description of what happened; for a crashed worker it names
        the job's log.
    details : Mapping[str, Any]
        JSON object: ``reason``, the job's own cause (ERR-1), and the context
        of the error (``blocked_by``, ``source``, ``<package>``…).
    hint : str or None
        Polish line telling how to fix it, when a fix is known.
    """

    code: str
    detail: str
    details: Mapping[str, Any] = field(default_factory=dict)
    hint: str | None = None

    @property
    def reason(self) -> str | None:
        """Str or None: the job's own cause, ``details["reason"]``."""
        reason = self.details.get("reason")
        return reason if isinstance(reason, str) else None

    @classmethod
    def of(cls, error: ArchiwistaError) -> Self:
        """Return the error of a job that ended with ``error`` (``describe``)."""
        problem = describe(error)
        return cls(problem.code, problem.detail, dict(problem.details), problem.hint)

    @classmethod
    def from_message(cls, data: Mapping[str, Any]) -> Self:
        """Return the error a worker reported in its ``error`` message.

        The message has a registry ``code`` and a ``detail`` (the protocol
        checks it), and ``hint`` and ``details`` when it has any.
        """
        hint = data.get("hint")
        return cls(
            str(data["code"]),
            str(data["detail"]),
            dict(data.get("details") or {}),
            None if hint is None else str(hint),
        )

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        """Return the error a ``to_json`` document holds, or a 0.2.x one's.

        A document without ``details`` has the job code of 0.2.x in ``code``
        and, for a blocked snapshot, why in ``reason``; it is read as the
        error it would be now (see the module).
        """
        if "details" in data:
            hint = data.get("hint")
            return cls(
                str(data["code"]),
                str(data["detail"]),
                dict(data["details"]),
                None if hint is None else str(hint),
            )
        old = str(data["code"])
        if old in _JOB_CODES:
            code, reason = _JOB_CODES[old]
        elif old in BY_CODE:
            code, reason = old, None
        elif old.endswith("_error"):
            code, reason = "data_error", old
        else:
            code, reason = CODE_INTERNAL_ERROR, old
        details: dict[str, Any] = {} if reason is None else {"reason": reason}
        blocked_by = data.get("reason")
        if old == "snapshot_blocked" and isinstance(blocked_by, str):
            details["blocked_by"] = blocked_by
        return cls(code, str(data["detail"]), details)

    def to_json(self) -> JsonObject:
        """Return the error as kept and sent: a JSON object.

        ``code``, ``detail``, ``hint`` (left out when there is none) and
        ``details``, which is always there, even empty: it tells a current
        error from a 0.2.x one (``from_json``).
        """
        data: JsonObject = {"code": self.code, "detail": self.detail}
        if self.hint:
            data["hint"] = self.hint
        data["details"] = dict(self.details)
        return data
