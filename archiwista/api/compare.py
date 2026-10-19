"""The metadata comparison over HTTP (plan v0.2, step 10; SPEC 9.2, 8.5).

``GET /compare?a=<ref>&b=<ref>`` translates only: ``services.compare``
reads both objects from the local index; ``archiwista compare`` calls the
same function.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from archiwista.api.dependencies import index_queries, visible_projects
from archiwista.api.errors import problem_responses
from archiwista.api.models_compare import CompareQuery, Comparison
from archiwista.auth import ProjectVisibility
from archiwista.index import IndexQueries
from archiwista.services.compare import compare

router = APIRouter(tags=["compare"])


@router.get(
    "/compare",
    response_model=Comparison,
    responses=problem_responses(404, 422),
)
def get_comparison(
    query: Annotated[CompareQuery, Query()],
    visible: Annotated[ProjectVisibility, Depends(visible_projects)],
    queries: Annotated[IndexQueries, Depends(index_queries)],
) -> Comparison:
    """Compare the metadata of two objects, each named by a `ref` of an answer.

    Rows hold a field's human name and the values of A and B, marked by
    `differs`: a store version's index fields, then its raw sidecar's fields
    as flattened JSON paths; an own file's or a snapshot's fields (objects,
    extent, CRS, size, content identity, author, note, dates), then its
    objects per layer. Mixed pairs are allowed (a snapshot with its working
    file, versions of two slots); `schema_diff` lists layers and fields added,
    removed or retyped when both sides have vector layers. A malformed
    reference is `422 invalid_ref`; an unknown object, or one of a project
    the caller does not see, `404`.
    """
    return compare(queries, query.a, query.b, visible=visible)
