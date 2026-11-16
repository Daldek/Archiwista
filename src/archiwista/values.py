"""Values of documents and rows Archiwista reads: taken only with the expected type.

A member of a producer's sidecar, a field of a JSON document or a column of a
local database is used only when it has the type asked for; anything else
counts as absent. Standard library only: the adapters, the index and the job
processes share it.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any


def as_mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` when it is a mapping, else an empty one."""
    return value if isinstance(value, Mapping) else {}


def as_text(value: object) -> str | None:
    """Return ``value`` when it is a text that is not empty, else ``None``."""
    return value if isinstance(value, str) and value else None


def as_date(value: object) -> date | None:
    """Return the date of an ISO 8601 text, else ``None``."""
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def as_datetime(value: object) -> datetime | None:
    """Return the time of an ISO 8601 text, else ``None``."""
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
