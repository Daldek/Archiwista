"""``archiwista preview-warm``: the first look at current versions prepared ahead.

``archiwista preview-warm [--store MAGAZYN] [--product PRODUKT] [--segment
SEGMENT] [--project PROJEKT] [--area-id OBSZAR]`` (plan of 2026-10-25, A9;
ADR-041) starts the ``preview_warm`` job as ``POST /previews/warm`` does and
follows it to its end in the foreground (``archiwista.jobs.foreground``): the
preview pane's thumbnail and the map's tiles at the file's smallest zoom of
the current versions the filters select (with ``--project`` also the
project's own data), rendered at the lowest priority into the preview cache
the server uses, without evicting previews used in the last week. It is a
command of its own, not ``preview warm``: ``preview`` takes an object's ref.
It prints the job as it ended (``GET /jobs/{job}``, ``JobDetail``) and exits
with its outcome: ``0`` succeeded, ``10`` partial (files that failed, or
versions skipped when the cache had no more room), ``11`` failed, ``130``
cancelled or interrupted (ERR §1). It calls ``archiwista.services.warm``
without HTTP, as the owner of the installation (``LOCAL_OWNER``, who sees
every project); ``--json`` prints the route's model, a refusal prints no
model and ends standard error with its ``archiwista-error/1`` document.
"""

import argparse
import sqlite3
from contextlib import ExitStack
from typing import Any, TextIO

from pydantic import ValidationError

from archiwista.api.models_previews import WarmRequest
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.commands import Commands, add_parser
from archiwista.commands.jobs import foreground
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import exception_problem, refuse, validation_problem
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message, with_detail
from archiwista.services.warm import start
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"preview-warm"})
# The filters: option, field of ``WarmRequest``, placeholder (a catalog entry,
# else the word itself, the same in both languages) and help.
_FILTERS = (
    ("--store", "store", "metavar.store", "cli.preview_warm_store_help"),
    ("--product", "product", "metavar.product", "cli.preview_warm_product_help"),
    ("--segment", "segment", None, "cli.preview_warm_segment_help"),
    ("--project", "project", "metavar.project", "cli.preview_warm_project_help"),
    ("--area-id", "area_id", "metavar.area", "cli.preview_warm_area_id_help"),
)

# What keeps the command from opening the settings, the index or the jobs.
_UNUSABLE = (
    SettingsValidationError,
    IndexUnsupportedError,
    OSError,
    sqlite3.Error,
)


def add_commands(commands: Commands) -> None:
    """Add ``archiwista preview-warm`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    parser = add_parser(commands, "preview-warm", "cli.preview_warm_help")
    for option, field, metavar, help_key in _FILTERS:
        parser.add_argument(
            option,
            dest=field,
            metavar="SEGMENT" if metavar is None else message(metavar),
            help=message(help_key),
        )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Start a warm-up of previews, follow it and print it as it ended.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments: the filters and ``json``.
    paths : AppPaths
        Configuration (the stores, the preview cache limit), local index,
        preview cache and jobs.
    registry : PluginRegistry
        Producer plugins, to read the settings.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's message and
        its ``archiwista-error/1`` document, and the progress of the job, go
        to ``err``.

    Returns
    -------
    int
        ``0``; the outcome of a job that did not succeed (``10``, ``11`` or
        ``130``); the exit code of the registry code of a refusal.
    """
    given: dict[str, Any] = {
        field: value
        for _, field, _, _ in _FILTERS
        if (value := getattr(args, field)) is not None
    }
    try:
        request = WarmRequest.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    with ExitStack() as stack:
        try:
            service = SettingsService(ConfigStore(paths.config_file), registry)
            settings = service.get()
            queries = stack.enter_context(IndexQueries(paths.index_file))
            jobs = stack.enter_context(JobSupervisor(paths, service))
        except _UNUSABLE as error:
            detail = with_detail(message("cli.jobs_failed"), str(error))
            return refuse(exception_problem(error, detail), err)

        def submit() -> JobRecord:
            return start(
                settings,
                jobs,
                queries,
                store=request.store,
                product=request.product,
                segment=request.segment,
                project=request.project,
                area_id=request.area_id,
                actor=LOCAL_OWNER,
                visible=ALL_PROJECTS,
            )

        return foreground(jobs, submit, args, out, err)
