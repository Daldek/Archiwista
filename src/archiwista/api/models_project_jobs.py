"""API model of a job over a project's groups (A-ADR-049 decision 11).

``POST /projects/{project}/jobs`` answers the job (``JobDetail``); its result
is the summary of the job's kind (AGENT_API 9). The request model refuses
unknown members, a re-pin that does not name exactly one group and a
``plan_job`` of a verification or a check: only a re-pin and a restore
confirm the plan of a check (ADR-042 erratum 2).
"""

from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from archiwista.services.project_jobs import ProjectJobKind

# An example job id, 16 hexadecimal digits as the supervisor makes them.
_JOB_ID = "8a41c0d29e7b5f13"


class ProjectJobRequest(BaseModel):
    """A job of a project's groups (`POST /projects/{project}/jobs`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"kind": "verify"},
                {"kind": "check", "groups": ["NMT 2023"]},
                {"kind": "repin", "groups": ["NMT 2023"]},
                {"kind": "repin", "groups": ["NMT 2023"], "plan_job": _JOB_ID},
                {"kind": "restore"},
            ]
        },
    )

    kind: ProjectJobKind = Field(
        description=(
            "`verify`: hash the pinned files in the store, without the network;"
            " `check`: compare the pins with the source over the network, without"
            " effects. Both need only to see the project. `repin`: run one group's"
            " calls in the producer's update mode and, when all of them succeeded,"
            " pin the group anew; `restore`: download the missing pinned versions"
            " again in the producer's default mode. Both write the store, so they"
            " need `project.write` of the project and the role `store_writer` or"
            " the setting `store_write_for_all`."
        )
    )
    groups: list[Annotated[str, Field(min_length=1)]] | None = Field(
        default=None,
        min_length=1,
        description=(
            "The groups by name (compared case-folded); left out or `null`: every"
            " group of the project. A `repin` names exactly one; a name given twice"
            " counts once."
        ),
    )
    plan_job: str | None = Field(
        default=None,
        min_length=1,
        description=(
            "`repin` and `restore` only: the `project_check` job whose plan the"
            " person confirmed, the card's plan window (ADR-042 erratum 2): a"
            " check of this project that ended with its plan (`succeeded` or"
            " `partial`), of every group the request names, whose pins of them"
            " are still those it checked. Refused before a job: a job the session"
            " does not see (`404`, as an unknown one), a check without a plan"
            " yet or that failed (`404`), another kind, project or group, or a"
            " set changed since (`409 plan_mismatch`, the job in"
            " `details.job`). The worker plans again (the source may have"
            " changed since); the job keeps it in `params.plan_job`. Left out:"
            " the job starts without a confirmed plan (`null`)."
        ),
        examples=[_JOB_ID],
    )

    @field_validator("plan_job")
    @classmethod
    def _only_a_writing_job_confirms_a_plan(
        cls, value: str | None, info: ValidationInfo
    ) -> str | None:
        """Refuse ``plan_job`` with a verification or a check."""
        if value is not None and info.data.get("kind") not in ("repin", "restore"):
            raise ValueError("only a repin or a restore confirms the plan of a check")
        return value

    @model_validator(mode="after")
    def _one_group_to_repin(self) -> Self:
        """Refuse a re-pin that does not name exactly one group."""
        if self.kind == "repin" and (
            self.groups is None or len({name.casefold() for name in self.groups}) != 1
        ):
            raise ValueError("a repin names exactly one group in groups")
        return self
