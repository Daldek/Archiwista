"""The error of a job that did not succeed (``GET /jobs/{id}``, the final event).

A job's error is described as the problem of a request is
(``archiwista.error_document``): a ``code`` of the shared error registry
(``archiwista._errors``, ERR §2), a ``detail``, a ``hint`` when a fix is
known and the JSON ``details``, whose ``reason`` is the project's own cause
(ERR-1) and the rest the context (``blocked_by`` of a blocked snapshot,
``source`` of an unusable producer plugin). The worker reports an
``ArchiwistaError`` through that description, so the problem of a request and
the error of a job agree on one cause.

The ``detail`` and the ``hint`` are catalog messages (``archiwista.messages``).
The job ends in another process and is read later, in another language than
the one it failed in, so the error keeps each text with the key and the values
of its message (``key`` and ``values``, ``hint_key`` and ``hint_values`` in
the JSON) beside the text in Polish, the language of the texts that are stored.
Reading renders the message again in the language of the reader
(``localized``); a text with no key, or one the catalog does not know any
more, is read as it was written. The texts inside ``details`` are not kept
this way: they stay in the language they were made in.

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
from archiwista.error_document import Problem, describe
from archiwista.errors import ArchiwistaError
from archiwista.jobs.protocol import CODE_INTERNAL_ERROR, JsonObject
from archiwista.messages import STORED_LANG, Lang, dump, load, localize, localize_json

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


def _put_text(data: JsonObject, text: str, key: str, values: str) -> None:
    """Add the key and the values of a catalog message to a JSON object.

    Parameters
    ----------
    data : dict
        The object to add to.
    text : str
        A `Message`; another string adds nothing.
    key, values : str
        The names of the two members.
    """
    dumped = dump(text)
    if dumped is not None:
        data[key], data[values] = dumped


def _read_text(data: Mapping[str, Any], name: str, key: str, values: str) -> str:
    """Return a text of a JSON object as the catalog message it was, if it was one.

    Parameters
    ----------
    data : Mapping[str, Any]
        The object.
    name : str
        The member with the text.
    key, values : str
        The members with its key and values (``_put_text``), when it has them.

    Returns
    -------
    str
        The message in the language of the running context; the text itself
        when the object has no key or the catalog does not know it.
    """
    return load(data.get(key), data.get(values), str(data[name]))


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job did not succeed.

    Attributes
    ----------
    code : str
        Code of the shared error registry (ERR §2).
    detail : str
        Description of what happened, a catalog message when it has a key;
        for a crashed worker it names the job's log.
    details : Mapping[str, Any]
        JSON object: ``reason``, the job's own cause (ERR-1), and the context
        of the error (``blocked_by``, ``source``, ``<package>``…).
    hint : str or None
        Line telling how to fix it, when a fix is known.
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
        return cls.from_problem(describe(error))

    @classmethod
    def from_problem(cls, problem: Problem) -> Self:
        """Return the error of a job that failed with ``problem``."""
        return cls(problem.code, problem.detail, dict(problem.details), problem.hint)

    @classmethod
    def from_message(cls, data: Mapping[str, Any]) -> Self:
        """Return the error a worker reported in its ``error`` message.

        The message has a registry ``code`` and a ``detail`` (the protocol
        checks it), and ``hint``, ``details`` and the keys and values of the
        two texts when it has any.
        """
        return cls._from_members(data)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Self:
        """Return the error a ``to_json`` document holds, or a 0.2.x one's.

        A document without ``details`` has the job code of 0.2.x in ``code``
        and, for a blocked snapshot, why in ``reason``; it is read as the
        error it would be now (see the module).
        """
        if "details" in data:
            return cls._from_members(data, details=data["details"])
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

    @classmethod
    def _from_members(cls, data: Mapping[str, Any], *, details: object = None) -> Self:
        hint = data.get("hint")
        return cls(
            str(data["code"]),
            _read_text(data, "detail", "key", "values"),
            dict(
                details if isinstance(details, Mapping) else data.get("details") or {}
            ),
            None
            if hint is None
            else _read_text(data, "hint", "hint_key", "hint_values"),
        )

    def localized(self, lang: Lang) -> Self:
        """Return the error with its texts rendered in ``lang``.

        The ``detail``, the ``hint`` and the catalog messages in the
        ``details`` become plain strings, the language of the reader.
        """
        return type(self)(
            self.code,
            localize(self.detail, lang),
            localize_json(self.details, lang),
            None if self.hint is None else localize(self.hint, lang),
        )

    def to_json(self) -> JsonObject:
        """Return the error as kept and sent between processes: a JSON object.

        ``code``, ``detail``, ``hint`` (left out when there is none), the keys
        and values of the texts that are catalog messages, and ``details``,
        which is always there, even empty: it tells a current error from a
        0.2.x one (``from_json``). The texts are in Polish; the keys and
        values let a reader render them again.
        """
        data: JsonObject = {
            "code": self.code,
            "detail": localize(self.detail, STORED_LANG),
        }
        _put_text(data, self.detail, "key", "values")
        if self.hint:
            data["hint"] = localize(self.hint, STORED_LANG)
            _put_text(data, self.hint, "hint_key", "hint_values")
        data["details"] = dict(self.details)
        return data

    def public_json(self, lang: Lang) -> JsonObject:
        """Return the error as the API sends it, in ``lang``.

        ``code``, ``detail``, ``hint`` when there is one and ``details``;
        without the keys and values of the texts.
        """
        shown = self.localized(lang)
        data: JsonObject = {"code": shown.code, "detail": shown.detail}
        if shown.hint:
            data["hint"] = shown.hint
        data["details"] = dict(shown.details)
        return data
