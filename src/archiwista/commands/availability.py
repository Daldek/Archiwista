"""``archiwista availability``: what the source has for an area (plan 2026-10-25, A2).

``availability show OBSZAR --product PRODUKT [--producer ID]`` prints the last
report of an area and a product from the index (``GET /availability``)
without the network. ``availability check OBSZAR --product PRODUKT
[--producer ID] [--force]`` asks the source (``POST /availability``): a
report younger than seven days answers at once unless ``--force`` is given;
otherwise the ``availability`` job runs in the foreground
(``archiwista.jobs.foreground``) and the command prints the report it kept,
as ``GET /availability`` returns it. Both call
``archiwista.services.availability`` without HTTP, as the owner of the
installation (``LOCAL_OWNER``); ``--json`` prints the route's model,
``AvailabilityInfo``. A check that does not succeed prints its ``JobDetail``
and exits with the outcome (``11`` failed, ``130`` cancelled or
interrupted); a refusal prints no model, its ``archiwista-error/1`` document
ends standard error (offline mode: ``conflict``, exit 4).
"""

import argparse
import sqlite3
from contextlib import ExitStack
from typing import TextIO

from pydantic import BaseModel, ValidationError

from archiwista.api.models import JobDetail
from archiwista.api.models_availability import (
    AvailabilityInfo,
    AvailabilityQuery,
    AvailabilityRequest,
)
from archiwista.auth import LOCAL_OWNER
from archiwista.commands import Commands, add_parser
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
from archiwista.services.availability import AreaAvailability, check, stored
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"availability"})


