"""The jobs over a project's groups in a worker (A-ADR-049 decisions 11 and 12).

Each job reads its project and the groups its parameters name (every group
for ``None``) from the index, and works on the configured store the project
names for each producer of a group (``services.project_jobs.group_store``):

- ``verify`` (no network) hashes each pinned version's file inside its
  store's root (SHA-256 in chunks of ``HASH_CHUNK_BYTES``, no symbolic link
  out of the root): ``ok``; ``corrupt`` (other bytes); ``missing``, unless
  the index holds another present version of the pin's slot whose
  ``content_sha256`` is the pin's, then ``content_match`` with that version
  (``found``); ``no_store`` for a pin whose store is not configured. It
  changes nothing and succeeds, with ``ok`` false when it found a problem;
- ``check`` asks the source through ``ActionAdapter.check`` (its notices
  become the job's): a plan group by its calls, a local group by the call of
  each pin (``command_for_version`` through the index's ``version_calls``,
  each call asked once). Each pin is compared by its slot and SHA-256:
  ``current``, ``newer``, ``missing``, ``removed``, ``unverifiable``,
  ``check_failed`` or ``not_checkable`` (a local pin whose call the producer
  cannot rebuild, with its text: D5); a position of a plan group's calls
  without a pin is ``added``;
- ``repin`` runs the group's calls (a local group: the calls of its pins) in
  the producer's update mode (``upgrade``); only when every call and every
  unit succeeded are the group's pins replaced under the file's lock: a plan
  group's by the files of the runs, a local group's each by the file of the
  run at its slot (a pin whose slot no run returned stays); a pin whose
  version and SHA-256 did not change keeps its ``pinned_at`` and
  ``pinned_by``, the others get the job's actor and time;
- ``restore`` runs, for the groups with pins missing from the store, their
  calls in the producer's default mode (the versions the store holds are
  kept): a missing pin whose SHA-256 returns is ``restored``, one whose
  ``content_sha256`` returns with other bytes ``content_match``, another
  ``not_restored`` (reason ``other_content`` or ``not_returned``), a local
  pin without a call ``not_restorable`` with the producer's text (D5). It
  never writes the project file.

After a run the slots of its files are read again into the index, and after
an interruption the slots its progress named, as a ``download`` does. Each
function returns the job's summary and whether the job did all its work;
the worker makes a ``partial`` result of the rest (``worker._ended``).
"""

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from archiwista.auth import ALL_PROJECTS
from archiwista.errors import (
    ArchiwistaError,
    CheckFailedError,
    NotFoundError,
    OfflineModeError,
    RunFailedError,
)
from archiwista.index import (
    IndexQueries,
    IndexWriter,
    PinGroupRef,
    ProjectPinRef,
    ProjectRecord,
    ProjectRef,
    VersionFacts,
)
from archiwista.index.projects import record_project
from archiwista.jobs.availability import store_unreachable
from archiwista.jobs.protocol import JobSpec, JsonObject
from archiwista.jobs.worker import (
    RESCAN_STOP_S,
    _CallRun,
    _checked_plan,
    _geo,
    _plan_section,
    _rescan,
    _run_call,
    _run_scopes,
    _run_section,
)
from archiwista.messages import message, with_detail
from archiwista.projects import change_project_file, format_time
from archiwista.services.commands import (
    actions,
    not_rebuildable,
    version_calls,
    version_commands,
)
from archiwista.services.pins import find_group
from archiwista.services.project_jobs import (
    chosen_groups,
    group_producers,
    group_store,
)
from archiwista.services.projects import project_directory
from archiwista.sources import (
    ActionAdapter,
    ActionFile,
    ActionPlan,
    CommandCall,
    PlanEntry,
    SourceAdapter,
)
from archiwista.sources.registry import SourceRegistry, load_registry

if TYPE_CHECKING:
    from archiwista.jobs.worker import Emitter

