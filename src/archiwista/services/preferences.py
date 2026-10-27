"""Each person's own preferences (ADR-047 decision 6, plan v0.4 C12).

The preferences of a principal are its account's: a signed-in person's, an
agent's account's, and ``local`` for the owner of a local installation (and
the command line, which acts as the owner). They hold the year type
remembered for hydro and for meteo data (the numbering of the station views
without ``year_type``), the basemap of the map and the person's path aliases.
``read_preferences`` gives the defaults before the first change;
``save_preferences`` replaces them all, refusing a basemap the settings do
not configure. Nothing is logged: preferences change what one person sees,
not what anyone may do. A path alias only changes the paths shown and copied
(``CopyPath.personal``); no route reads a path through one.
"""

import logging

from pydantic import ValidationError

from archiwista.api.models import Preferences
from archiwista.auth import Principal
from archiwista.config import AppSettings
from archiwista.errors import InvalidChangeError
from archiwista.messages import message
from archiwista.state import StateStore

logger = logging.getLogger(__name__)


def read_preferences(state: StateStore, principal: Principal) -> Preferences:
    """Return a principal's preferences: the defaults before the first change.

    A document the table holds that no longer validates (e.g. a server
    prefix of another system, restored from a backup) gives the defaults
    too, with a warning in the server's log, until the person saves new ones.
    """
    record = state.preferences(principal.id)
    if record is None:
        return Preferences()
    try:
        return Preferences.model_validate(record.document)
    except ValidationError as error:
        logger.warning(
            "The preferences of %s are not valid, the defaults apply: %s",
            principal.id,
            error,
        )
        return Preferences()


def save_preferences(
    state: StateStore,
    settings: AppSettings,
    principal: Principal,
    preferences: Preferences,
) -> Preferences:
    """Replace a principal's preferences; return them as saved.

    Raises
    ------
    InvalidChangeError
        ``basemap`` names no configured basemap (``400 validation_error``,
        reason ``unknown_basemap``, ``details.basemaps`` the configured ones).
    NotFoundError
        The principal's account no longer exists.
    """
    names = [basemap.name for basemap in settings.basemaps]
    chosen = preferences.basemap
    if chosen and chosen not in names:
        raise InvalidChangeError(
            message(
                "preferences.unknown_basemap",
                basemap=chosen,
                names=", ".join(names) or "–",
            ),
            reason="unknown_basemap",
            details={"basemaps": names},
        )
    record = state.set_preferences(principal.id, preferences.model_dump(mode="json"))
    return Preferences.model_validate(record.document)
