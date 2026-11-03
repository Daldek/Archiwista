"""API model of a job over a project's groups (A-ADR-049 decision 11).

``POST /projects/{project}/jobs`` answers the job (``JobDetail``); its result
is the summary of the job's kind (AGENT_API 9). The request model refuses
unknown members and a re-pin that does not name exactly one group.
"""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archiwista.services.project_jobs import ProjectJobKind


class ProjectJobRequest(BaseModel):
    """A job of a project's groups (`POST /projects/{project}/jobs`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"kind": "verify"},
                {"kind": "check", "groups": ["NMT 2023"]},
                {"kind": "repin", "groups": ["NMT 2023"]},
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

    @model_validator(mode="after")
    def _one_group_to_repin(self) -> Self:
        """Refuse a re-pin that does not name exactly one group."""
        if self.kind == "repin" and (
            self.groups is None or len({name.casefold() for name in self.groups}) != 1
        ):
            raise ValueError("a repin names exactly one group in groups")
        return self
