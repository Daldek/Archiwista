"""``archiwista preview``: the preview of an object for people and AI agents.

``archiwista preview REF [--style STYL] [--size BOK] [--output PLIK.png]
[--build] [--json]`` (plan v0.2, decision 11) prints the ``PreviewInfo`` of
the object ``REF`` (the ``ref`` of an API answer) as ``GET …/preview``
answers it. ``--output`` also writes its PNG thumbnail (``GET
…/preview.png``), rendered by a render process of the command into the
preview cache the server uses, so an agent that sees images looks at it
without a browser; ``--build`` first builds what the file needs (its local
COG, past the auto-build limits too) in a ``preview`` job run in the
foreground (``archiwista.jobs.foreground``; ``POST …/preview`` with
``force``). Everything goes through ``PreviewService`` with one render
process, as the owner of the installation (``LOCAL_OWNER``). Without
``--build`` no job supervisor runs, so the answer names no ``job``: a file a
server is building shows ``needs_build``. A build that does not succeed still
prints the preview and exits with its outcome (``11`` failed, ``130``
cancelled or interrupted); a refusal prints no preview, its
``archiwista-error/1`` document ends standard error.
"""

import argparse
import asyncio
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from archiwista.api.models_previews import PreviewInfo, ThumbnailQuery
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
from archiwista.config import (
    AppPaths,
    AppSettings,
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
    JobEvent,
    JobRecord,
    JobState,
    JobSupervisor,
    label,
)
from archiwista.jobs.foreground import exit_status, run_foreground
from archiwista.messages import MESSAGES, with_detail
from archiwista.previews.cache import PreviewCache
from archiwista.previews.pool import RenderPool
from archiwista.previews.service import PreviewService
from archiwista.refs import ObjectResolver, VisibleProjects, format_ref, parse_ref
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset({"preview"})
# Side of the thumbnail ``--output`` writes.
DEFAULT_SIZE = 512


@dataclass(frozen=True, slots=True)
class LocalPreviews:
    """What a command previews with: the index, a render pool, the service."""

    queries: IndexQueries
    pool: RenderPool
    service: PreviewService


@contextmanager
def local_previews(
    paths: AppPaths,
    settings: AppSettings,
    *,
    jobs: JobSupervisor | None = None,
    visible: VisibleProjects | None = None,
) -> Iterator[LocalPreviews]:
    """Open the index, the server's preview cache and one render process.

    Parameters
    ----------
    paths : AppPaths
        The local index and the preview cache (``previews_dir``): what the
        command renders, the server finds, and the other way round.
    settings : AppSettings
        The stores' directories and the preview cache limit.
    jobs : JobSupervisor or None, optional
        The started supervisor of ``PreviewService.build``, if any.
    visible : Callable[[Principal], ProjectVisibility] or None, optional
        The projects a principal sees (``Authorizer.visible_projects``):
        their own data and snapshots are previewed too; without it only
        store versions.

    Raises
    ------
    IndexUnsupportedError
        The index has a schema this version does not read.
    OSError, sqlite3.Error
        The preview cache cannot be opened.
    """
    with ExitStack() as stack:
        queries = stack.enter_context(IndexQueries(paths.index_file))
        cache = stack.enter_context(
            PreviewCache(
                paths.previews_dir, limit_bytes=settings.preview_cache_limit_bytes
            )
        )
        pool = stack.enter_context(
            RenderPool(workers=1, cache=cache, work_dir=paths.work_dir)
        )
        resolver = ObjectResolver(queries, lambda: settings, visible=visible)
        yield LocalPreviews(queries, pool, PreviewService(pool, resolver, jobs))


def add_commands(commands: Commands) -> None:
    """Add ``archiwista preview`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    preview = add_parser(commands, "preview", "cli_preview_help")
    preview.add_argument("ref", metavar="REF", help=MESSAGES["cli_preview_ref_help"])
    preview.add_argument(
        "--style", metavar="STYL", help=MESSAGES["cli_preview_style_help"]
    )
    preview.add_argument(
        "--size",
        type=int,
        default=DEFAULT_SIZE,
        metavar="BOK",
        help=MESSAGES["cli_preview_size_help"],
    )
    preview.add_argument(
        "--output",
        type=Path,
        metavar="PLIK.png",
        help=MESSAGES["cli_preview_output_help"],
    )
    preview.add_argument(
        "--build", action="store_true", help=MESSAGES["cli_preview_build_help"]
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run ``archiwista preview``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``preview``.
    paths : AppPaths
        Configuration file, local index, preview cache and jobs.
    registry : PluginRegistry
        Producer plugins, for the settings.
    out, err : TextIO
        The ``PreviewInfo`` (as JSON with ``--json``) or the problem;
        Polish messages, progress of the build.

    Returns
    -------
    int
        ``0`` on success; the exit code of the registry code of a refusal
        (the object, the thumbnail that cannot be written, the settings, the
        index or the preview cache); ``11`` or ``130`` when the build does not
        succeed.
    """
    try:
        query = ThumbnailQuery(style=args.style, size=args.size)
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    with ExitStack() as stack:
        try:
            settings = SettingsService(ConfigStore(paths.config_file), registry)
            decisions = Authorizer(StateStore(paths.state_file), settings.get)
            jobs = None
            if args.build:
                jobs = stack.enter_context(JobSupervisor(paths, settings))
            previews = stack.enter_context(
                local_previews(
                    paths,
                    settings.get(),
                    jobs=jobs,
                    visible=decisions.visible_projects,
                )
            )
        except (
            SettingsValidationError,
            IndexUnsupportedError,
            StateError,
            OSError,
            sqlite3.Error,
        ) as error:
            return refuse(
                exception_problem(
                    error, with_detail(MESSAGES["cli_preview_failed"], str(error))
                ),
                err,
            )
        try:
            return _preview(args, query, previews.service, jobs, out, err)
        except ArchiwistaError as error:
            return refuse(describe(error), err)


