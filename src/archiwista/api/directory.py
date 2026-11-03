"""Whom a project can be shared with: ``GET /directory`` (SPEC 9.2, ADR-047).

Any session reads the enabled accounts and the groups, each with its id and
name only, so that a project's owner picks people and groups on the sharing
screen; ``GET /users`` and ``GET /groups``, with roles, memberships and
disabled accounts, stay an administrator's (``archiwista.services.access``).
"""

from typing import Annotated, Self

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from archiwista.api.dependencies import authorizer
from archiwista.api.errors import problem_responses
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.security import current_principal
from archiwista.services import access as access_service

router = APIRouter(tags=["permissions"])


class DirectoryEntry(BaseModel):
    """An account or a group as every session sees it."""

    id: str = Field(description="Account or group id.")
    name: str = Field(description="Display name.")


class Directory(BaseModel):
    """The enabled accounts and the groups to share a project with."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "users": [
                        {"id": "anna.nowak", "name": "Anna Nowak"},
                        {"id": "kasia.wrona", "name": "Kasia Wrona"},
                    ],
                    "groups": [{"id": "hydro", "name": "Dział hydrologii"}],
                }
            ]
        }
    )

    users: list[DirectoryEntry] = Field(
        description="Enabled accounts ordered by id; disabled ones are left out."
    )
    groups: list[DirectoryEntry] = Field(description="Every group ordered by id.")

    @classmethod
    def of(cls, found: access_service.Directory) -> Self:
        """Return the model of the directory: ids and names only."""
        return cls(
            users=[DirectoryEntry(id=user.id, name=user.name) for user in found.users],
            groups=[
                DirectoryEntry(id=group.id, name=group.name) for group in found.groups
            ],
        )


@router.get("/directory", response_model=Directory, responses=problem_responses())
def get_directory(
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> Directory:
    """List the enabled accounts and the groups to share a project with.

    Any session, an agent's too: ids and names only, without roles,
    memberships or disabled accounts.
    """
    return Directory.of(access_service.directory(decisions))
