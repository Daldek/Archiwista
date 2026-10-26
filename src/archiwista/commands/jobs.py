"""``archiwista jobs``: background jobs (plan of 2026-10-25, A4 to A6).

``jobs start RODZAJ PRODUCENT POLECENIE --store ID [--options JSON] [--plan
ZADANIE]`` starts a job of a command of the producer's catalog on a configured
store (``POST /jobs``) and follows it to its end in the foreground
(``archiwista.jobs.foreground``): kind ``check`` plans a run without its
effects, ``download`` runs it in the store, with ``--plan`` the plan a
``check`` job kept. It prints the job as it ended (``GET /jobs/{job}``,
``JobDetail``) and exits with its outcome: ``0`` succeeded, ``10`` partial,
``11`` failed, ``130`` cancelled or interrupted (ERR §1). ``jobs retry
ZADANIE`` starts a job that did not succeed again (``POST
/jobs/{job}/retry``) and follows the new job the same way. ``jobs plan
ZADANIE`` prints the plan a ``check`` job kept (``GET /jobs/{job}/plan``,
``ActionPlanInfo``) without the network; ``jobs list`` the jobs (``GET
/jobs``, ``JobList``, with its filters), ``jobs show ZADANIE`` one job
(``JobDetail``), ``jobs cancel ZADANIE`` cancels a job that waits or runs,
also one a running server supervises (``POST /jobs/{job}/cancel``: the job as
it is right after the request), and ``jobs log ZADANIE`` prints the end of its
log (``GET /jobs/{job}/log``, ``JobLog``); these exit ``0``. All of them call
``archiwista.services`` without HTTP, as the owner of the installation
(``LOCAL_OWNER``, who may write the stores and sees every job), with the
``Authorizer`` over the state database; ``--json`` prints the route's model,
a refusal prints no model and ends standard error with its
``archiwista-error/1`` document.
"""

import argparse
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from typing import Any, TextIO

from pydantic import BaseModel, ValidationError

from archiwista.api.models import JobDetail, JobFilters, JobList, JobLog
from archiwista.api.models_actions import ActionPlanInfo, JobRequest
from archiwista.api.slots import checked_project
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
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
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.jobs import (
    ACTIVE_STATES,
    FINISHED_STATES,
    JobEvent,
    JobRecord,
    JobSupervisor,
)
from archiwista.jobs.foreground import exit_status, run_foreground
from archiwista.jobs.protocol import STOP_TIMEOUT_S
from archiwista.messages import label, message, with_detail
from archiwista.services import jobs as job_controls
from archiwista.services.actions import kept_plan, start
from archiwista.sources import (
    FILE_STATUSES,
    PLAN_STATUSES,
    PLAN_TODO,
    PROJECT_FILE_STATUSES,
    TASK_OUTCOMES,
    PlanStatus,
)
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

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
    started.add_argument(
        "--plan",
        dest="plan_job",
        metavar=message("metavar.job"),
        help=message("cli.jobs_plan_job_help"),
    )
    listed = add_parser(actions, "list", "cli.jobs_list_help")
    listed.add_argument(
        "--kind",
        metavar=message("metavar.kind"),
        help=message("cli.jobs_list_kind_help"),
    )
    listed.add_argument(
        "--store",
        metavar=message("metavar.store"),
        help=message("cli.jobs_list_store_help"),
    )
    listed.add_argument(
        "--state",
        metavar=message("metavar.state"),
        help=message("cli.jobs_list_state_help"),
    )
    listed.add_argument(
        "--project",
        metavar=message("metavar.project"),
        help=message("cli.jobs_list_project_help"),
    )
    listed.add_argument(
        "--limit",
        metavar=message("metavar.number"),
        help=message("cli.jobs_list_limit_help"),
    )
    listed.add_argument(
        "--cursor",
        metavar=message("metavar.cursor"),
        help=message("cli.jobs_list_cursor_help"),
    )
    for action, help_key in (
        ("plan", "cli.jobs_plan_help"),
        ("show", "cli.jobs_show_help"),
        ("cancel", "cli.jobs_cancel_help"),
        ("retry", "cli.jobs_retry_help"),
        ("log", "cli.jobs_log_help"),
    ):
        one = add_parser(actions, action, help_key)
        one.add_argument(
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
        if args.action == "start":
            return _start(stack, args, paths, registry, out, err)
        if args.action == "list":
            return _list(stack, args, paths, registry, out, err)
        if args.action == "plan":
            return _plan(stack, args, paths, registry, out, err)
        return _control(stack, args, paths, registry, out, err)


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
    if args.plan_job is not None:
        given["plan_job"] = args.plan_job
    try:
        request = JobRequest.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    try:
        service = SettingsService(ConfigStore(paths.config_file), registry)
        settings = service.get()
        decisions = Authorizer(StateStore(paths.state_file), service.get)
        queries = stack.enter_context(IndexQueries(paths.index_file))
        jobs = stack.enter_context(JobSupervisor(paths, service))
    except _UNUSABLE as error:
        return _unusable(error, err)

    def submit() -> JobRecord:
        return start(
            registry,
            settings,
            jobs,
            queries,
            decisions,
            kind=request.kind,
            store=request.store,
            call=request.call(),
            actor=LOCAL_OWNER,
            visible=ALL_PROJECTS,
            plan_job=request.plan_job,
        )

    return foreground(jobs, submit, args, out, err)


def foreground(
    jobs: JobSupervisor,
    submit: Callable[[], JobRecord],
    args: argparse.Namespace,
    out: TextIO,
    err: TextIO,
) -> int:
    """Submit a job, follow it to its end and print it as it ended.

    Parameters
    ----------
    jobs : JobSupervisor
        Started supervisor of the job.
    submit : Callable[[], JobRecord]
        Submits the job; a refusal raises before a job exists.
    args : argparse.Namespace
        The command's arguments: ``json`` chooses the output.
    out, err : TextIO
        The job's ``JobDetail`` (as JSON with ``--json``); its progress, its
        notices, why it did not succeed and a refusal go to ``err``.

    Returns
    -------
    int
        ``0`` succeeded, ``10`` partial, ``11`` failed, ``130`` cancelled or
        interrupted; the exit code of the registry code of a refusal.
    """

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
            started=lambda job: message(
                "cli.jobs_started", kind=label("job.kind", job.kind), job=job.id
            ),
            event=heard,
            cancelling=lambda job: message(
                "cli.jobs_cancelling", kind=label("job.kind", job.kind), job=job.id
            ),
        )
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    detail = JobDetail.of(jobs.get(record.id) or record)
    if detail.state in FINISHED_STATES and detail.error is not None:
        err.write(_failure(detail) + "\n")
    out.write((detail.model_dump_json() if args.json else _job_text(detail)) + "\n")
    return exit_status(detail.state)


