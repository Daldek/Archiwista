"""Models of the producers' commands run as jobs (plan of 2026-10-25, A4, A5; SPEC 9.2).

``JobRequest`` is the body of ``POST /jobs`` and of ``archiwista jobs start``:
the kind of the job, the producer, the configured store, the calls of commands
of the producer's catalog (``CallRequest``; all the lines of a report's row in
one job, ADR-044) and, for a download, the ``check`` job whose plans it runs;
the answer is the ``JobDetail`` of the job. ``ActionPlanInfo`` answers ``GET
/jobs/{job}/plan`` and ``archiwista jobs plan``: the plans a ``check`` job
kept (ADR-036), their totals and one ``CallPlanItem`` per call planned, its
positions as ``PlanEntryItem``. The store root is never an option: the
store's id names it (ADR-034, decision 2). The request model refuses unknown
members and a plan of another kind than ``download`` (``400
validation_error``).
"""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from archiwista.api.models_availability import AvailabilityNoticeItem
from archiwista.index import PlanTotals, StoredPlan
from archiwista.jobs import MAX_JOB_CALLS
from archiwista.projects import MAX_GROUP_NAME_CHARS
from archiwista.services.actions import ActionKind, KeptPlans
from archiwista.sources import CommandCall, PlanEntry, PlanStatus

