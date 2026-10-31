"""The commands of the jobs over a project's groups (A-ADR-049 decision 11).

``archiwista project-verify PROJEKT [GRUPA ...]`` hashes the pinned files in
their store without the network, ``project-check PROJEKT [GRUPA ...]``
compares the pins with the source, ``project-repin PROJEKT GRUPA`` pins one
group anew to the source's newer versions and ``project-restore PROJEKT
[GRUPA ...]`` downloads the missing pinned versions again; no group named is
every group. Each starts its job as ``POST /projects/{project}/jobs`` does,
follows it to its end in the foreground (``archiwista.jobs.foreground``),
prints the job as it ended (``GET /jobs/{job}``, ``JobDetail``) and exits
with its outcome: ``0`` succeeded, ``10`` partial, ``11`` failed, ``130``
cancelled or interrupted (ERR §1). They call
``archiwista.services.project_jobs`` without HTTP, as the owner of the
installation (``LOCAL_OWNER``, who may change every project and write the
stores), through the ``Authorizer`` over the state database; ``--json``
prints the route's model, a refusal prints no model and ends standard error
with its ``archiwista-error/1`` document.
"""

import argparse
import sqlite3
from contextlib import ExitStack
from typing import Any, TextIO

from pydantic import ValidationError

from archiwista.api.models_project_jobs import ProjectJobRequest
from archiwista.auth import ALL_PROJECTS, LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
from archiwista.commands.jobs import foreground
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import exception_problem, refuse, validation_problem
from archiwista.errors import StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.jobs import JobRecord, JobSupervisor
from archiwista.messages import message, with_detail
from archiwista.services.project_jobs import ProjectJobKind, start
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

# The kind of the job each command starts, and its help.
_KINDS: dict[str, tuple[ProjectJobKind, str]] = {
    "project-verify": ("verify", "cli.project_verify_help"),
    "project-check": ("check", "cli.project_check_help"),
    "project-repin": ("repin", "cli.project_repin_help"),
    "project-restore": ("restore", "cli.project_restore_help"),
}
COMMANDS = frozenset(_KINDS)

# What keeps a command from opening the settings, the state, the index or the jobs.
_UNUSABLE = (
    SettingsValidationError,
    StateError,
    IndexUnsupportedError,
    OSError,
    sqlite3.Error,
)


def add_commands(commands: Commands) -> None:
    """Add the four commands of a project's jobs (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    for name, (kind, help_key) in _KINDS.items():
        parser = add_parser(commands, name, help_key)
        parser.add_argument(
            "project",
            metavar=message("metavar.project"),
            help=message("cli.project_help"),
        )
        if kind == "repin":
            parser.add_argument(
                "group",
                metavar=message("metavar.group"),
                help=message("cli.project_repin_group_help"),
            )
        else:
            parser.add_argument(
                "groups",
                nargs="*",
                metavar=message("metavar.group"),
                help=message("cli.project_job_groups_help"),
            )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Start a job of a project's groups, follow it and print it as it ended.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments (``command`` names the command).
    paths : AppPaths
        Configuration (the stores, project directories, offline mode), local
        index, state database and jobs.
    registry : PluginRegistry
        Producer plugins: the producers of the groups run the calls.
    out, err : TextIO
        The route's model (as JSON with ``--json``); a refusal's Polish
        message and its ``archiwista-error/1`` document, and the progress of
        the job, go to ``err``.

    Returns
    -------
    int
        ``0``; the outcome of a job that did not succeed (``10``, ``11`` or
        ``130``); the exit code of the registry code of a refusal.
    """
    kind, _ = _KINDS[args.command]
    given: dict[str, Any] = {"kind": kind}
    if kind == "repin":
        given["groups"] = [args.group]
    elif args.groups:
        given["groups"] = args.groups
    try:
        request = ProjectJobRequest.model_validate(given)
    except ValidationError as error:
        located = ({**item, "loc": ("body", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    with ExitStack() as stack:
        try:
            service = SettingsService(ConfigStore(paths.config_file), registry)
            settings = service.get()
            decisions = Authorizer(StateStore(paths.state_file), service.get)
            queries = stack.enter_context(IndexQueries(paths.index_file))
            jobs = stack.enter_context(JobSupervisor(paths, service))
        except _UNUSABLE as error:
            detail = with_detail(message("cli.jobs_failed"), str(error))
            return refuse(exception_problem(error, detail), err)

        def submit() -> JobRecord:
            return start(
                registry,
                settings,
                jobs,
                queries,
                decisions,
                args.project,
                kind=request.kind,
                groups=request.groups,
                actor=LOCAL_OWNER,
                visible=ALL_PROJECTS,
            )

        return foreground(jobs, submit, args, out, err)
