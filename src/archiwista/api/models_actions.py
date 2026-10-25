"""Models of the producers' commands run as jobs (plan of 2026-10-25, A4, A5; SPEC 9.2).

``JobRequest`` is the body of ``POST /jobs`` and of ``archiwista jobs start``:
the kind of the job, the producer, the configured store, the call of a command
of the producer's catalog and, for a download, the ``check`` job whose plan it
runs; the answer is the ``JobDetail`` of the job. ``ActionPlanInfo`` answers
``GET /jobs/{job}/plan`` and ``archiwista jobs plan``: the plan a ``check``
job kept (ADR-036), its positions as ``PlanEntryItem``. The store root is
never an option: the store's id names it (ADR-034, decision 2). The request
model refuses unknown members and a plan of another kind than ``download``
(``400 validation_error``).
"""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from archiwista.api.models_availability import AvailabilityNoticeItem
from archiwista.index import StoredPlan
from archiwista.services.actions import ActionKind
from archiwista.sources import CommandCall, PlanEntry, PlanStatus

_JOB_ID = "3f9c1a7e5b2d4c60"
_OPTIONS: dict[str, Any] = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}
_REQUEST_EXAMPLE: dict[str, Any] = {
    "kind": "check",
    "producer": "kartograf",
    "store": "zespol",
    "command": "elevation download",
    "options": _OPTIONS,
}
_SEGMENT = "nmt/pl_1992_1m_evrf2007"
_ENTRY_EXAMPLE: dict[str, Any] = {
    "path": f"{_SEGMENT}/N-34-130-D-d-2-2.asc",
    "unit": "N-34-130-D-d-2-2",
    "status": "newer",
    "local_label": "2021",
    "available_label": "2023",
    "size_bytes": None,
    "error": None,
    "conflict": None,
}
_PLAN_EXAMPLE: dict[str, Any] = {
    "job_id": _JOB_ID,
    "store": "zespol",
    "producer": "kartograf",
    "command": "elevation download",
    "line": (
        "kartograf elevation download --product nmt --sheet N-34-130-D-d-2"
        " --resolution 1m --vertical-crs EVRF2007 --root /mnt/nas/kartograf"
    ),
    "root": "/mnt/nas/kartograf",
    "schema": "kartograf-plan/1",
    "checked_at": "2026-10-25T08:15:02Z",
    "ok": True,
    "counts": {
        "current": 1,
        "newer": 1,
        "missing": 1,
        "unverifiable": 1,
        "check_failed": 0,
    },
    "todo": 2,
    "size_bytes": None,
    "size_complete": False,
    "entries": [
        {
            **_ENTRY_EXAMPLE,
            "path": f"{_SEGMENT}/N-34-130-D-d-2-1.asc",
            "unit": "N-34-130-D-d-2-1",
            "status": "current",
            "local_label": "2023",
        },
        _ENTRY_EXAMPLE,
        {
            **_ENTRY_EXAMPLE,
            "path": f"{_SEGMENT}/N-34-130-D-d-2-3.asc",
            "unit": "N-34-130-D-d-2-3",
            "status": "missing",
            "local_label": None,
        },
        {
            **_ENTRY_EXAMPLE,
            "path": f"{_SEGMENT}/N-34-130-D-d-2-4.asc",
            "unit": "N-34-130-D-d-2-4",
            "status": "unverifiable",
            "local_label": "2022",
            "available_label": None,
        },
    ],
    "notices": [],
}


class JobRequest(BaseModel):
    """A job of a producer's command on a configured store (`POST /jobs`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                _REQUEST_EXAMPLE,
                {**_REQUEST_EXAMPLE, "kind": "download", "plan_job": _JOB_ID},
            ]
        },
    )

    kind: ActionKind = Field(
        description=(
            "`check`: plan a run of the command in the store without its effects"
            " (what it would download, the labels, the size when the producer"
            " tells it), over the network; read the plan with `GET"
            " /jobs/{job}/plan`. `download`: run the command in the store, over"
            " the network; it writes the store, so it needs the role"
            " `store_writer` or the setting `store_write_for_all`."
        )
    )
    producer: str = Field(min_length=1, description="Producer id.")
    store: str = Field(
        min_length=1,
        description=(
            "Id of the configured store whose directory of the producer the"
            " command works on, never the producer's default root."
        ),
    )
    command: str = Field(
        min_length=1,
        description=(
            "Command of the producer's catalog (`GET /commands`) that works on a"
            " store (`store`) and has a check (`check`)."
        ),
    )
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The options in the JSON form of the catalog; no option that is a file"
            " path (`path_role`)."
        ),
    )
    plan_job: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "`download` only: the `check` job whose kept plan the run runs, a"
            " plan of the same store, producer, command and options. The run"
            " fetches only its positions to download; one whose source changed"
            " since is a failed item (`conflict`, `stale_plan`). Without it the"
            " run fetches what the source has that the store does not hold."
        ),
        examples=[_JOB_ID],
    )

    @field_validator("plan_job")
    @classmethod
    def _only_a_download_runs_a_plan(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is not None and info.data.get("kind") != "download":
            raise ValueError("only a download runs the plan of a check job")
        return value

    def call(self) -> CommandCall:
        """Return the call of the job's command."""
        return CommandCall(self.producer, self.command, self.options)