def add_commands(commands: Commands) -> None:
    """Add ``archiwista availability`` and its actions (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    text = message("cli.availability_help")
    parser = commands.add_parser("availability", help=text, description=text)
    actions = parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )
    _request(add_parser(actions, "show", "cli.availability_show_help"))
    asked = add_parser(actions, "check", "cli.availability_check_help")
    _request(asked)
    asked.add_argument(
        "--force", action="store_true", help=message("cli.availability_force_help")
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run an action of ``archiwista availability``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``availability`` (``action`` names the action).
    paths : AppPaths
        Local index, configuration (offline mode) and jobs.
    registry : PluginRegistry
        Producer plugins: the products a producer checks.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's Polish
        message and its ``archiwista-error/1`` document, and the progress of
        a check, go to ``err``.

    Returns
    -------
    int
        ``0`` with a report; the exit code of the registry code of a refusal;
        ``11`` or ``130`` when the check does not succeed.
    """
    try:
        request = _validated(args)
    except ValidationError as error:
        where = "body" if args.action == "check" else "query"
        located = ({**item, "loc": (where, *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    with ExitStack() as stack:
        try:
            queries = stack.enter_context(IndexQueries(paths.index_file))
            jobs = None
            if isinstance(request, AvailabilityRequest):
                settings = SettingsService(ConfigStore(paths.config_file), registry)
                jobs = stack.enter_context(JobSupervisor(paths, settings))
        except (
            SettingsValidationError,
            IndexUnsupportedError,
            OSError,
            sqlite3.Error,
        ) as error:
            return refuse(
                exception_problem(
                    error, with_detail(message("cli.availability_failed"), str(error))
                ),
                err,
            )
        try:
            if isinstance(request, AvailabilityRequest):
                assert jobs is not None  # started for a check
                record = _check(queries, registry, jobs, request, err)
                if record is not None and record.state != "succeeded":
                    return _unsuccessful(args, jobs, record, out, err)
            found = stored(
                queries,
                area_id=request.area_id,
                product=request.product,
                producer=request.producer,
            )
        except ArchiwistaError as error:
            return refuse(describe(error), err)
    info = AvailabilityInfo.of(found)
    _print(args, out, info, _report_text(info))
    return 0


def _request(parser: argparse.ArgumentParser) -> None:
    """Add the area, ``--product`` and ``--producer`` of both actions."""
    parser.add_argument(
        "area_id",
        metavar=message("metavar.area"),
        help=message("cli.availability_area_help"),
    )
    parser.add_argument(
        "--product",
        required=True,
        metavar=message("metavar.product"),
        help=message("cli.availability_product_help"),
    )
    parser.add_argument(
        "--producer",
        default="kartograf",
        metavar=message("metavar.producer"),
        help=message("cli.availability_producer_help"),
    )


def _validated(args: argparse.Namespace) -> AvailabilityRequest | AvailabilityQuery:
    """Validate the arguments as the route its body or query.

    Raises
    ------
    pydantic.ValidationError
        A value the route refuses (``400 validation_error``).
    """
    given = {
        "area_id": args.area_id,
        "product": args.product,
        "producer": args.producer,
    }
    if args.action == "check":
        return AvailabilityRequest.model_validate({**given, "force": args.force})
    return AvailabilityQuery.model_validate(given)


def _check(
    queries: IndexQueries,
    registry: PluginRegistry,
    jobs: JobSupervisor,
    request: AvailabilityRequest,
    err: TextIO,
) -> JobRecord | None:
    """Ask the source unless a fresh report is kept; return the job as it ended.

    ``None`` when the kept report answers (also after a check of another
    process that this one joined and that kept a fresh report meanwhile).
    """

    def submit() -> JobRecord | None:
        found = check(
            queries,
            registry,
            jobs,
            area_id=request.area_id,
            product=request.product,
            producer=request.producer,
            force=request.force,
            actor=LOCAL_OWNER,
        )
        return None if isinstance(found, AreaAvailability) else found

    return run_foreground(
        jobs,
        submit,
        err,
        started=lambda job: message("cli.availability_started", job=job.id),
        event=_event,
        cancelling=lambda job: message("cli.availability_cancelling", job=job.id),
    )


def _unsuccessful(
    args: argparse.Namespace,
    jobs: JobSupervisor,
    record: JobRecord,
    out: TextIO,
    err: TextIO,
) -> int:
    """Print a check that did not succeed as ``GET /jobs/{job}``; return its status.

    A job of another process still active (Ctrl+C stopped the waiting, which
    said so already) is printed as it is now.
    """
    detail = JobDetail.of(jobs.get(record.id) or record)
    if detail.state in FINISHED_STATES:
        failure = message(
            "cli.availability_job_failed",
            job=detail.id,
            state=label("job.state", detail.state),
            detail="" if detail.error is None else detail.error.detail,
        )
        err.write(failure + "\n")
    title = message(
        "cli.availability_job", job=detail.id, state=label("job.state", detail.state)
    )
    _print(args, out, detail, title)
    return exit_status(detail.state)


def _event(event: JobEvent) -> str | None:
    if event.type == "notice":
        return message("cli.availability_notice", message=event.data["message"])
    return None


def _print(args: argparse.Namespace, out: TextIO, model: BaseModel, text: str) -> None:
    """Print the route's model with ``--json``, else the Polish text."""
    out.write((model.model_dump_json() if args.json else text) + "\n")


def _report_text(info: AvailabilityInfo) -> str:
    """Return a report for a person: when it was checked, then each combination."""
    report = info.report
    lines = [
        message(
            "cli.availability_report",
            product=info.product,
            area=info.area.name or info.area.id,
            producer=info.producer,
            checked_at=info.checked_at.astimezone().strftime("%Y-%m-%d %H:%M"),
        )
    ]
    for item in report.combinations:
        variant = (
            item.year,
            item.horizontal,
            item.resolution,
            item.vertical_crs,
            item.format,
        )
        lines.append(
            message(
                "cli.availability_combination",
                variant=" · ".join(str(part) for part in variant if part is not None),
                state=label(
                    "cli.availability_state", "complete" if item.complete else "partial"
                ),
                full=len(item.sheets_full),
                partial=len(item.sheets_partial),
                missing=len(item.sheets_missing),
            )
        )
    if not report.combinations:
        lines.append(message("cli.availability_nothing"))
    lines.extend(
        message("cli.availability_not_checked", part=item.part, detail=item.detail)
        for item in report.failed
    )
    return "\n".join(lines)