def _list(
    stack: ExitStack,
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Print the jobs as ``GET /jobs`` lists them, with its filters."""
    names = ("kind", "store", "state", "project", "limit", "cursor")
    given = {name: getattr(args, name) for name in names}
    try:
        filters = JobFilters.model_validate(
            {name: value for name, value in given.items() if value is not None}
        )
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    try:
        queries = stack.enter_context(IndexQueries(paths.index_file))
        service = SettingsService(ConfigStore(paths.config_file), registry)
        jobs = stack.enter_context(JobSupervisor(paths, service))
    except _UNUSABLE as error:
        return _unusable(error, err)
    try:
        checked_project(queries, filters.project, ALL_PROJECTS)
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    page = jobs.list(
        kind=filters.kind,
        store=filters.store,
        state=filters.state,
        project=filters.project,
        limit=filters.limit,
        cursor=filters.cursor,
        visible=ALL_PROJECTS,
    )
    listed = JobList.of(page)
    out.write((listed.model_dump_json() if args.json else _list_text(listed)) + "\n")
    return 0


def _control(
    stack: ExitStack,
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Show, cancel, retry a job or print its log, as the routes of the job do."""
    try:
        service = SettingsService(ConfigStore(paths.config_file), registry)
        decisions = Authorizer(StateStore(paths.state_file), service.get)
        queries = stack.enter_context(IndexQueries(paths.index_file))
        jobs = stack.enter_context(JobSupervisor(paths, service))
    except _UNUSABLE as error:
        return _unusable(error, err)
    if args.action == "retry":

        def submit() -> JobRecord:
            return job_controls.retry(
                jobs,
                decisions,
                queries,
                job_id=args.job,
                actor=LOCAL_OWNER,
                visible=ALL_PROJECTS,
            )

        return foreground(jobs, submit, args, out, err)
    model: BaseModel
    try:
        if args.action == "log":
            tail = job_controls.log(jobs, job_id=args.job, visible=ALL_PROJECTS)
            model, text = JobLog.of(args.job, tail), tail.text
            if tail.truncated and not args.json:
                err.write(
                    message("cli.jobs_log_truncated", size=tail.size_bytes) + "\n"
                )
        elif args.action == "cancel":
            record = job_controls.cancel(
                jobs,
                decisions,
                job_id=args.job,
                actor=LOCAL_OWNER,
                visible=ALL_PROJECTS,
            )
            model = detail = JobDetail.of(record)
            text = _job_text(detail)
            if detail.state in ACTIVE_STATES:
                stopping = message(
                    "cli.jobs_cancel_requested", seconds=round(STOP_TIMEOUT_S)
                )
                text = f"{text}\n{stopping}"
        else:
            detail = JobDetail.of(
                job_controls.visible_job(jobs, args.job, ALL_PROJECTS)
            )
            model, text = detail, _job_text(detail)
            if detail.error is not None:
                text = f"{text}\n{_failure(detail)}"
    except ArchiwistaError as error:
        return refuse(describe(error), err)
    if args.json:
        out.write(model.model_dump_json() + "\n")
    else:
        out.write(text if text.endswith("\n") or not text else f"{text}\n")
    return 0


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


# What keeps a command from opening the settings, the state, the index or the jobs.
_UNUSABLE = (
    SettingsValidationError,
    StateError,
    IndexUnsupportedError,
    OSError,
    sqlite3.Error,
)


def _unusable(error: Exception, err: TextIO) -> int:
    """Refuse a command whose settings, index or jobs cannot be opened."""
    detail = with_detail(message("cli.jobs_failed"), str(error))
    return refuse(exception_problem(error, detail), err)


def _job_text(detail: JobDetail) -> str:
    """Return a job as it ended for a person.

    A plan adds its counts and its line, a download the files by status and
    the units that failed, a project's download or repin its tasks by
    outcome, a project's check or verification its files by state.
    """
    kind = label("job.kind", detail.kind)
    state = label("job.state", detail.state)
    lines: list[str] = [message("cli.jobs_job", kind=kind, job=detail.id, state=state)]
    result = detail.result
    if result is None:
        return lines[0]
    if detail.kind == "check":
        counts = result["counts"]
        todo = sum(counts[status] for status in PLAN_TODO)
        size, complete = result["size_bytes"], result["size_complete"]
        lines.append(_counts(counts, todo=todo, size=size, complete=complete))
        lines.append(message("cli.jobs_line", line=result["line"]))
    if detail.kind == "download":
        files: Mapping[str, int] = result["counts"]
        named = ", ".join(
            f"{label('job.file', status)} {files[status]}" for status in FILE_STATUSES
        )
        lines.append(
            message(
                "cli.jobs_files",
                files=sum(files.values()),
                counts=named,
                failed=result["failed"],
            )
        )
    if detail.kind in ("project_download", "project_repin"):
        tasks: Mapping[str, int] = result["counts"]
        named = ", ".join(
            f"{label('job.task', outcome)} {tasks[outcome]}"
            for outcome in TASK_OUTCOMES
            if tasks[outcome]
        )
        lines.append(
            message("cli.jobs_project_tasks", tasks=sum(tasks.values()), counts=named)
        )
    if detail.kind in ("project_check", "project_verify"):
        states: Mapping[str, int] = result["counts"]
        named = ", ".join(
            f"{label('job.project_file', status)} {states[status]}"
            for status in PROJECT_FILE_STATUSES
            if states[status]
        )
        lines.append(
            message(
                "cli.jobs_project_files",
                files=sum(states.values()),
                counts=named,
                not_downloaded=len(result["not_downloaded"]),
            )
        )
    return "\n".join(lines)


def _failure(detail: JobDetail) -> str:
    """Return why a job did not succeed, for a person."""
    assert detail.error is not None
    return message(
        "cli.jobs_job_failed",
        kind=label("job.kind", detail.kind),
        job=detail.id,
        state=label("job.state", detail.state),
        detail=detail.error.detail,
    )


def _list_text(listed: JobList) -> str:
    """Return a page of jobs for a person: a line per job, then the next page."""
    lines = [
        message(
            "cli.jobs_list_line",
            job=item.id,
            kind=label("job.kind", item.kind),
            state=label("job.state", item.state),
            actor=item.actor,
            created=item.created_at.isoformat(timespec="seconds"),
        )
        for item in listed.items
    ]
    if not lines:
        lines.append(message("cli.jobs_list_none"))
    if listed.next_cursor is not None:
        lines.append(message("cli.jobs_list_next", cursor=listed.next_cursor))
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
