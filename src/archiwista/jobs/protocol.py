"""JSON Lines protocol between the job supervisor and a worker (SPEC 5.6).

The supervisor starts one worker process per job (``python -m
archiwista.jobs.worker``, A-ADR-007) and writes the job (``JobSpec``) to its
standard input as one JSON line. The input then stays open without further
data: its end tells the worker that the supervisor is gone. The worker
answers on its standard output with JSON Lines, one ``WorkerMessage`` each:

- ``progress``: how far the job is, with integers ``current`` and ``total``
  and counts of the job's kind (a scan adds ``segment`` and ``entries``, a
  download the ``unit``, ``status`` and ``message`` of the producer's event);
- ``notice``: something the person should know: ``level`` (``info`` or
  ``warning``), a stable ``code`` and a ``message`` in Polish, the language of
  the texts a worker stores;
- ``result``: the job's summary, a JSON object; the last line of a job
  that succeeded;
- ``partial``: the summary of a job that did only part of its work (a plan
  some of whose positions could not be checked), the units that failed named
  in it; its last line, in place of ``result``;
- ``error``: why the job failed: a registry ``code`` (ERR §2), a
  ``detail``, the ``exception`` class behind it, and when there are any a
  ``hint`` and the JSON ``details`` (``reason``, the project's own cause,
  and the context), as ``archiwista.error_document.describe`` reports an
  error of a request. The texts are in Polish and, when they are catalog
  messages, come with their ``key`` and ``values`` (``hint_key`` and
  ``hint_values`` for the hint) to be rendered again in the language of
  whoever reads the job (``archiwista.jobs.error.JobError``).

Everything else the worker or a library writes goes to standard error, the
job's log. The supervisor keeps ``progress`` and ``notice`` as job events
and turns ``result``, ``partial`` and ``error`` into the job's final state.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast, get_args

from pydantic import ValidationError

from archiwista._errors import BY_CODE
from archiwista.auth import PrincipalKind
from archiwista.config import AppSettings

PROTOCOL_VERSION = 7
# Exit status of a worker stopped by an interrupt (as a shell's 128 + SIGINT).
INTERRUPTED_EXIT = 130
# Seconds an interrupted worker has to stop. The supervisor kills it then, and
# the worker ends itself then, for the case that the supervisor is gone or the
# stop stalls (``archiwista.jobs.worker``).
STOP_TIMEOUT_S = 30.0

# One line per kind; its rule is in ``archiwista.jobs.supervisor.JOB_RULES``.
type JobKind = Literal[
    "scan",
    "footprints",
    "link_check",
    "preview",
    "own_scan",
    "snapshot",
    "availability",
    "check",
    "download",
]
type MessageType = Literal["progress", "notice", "result", "partial", "error"]
type NoticeLevel = Literal["info", "warning"]
type JsonObject = dict[str, Any]

JOB_KINDS: tuple[JobKind, ...] = get_args(JobKind.__value__)
MESSAGE_TYPES: tuple[MessageType, ...] = get_args(MessageType.__value__)
NOTICE_LEVELS: tuple[NoticeLevel, ...] = ("info", "warning")
_PRINCIPAL_KINDS: tuple[PrincipalKind, ...] = get_args(PrincipalKind.__value__)
# The members of an ``error`` message besides ``code`` and ``detail``, when it
# has them: texts, and objects (the keys and values of the texts).
_ERROR_TEXTS = ("hint", "key", "hint_key")
_ERROR_OBJECTS = ("details", "values", "hint_values")

# What a job that did not succeed reports as its ``error``: a code of the
# shared registry (ERR §2) and its own cause as ``details["reason"]`` (ERR-1).
# The worker reports an ``ArchiwistaError`` as a request's problem is
# (``archiwista.error_document.describe``), so that both agree on one cause;
# these are the codes and reasons the supervisor and the worker choose
# themselves.
CODE_CANCELLED = "cancelled"
CODE_INTERNAL_ERROR = "internal_error"
REASON_INTERRUPTED = "interrupted"
REASON_WORKER_CRASHED = "worker_crashed"
REASON_PROTOCOL_ERROR = "protocol_error"


class ProtocolError(ValueError):
    """A line of the job protocol is not a valid message or job."""


@dataclass(frozen=True, slots=True)
class WorkerMessage:
    """One line a worker writes: its ``type`` and its JSON object ``data``."""

    type: MessageType
    data: JsonObject


@dataclass(frozen=True, slots=True)
class JobSpec:
    """A job as its worker receives it, with the local resources it may use.

    Attributes
    ----------
    job_id : str
        The job's id in the index.
    kind : JobKind
        What to run, one of ``JOB_KINDS``.
    store : str or None
        Configured id of the store the job works on; ``None`` for a kind
        working on no store (``preview``, ``own_scan``, ``snapshot``,
        ``availability``).
    params : dict
        Parameters of the kind, validated by the supervisor (``scan``:
        ``mode`` and ``segment``; ``link_check``: ``slot``; ``preview``:
        ``refs``, their ``contents`` and ``force``; ``own_scan``: optional
        ``project``; ``snapshot``: ``project``, ``file_id`` and ``note``;
        ``availability``: ``area_id``, ``producer``, ``product`` and
        ``force``; ``check``: ``producer``, ``command`` and ``options``;
        ``download``: those of ``check`` and ``plan_job``).
    actor : str
        Who asked for the job (``Principal.id``).
    actor_kind : {"local_owner", "user", "agent", "scheduler"}
        How (``Principal.kind``): a snapshot names its author so.
    session : str or None
        Label of the session the job was asked in; ``None`` at the terminal
        and for the scheduler.
    index_path : Path
        The local index.
    cache_dir : Path
        Root of the local caches, one directory per producer.
    previews_dir : Path
        The preview cache (``AppPaths.previews_dir``).
    work_dir : Path
        Root of the scratch directories of processes reading files
        (``AppPaths.work_dir``).
    settings : AppSettings
        Settings in effect when the job started.
    """

    job_id: str
    kind: JobKind
    store: str | None
    params: JsonObject
    actor: str
    actor_kind: PrincipalKind
    session: str | None
    index_path: Path
    cache_dir: Path
    previews_dir: Path
    work_dir: Path
    settings: AppSettings


def encode_message(message: WorkerMessage) -> str:
    """Return a message as one JSON line, without the line end."""
    return _dump({"type": message.type, "data": message.data})


def decode_message(line: str) -> WorkerMessage:
    """Read one line of a worker's output.

    Parameters
    ----------
    line : str
        One line of standard output, with or without its line end.

    Returns
    -------
    WorkerMessage
        The message, its data checked for the members of its type.

    Raises
    ------
    ProtocolError
        The line is not JSON, names no known type or lacks a member.
    """
    value = _load(line)
    kind = value.get("type")
    data = value.get("data")
    if kind not in MESSAGE_TYPES or not isinstance(data, dict):
        raise ProtocolError(f"not a worker message: {line.strip()[:200]!r}")
    message_type = cast(MessageType, kind)
    _check(message_type, data)
    return WorkerMessage(message_type, data)


def encode_spec(spec: JobSpec) -> str:
    """Return a job as the one JSON line a worker reads first."""
    return _dump(
        {
            "protocol": PROTOCOL_VERSION,
            "job": {
                "id": spec.job_id,
                "kind": spec.kind,
                "store": spec.store,
                "params": spec.params,
                "actor": spec.actor,
                "actor_kind": spec.actor_kind,
                "session": spec.session,
            },
            "index_path": str(spec.index_path),
            "cache_dir": str(spec.cache_dir),
            "previews_dir": str(spec.previews_dir),
            "work_dir": str(spec.work_dir),
            "settings": spec.settings.model_dump(mode="json"),
        }
    )


def decode_spec(line: str) -> JobSpec:
    """Read the job a worker received.

    Raises
    ------
    ProtocolError
        Another protocol version, a missing member or invalid settings.
    """
    value = _load(line)
    if value.get("protocol") != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported job protocol {value.get('protocol')!r}")
    job = value.get("job")
    try:
        if not isinstance(job, dict):
            raise TypeError("job")
        kind = job["kind"]
        if kind not in JOB_KINDS:
            raise ValueError(f"unknown job kind {kind!r}")
        params = job["params"]
        if not isinstance(params, dict):
            raise TypeError("params")
        store = job["store"]
        if store is not None and not isinstance(store, str):
            raise TypeError("store")
        actor_kind = job["actor_kind"]
        if actor_kind not in _PRINCIPAL_KINDS:
            raise ValueError(f"unknown actor kind {actor_kind!r}")
        session = job["session"]
        if session is not None and not isinstance(session, str):
            raise TypeError("session")
        return JobSpec(
            job_id=str(job["id"]),
            kind=kind,
            store=store,
            params=params,
            actor=str(job["actor"]),
            actor_kind=actor_kind,
            session=session,
            index_path=Path(value["index_path"]),
            cache_dir=Path(value["cache_dir"]),
            previews_dir=Path(value["previews_dir"]),
            work_dir=Path(value["work_dir"]),
            settings=AppSettings.model_validate(value["settings"]),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise ProtocolError(f"invalid job: {error}") from error


def _dump(value: JsonObject) -> str:
    # JSON escapes control characters, so a value never breaks the line.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _load(line: str) -> JsonObject:
    try:
        value = json.loads(line)
    except ValueError as error:
        raise ProtocolError(f"not JSON: {line.strip()[:200]!r}") from error
    if not isinstance(value, dict):
        raise ProtocolError(f"not a JSON object: {line.strip()[:200]!r}")
    return value


def _check(kind: MessageType, data: JsonObject) -> None:
    """Require the members the supervisor relies on for each message type."""
    if kind == "progress":
        valid = all(
            isinstance(data.get(name), int) and not isinstance(data.get(name), bool)
            for name in ("current", "total")
        )
    elif kind == "notice":
        valid = data.get("level") in NOTICE_LEVELS and all(
            isinstance(data.get(name), str) for name in ("code", "message")
        )
    elif kind == "error":
        valid = (
            all(isinstance(data.get(name), str) for name in ("code", "detail"))
            and data["code"] in BY_CODE
            and all(isinstance(data.get(name, ""), str) for name in _ERROR_TEXTS)
            and all(isinstance(data.get(name, {}), dict) for name in _ERROR_OBJECTS)
        )
    else:
        valid = True
    if not valid:
        raise ProtocolError(f"{kind} message without its members: {data!r}"[:300])
