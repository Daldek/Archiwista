"""``archiwista files``, ``file``, ``snapshot``, ``own-scan``: own data of projects.

The commands of plan v0.2, decision 11, over the functions behind the routes
of ``archiwista.api.owndata``, as the owner of the installation
(``LOCAL_OWNER``) through the same ``Authorizer``:

- ``files PROJEKT [--q TEKST] [--state STAN] [--limit N] [--cursor K]``:
  ``OwnFileList`` (``GET /projects/{project}/files``);
- ``file PROJEKT PLIK``: ``OwnFileCard`` (``GET …/files/{file_id}``), its
  preview told by a render process of the command, as ``archiwista preview``
  does;
- ``snapshot PROJEKT PLIK --plan``: ``SnapshotPlan`` (``GET
  …/snapshot-plan``), nothing written;
- ``snapshot PROJEKT PLIK [--note TEKST]``: the route's checks (``POST
  …/snapshots``), then the ``snapshot`` job in the foreground
  (``archiwista.jobs.foreground``) and its ``JobDetail`` as ``GET
  /jobs/{job}`` answers it once it ended;
- ``own-scan [--project PROJEKT]``: the ``own_scan`` of one project's folder
  (``POST /projects/{project}/scan``) or of every project's, in the
  foreground, with its ``JobDetail``: an agent that changed a file sees its
  ``change`` afterwards.

``PLIK`` is the file's ``file_id`` (16 hexadecimal characters) or its path in
the data folder (``/`` separated). A job that does not succeed prints its
``JobDetail`` too and exits with status 1.
"""

import argparse
import asyncio
import re
import sqlite3
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from pydantic import ValidationError