# Bytes of a pinned file read at a time while it is hashed.
HASH_CHUNK_BYTES = 1024 * 1024
# The states of a verified pin, of a checked pin and of a restored missing pin.
VERIFY_STATUSES = ("ok", "corrupt", "missing", "content_match", "no_store")
CHECK_STATUSES = (
    "current",
    "newer",
    "missing",
    "removed",
    "unverifiable",
    "check_failed",
    "not_checkable",
)
RESTORE_STATUSES = ("restored", "content_match", "not_restored", "not_restorable")
# The check states of a pin the source could not be asked about.
_NOT_ASKED = ("check_failed", "not_checkable")

type _PinKey = tuple[str, str]


@dataclass(frozen=True, slots=True)
class _Job:
    """A project job's project, its chosen groups and the job's registry."""

    record: ProjectRecord
    groups: tuple[PinGroupRef, ...]
    registry: SourceRegistry

    @property
    def project(self) -> ProjectRef:
        """Return the project as the index lists it."""
        return self.record.project


@dataclass(slots=True)
class _GroupCalls:
    """The calls of a group, and what became of the calls of its local pins.

    ``calls`` are the distinct calls in their order: a plan group's origin, a
    local group's pins' (``of_pin`` the place of each pin's call). A local pin
    whose call the producer cannot rebuild is in ``refused`` with its text;
    one the producer refused otherwise in ``failed`` with the error.
    """

    calls: list[CommandCall] = field(default_factory=list)
    of_pin: dict[_PinKey, int] = field(default_factory=dict)
    refused: dict[_PinKey, str] = field(default_factory=dict)
    failed: dict[_PinKey, ArchiwistaError] = field(default_factory=dict)


class _Stores:
    """The store and root of each producer of a project job, read once.

    ``readable`` probes the store's root the first time (``store_unavailable``
    when it cannot be read).
    """

    def __init__(self, spec: JobSpec, job: _Job) -> None:
        self._spec = spec
        self._job = job
        self._probed: set[Path] = set()

    def of(self, producer: str) -> tuple[str, Path]:
        """Return the configured store and root of ``producer`` of the project."""
        store = group_store(self._job.project, producer)
        return store, self.root(store, producer)

    def root(self, store: str, producer: str) -> Path:
        """Return the producer's directory of a configured store, probed once."""
        config = self._spec.settings.store(store)
        root = None if config is None else config.roots().get(producer)
        if root is None:
            raise NotFoundError(message("api.store_not_configured", store=store))
        if root not in self._probed:
            refused = store_unreachable(
                self._job.registry.probe(producer, root), root, indexed=True
            )
            if refused is not None:
                raise refused
            self._probed.add(root)
        return root


def verify(spec: JobSpec, emit: "Emitter") -> tuple[JsonObject, bool]:
    """Hash the pinned files of a project's groups; report each pin's state."""
    started = time.perf_counter()
    job = _job(spec)
    stores = _Stores(spec, job)
    total = sum(len(group.pins) for group in job.groups)
    rows: list[JsonObject] = []
    with IndexQueries(spec.index_path) as queries:
        for group in job.groups:
            for pin in group.pins:
                status, found = "no_store", None
                if pin.store is not None:
                    root = stores.root(pin.store, pin.producer)
                    status, found = _verified(queries, root, pin)
                rows.append(_pin_row(group, pin, status=status, found=found))
                emit.progress(len(rows), total)
    counts = _counts(VERIFY_STATUSES, rows)
    ok = counts["ok"] == len(rows)
    summary: JsonObject = {
        **_head(job),
        "ok": ok,
        "counts": counts,
        "pins": rows,
        "seconds": _seconds(started),
    }
    return summary, True


