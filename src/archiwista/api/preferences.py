"""A person's own preferences over HTTP: ``GET`` and ``PUT /preferences`` (SPEC 9.2).

Any session reads and replaces its principal's own preferences, and no one
else's (``archiwista.services.preferences``): the year types of the station
views, the basemap and the path aliases of the person's computer.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from archiwista.api.dependencies import (
    authorizer,
    principal_preferences,
    settings_service,
)
from archiwista.api.errors import problem_responses
from archiwista.api.models import Preferences
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.security import current_principal
from archiwista.services.preferences import save_preferences

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=Preferences, responses=problem_responses())
def get_preferences(
    preferences: Annotated[Preferences, Depends(principal_preferences)],
) -> Preferences:
    """Return the session's own preferences; the defaults before the first change.

    A person's, an agent's account's, the owner's in local mode.
    """
    return preferences


@router.put("", response_model=Preferences, responses=problem_responses(400))
def put_preferences(
    body: Preferences,
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
    settings: Annotated[SettingsService, Depends(settings_service)],
) -> Preferences:
    """Replace the session's own preferences; answer them as saved.

    A field the body omits takes its default. Without `year_type` the
    station routes number the years as `year_types` says for the data's
    family, a list of both families as for hydro; `basemap` must be a
    configured basemap's name, `""` or `null` (else `400`, reason
    `unknown_basemap`). `path_aliases` (at most 20; a prefix on the server
    must be absolute) give `personal` of every copy path (`CopyPath`): only
    shown and copied, never used to reach a file.
    """
    return save_preferences(decisions.state, settings.get(), principal, body)