_JOB_ID = "3f9c1a7e5b2d4c60"
_COMMAND = "elevation download"
_OPTIONS: dict[str, Any] = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}
_NEXT_OPTIONS: dict[str, Any] = {**_OPTIONS, "sheet": "N-34-130-D-d-4"}
_CALL_EXAMPLE: dict[str, Any] = {"command": _COMMAND, "options": _OPTIONS}
_REQUEST_EXAMPLE: dict[str, Any] = {
    "kind": "check",
    "producer": "kartograf",
    "store": "zespol",
    "calls": [_CALL_EXAMPLE, {"command": _COMMAND, "options": _NEXT_OPTIONS}],
}
_ROOT = "/mnt/nas/kartograf"
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
_FIRST_CALL: dict[str, Any] = {
    "call": 0,
    **_CALL_EXAMPLE,
    "line": (
        "kartograf elevation download --product nmt --sheet N-34-130-D-d-2"
        f" --resolution 1m --vertical-crs EVRF2007 --root {_ROOT}"
    ),
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
_NEXT_CALL: dict[str, Any] = {
    **_FIRST_CALL,
    "call": 1,
    "options": _NEXT_OPTIONS,
    "line": _FIRST_CALL["line"].replace("D-d-2", "D-d-4"),
    "counts": {**_FIRST_CALL["counts"], "current": 0, "newer": 0, "unverifiable": 0},
    "todo": 1,
    "entries": [
        {
            **_ENTRY_EXAMPLE,
            "path": f"{_SEGMENT}/N-34-130-D-d-4-1.asc",
            "unit": "N-34-130-D-d-4-1",
            "status": "missing",
            "local_label": None,
        }
    ],
}
_PLAN_EXAMPLE: dict[str, Any] = {
    "job_id": _JOB_ID,
    "store": "zespol",
    "producer": "kartograf",
    "root": _ROOT,
    "checked_at": "2026-10-25T08:15:02Z",
    "ok": True,
    "counts": {
        "current": 1,
        "newer": 1,
        "missing": 2,
        "unverifiable": 1,
        "check_failed": 0,
    },
    "positions": 5,
    "todo": 3,
    "size_bytes": None,
    "size_complete": False,
    "calls": [_FIRST_CALL, _NEXT_CALL],
}


class CallRequest(BaseModel):
    """One call of a job: a command of the producer's catalog and its options."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [_CALL_EXAMPLE]}
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


class JobPin(BaseModel):
    """The project and the new group a download pins its files into."""

    model_config = ConfigDict(extra="forbid")

    project: str = Field(
        min_length=1,
        description="Project id (`project` of /projects).",
        examples=["raba"],
    )
    group: str = Field(
        min_length=1,
        max_length=MAX_GROUP_NAME_CHARS,
        description=(
            "The new group's name: 1 to 80 characters, no control character, no"
            " `/`, free in the project (compared case-folded)."
        ),
        examples=["NMT 2023"],
    )


class JobRequest(BaseModel):
    """A job of a producer's calls on a configured store (`POST /jobs`)."""

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
            "`check`: plan a run of each call in the store without its effects"
            " (what it would download, the labels, the size when the producer"
            " tells it), over the network; read the plans with `GET"
            " /jobs/{job}/plan`. `download`: run the calls in the store, over"
            " the network; it writes the store, so it needs the role"
            " `store_writer` or the setting `store_write_for_all`."
        )
    )
    producer: str = Field(min_length=1, description="Producer id.")
    store: str = Field(
        min_length=1,
        description=(
            "Id of the configured store whose directory of the producer the"
            " calls work on, never the producer's default root."
        ),
    )
    calls: list[CallRequest] = Field(
        min_length=1,
        max_length=MAX_JOB_CALLS,
        description=(
            "The calls, run one after the other in one job: all the lines of a"
            " report's row, or of a pasted list, in their order (one call for"
            " one line). A refusal of one call names its place as"
            " `details.call`, from 0."
        ),
    )
    plan_job: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "`download` only: the `check` job whose kept plans the run runs, a"
            " job of the same store, producer and calls (in the same order)."
            " Each call fetches only its plan's positions to download; one"
            " whose source changed since is a failed item (`conflict`,"
            " `stale_plan`), and a call whose check failed or whose plan has"
            " nothing to download is skipped. Without it each call fetches"
            " what the source has that the store does not hold."
        ),
        examples=[_JOB_ID],
    )
    pin: "JobPin | None" = Field(
        default=None,
        description=(
            "`download` only: pin what the run leaves into a new group of a"
            " project (A-ADR-049 decision 9). When the job succeeds (no failed"
            " unit, nothing taken) its worker writes the group, origin `plan`"
            " with the job's producer and calls: a pin for every file of"
            " `files[]` and, for each call with a kept plan, for every other"
            " position the version the index holds at its standard path. The"
            " request also needs `project.write`; a taken name is `409"
            " group_exists` before a job exists. The summary's `pin` says"
            " what was written."
        ),
    )

    @field_validator("plan_job")
    @classmethod
    def _only_a_download_runs_a_plan(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        if value is not None and info.data.get("kind") != "download":
            raise ValueError("only a download runs the plans of a check job")
        return value

    @field_validator("pin")
    @classmethod
    def _only_a_download_pins(
        cls, value: "JobPin | None", info: ValidationInfo
    ) -> "JobPin | None":
        if value is not None and info.data.get("kind") != "download":
            raise ValueError("only a download pins its files into a project")
        return value

    def command_calls(self) -> tuple[CommandCall, ...]:
        """Return the calls of the job, in their order."""
        return tuple(
            CommandCall(self.producer, call.command, call.options)
            for call in self.calls
        )

    def pin_target(self) -> tuple[str, str] | None:
        """Return ``pin`` as ``(project, group)``."""
        return None if self.pin is None else (self.pin.project, self.pin.group)


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


class CallPlanItem(BaseModel):
    """The plan of one call: what a run of it would do in the store."""

    model_config = ConfigDict(
        serialize_by_alias=True,
        validate_by_alias=True,
        validate_by_name=True,
        json_schema_extra={"examples": [_FIRST_CALL]},
    )

    call: int = Field(description="Its place in the job's `calls`, from 0.", ge=0)
    command: str = Field(description="The command planned, of the producer's catalog.")
    options: dict[str, Any] = Field(
        description="Its options as the producer read them."
    )
    line: str = Field(
        description=(
            "The producer's command line of the run, with the store's root: the"
            " same run from a terminal."
        )
    )
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
        description="What the producer said while it checked the call."
    )

    @classmethod
    def of(cls, stored: StoredPlan, options: dict[str, Any]) -> Self:
        """Return the model of the kept plan of a call with the call's options."""
        plan = stored.plan
        return cls(
            call=stored.call,
            command=plan.command,
            options=options,
            line=stored.line,
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


class ActionPlanInfo(BaseModel):
    """The plans a `check` job kept: what a run of its calls would do in the store."""

    model_config = ConfigDict(json_schema_extra={"examples": [_PLAN_EXAMPLE]})

    job_id: str = Field(description="The `check` job that made the plans.")
    store: str = Field(description="The configured store the plans are of.")
    producer: str = Field(description="Producer id.")
    root: str = Field(description="The store root the producer planned for.")
    checked_at: datetime = Field(
        description="When the source was asked for the oldest of the plans (UTC)."
    )
    ok: bool = Field(
        description=(
            "Every call was planned and every position checked: no call failed"
            " (the job's `result.calls` says why one did) and no position is"
            " `check_failed`."
        )
    )
    counts: dict[PlanStatus, int] = Field(
        description="Positions of each status in all the plans, every status named."
    )
    positions: int = Field(description="Positions of all the plans.")
    todo: int = Field(description="Positions the runs of the plans download.")
    size_bytes: int | None = Field(
        description=(
            "Bytes the runs download as far as the producer tells the sizes of"
            " the positions to download; `null` when it tells none of them,"
            " never 0 for an unknown size."
        )
    )
    size_complete: bool = Field(
        description="Every position to download has its size: `size_bytes` is whole."
    )
    calls: list[CallPlanItem] = Field(
        description=(
            "The plan of each call planned, in the order of the job's `calls`;"
            " a call whose check failed has none."
        )
    )

    @classmethod
    def of(cls, kept: KeptPlans) -> Self:
        """Return the model of the plans a job kept."""
        calls: list[dict[str, Any]] = kept.job.params["calls"]
        plans = [stored.plan for stored in kept.plans]
        totals = PlanTotals.of(plans)
        return cls(
            job_id=kept.job.id,
            store=kept.plans[0].store,
            producer=plans[0].producer,
            root=plans[0].root,
            checked_at=totals.checked_at,
            ok=totals.ok and len(plans) == len(calls),
            counts=totals.counts,
            positions=totals.positions,
            todo=totals.todo,
            size_bytes=totals.size_bytes,
            size_complete=totals.size_complete,
            calls=[
                CallPlanItem.of(stored, calls[stored.call]["options"])
                for stored in kept.plans
            ],
        )