def check(spec: JobSpec, emit: "Emitter") -> tuple[JsonObject, bool]:
    """Compare the pins of a project's groups with what the source has now.

    Ends ``partial`` when some pins could not be asked about; fails
    (``CheckFailedError``) when none could.
    """
    _require_online(spec)
    started = time.perf_counter()
    job = _job(spec)
    stores = _Stores(spec, job)
    rows: list[JsonObject] = []
    added: list[JsonObject] = []
    sections: list[JsonObject] = []
    errors: list[ArchiwistaError] = []
    for group in job.groups:
        calls = _group_calls(spec, job, stores, group, group.pins)
        plans: list[ActionPlan | None] = []
        for place, call in enumerate(calls.calls):
            adapter = actions(job.registry, call.producer)
            _, root = stores.of(call.producer)
            line = adapter.format(replace(call, run={"root": str(root)}))
            try:
                plan = _checked_plan(adapter, call, root, emit)
            except ArchiwistaError as error:
                errors.append(error)
                plans.append(None)
                section = _plan_section(call, line, error=error)
            else:
                plans.append(plan)
                section = _plan_section(call, line, plan=plan)
            sections.append({**section, "group": group.name})
            emit.progress(place + 1, len(calls.calls), group=group.name)
        rows += [_checked_pin(group, pin, calls, plans) for pin in group.pins]
        if group.origin == "plan":
            pinned = {_slot(pin) for pin in group.pins}
            for entry in _entries(plans).values():
                if entry.path not in pinned:
                    added.append(
                        {
                            "group": group.name,
                            "unit": entry.unit,
                            "path": entry.path,
                            "available_label": entry.available_label,
                        }
                    )
    not_asked = [row for row in rows if row["status"] in _NOT_ASKED]
    if rows and len(not_asked) == len(rows):
        text = message("job.project_check_failed", count=len(rows))
        raise CheckFailedError(with_detail(text, not_asked[0]["detail"]))
    if not rows and errors and len(errors) == len(sections):
        raise errors[0]
    ok = not not_asked and not errors
    summary: JsonObject = {
        **_head(job),
        "ok": ok,
        "counts": _counts(CHECK_STATUSES, rows),
        "pins": rows,
        "added": added,
        "calls": sections,
        "seconds": _seconds(started),
    }
    return summary, ok


def repin(spec: JobSpec, emit: "Emitter") -> tuple[JsonObject, bool]:
    """Run one group's calls in update mode; replace its pins on a whole success.

    A run some of whose calls or units failed changes no pin and ends
    ``partial`` (the downloaded versions stay in the store); one none of
    whose calls succeeded fails with the error of its first.
    """
    _require_online(spec)
    started = time.perf_counter()
    job = _job(spec)
    (group,) = job.groups
    stores = _Stores(spec, job)
    calls = _group_calls(spec, job, stores, group, group.pins)
    for key, text in calls.refused.items():
        # Checked when the job started; the index may have learnt it since.
        raise not_rebuildable(key[0], key[1], text)
    for error in calls.failed.values():
        raise error
    runs, sections, rescanned = _run_calls(
        spec, job, stores, group, calls.calls, emit, upgrade=True
    )
    errors = [run.error for run, _ in runs if run.error is not None]
    if runs and len(errors) == len(runs):
        raise errors[0]
    files = [(call, file) for run, call in runs for file in _files(run)]
    head: JsonObject = {
        "project": job.project.key,
        "group": group.name,
        "calls": sections,
        "files": [
            {**asdict(file), "call": calls.calls.index(call)} for call, file in files
        ],
        "rescanned": rescanned,
    }
    whole = all(run.status() == "ok" for run, _ in runs)
    if not whole:
        unchanged: JsonObject = {
            **head,
            "status": "unchanged",
            "written": False,
            "pins": {"kept": 0, "new": 0, "dropped": 0},
            "seconds": _seconds(started),
        }
        return unchanged, False
    counts = _replace_pins(spec, job, stores, group, files, emit)
    status = "replaced" if counts["new"] or counts["dropped"] else "unchanged"
    summary: JsonObject = {
        **head,
        "status": status,
        "written": True,
        "pins": counts,
        "seconds": _seconds(started),
    }
    return summary, True