from archiwista.api.errors import service_problem, validation_problem
from archiwista.api.models import Issue, JobDetail
from archiwista.api.models_owndata import (
    OwnFileCard,
    OwnFileList,
    OwnFilesQuery,
    SnapshotPlan,
    SnapshotRequest,
)
from archiwista.api.owndata import (
    own_file_card,
    read_own_files,
    snapshot_plan,
    start_own_scan,
    start_snapshot,
)
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser, refuse
from archiwista.commands.previews import local_previews
from archiwista.config import (
    AppPaths,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError, own_file_id
from archiwista.jobs import FINISHED_STATES, JobEvent, JobRecord, JobSupervisor, label
from archiwista.jobs.foreground import run_foreground
from archiwista.messages import MESSAGES, with_detail
from archiwista.previews.service import PreviewService
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset({"files", "file", "snapshot", "own-scan"})
# A ``PLIK`` of this form is a ``file_id``, any other a path in the folder.
_FILE_ID = re.compile(r"[0-9a-f]{16}")


def add_commands(commands: Commands) -> None:
    """Add ``files``, ``file``, ``snapshot`` and ``own-scan`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    files = add_parser(commands, "files", "cli_files_help")
    _project(files)
    files.add_argument("--q", metavar="TEKST", help=MESSAGES["cli_files_q_help"])
    files.add_argument("--state", metavar="STAN", help=MESSAGES["cli_files_state_help"])
    files.add_argument(
        "--limit", metavar="LICZBA", help=MESSAGES["cli_files_limit_help"]
    )
    files.add_argument(
        "--cursor", metavar="KURSOR", help=MESSAGES["cli_files_cursor_help"]
    )
    card = add_parser(commands, "file", "cli_file_help")
    _project(card)
    _file(card)
    snapshot = add_parser(commands, "snapshot", "cli_snapshot_help")
    _project(snapshot)
    _file(snapshot)
    what = snapshot.add_mutually_exclusive_group()
    what.add_argument(
        "--note", metavar="TEKST", default="", help=MESSAGES["cli_snapshot_note_help"]
    )
    what.add_argument(
        "--plan", action="store_true", help=MESSAGES["cli_snapshot_plan_help"]
    )
    scan = add_parser(commands, "own-scan", "cli_own_scan_help")
    scan.add_argument(
        "--project", metavar="PROJEKT", help=MESSAGES["cli_own_scan_project_help"]
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run one of the module's commands; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``files``, ``file``, ``snapshot`` or ``own-scan``.
    paths : AppPaths
        Configuration file, local index, state database, preview cache and
        jobs.
    registry : PluginRegistry
        Producer plugins, for the settings.
    out, err : TextIO
        The route's model (as JSON with ``--json``) or the problem; Polish
        messages, progress of a job.

    Returns
    -------
    int
        ``0`` on success; ``1`` when the request is refused (its problem),
        its job does not succeed, or the settings, the index, the state
        database or the preview cache cannot be used.
    """
    try:
        query, body = _requests(args)
    except ValidationError as error:
        where = "query" if args.command == "files" else "body"
        located = ({**item, "loc": (where, *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), out, err, as_json=args.json)
    with ExitStack() as stack:
        try:
            settings = SettingsService(ConfigStore(paths.config_file), registry)
            decisions = Authorizer(StateStore(paths.state_file), settings.get)
            previews = None
            if args.command == "file":
                local = stack.enter_context(
                    local_previews(
                        paths, settings.get(), visible=decisions.visible_projects
                    )
                )
                queries, previews = local.queries, local.service
            else:
                queries = stack.enter_context(IndexQueries(paths.index_file))
            jobs = None
            if body is not None or args.command == "own-scan":
                jobs = stack.enter_context(JobSupervisor(paths, settings))
        except (
            SettingsValidationError,
            IndexUnsupportedError,
            StateError,
            OSError,
            sqlite3.Error,
        ) as error:
            err.write(with_detail(MESSAGES["cli_own_failed"], str(error)) + "\n")
            return 1
        local_data = _Local(
            args, paths, settings, decisions, queries, previews, jobs, out, err
        )
        try:
            return _RUN[args.command](local_data, query, body)
        except ArchiwistaError as error:
            problem = service_problem(error)
            if problem is None:
                raise
            return refuse(problem, out, err, as_json=args.json)


@dataclass(frozen=True, slots=True)
class _Local:
    """What a command works with: its arguments, the index, previews, jobs."""

    args: argparse.Namespace
    paths: AppPaths
    settings: SettingsService
    decisions: Authorizer
    queries: IndexQueries
    previews: PreviewService | None
    jobs: JobSupervisor | None
    out: TextIO
    err: TextIO

    def print(
        self, model: JobDetail | OwnFileCard | OwnFileList | SnapshotPlan, text: str
    ) -> None:
        """Print the route's model with ``--json``, else the Polish text."""
        self.out.write((model.model_dump_json() if self.args.json else text) + "\n")


def _requests(
    args: argparse.Namespace,
) -> tuple[OwnFilesQuery | None, SnapshotRequest | None]:
    """Validate the query of ``files`` and the body of a snapshot, as the routes.

    Options left out keep the model's defaults, as parameters left out of
    the URL do.

    Raises
    ------
    pydantic.ValidationError
        A value the route refuses (``422 validation_error``).
    """
    if args.command == "files":
        names = OwnFilesQuery.model_fields
        values = {name: getattr(args, name) for name in names}
        given = {name: value for name, value in values.items() if value is not None}
        return OwnFilesQuery.model_validate(given), None
    if args.command == "snapshot" and not args.plan:
        return None, SnapshotRequest(note=args.note)
    return None, None


def _project(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "project", metavar="PROJEKT", help=MESSAGES["cli_own_project_help"]
    )


def _file(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("file", metavar="PLIK", help=MESSAGES["cli_own_file_help"])


def _file_id(file: str) -> str:
    """Return the ``file_id`` of ``PLIK``: given, or of the path in the folder."""
    return file if _FILE_ID.fullmatch(file) else own_file_id(file)


# Commands.


def _files(
    local: _Local, query: OwnFilesQuery | None, body: SnapshotRequest | None
) -> int:
    assert query is not None  # validated by ``_requests``
    visible = local.decisions.visible_projects(LOCAL_OWNER)
    listing = read_own_files(
        local.queries,
        local.settings.get(),
        local.paths,
        local.args.project,
        query,
        visible=visible,
    )
    local.print(listing, _files_text(local.args.project, listing))
    return 0


def _card(
    local: _Local, query: OwnFilesQuery | None, body: SnapshotRequest | None
) -> int:
    visible = local.decisions.visible_projects(LOCAL_OWNER)
    card = asyncio.run(
        own_file_card(
            local.queries,
            local.settings.get(),
            local.previews,
            local.args.project,
            _file_id(local.args.file),
            principal=LOCAL_OWNER,
            visible=visible,
        )
    )
    local.print(card, _card_text(card))
    return 0


def _snapshot(
    local: _Local, query: OwnFilesQuery | None, body: SnapshotRequest | None
) -> int:
    args, file_id = local.args, _file_id(local.args.file)
    if body is None:
        visible = local.decisions.visible_projects(LOCAL_OWNER)
        plan = snapshot_plan(
            local.queries,
            local.settings.get(),
            local.paths,
            args.project,
            file_id,
            visible=visible,
        )
        local.print(plan, _plan_text(plan))
        return 0
    jobs = local.jobs
    assert jobs is not None  # started for a snapshot
    record = run_foreground(
        jobs,
        lambda: start_snapshot(
            local.decisions,
            LOCAL_OWNER,
            jobs,
            local.queries,
            local.settings.get(),
            local.paths,
            args.project,
            file_id,
            body.note,
        ),
        local.err,
        started=lambda job: MESSAGES["cli_snapshot_started"].format(job=job.id),
        event=_snapshot_event,
        cancelling=lambda job: MESSAGES["cli_snapshot_cancelling"].format(job=job.id),
    )
    return _job(local, record, _snapshot_text)


def _own_scan(
    local: _Local, query: OwnFilesQuery | None, body: SnapshotRequest | None
) -> int:
    jobs = local.jobs
    assert jobs is not None  # started for a scan
    visible = local.decisions.visible_projects(LOCAL_OWNER)
    record = run_foreground(
        jobs,
        lambda: start_own_scan(
            jobs,
            local.queries,
            local.args.project,
            principal=LOCAL_OWNER,
            visible=visible,
        ),
        local.err,
        started=lambda job: MESSAGES["cli_own_scan_started"].format(job=job.id),
        event=_own_scan_event,
        cancelling=lambda job: MESSAGES["cli_own_scan_cancelling"].format(job=job.id),
    )
    return _job(local, record, _own_scan_text)


_RUN: dict[
    str, Callable[[_Local, OwnFilesQuery | None, SnapshotRequest | None], int]
] = {"files": _files, "file": _card, "snapshot": _snapshot, "own-scan": _own_scan}


def _job(local: _Local, record: JobRecord, done: Callable[[JobDetail], str]) -> int:
    """Print a job as ``GET /jobs/{job}`` shows it; ``1`` unless it succeeded.

    A job of another process still active (Ctrl+C stopped the waiting, which
    said so already) is printed as it is now.
    """
    assert local.jobs is not None  # the job's supervisor
    visible = local.decisions.visible_projects(LOCAL_OWNER)
    detail = JobDetail.of(local.jobs.get(record.id, visible=visible) or record)
    succeeded = detail.state == "succeeded"
    if not succeeded and detail.state in FINISHED_STATES:
        failure = MESSAGES["cli_own_job_failed"].format(
            job=detail.id,
            kind=label("job_kind", detail.kind),
            state=label("job_state", detail.state),
            detail="" if detail.error is None else detail.error.detail,
        )
        local.err.write(failure + "\n")
    local.print(detail, done(detail) if succeeded else _job_title(detail))
    return 0 if succeeded else 1


def _snapshot_event(event: JobEvent) -> str | None:
    data = event.data
    if event.type == "progress" and data.get("phase") is not None:
        return MESSAGES["cli_snapshot_progress"].format(
            current=data["current"],
            total=data["total"],
            phase=label("cli_snapshot_phase", data["phase"]),
        )
    if event.type == "notice":
        return MESSAGES["cli_snapshot_notice"].format(message=data["message"])
    return None


def _own_scan_event(event: JobEvent) -> str | None:
    data = event.data
    if event.type == "progress":
        return MESSAGES["cli_own_scan_progress"].format(
            current=data["current"],
            total=data["total"],
            files=data.get("files", 0),
            read=data.get("read", 0),
        )
    if event.type == "notice":
        return MESSAGES["cli_own_scan_notice"].format(message=data["message"])
    return None


# Texts for people.


def _files_text(project: str, listing: OwnFileList) -> str:
    folder = listing.folder
    lines = [
        MESSAGES["cli_own_folder"].format(
            project=project,
            path=folder.path.local,
            state=label("cli_own_state", folder.state),
            files=folder.files,
            size=_size(folder.size_bytes),
            snapshots=_size(folder.snapshots_bytes),
            scanned=_time(folder.scanned_at),
        ),
        *_problems(folder.problems),
    ]
    lines += [
        MESSAGES["cli_own_row"].format(
            path=item.path,
            state=label("cli_own_state", item.state),
            change=label("cli_own_change", item.change),
            snapshots=item.snapshots,
        )
        for item in listing.items
    ] or [MESSAGES["cli_own_no_files"]]
    if listing.next_cursor is not None:
        lines.append(MESSAGES["cli_search_next"].format(cursor=listing.next_cursor))
    return "\n".join(lines)


def _card_text(card: OwnFileCard) -> str:
    last = card.last_snapshot
    lines = [
        MESSAGES["cli_own_card_title"].format(
            ref=card.ref,
            file_id=card.file_id,
            kind=card.kind,
            format=card.format or MESSAGES["cli_none"],
            size=_size(card.size_bytes),
        ),
        MESSAGES["cli_own_card_state"].format(
            state=label("cli_own_state", card.state),
            change=label("cli_own_change", card.change),
            last=MESSAGES["cli_none"]
            if last is None
            else f"{last.label} ({_time(last.created_at)})",
            modified=_time(card.modified_at),
        ),
        MESSAGES["cli_own_card_path"].format(path=card.paths.local),
    ]
    if card.crs is not None:
        lines.append(MESSAGES["cli_own_card_crs"].format(crs=card.crs))
    lines += [
        MESSAGES["cli_own_card_layer"].format(
            name=layer["name"],
            geometry=layer["geometry_type"] or MESSAGES["cli_none"],
            count=MESSAGES["cli_none"]
            if layer["feature_count"] is None
            else layer["feature_count"],
        )
        for layer in card.layers
    ]
    if card.raster is not None:
        lines.append(MESSAGES["cli_own_card_raster"].format(**card.raster))
    if card.snapshots:
        lines.append(
            MESSAGES["cli_own_card_snapshots"].format(count=len(card.snapshots))
        )
    lines += [
        MESSAGES["cli_own_card_snapshot"].format(
            label=item.label,
            created=_time(item.created_at),
            size=_size(item.size_bytes),
            state=label("cli_snapshot_state", item.state),
            note=f"  „{item.note}”" if item.note else "",
        )
        for item in card.snapshots
    ]
    if card.preview is not None:
        state = MESSAGES[f"preview_state_{card.preview.state}"]
        lines.append(MESSAGES["cli_own_card_preview"].format(state=state))
    return "\n".join([*lines, *_problems(card.problems)])


def _plan_text(plan: SnapshotPlan) -> str:
    lines = [
        MESSAGES["cli_snapshot_plan"].format(
            file=plan.file,
            size=_size(plan.size_bytes),
            destination=plan.destination.local,
            copy_method=plan.copy_method,
            content_method=plan.content_method,
        )
    ]
    since = plan.unchanged_since
    if since is not None:
        lines.append(
            MESSAGES["cli_snapshot_plan_unchanged"].format(
                label=since.label, created=_time(since.created_at)
            )
        )
    if plan.blocked is not None:
        lines.append(
            MESSAGES["cli_snapshot_plan_blocked"].format(message=plan.blocked.message)
        )
    free = MESSAGES["cli_none"] if plan.free_bytes is None else _size(plan.free_bytes)
    lines.append(MESSAGES["cli_snapshot_plan_free"].format(free=free))
    lines += [
        MESSAGES["cli_snapshot_plan_warning"].format(message=item.message)
        for item in plan.warnings
    ]
    return "\n".join(lines)


def _snapshot_text(detail: JobDetail) -> str:
    result = detail.result or {}
    if result.get("status") == "unchanged":
        return MESSAGES["cli_snapshot_unchanged"].format(
            job=detail.id, label=result["label"]
        )
    return MESSAGES["cli_snapshot_created"].format(
        job=detail.id,
        label=result["label"],
        size=_size(result["size_bytes"]),
        sha256=result["content_sha256"],
        seconds=_seconds(result["seconds"]),
    )


def _own_scan_text(detail: JobDetail) -> str:
    result = detail.result or {}
    counts = ("projects", "files", "new", "changed", "missing", "unreadable")
    return MESSAGES["cli_own_scan_done"].format(
        job=detail.id,
        **{name: result.get(name, 0) for name in (*counts, "snapshots", "problems")},
        seconds=_seconds(result.get("seconds", 0)),
    )


def _job_title(detail: JobDetail) -> str:
    """Return the line of a job that did not succeed (its failure went to stderr)."""
    return MESSAGES["cli_own_job"].format(
        job=detail.id,
        kind=label("job_kind", detail.kind),
        state=label("job_state", detail.state),
    )


def _problems(problems: list[Issue]) -> list[str]:
    return [
        MESSAGES["cli_own_problem"]
        .format(message=item.message, instruction=item.instruction)
        .rstrip()
        for item in problems
    ]


def _time(value: datetime | None) -> str:
    if value is None:
        return MESSAGES["cli_never"]
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def _size(size: int) -> str:
    if size < 1_000_000:
        return f"{size / 1000:.1f} kB".replace(".", ",")
    return f"{size / 1_000_000:.1f} MB".replace(".", ",")


def _seconds(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")