def _preview(
    args: argparse.Namespace,
    query: ThumbnailQuery,
    service: PreviewService,
    jobs: JobSupervisor | None,
    out: TextIO,
    err: TextIO,
) -> int:
    """Build, write the thumbnail, then print the preview of the object."""
    ref = format_ref(parse_ref(args.ref))
    status = 0
    if jobs is not None:
        status = _build(ref, service, jobs, err)
    written = None
    if status == 0 and args.output is not None:
        thumbnail = asyncio.run(
            service.thumbnail(
                ref, principal=LOCAL_OWNER, style=query.style, size=query.size
            )
        )
        assert thumbnail.data is not None  # asked without If-None-Match
        try:
            args.output.write_bytes(thumbnail.data)
        except OSError as error:
            return refuse(
                exception_problem(
                    error, with_detail(MESSAGES["cli_preview_failed"], str(error))
                ),
                err,
            )
        written = args.output
    info = asyncio.run(service.info(ref, principal=LOCAL_OWNER))
    if written is not None:
        style = query.style or info.default_style
        message = MESSAGES["cli_preview_written"].format(
            path=written, size=query.size, style=style
        )
        err.write(message + "\n")
    out.write((info.model_dump_json() if args.json else _info_text(info)) + "\n")
    return status


def _build(ref: str, service: PreviewService, jobs: JobSupervisor, err: TextIO) -> int:
    """Build what the file needs in the foreground; return the exit status.

    Why it did not succeed goes to ``err``, unless Ctrl+C stopped the waiting
    for another process's job, which said so already.
    """
    record = run_foreground(
        jobs,
        lambda: asyncio.run(service.build([ref], principal=LOCAL_OWNER, force=True)),
        err,
        started=lambda job: MESSAGES["cli_preview_build_started"].format(job=job.id),
        event=_build_event,
        cancelling=lambda job: MESSAGES["cli_preview_build_cancelling"].format(
            job=job.id
        ),
    )
    if record is None:
        return exit_status("succeeded")
    state, failure = _build_end(record, ref)
    if failure is not None:
        err.write(failure + "\n")
    return exit_status(state)


def _build_event(event: JobEvent) -> str | None:
    data = event.data
    if event.type == "progress":
        return MESSAGES["cli_preview_build_progress"].format(
            current=data["current"],
            total=data["total"],
            built=data.get("built", 0),
            cached=data.get("cached", 0),
            failed=data.get("failed", 0),
        )
    if event.type == "notice":
        return MESSAGES["cli_preview_build_notice"].format(message=data["message"])
    return None


def _build_end(record: JobRecord, ref: str) -> tuple[JobState, str | None]:
    """Return the state of the build of ``ref`` and why it failed, if it did.

    A ``preview`` job that succeeded without building ``ref`` has failed for
    it; a job still active after Ctrl+C has no failure to tell.
    """
    if record.state in ACTIVE_STATES:
        return record.state, None
    if record.state == "succeeded":
        result = record.result or {}
        failed = [item for item in result.get("failed", ()) if item["ref"] == ref]
        if not failed:
            return record.state, None
        state: JobState = "failed"
        detail = failed[0]["detail"] or failed[0]["code"]
    else:
        state = record.state
        detail = "" if record.error is None else record.error.detail
    return state, MESSAGES["cli_preview_build_failed"].format(
        job=record.id, state=label("job_state", state), detail=detail
    )


def _info_text(info: PreviewInfo) -> str:
    lines = [
        MESSAGES["cli_preview_title"].format(
            ref=info.ref,
            kind=MESSAGES[f"preview_kind_{info.kind}"],
            state=MESSAGES[f"preview_state_{info.state}"],
        )
    ]
    if info.reason is not None:
        lines.append(
            MESSAGES["cli_preview_reason"]
            .format(message=info.reason.message, fix=info.reason.fix)
            .rstrip()
        )
    if info.styles:
        styles = ", ".join(
            f"{style} ({MESSAGES[f'preview_style_{style}']})" for style in info.styles
        )
        lines.append(
            MESSAGES["cli_preview_styles"].format(
                styles=styles, default=info.default_style
            )
        )
    if info.bounds is not None and info.minzoom is not None:
        lines.append(
            MESSAGES["cli_preview_map"].format(
                minzoom=info.minzoom,
                maxzoom=info.maxzoom,
                bounds=" ".join(f"{value:.5f}" for value in info.bounds),
            )
        )
    if info.job is not None:
        lines.append(
            MESSAGES["cli_preview_job"].format(
                job=info.job.id, state=label("job_state", info.job.state)
            )
        )
    return "\n".join(lines)