def restore(spec: JobSpec, emit: "Emitter") -> tuple[JsonObject, bool]:
    """Download the missing pins of a project's groups again, in default mode.

    Ends ``partial`` when some missing pins were not restored, and fails
    (``RunFailedError``) when none was restored or matched by content.
    """
    _require_online(spec)
    started = time.perf_counter()
    job = _job(spec)
    stores = _Stores(spec, job)
    rows: list[JsonObject] = []
    sections: list[JsonObject] = []
    rescanned = 0
    for group in job.groups:
        missing = [pin for pin in group.pins if pin.state == "missing"]
        if not missing:
            continue
        calls = _group_calls(spec, job, stores, group, missing)
        runs, ran, read = _run_calls(spec, job, stores, group, calls.calls, emit)
        sections += ran
        rescanned += read
        with IndexQueries(spec.index_path) as queries:
            rows += [_restored_pin(queries, group, pin, calls, runs) for pin in missing]
    counts = _counts(RESTORE_STATUSES, rows)
    if rows and not counts["restored"] and not counts["content_match"]:
        detail = next((row["detail"] for row in rows if row["detail"]), None)
        text = message("job.project_restore_failed", count=len(rows))
        raise RunFailedError(with_detail(text, detail))
    ok = counts["restored"] == len(rows)
    summary: JsonObject = {
        **_head(job),
        "ok": ok,
        "counts": counts,
        "pins": rows,
        "calls": sections,
        "rescanned": rescanned,
        "seconds": _seconds(started),
    }
    return summary, ok


def _job(spec: JobSpec) -> _Job:
    """Return the project of a job as the index holds it, with its chosen groups.

    Raises
    ------
    NotFoundError
        The index no longer holds the project (a scan dropped it), or one of
        its groups.
    """
    key = str(spec.params["project"])
    with IndexQueries(spec.index_path) as queries:
        record = queries.project(key, visible=ALL_PROJECTS)
    if record is None:
        raise NotFoundError(message("project.not_found", project=key))
    names = spec.params.get("groups")
    groups = chosen_groups(record, None if names is None else [str(n) for n in names])
    return _Job(record, groups, load_registry(cache_dir=spec.cache_dir))


def _require_online(spec: JobSpec) -> None:
    if spec.settings.offline:
        raise OfflineModeError(message("job.offline_mode"))


def _head(job: _Job) -> JsonObject:
    return {"project": job.project.key, "groups": [g.name for g in job.groups]}


