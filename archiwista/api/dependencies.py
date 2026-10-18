"""Route dependencies shared by the routers: authorizer, visibility, index.

``create_app`` keeps one ``Authorizer`` (``app.state.authorizer``) and one
``IndexQueries`` (``app.state.queries``). A route takes the projects the
current principal sees with ``visible_projects`` and passes them to the
index queries and services, which filter; routes never filter themselves
(A-ADR-029).
"""

from typing import Annotated

from fastapi import Depends, Request

from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.index import IndexQueries
from archiwista.security import current_principal


def authorizer(request: Request) -> Authorizer:
    """Return the application's ``Authorizer``."""
    value: Authorizer = request.app.state.authorizer
    return value


def index_queries(request: Request) -> IndexQueries:
    """Return the application's reader of the local index."""
    value: IndexQueries = request.app.state.queries
    return value


def visible_projects(
    principal: Annotated[Principal, Depends(current_principal)],
    decisions: Annotated[Authorizer, Depends(authorizer)],
) -> ProjectVisibility:
    """Return the projects the request's principal sees (``401`` without one)."""
    return decisions.visible_projects(principal)
