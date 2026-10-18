"""Server state: ``GET /health`` and ``GET /sources`` (SPEC 9.2, 5.8).

``/health`` gives the versions of Archiwista and of the producer libraries,
the local index and every configured store's state: availability, the last
complete pass, the last scan with its actor, a running job with its progress
and whether answers about the store are stale. ``archiwista status --json``
prints the same model (``read_health``). ``/sources`` lists the producer
plugins with a Polish description of their state and of its fix.
"""

from importlib.metadata import version
from typing import Annotated

from fastapi import APIRouter, Depends

from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import problem_responses
from archiwista.api.models import Health, SourceInfo, SourceList
from archiwista.auth import Principal
from archiwista.config import AppSettings, SettingsService
from archiwista.doctor import source_check
from archiwista.index import IndexQueries
from archiwista.security import current_principal
from archiwista.sources.registry import APP_DISTRIBUTION, PluginRegistry

router = APIRouter(tags=["health"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]


def source_infos(registry: PluginRegistry) -> list[SourceInfo]:
    """Return every producer plugin's state with its description and fix."""
    infos = []
    for state in registry.states():
        check = source_check(state, required=False)
        infos.append(SourceInfo.of(state, check.message, check.fix))
    return infos


def read_health(
    settings: AppSettings, registry: PluginRegistry, queries: IndexQueries
) -> Health:
    """Return the state of the server, its sources, index and stores.

    Parameters
    ----------
    settings : AppSettings
        Settings in effect (the configured stores, in their order).
    registry : PluginRegistry
        Producer plugins.
    queries : IndexQueries
        Reader of the local index.
    """
    return Health.of(
        version(APP_DISTRIBUTION),
        source_infos(registry),
        queries.status(),
        settings.stores,
    )


@router.get("/health", response_model=Health, responses=problem_responses())
def get_health(
    principal: _Principal,
    settings: _Settings,
    registry: _Registry,
    queries: _Queries,
) -> Health:
    """Return versions, producer plugins, the local index and each store's state.

    A store not scanned yet is `unknown`. An unavailable store (e.g. a
    disconnected share) is `stale`: lists still answer from the index as of
    its `indexed_at`.
    """
    return read_health(settings.get(), registry, queries)


@router.get("/sources", response_model=SourceList, responses=problem_responses())
def list_sources(principal: _Principal, registry: _Registry) -> SourceList:
    """List producer plugins: state, library version, range, schemas and fix.

    A source other than `available` is a state, not a failure: requests
    needing it answer `503 source_unavailable` or `503 source_incompatible`.
    """
    return SourceList(items=source_infos(registry))
