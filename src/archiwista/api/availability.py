"""The availability at the source over HTTP (plan of 2026-10-25, A2, A3; SPEC 9.2).

``POST /availability`` asks what the source has for an area and a product:
a report the index keeps that is younger than seven days answers ``200`` at
once unless the request sets ``force``; otherwise the answer is ``202`` with
the ``availability`` job and ``Location: /api/v1/jobs/{job}``, and ``GET
/availability`` returns its report once it succeeded. In offline mode a
request that needs the source answers ``409 offline_mode`` and records
nothing. ``GET /availability`` reads the index only and never uses the
network. A report comes with its rows (SPEC 6.3, 6.4): the labels in the
language of the request and, for a configured ``store``, the store badges.
The routes translate only: ``archiwista.services.availability`` does the
work, and ``archiwista availability`` calls the same functions. A session is
all they need. ``job_router`` (the ``POST``) is served with the job
supervisor.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import index_queries, plugin_registry, settings_service
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.jobs import job_supervisor
from archiwista.api.models import JobDetail
from archiwista.api.models_availability import (
    AVAILABILITY_EXAMPLE,
    AVAILABILITY_JOB_EXAMPLE,
    AvailabilityInfo,
    AvailabilityQuery,
    AvailabilityRequest,
)
from archiwista.auth import Principal
from archiwista.config import SettingsService
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import availability as availability_service
from archiwista.services.availability import AreaAvailability, VariantFilter
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["availability"])
job_router = APIRouter(tags=["availability"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Settings = Annotated[SettingsService, Depends(settings_service)]

_UNSUPPORTED: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "`unsupported`: the producer offers no commands (`no_commands`) or"
            " checks no availability of the product (`no_availability`, the"
            " products it checks in `details.allowed`)."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "example": problem_example(
                    "unsupported",
                    message(
                        "availability.product_unsupported",
                        "en",
                        producer="kartograf",
                        product="orto",
                        allowed="nmt, nmpt, laz",
                    ),
                    reason="no_availability",
                    details={"allowed": ["nmt", "nmpt", "laz"]},
                ),
            }
        },
    }
}
_ANSWERS: dict[int | str, dict[str, Any]] = {
    200: {
        "model": AvailabilityInfo,
        "description": "A report younger than seven days, without `force`: no job.",
        "content": {"application/json": {"example": AVAILABILITY_EXAMPLE}},
    },
    202: {
        "model": JobDetail,
        "description": (
            "The `availability` job that asks the source (`Location`); a request"
            " that asks what an active check asks gets that job. When it"
            " succeeds, `GET /availability` returns its report."
        ),
        "content": {"application/json": {"example": AVAILABILITY_JOB_EXAMPLE}},
    },
}


@router.get(
    "/availability",
    response_model=AvailabilityInfo,
    responses=problem_responses(404, 400),
)
def get_availability(
    query: Annotated[AvailabilityQuery, Query()],
    principal: _Principal,
    queries: _Queries,
    settings: _Settings,
) -> AvailabilityInfo:
    """Return the last report of what the source has for an area and a product.

    Read from the index, never from the network: `checked_at` says when the
    source was asked. Its rows rank the variants of each year; the fixed
    dimensions (`horizontal`, `resolution`, `vertical_crs`) leave a year without
    them `no_data`, and a `store` gives each variant its store badge. An
    unknown area, a store that is not configured, and an area without a report
    of the product, are `404`.
    """
    availability_service.known_store(settings.get(), query.store)
    found = availability_service.stored(
        queries, area_id=query.area_id, product=query.product, producer=query.producer
    )
    return _info(queries, found, store=query.store, fixed=query.fixed())


@job_router.post(
    "/availability",
    response_model=None,
    responses={
        **_ANSWERS,
        **problem_responses(404, 400, 409, 503),
        **_UNSUPPORTED,
    },
)
def check_availability(
    body: AvailabilityRequest,
    principal: _Principal,
    queries: _Queries,
    registry: _Registry,
    jobs: _Jobs,
    settings: _Settings,
) -> Response:
    """Ask what the source has for an area and a product.

    A report younger than seven days answers `200` with `AvailabilityInfo`
    (its rows read as `GET` reads them) unless `force` is set. Otherwise `202`
    with the `availability` job and `Location: /api/v1/jobs/{job}`; follow it
    with `GET /jobs/{job}/events`. In offline mode that is `409 offline_mode`,
    and nothing is recorded. An unknown area or a store that is not configured
    is `404`; a producer whose plugin is missing `503`; a product the producer
    does not check `422 unsupported`.
    """
    availability_service.known_store(settings.get(), body.store)
    found = availability_service.check(
        queries,
        registry,
        jobs,
        area_id=body.area_id,
        product=body.product,
        producer=body.producer,
        force=body.force,
        actor=principal,
    )
    if isinstance(found, AreaAvailability):
        info = _info(queries, found, store=body.store, fixed=body.fixed())
        return JSONResponse(info.model_dump(mode="json"))
    return JSONResponse(
        JobDetail.of(found).model_dump(mode="json"),
        status_code=202,
        headers={"Location": f"{API_PREFIX}/jobs/{found.id}"},
    )


def _info(
    queries: IndexQueries,
    found: AreaAvailability,
    *,
    store: str | None,
    fixed: VariantFilter,
) -> AvailabilityInfo:
    """Return a kept report with its rows and their badges in ``store``."""
    rows = availability_service.summary(
        queries, found.stored.report, store=store, fixed=fixed
    )
    return AvailabilityInfo.of(found, rows, store=store, fixed=fixed)
