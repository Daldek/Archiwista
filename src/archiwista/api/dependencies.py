"""Route dependencies shared by the routers: authorizer, visibility, index.

``create_app`` keeps one ``Authorizer`` (``app.state.authorizer``), one
``IndexQueries`` (``app.state.queries``), the settings
(``app.state.settings``) and the producer plugins (``app.state.registry``);
the server's data directory is the index's (``app_paths``).
A route takes the projects the current principal sees with
``visible_projects`` and passes them to the index queries and services,
which filter; routes never filter themselves (A-ADR-029). A route that
lists projects takes ``writable_projects`` too, to say of each whether the
principal may change it (``project_write``). A route that numbers the years
of station data or gives copy paths takes the principal's own preferences
(``principal_preferences``): their year types and path aliases.
"""

import os
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from archiwista.api.models import Preferences
from archiwista.auth import Principal, ProjectVisibility, WritableProjects
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppPaths, SettingsService
from archiwista.index import IndexQueries
from archiwista.security import current_principal
from archiwista.services.preferences import read_preferences
from archiwista.sources.registry import PluginRegistry


def authorizer(request: Request) -> Authorizer:
    """Return the application's ``Authorizer``."""
    value: Authorizer = request.app.state.authorizer
    return value


def index_queries(request: Request) -> IndexQueries:
    """Return the application's reader of the local index."""
    value: IndexQueries = request.app.state.queries
    return value


def settings_service(request: Request) -> SettingsService:
    """Return the application's settings service."""
    value: SettingsService = request.app.state.settings
    return value


def app_paths(request: Request) -> AppPaths:
    """Return the server's data directory: the index's (``AppPaths.data_dir``).

    Only the data directory counts here (the folder rules, the process's
    work directory); the settings come from the settings service.
    """
    index_path: Path = request.app.state.index_path
    return AppPaths(config_file=Path(os.devnull), data_dir=index_path.parent)


def plugin_registry(request: Request) -> PluginRegistry:
    """Return the application's producer plugins."""
    value: PluginRegistry = request.app.state.registry
    return value


def visible_projects(
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> ProjectVisibility:
    """Return the projects the request's principal sees (``401`` without one)."""
    return decisions.visible_projects(principal)


def writable_projects(
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> WritableProjects:
    """Return whether the request's principal may change each project."""
    return decisions.writable_projects(principal)


def principal_preferences(
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> Preferences:
    """Return the request's principal's own preferences (``401`` without one).

    A person's, an agent's account's, the local owner's in local mode.
    """
    return read_preferences(decisions.state, principal)
