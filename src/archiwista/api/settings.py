"""Settings over HTTP: ``GET /settings`` and ``PUT /settings`` (SPEC 9.2, 5.5).

``GET`` answers any session (the interface needs the basemaps and offline
mode). ``PUT`` replaces all settings: it needs ``settings.write`` (an
administrator; the local owner is one, A-ADR-029), and validates like the
configuration file (problems per field) and then
the directories: they exist and can be read, producer directories are not
nested, the producer accepts each new or moved one. A rejected change keeps
the file and the settings in effect. A saved change reaches subscribers
(the scan scheduler) and the CSP of the following responses.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from archiwista.api.dependencies import authorizer, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models import Settings
from archiwista.auth import Principal
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService, parse_settings
from archiwista.security import current_principal

router = APIRouter(prefix="/settings", tags=["settings"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Settings = Annotated[SettingsService, Depends(settings_service)]


def settings_writer(
    principal: _Principal, decisions: Annotated[Authorizer, Depends(authorizer)]
) -> Principal:
    """Return the principal allowed to change settings, or refuse with ``403``."""
    decisions.require(principal, "settings.write")
    return principal


def save_settings(service: SettingsService, body: Settings) -> Settings:
    """Validate and save complete new settings; return those in effect.

    Fields the body omits take their defaults, a store without ``kind`` has
    it detected.

    Raises
    ------
    SettingsValidationError
        A value or a directory is unusable; nothing changes.
    """
    changed = parse_settings(body.model_dump(mode="json", exclude_unset=True))
    return Settings.of(service.update(changed))


@router.get("", response_model=Settings, responses=problem_responses())
def get_settings(principal: _Principal, service: _Settings) -> Settings:
    """Return the settings in effect: stores, project directories, basemaps."""
    return Settings.of(service.get())


@router.put("", response_model=Settings, responses=problem_responses(403, 400))
def put_settings(
    body: Settings,
    principal: Annotated[Principal, Depends(settings_writer)],
    service: _Settings,
) -> Settings:
    """Replace all settings (administrator); answer those now in effect.

    Invalid values or unusable directories answer `400 validation_error`
    with `problems` (`code`, `field`, `message`, and `reason` and `hint` of a
    directory the producer refuses, e.g. a store without its marker) and
    change nothing. Changing offline mode or basemaps changes the CSP of later
    responses.
    """
    return save_settings(service, body)
