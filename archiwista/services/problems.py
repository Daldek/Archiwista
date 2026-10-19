"""Store and project problems with a Polish explanation and fix instruction.

Every problem is shown, never hidden, and none comes with a delete action:
the instruction tells a person what to do (SPEC 4.6, UC-13).
"""

from dataclasses import dataclass
from datetime import datetime

from archiwista.index import OWN_PROBLEM_CODES, IssueOrigin
from archiwista.messages import MESSAGES

# Codes with their own message and instruction; others use ``problem_other``.
KNOWN_PROBLEMS = frozenset(
    {
        "missing_sidecar",
        "invalid_sidecar",
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


@dataclass(frozen=True, slots=True)
class Problem:
    """A visible problem: what is wrong, where, and how a person fixes it.

    Attributes
    ----------
    code : str
        Stable code (``missing_sidecar``, ``orphan_sidecar``,
        ``missing_pin``, ``unknown_store``…); does not depend on the text.
    message : str
        Polish description naming the place.
    instruction : str
        Polish fix instruction; never a delete action of Archiwista.
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
    """Return the Polish message and instruction of a problem code.

    Parameters
    ----------
    code : str
        Problem code; an unknown one gets the generic texts.
    **values : object
        Values of the texts' placeholders (``path``, ``producer``…).

    Returns
    -------
    tuple[str, str]
        ``(message, instruction)``.
    """
    name = code if code in KNOWN_PROBLEMS else "other"
    fields = _Blank(
        {"code": code, **{key: value for key, value in values.items() if value}}
    )
    return (
        MESSAGES[f"problem_{name}"].format_map(fields),
        MESSAGES[f"fix_{name}"].format_map(fields),
    )


class _Blank(dict[str, object]):
    """Placeholder values; a missing or empty one reads as ``—``."""

    def __missing__(self, key: str) -> object:
        return "—"