class PlanEntryItem(BaseModel):
    """One position of a plan: a file of the run, local and at the source."""

    model_config = ConfigDict(json_schema_extra={"examples": [_ENTRY_EXAMPLE]})

    path: str = Field(
        description="Its place below the store root, `/`-separated.", min_length=1
    )
    unit: str = Field(description="The producer's unit (a sheet, a tile, a station).")
    status: PlanStatus = Field(
        description=(
            "`current` (the store holds the newest version), `newer` (the source"
            " has a newer one), `missing` (the store holds none), `unverifiable`"
            " (the source gives no cheap sign of its version) or `check_failed`"
            " (the source could not be asked: `error`). A run of the plan"
            " downloads `newer` and `missing`."
        )
    )
    local_label: str | None = Field(
        description="Label of the version the store holds; `null` without one."
    )
    available_label: str | None = Field(
        description="Label of the version at the source; `null` when unknown."
    )
    size_bytes: int | None = Field(
        description=(
            "Size of the file at the source when the producer tells it; `null`"
            " when it does not, never 0 for an unknown size."
        )
    )
    error: str | None = Field(
        description="The producer's text of a failed check or of a refused write."
    )
    conflict: str | None = Field(
        description=(
            "Why a run would refuse to write the position, the producer's reason"
            " (`nested_store`, `not_empty`); `null` for one a run may write."
        )
    )

    @classmethod
    def of(cls, entry: PlanEntry) -> Self:
        """Return the model of a position."""
        return cls(
            path=entry.path,
            unit=entry.unit,
            status=entry.status,
            local_label=entry.local_label,
            available_label=entry.available_label,
            size_bytes=entry.size_bytes,
            error=entry.error,
            conflict=entry.conflict,
        )


class ActionPlanInfo(BaseModel):
    """The plan a `check` job kept: what a run of its command would do in the store."""

    model_config = ConfigDict(
        serialize_by_alias=True,
        validate_by_alias=True,
        validate_by_name=True,
        json_schema_extra={"examples": [_PLAN_EXAMPLE]},
    )

    job_id: str = Field(description="The `check` job that made the plan.")
    store: str = Field(description="The configured store the plan is of.")
    producer: str = Field(description="Producer id.")
    command: str = Field(description="The command planned, of the producer's catalog.")
    line: str = Field(
        description=(
            "The producer's command line of the run, with the store's root: the"
            " same run from a terminal."
        )
    )
    root: str = Field(description="The store root the producer planned for.")
    plan_schema: str = Field(
        alias="schema",
        description="Schema of the producer's own plan (`kartograf-plan/1`).",
    )
    checked_at: datetime = Field(description="When the source was asked (UTC).")
    ok: bool = Field(description="Every position was checked: none is `check_failed`.")
    counts: dict[PlanStatus, int] = Field(
        description="Positions of each status, every status named."
    )
    todo: int = Field(description="Positions a run of the plan downloads.")
    size_bytes: int | None = Field(
        description=(
            "Bytes a run downloads as far as the producer tells the sizes of the"
            " positions to download; `null` when it tells none of them, never 0"
            " for an unknown size."
        )
    )
    size_complete: bool = Field(
        description="Every position to download has its size: `size_bytes` is whole."
    )
    entries: list[PlanEntryItem] = Field(
        description="The positions, in the producer's order."
    )
    notices: list[AvailabilityNoticeItem] = Field(
        description="What the producer said while it checked."
    )

    @classmethod
    def of(cls, stored: StoredPlan) -> Self:
        """Return the model of a kept plan."""
        plan = stored.plan
        return cls(
            job_id=stored.job_id,
            store=stored.store,
            producer=plan.producer,
            command=plan.command,
            line=stored.line,
            root=plan.root,
            schema=plan.schema,
            checked_at=plan.checked_at,
            ok=plan.ok,
            counts=plan.counts(),
            todo=len(plan.todo),
            size_bytes=plan.size_bytes,
            size_complete=plan.size_complete,
            entries=[PlanEntryItem.of(entry) for entry in plan.entries],
            notices=[AvailabilityNoticeItem.of(notice) for notice in plan.notices],
        )
