"""``archiwista jobs``: jobs of producers' commands (plan of 2026-10-25, A4).

``jobs start RODZAJ PRODUCENT POLECENIE --store ID [--options JSON]`` starts a
job of a command of the producer's catalog on a configured store (``POST
/jobs``) and follows it to its end in the foreground
(``archiwista.jobs.foreground``): kind ``check`` plans a run without its
effects. It prints the job as it ended (``GET /jobs/{job}``, ``JobDetail``)
and exits with its outcome: ``0`` succeeded, ``10`` partial, ``11`` failed,
``130`` cancelled or interrupted (ERR §1). ``jobs plan ZADANIE`` prints the plan
a ``check`` job kept (``GET /jobs/{job}/plan``, ``ActionPlanInfo``) without the
network. Both call ``archiwista.services.actions`` without HTTP, as the owner
of the installation (``LOCAL_OWNER``); ``--json`` prints the route's model, a
refusal prints no model and ends standard error with its ``archiwista-error/1``
document.
"""

import argparse
import sqlite3
from collections.abc import Mapping
from contextlib import ExitStack
from typing import Any, TextIO

from pydantic import ValidationError

from archiwista.api.models import JobDetail
from archiwista.api.models_actions import ActionPlanInfo, JobRequest
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.commands import Commands, add_parser
from archiwista.commands.producer_commands import json_object
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import (
    describe,
    exception_problem,
    refuse,
    validation_problem,
)
from archiwista.errors import ArchiwistaError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.jobs import FINISHED_STATES, JobEvent, JobRecord, JobSupervisor
from archiwista.jobs.foreground import exit_status, run_foreground
from archiwista.messages import label, message, with_detail
from archiwista.services.actions import kept_plan, start
from archiwista.sources import PLAN_STATUSES, PLAN_TODO, PlanStatus
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"jobs"})


def add_commands(commands: Commands) -> None:
    """Add ``archiwista jobs`` and its actions (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    text = message("cli.jobs_help")
    parser = commands.add_parser("jobs", help=text, description=text)
    actions = parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )
    started = add_parser(actions, "start", "cli.jobs_start_help")
    started.add_argument(
        "kind", metavar=message("metavar.kind"), help=message("cli.jobs_kind_help")
    )
    started.add_argument(
        "producer",
        metavar=message("metavar.producer"),
        help=message("cli.commands_producer_help"),
    )
    # Not ``command``: the namespace's ``command`` names ``jobs`` itself.
    started.add_argument(
        "name",
        metavar=message("metavar.command"),
        help=message("cli.jobs_command_help"),
    )
    started.add_argument(
        "--store", metavar=message("metavar.store"), help=message("cli.jobs_store_help")
    )
    started.add_argument(
        "--options",
        type=json_object,
        default={},
        metavar="JSON",
        help=message("cli.commands_options_help"),
    )
    planned = add_parser(actions, "plan", "cli.jobs_plan_help")
    planned.add_argument(
        "job", metavar=message("metavar.job"), help=message("cli.jobs_job_help")
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run an action of ``archiwista jobs``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``jobs`` (``action`` names the action).
    paths : AppPaths
        Local index, configuration (the stores, offline mode) and jobs.
    registry : PluginRegistry
        Producer plugins: the producer's catalog and its check of the options.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's Polish
        message and its ``archiwista-error/1`` document, and the progress of
        a job, go to ``err``.

    Returns
    -------
    int
        ``0``; the outcome of a job that did not succeed (``10``, ``11`` or
        ``130``); the exit code of the registry code of a refusal.
    """
    with ExitStack() as stack:
        if args.action == "plan":
            return _plan(stack, args, paths, registry, out, err)
        return _start(stack, args, paths, registry, out, err)


