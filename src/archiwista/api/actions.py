"""Producers' commands run as jobs over HTTP (plan of 2026-10-25, A4, A5; SPEC 9.2).

``POST /jobs`` starts a job of a command of a producer's catalog on a
configured store, kind ``check`` (the plan of a run without its effects,
ADR-036) or ``download`` (the run, the plan of a ``check`` job if named,
ADR-037): it answers ``202`` with the job and ``Location:
/api/v1/jobs/{job}``, and refuses before a job exists what the job's worker
would refuse; a download needs the permission to write the stores
(``store.write``). ``GET /jobs/{job}/plan`` returns the plan the ``check`` job
kept, from the index, without the network; a job the session does not see,
or one without a plan, is ``404``. The routes translate only:
``archiwista.services.actions`` does the work and asks the ``Authorizer``, and
``archiwista jobs`` calls the same functions. The router is served with the
job supervisor.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response

from archiwista.api import API_PREFIX
from archiwista.api.dependencies import (
    authorizer,
    index_queries,
    plugin_registry,
    settings_service,
    visible_projects,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.jobs import job_supervisor
from archiwista.api.models import JobDetail
from archiwista.api.models_actions import ActionPlanInfo, JobRequest
from archiwista.auth import Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import SettingsService
from archiwista.index import IndexQueries
from archiwista.jobs import JobSupervisor
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import actions as action_service
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["jobs"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Authorizer = Annotated[Authorizer, Depends(authorizer)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Jobs = Annotated[JobSupervisor, Depends(job_supervisor)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]
_Visible = Annotated[ProjectVisibility, Depends(visible_projects)]
_JobId = Annotated[str, Path(description="Job id.", examples=["3f9c1a7e5b2d4c60"])]

_UNSUPPORTED: dict[int | str, dict[str, Any]] = {
    422: {
        "description": (
            "`unsupported`: the producer offers no commands (`no_commands`), or"
            " the command works on no store (`no_store`) or has no plan without"
            " effects (`no_check`)."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "example": problem_example(
                    "unsupported",
                    message(
                        "command.no_check",
                        "en",
                        producer="kartograf",
                        command="store overview",
                    ),
                    reason="no_check",
                ),
            }
        },
    }
}


@router.post(
    "/jobs",
    response_model=JobDetail,
    status_code=202,
    responses={**problem_responses(400, 403, 404, 409, 503), **_UNSUPPORTED},
)
def start_job(
    body: JobRequest,
    principal: _Principal,
    decisions: _Authorizer,
    visible: _Visible,
    registry: _Registry,
    settings: _Settings,
    jobs: _Jobs,
    queries: _Queries,
    response: Response,
) -> JobDetail:
    """Start a job of a command of a producer's catalog on a configured store.

    `check` plans a run of the command in the store's directory of the
    producer without its effects, over the network; its plan is read with
    `GET /jobs/{job}/plan` once the job succeeded or ended `partial`.
    `download` runs the command there and writes the store; with `plan_job`
    it runs the plan that `check` job kept. The answer is `202` with the job
    and `Location: /api/v1/jobs/{job}`; follow it with `GET
    /jobs/{job}/events`. Refused before a job exists: a download by a session
    that may not write the stores (`403`, `permission_denied`: neither the
    role `store_writer` nor the setting `store_write_for_all`), a store that is
    not configured (`404`), a command outside the catalog (`400`,
    `unknown_command`), a store without a directory of the producer (`400`,
    `store_without_producer`), a command on no store or without a check
    (`422`, `no_store`, `no_check`), an option that is a file path (`403`,
    `path_outside_root`), the producer's refusal of the options (`400` with
    its text and `details.option`), a `plan_job` the session does not see or
    without a kept plan (`404`) or of another store or call (`409`,
    `plan_mismatch`), a producer whose plugin is missing (`503`) and offline
    mode (`409 offline_mode`).
    """
    job = action_service.start(
        registry,
        settings.get(),
        jobs,
        queries,
        decisions,
        kind=body.kind,
        store=body.store,
        call=body.call(),
        actor=principal,
        visible=visible,
        plan_job=body.plan_job,
    )
    response.headers["Location"] = f"{API_PREFIX}/jobs/{job.id}"
    return JobDetail.of(job)


@router.get(
    "/jobs/{job}/plan",
    response_model=ActionPlanInfo,
    responses=problem_responses(404),
)
def get_job_plan(
    job: _JobId,
    principal: _Principal,
    visible: _Visible,
    jobs: _Jobs,
    queries: _Queries,
) -> ActionPlanInfo:
    """Return the plan a `check` job kept: what a run of its command would do.

    Read from the index, never from the network: `checked_at` says when the
    source was asked. The plan is kept from the end of a job that succeeded
    or ended `partial` for as long as the job. A job the session does not
    see, one that is no `check`, one still running and one that failed are
    `404`.
    """
    stored = action_service.kept_plan(queries, jobs, job, visible=visible)
    return ActionPlanInfo.of(stored)
