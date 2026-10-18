"""Configured stores: ``GET /stores`` and ``GET /stores/{store}`` (SPEC 9.2).

Both answer from the index alone, so a disconnected store keeps its last
known state (``state.stale``, ``state.indexed_at``). ``/stores/{store}`` is
the „Magazyn” view: usage per product with each content once, the report of
versions neither current nor pinned, the projects naming the store (only
those the principal sees; counts cover all) and problems with instructions.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path

from archiwista.api.dependencies import (
    index_queries,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import problem_responses
from archiwista.api.models import StoreDetail, StoreItem, StoreList
from archiwista.auth import Principal, ProjectVisibility
from archiwista.config import AppSettings, SettingsService
from archiwista.errors import NotFoundError
from archiwista.index import IndexQueries
from archiwista.messages import MESSAGES
from archiwista.security import current_principal
from archiwista.services import store_summary

router = APIRouter(tags=["stores"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Store = Annotated[str, Path(description="Store id.", examples=["zespol"])]


def read_stores(settings: AppSettings, queries: IndexQueries) -> StoreList:
    """Return the configured stores with their index state, in settings order."""
    states = {state.store: state for state in queries.status().stores}
    return StoreList(
        items=[StoreItem.of(store, states.get(store.id)) for store in settings.stores]
    )


def read_store(
    settings: AppSettings,
    queries: IndexQueries,
    store: str,
    *,
    visible: ProjectVisibility,
) -> StoreDetail:
    """Return a configured store's state for the „Magazyn” view.

    Raises
    ------
    NotFoundError
        The store is not configured.
    """
    config = settings.store(store)
    if config is None:
        raise NotFoundError(MESSAGES["api_store_not_configured"].format(store=store))
    return StoreDetail.of(store_summary(queries, config, visible=visible), config)


@router.get("/stores", response_model=StoreList, responses=problem_responses())
def list_stores(
    principal: _Principal, settings: _Settings, queries: _Queries
) -> StoreList:
    """List configured stores: availability, counts, last scan and running job."""
    return read_stores(settings.get(), queries)


@router.get(
    "/stores/{store}", response_model=StoreDetail, responses=problem_responses(404)
)
def get_store(
    store: _Store, visible: _Visible, settings: _Settings, queries: _Queries
) -> StoreDetail:
    """Return one store: usage per product, clean-up report, projects, problems.

    Problems come with a Polish instruction and never with a delete action;
    only projects the session's principal sees are named.
    """
    return read_store(settings.get(), queries, store, visible=visible)