def _seconds(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def _counts(statuses: Sequence[str], rows: Iterable[JsonObject]) -> dict[str, int]:
    """Return the number of rows of each status, every status named."""
    found = Counter(str(row["status"]) for row in rows)
    return {status: found[status] for status in statuses}


def _slot(pin: ProjectPinRef) -> str:
    """Return the standard path of a pin's slot; its version's path unindexed."""
    return pin.slot or pin.version


def _pin_row(group: PinGroupRef, pin: ProjectPinRef, **state: object) -> JsonObject:
    return {
        "group": group.name,
        "producer": pin.producer,
        "version": pin.version,
        **state,
    }


def _verified(
    queries: IndexQueries, root: Path, pin: ProjectPinRef
) -> tuple[str, str | None]:
    """Return the state of one pin in the store, and the version that matched."""
    digest = _file_sha256(root, pin.version)
    if digest == pin.sha256:
        return "ok", None
    if digest is not None:
        return "corrupt", None
    found = _content_match(queries, pin)
    return ("missing", None) if found is None else ("content_match", found)


def _file_sha256(root: Path, version: str) -> str | None:
    """Return the SHA-256 of a version's file; ``None`` without one in the root."""
    try:
        path = (root / version).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _content_match(queries: IndexQueries, pin: ProjectPinRef) -> str | None:
    """Return another present version of the pin's slot holding its content."""
    if pin.content_sha256 is None or pin.store is None:
        return None
    for fact in queries.slot_versions(pin.store, _slot(pin)):
        if fact.path != pin.version and fact.content_sha256 == pin.content_sha256:
            return fact.path
    return None


def _group_calls(
    spec: JobSpec,
    job: _Job,
    stores: _Stores,
    group: PinGroupRef,
    pins: Sequence[ProjectPinRef],
) -> _GroupCalls:
    """Return a group's calls: a plan group's origin, a local group's pins'.

    The call of a local pin comes from the index's ``version_calls`` of the
    installed producer, else from the producer (``command_for_version``),
    whose answer is kept.
    """
    found = _GroupCalls()
    if group.origin == "plan":
        found.calls = list(group.calls)
        return found
    places: dict[str, int] = {}
    with (
        IndexQueries(spec.index_path) as queries,
        IndexWriter(spec.index_path) as writer,
    ):
        for producer in group_producers(group):
            adapter = version_commands(job.registry, producer)
            installed = job.registry.state(producer).package_version or ""
            store, root = stores.of(producer)
            for pin in pins:
                if pin.producer != producer:
                    continue
                key = (pin.producer, pin.version)
                try:
                    answer = version_calls(
                        adapter,
                        installed,
                        queries,
                        writer,
                        store=store,
                        root=root,
                        paths=(pin.version,),
                    )[pin.version]
                except ArchiwistaError as error:
                    found.failed[key] = error
                    continue
                if answer.call is None:
                    found.refused[key] = answer.refusal or ""
                    continue
                same = json.dumps(
                    [producer, answer.call.command, dict(answer.call.options)],
                    sort_keys=True,
                )
                if same not in places:
                    places[same] = len(found.calls)
                    found.calls.append(answer.call)
                found.of_pin[key] = places[same]
    return found


def _entries(plans: Iterable[ActionPlan | None]) -> dict[str, PlanEntry]:
    """Return the positions of the plans by path, the first of a path kept."""
    found: dict[str, PlanEntry] = {}
    for plan in plans:
        for entry in () if plan is None else plan.entries:
            found.setdefault(entry.path, entry)
    return found


def _checked_pin(
    group: PinGroupRef,
    pin: ProjectPinRef,
    calls: _GroupCalls,
    plans: Sequence[ActionPlan | None],
) -> JsonObject:
    """Return the state of one pin against the plans of its group's calls."""
    key = (pin.producer, pin.version)
    entry: PlanEntry | None = None
    detail: str | None = None
    if key in calls.refused:
        status, detail = "not_checkable", calls.refused[key]
    elif key in calls.failed:
        status, detail = "check_failed", calls.failed[key].message
    elif pin.state == "missing":
        status = "missing"
    else:
        own = (
            plans
            if group.origin == "plan"
            else [plans[calls.of_pin[key]]]
            if key in calls.of_pin
            else []
        )
        entry = _entries(own).get(_slot(pin))
        if entry is None:
            asked = [plan for plan in own if plan is not None]
            status = "removed" if len(asked) == len(own) and own else "check_failed"
        elif entry.status == "check_failed":
            status, detail = "check_failed", entry.error
        elif entry.status == "unverifiable":
            status = "unverifiable"
        elif entry.status == "current" and pin.is_current:
            status = "current"
        else:
            status = "newer"
    return {
        **_pin_row(group, pin, status=status),
        "unit": pin.unit,
        "path": _slot(pin),
        "pinned_label": pin.label,
        "available_label": None if entry is None else entry.available_label,
        "detail": detail,
    }


def _run_calls(
    spec: JobSpec,
    job: _Job,
    stores: _Stores,
    group: PinGroupRef,
    calls: Sequence[CommandCall],
    emit: "Emitter",
    *,
    upgrade: bool = False,
) -> tuple[list[tuple[_CallRun, CommandCall]], list[JsonObject], int]:
    """Run a group's calls, then read the slots of their files again.

    Returns each call's run with its call, the sections of the summary and
    the number of units read again. When the job is interrupted the slots
    the runs wrote or named are read again within ``RESCAN_STOP_S``.
    """
    runs: list[tuple[_CallRun, CommandCall]] = []
    sections: list[JsonObject] = []

    def rescan(timeout_s: float | None) -> int:
        read = 0
        for producer in dict.fromkeys(call.producer for _, call in runs):
            store, root = stores.of(producer)
            adapter = actions(job.registry, producer)
            reader = job.registry.adapter(producer)
            own = [run for run, call in runs if call.producer == producer]
            read += _rescan(
                spec,
                reader,
                store,
                _scopes_of(adapter, reader, root, own),
                emit,
                timeout_s=timeout_s,
            )
        return read

    try:
        for place, call in enumerate(calls):
            adapter = actions(job.registry, call.producer)
            _, root = stores.of(call.producer)
            run = _CallRun(place, None)
            runs.append((run, call))
            _run_call(
                adapter, call, root, run, calls=len(calls), emit=emit, upgrade=upgrade
            )
            line = adapter.format(replace(call, run={"root": str(root)}))
            section = _run_section(
                call, line, run.status(), error=run.error, result=run.result
            )
            sections.append({**section, "group": group.name})
    except BaseException:
        rescan(RESCAN_STOP_S)
        raise
    return runs, sections, rescan(None)


def _scopes_of(
    adapter: ActionAdapter,
    reader: SourceAdapter,
    root: Path,
    runs: Sequence[_CallRun],
) -> Callable[[], Mapping[str | None, Sequence[str]]]:
    return lambda: _run_scopes(adapter, reader, root, runs)


def _files(run: _CallRun) -> tuple[ActionFile, ...]:
    return () if run.result is None else run.result.files


def _restored_pin(
    queries: IndexQueries,
    group: PinGroupRef,
    pin: ProjectPinRef,
    calls: _GroupCalls,
    runs: Sequence[tuple[_CallRun, CommandCall]],
) -> JsonObject:
    """Return what became of one missing pin after its group's runs."""
    key = (pin.producer, pin.version)
    if key in calls.refused:
        return _pin_row(
            group, pin, status="not_restorable", reason=None, detail=calls.refused[key]
        )
    if key in calls.failed:
        error = calls.failed[key]
        return _pin_row(
            group,
            pin,
            status="not_restored",
            reason="not_returned",
            detail=error.message,
        )
    own = (
        list(runs)
        if group.origin == "plan"
        else [runs[calls.of_pin[key]]]
        if key in calls.of_pin
        else []
    )
    returned = [
        file for run, _ in own for file in _files(run) if file.path == _slot(pin)
    ]
    facts = _facts(queries, pin.store, [pin.version, *_versions(returned)])
    again = facts.get(pin.version)
    if (again is not None and again.present and again.sha256 == pin.sha256) or any(
        file.version_path == pin.version and file.sha256 == pin.sha256
        for file in returned
    ):
        return _pin_row(group, pin, status="restored", reason=None, detail=None)
    for file in returned:
        fact = facts.get(file.version_path or "")
        if (
            pin.content_sha256 is not None
            and fact is not None
            and fact.content_sha256 == pin.content_sha256
        ):
            return _pin_row(
                group,
                pin,
                status="content_match",
                reason=None,
                detail=None,
                found=file.version_path,
            )
    errors = [run.error for run, _ in own if run.error is not None]
    return _pin_row(
        group,
        pin,
        status="not_restored",
        reason="other_content" if returned else "not_returned",
        detail=None if returned or not errors else errors[0].message,
    )


def _versions(files: Iterable[ActionFile]) -> list[str]:
    return [file.version_path for file in files if file.version_path is not None]


def _facts(
    queries: IndexQueries, store: str | None, paths: Sequence[str]
) -> dict[str, VersionFacts]:
    return {} if store is None else queries.version_facts(store, paths)


def _replace_pins(
    spec: JobSpec,
    job: _Job,
    stores: _Stores,
    group: PinGroupRef,
    files: Sequence[tuple[CommandCall, ActionFile]],
    emit: "Emitter",
) -> dict[str, int]:
    """Write the group's pins of a re-pin that wholly succeeded; return the counts.

    Under the file's lock: a plan group's pins become the runs' files, a
    local group's each the file at its slot (one without stays). A pin of
    the same version and SHA-256 is kept as the file holds it.
    """
    moment = format_time(datetime.now(UTC).replace(microsecond=0))
    by_producer: dict[str, dict[str, ActionFile]] = {}
    for call, file in files:
        if file.version_path is not None:
            by_producer.setdefault(call.producer, {}).setdefault(file.path, file)
    contents: dict[tuple[str, str], str | None] = {}
    with IndexQueries(spec.index_path) as queries:
        for producer, found in by_producer.items():
            store, _ = stores.of(producer)
            paths = [file.version_path for file in found.values() if file.version_path]
            for path, fact in queries.version_facts(store, paths).items():
                contents[(producer, path)] = fact.content_sha256
    slots = {(pin.producer, pin.version): _slot(pin) for pin in group.pins}

    def pin_of(producer: str, file: ActionFile) -> dict[str, Any]:
        version = str(file.version_path)
        pin: dict[str, Any] = {
            "producer": producer,
            "version": version,
            "sha256": file.sha256,
        }
        content = contents.get((producer, version))
        if content is not None:
            pin["content_sha256"] = content
        pin.update(
            size_bytes=file.size_bytes,
            unit=file.unit,
            label=file.label,
            pinned_at=moment,
            pinned_by=spec.actor,
        )
        return pin

    counts = {"kept": 0, "new": 0, "dropped": 0}

    def change(data: dict[str, Any]) -> None:
        target = find_group(data, group.name)
        if target is None:
            raise NotFoundError(
                message(
                    "project.group_not_found", project=job.project.key, group=group.name
                )
            )
        old: list[dict[str, Any]] = target["pins"]
        held = {(item["producer"], item["version"]): item for item in old}
        if group.origin == "plan" and group.producer is not None:
            wanted = [
                (group.producer, file)
                for file in by_producer.get(group.producer, {}).values()
            ]
            chosen = [
                _kept_or_new(held, producer, file, pin_of) for producer, file in wanted
            ]
        else:
            chosen = []
            for item in old:
                key = (item["producer"], item["version"])
                file = by_producer.get(key[0], {}).get(slots.get(key, key[1]))
                chosen.append(
                    item if file is None else _kept_or_new(held, key[0], file, pin_of)
                )
        pins = list(
            {(item["producer"], item["version"]): item for item in chosen}.values()
        )
        kept = {id(item) for item in old}
        counts["kept"] = sum(1 for item in pins if id(item) in kept)
        counts["new"] = len(pins) - counts["kept"]
        now = {(item["producer"], item["version"]) for item in pins}
        counts["dropped"] = sum(
            1 for item in old if (item["producer"], item["version"]) not in now
        )
        target["pins"] = pins

    directory = project_directory(job.project, spec.settings)
    change_project_file(directory, change)
    try:
        with IndexWriter(spec.index_path) as writer:
            record_project(
                writer, directory, stores=spec.settings.stores, geo=_geo(job.registry)
            )
    except (ArchiwistaError, OSError, ValueError) as error:
        # The file holds the new pins; the next scan reads it again.
        text = with_detail(message("job.project_not_indexed"), str(error))
        emit.notice("warning", "project_not_indexed", text)
    return counts


def _kept_or_new(
    held: Mapping[tuple[str, str], dict[str, Any]],
    producer: str,
    file: ActionFile,
    pin_of: Callable[[str, ActionFile], dict[str, Any]],
) -> dict[str, Any]:
    """Return the file's pin as the group holds it, else a new one."""
    item = held.get((producer, str(file.version_path)))
    if item is not None and item.get("sha256") == file.sha256:
        return item
    return pin_of(producer, file)
