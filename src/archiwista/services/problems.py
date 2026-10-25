"""Store and project problems with an explanation and fix instruction.

Every problem is shown, never hidden, and none comes with a delete action:
the instruction tells a person what to do (SPEC 4.6, UC-13).
"""

from dataclasses import dataclass
from datetime import datetime

from archiwista.index import OWN_PROBLEM_CODES, IssueOrigin
from archiwista.messages import entry, message, placeholders

# Codes with their own message and instruction; others use ``problem_other``.
KNOWN_PROBLEMS = frozenset(
    {
        "missing_sidecar",
        "invalid_sidecar",
        "unknown_schema",
        "unknown_segment",
        "legacy_campaigns",
        "stale_incoming",
        "link_mismatch",
        "orphan_sidecar",
        "missing_pin",
        "pin_sha256_mismatch",
        "invalid_manifest",
        "unknown_store",
        *OWN_PROBLEM_CODES,
    }
)
# Codes whose text depends on the producer, as ``(producer, code)``: their
# entries are ``problem.<producer>_<code>`` and ``fix.<producer>_<code>``.
# IMGWTools' ``missing_sidecar`` is a download in progress or an interrupted
# one, not the file Kartograf's code means.
PRODUCER_TEXTS = frozenset({("imgw", "missing_sidecar")})


@dataclass(frozen=True, slots=True)
class Problem:
    """A visible problem: what is wrong, where, and how a person fixes it.

    Attributes
    ----------
    code : str
        Stable code (``missing_sidecar``, ``orphan_sidecar``,
        ``missing_pin``, ``unknown_store``…); does not depend on the text.
    message : str
        Description naming the place.
    instruction : str
        Fix instruction; never a delete action of Archiwista.
    path : str or None
        Store-relative path the problem is about.
    segment, slot : str or None
        Segment and slot of ``path`` when known.
    project, task : str or None
        Project key and task of a project problem.
    origin : {"scan", "check"} or None
        Who found a store problem: a scan or a check job.
    first_seen_at : datetime or None
        When the problem was first recorded.
    """

    code: str
    message: str
    instruction: str
    path: str | None = None
    segment: str | None = None
    slot: str | None = None
    project: str | None = None
    task: str | None = None
    origin: IssueOrigin | None = None
    first_seen_at: datetime | None = None


def explain(code: str, **values: object) -> tuple[str, str]:
    """Return the message and instruction of a problem code.

    Parameters
    ----------
    code : str
        Problem code; an unknown one gets the generic texts.
    **values : object
        Values of the texts' placeholders (``path``, ``producer``…); a missing
        or empty one reads as ``—``. The ``producer`` also chooses the texts of
        a code that has its own for it (``PRODUCER_TEXTS``).

    Returns
    -------
    tuple[str, str]
        ``(message, instruction)``.
    """
    if (values.get("producer"), code) in PRODUCER_TEXTS:
        name = f"{values['producer']}_{code}"
    else:
        name = code if code in KNOWN_PROBLEMS else "other"
    given = {"code": code, **{key: value for key, value in values.items() if value}}
    return _filled(f"problem.{name}", given), _filled(f"fix.{name}", given)


def _filled(key: str, given: dict[str, object]) -> str:
    """Render ``key`` with ``given``; a placeholder without a value reads ``—``."""
    names = placeholders(entry(key).en)
    return message(key, **{name: given.get(name, "—") for name in names})
