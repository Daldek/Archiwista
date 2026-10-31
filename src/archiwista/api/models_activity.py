"""API models of a project's activity (A-ADR-049 decision 14).

The entries of the action log about a project, as whoever sees the project
reads them: without the client address, the session and the states before
and after, which stay the administrators' (``ActionEntryModel`` of ``GET
/log``). The query model refuses unknown parameters.
"""

from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.services.activity import ActivityPage
from archiwista.state import ActionEntry, ActorKind

# The entries the card shows at first; a page is at most ``MAX_ACTIVITY_LIMIT``.
DEFAULT_ACTIVITY_LIMIT = 20
MAX_ACTIVITY_LIMIT = 100

_PINNED_EXAMPLE: dict[str, Any] = {
    "id": 1311,
    "at": "2026-10-31T09:14:02Z",
    "actor": "marek.lis",
    "actor_name": "Marek Lis",
    "actor_kind": "user",
    "action": "project.pin",
    "outcome": "ok",
    "details": {"group": "NMT 2023", "pins": 4},
}
_STARTED_EXAMPLE: dict[str, Any] = {
    "id": 1290,
    "at": "2026-10-30T15:40:51Z",
    "actor": "marek.lis",
    "actor_name": "Marek Lis",
    "actor_kind": "agent",
    "action": "job.start",
    "outcome": "ok",
    "details": {
        "kind": "download",
        "store": "zespol",
        "project": "raba",
        "group": "NMT 2023",
    },
}


class ProjectActivityQuery(BaseModel):
    """The page of `GET /projects/{project}/activity`, newest entry first."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(
        default=DEFAULT_ACTIVITY_LIMIT,
        ge=1,
        le=MAX_ACTIVITY_LIMIT,
        description="Page size.",
    )
    cursor: int | None = Field(
        default=None, ge=1, description="`next_cursor` of the previous page."
    )


class ProjectActivityEntry(BaseModel):
    """An entry of a project's activity: who did what to it, when, how it ended."""

    model_config = ConfigDict(json_schema_extra={"examples": [_PINNED_EXAMPLE]})

    id: int = Field(description="Order of the entries: a later one has a greater id.")
    at: datetime = Field(description="When (UTC).")
    actor: str = Field(
        description=(
            "Who: an account id; `local`, the owner of a local installation, also"
            " for the server's scheduler."
        )
    )
    actor_name: str | None = Field(
        description=(
            "The account's name; null for `local` and for an account removed since."
        )
    )
    actor_kind: ActorKind | None = Field(
        description=(
            "How: `local_owner`, `user`, `agent` (acting for `actor`) or"
            " `scheduler`; null for an entry written before v0.4."
        )
    )
    action: str = Field(
        description=(
            "What: `project.create`, `project.update`, `project.area`,"
            " `project.store`, `project.access`, `project.data_dir`,"
            " `project.pin`, `project.unpin`, `project.export`, or `job.start`,"
            " `job.retry` and `job.cancel` of a job of the project."
        )
    )
    outcome: Literal["ok", "failed"] = Field(description="`ok` or `failed`.")
    details: dict[str, Any] | None = Field(
        description=(
            "What else the action tells, e.g. a pin's `group`, a job's `kind` and"
            " `store`."
        )
    )

    @classmethod
    def of(cls, entry: ActionEntry, names: dict[str, str]) -> Self:
        """Return an entry of the log as the project's activity shows it."""
        return cls.model_validate(
            {
                "id": entry.id,
                "at": entry.at,
                "actor": entry.actor,
                "actor_name": names.get(entry.actor),
                "actor_kind": entry.actor_kind,
                "action": entry.action,
                "outcome": entry.outcome,
                "details": entry.details,
            }
        )


class ProjectActivity(BaseModel):
    """A page of a project's activity, newest entry first; `next_cursor` goes on."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"items": [_PINNED_EXAMPLE, _STARTED_EXAMPLE], "next_cursor": 1290}
            ]
        }
    )

    items: list[ProjectActivityEntry]
    next_cursor: int | None = Field(
        description="`cursor` of the next page; null on the last page."
    )

    @classmethod
    def of(cls, found: ActivityPage) -> Self:
        """Return the model of a page of a project's activity."""
        return cls(
            items=[
                ProjectActivityEntry.of(entry, found.names)
                for entry in found.page.entries
            ],
            next_cursor=found.page.next_cursor,
        )