def _start(
    stack: ExitStack,
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Start a job as ``POST /jobs`` does, follow it and print it as it ended."""
    given: dict[str, Any] = {
        "kind": args.kind,
        "producer": args.producer,
        "command": args.name,
        "options": args.options,
    }
    if args.store is not None:
        given["store"] = args.store
    try:
        request = JobRequest.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    try:
        service = SettingsService(ConfigStore(paths.config_file), registry)
        settings = service.get()
        jobs = stack.enter_context(JobSupervisor(paths, service))
    except _UNUSABLE as error:
        return _unusable(error, err)
    kind = label("job.kind", request.kind)

    def submit() -> JobRecord:
        return start(
            registry,
            settings,
            jobs,
            kind=request.kind,
            store=request.store,
            call=request.call(),
            actor=LOCAL_OWNER,
        )

    def heard(event: JobEvent) -> str | None:
        if event.type != "notice":
            return None
        text = event.data["message"]
        return message("cli.jobs_notice", job=event.job_id, message=text)

    try:
        record = run_foreground(
            jobs,
            submit,
            err,
            started=lambda job: message("cli.jobs_started", kind=kind, job=job.id),
            event=heard,
            cancelling=lambda job: message(
                "cli.jobs_cancelling", kind=kind, job=job.id
            ),
        )
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    detail = JobDetail.of(jobs.get(record.id) or record)
    if detail.state in FINISHED_STATES and detail.error is not None:
        failure = message(
            "cli.jobs_job_failed",
            kind=kind,
            job=detail.id,
            state=label("job.state", detail.state),
            detail=detail.error.detail,
        )
        err.write(failure + "\n")
    out.write((detail.model_dump_json() if args.json else _job_text(detail)) + "\n")
    return exit_status(detail.state)


def _plan(
    stack: ExitStack,
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Print the plan a ``check`` job kept, as ``GET /jobs/{job}/plan``."""
    try:
        queries = stack.enter_context(IndexQueries(paths.index_file))
        service = SettingsService(ConfigStore(paths.config_file), registry)
        jobs = stack.enter_context(JobSupervisor(paths, service))
    except _UNUSABLE as error:
        return _unusable(error, err)
    try:
        stored = kept_plan(queries, jobs, args.job, visible=ALL_PROJECTS)
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    plan = ActionPlanInfo.of(stored)
    out.write((plan.model_dump_json() if args.json else _plan_text(plan)) + "\n")
    return 0


# What keeps a command from opening the settings, the index or the jobs.
_UNUSABLE = (SettingsValidationError, IndexUnsupportedError, OSError, sqlite3.Error)


def _unusable(error: Exception, err: TextIO) -> int:
    """Refuse a command whose settings, index or jobs cannot be opened."""
    detail = with_detail(message("cli.jobs_failed"), str(error))
    return refuse(exception_problem(error, detail), err)


def _job_text(detail: JobDetail) -> str:
    """Return a job as it ended for a person; a plan adds its counts and its line."""
    kind = label("job.kind", detail.kind)
    state = label("job.state", detail.state)
    lines: list[str] = [message("cli.jobs_job", kind=kind, job=detail.id, state=state)]
    result = detail.result
    if detail.kind == "check" and result is not None:
        counts = result["counts"]
        todo = sum(counts[status] for status in PLAN_TODO)
        size, complete = result["size_bytes"], result["size_complete"]
        lines.append(_counts(counts, todo=todo, size=size, complete=complete))
        lines.append(message("cli.jobs_line", line=result["line"]))
    return "\n".join(lines)


def _plan_text(plan: ActionPlanInfo) -> str:
    """Return a kept plan for a person: a line per position, then the counts."""
    checked_at = plan.checked_at.isoformat(timespec="seconds")
    lines: list[str] = [
        message(
            "cli.jobs_plan", job=plan.job_id, store=plan.store, checked_at=checked_at
        )
    ]
    none = message("cli.jobs_no_label")
    lines += [
        message(
            "cli.jobs_plan_entry",
            status=label("job.plan", entry.status),
            path=entry.path,
            local=entry.local_label or none,
            available=entry.available_label or none,
        )
        for entry in plan.entries
    ]
    size, complete = plan.size_bytes, plan.size_complete
    lines.append(_counts(plan.counts, todo=plan.todo, size=size, complete=complete))
    lines.append(message("cli.jobs_line", line=plan.line))
    return "\n".join(lines)


def _counts(
    counts: Mapping[PlanStatus, int], *, todo: int, size: int | None, complete: bool
) -> str:
    """Return the positions of a plan by status, what a run downloads and its size."""
    named = ", ".join(
        f"{label('job.plan', status)} {counts[status]}"
        for status in PLAN_STATUSES
        if counts[status]
    )
    return message(
        "cli.jobs_counts",
        positions=sum(counts.values()),
        counts=named,
        todo=todo,
        size=_size(size, complete=complete),
    )


def _size(size: int | None, *, complete: bool) -> str:
    """Return the size of a run for a person: unknown, at least, or whole."""
    if size is None:
        return message("cli.jobs_size_unknown")
    megabytes = f"{size / 1_000_000:.1f} MB".replace(".", ",")
    if complete:
        return message("cli.jobs_size", size=megabytes)
    return message("cli.jobs_size_partial", size=megabytes)
