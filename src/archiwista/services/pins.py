"""Pinning into a project's groups (A-ADR-049 decisions 7, 8 and 9, erratum 6).

A group is a set („zestaw”): ``open``, a set in the making whose content
changes, or ``closed``, a frozen one (a group without ``state``). Only an
open set takes pins, loses them or takes a call; a set is changed by opening
it (``reopen_set``), changing it and closing it again (``close_set``, a new
``pins_sha256``). An open set holds the data of one producer (D12, fixed by
its first call or pin; ``set_producer``).

``pin_local`` adds versions the index holds to a group of a project file: a
new group (written closed with its closing at once, or open with ``open_set``
or when every version was skipped; an empty draft names no versions) or an
open one the project has (into a ``plan`` group the pins get ``calls`` ``[]``
and the request goes to ``origin.selections``). The versions are named (a
store and a path: older ones too) or chosen by the query of ``GET /slots``
(the versions of its rows, through every page). Their ``sha256``,
``content_sha256``, size, unit and label come from the index: no network, no
producer. A version that is not present or has no ``sha256`` is skipped with
its reason; one the group pins already is counted. The first pin of a
producer names the project's store of that producer; a pin from another
store, or while the project's store matches no configured one, is refused.
``unpin`` removes pins of an open group, or a whole group of either state;
``remove_call`` removes a call of an open ``plan`` group with the pins only
its run pinned. ``close_set`` closes an open set whose pins are all ``ok``
in the index and that no job writes into; ``reopen_set`` opens a closed one.
Each needs ``project.write``, writes the file under its lock
(``archiwista.projects.change_project_file``), logs ``project.pin``,
``project.unpin``, ``project.set_close`` or ``project.set_open`` and records
the project in the index at once. ``pin_local`` also keeps the producer's
call of each version it pinned in the index (``version_calls``, A-ADR-049
D-10), so the card knows which pins a job can check, restore and re-pin.

A download of the plan window that names ``pin`` (decision 9) is checked
before its job exists by ``check_plan_pin`` (the project, its name or its
open set, and its store), and its worker writes the group with
``pin_download`` when the job succeeded: a new ``plan`` group, or its calls
and pins appended to an open set (``add``), each pin naming the calls whose
runs pinned it. A call naming an area's GeoJSON names the project's
``obszary/<area id>.geojson`` there (A-ADR-035 erratum 2).
"""

import logging
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from archiwista.areas import area_geojson_id
from archiwista.auth import ALL_PROJECTS, Principal, ProjectVisibility
from archiwista.auth.authorize import Authorizer
from archiwista.config import AppSettings
from archiwista.errors import (
    ArchiwistaError,
    ConflictError,
    InvalidChangeError,
    NotFoundError,
)
from archiwista.index import IndexQueries, IndexWriter, VersionFacts
from archiwista.index.projects import match_store, record_project
from archiwista.messages import label, message
from archiwista.projects import (
    MAX_GROUP_CALLS,
    MAX_GROUP_NAME_CHARS,
    SelectionSource,
    SetState,
    change_project_file,
    clean_name,
    copy_area_geojson,
    format_time,
    group_state,
    read_project_json,
    seal_group,
    unseal_group,
)
from archiwista.projects import document as project_document
from archiwista.services.commands import version_calls, version_commands
from archiwista.services.project_jobs import set_closed
from archiwista.services.projects import (
    changed_project,
    project_directory,
    record_changed,
    written_root,
)
from archiwista.sources import CommandCall, GeoAdapter
from archiwista.sources.registry import PluginRegistry

if TYPE_CHECKING:
    from archiwista.api.models import SlotFilters
    from archiwista.jobs import JobSupervisor

type SkipReason = Literal["missing", "no_sha256"]
# How a download pins into a project: a new set written closed, a new set
# left open, or its calls and pins added to an open set.
type PinMode = Literal["new", "open", "add"]

# The pins a refusal of a closing lists at most (``set_pins_not_ok``).
MAX_LISTED_PINS = 100
# The pin states of the index a closing refuses, in the order they are counted.
_NOT_OK_STATES = ("missing", "sha256_mismatch", "unknown")

logger = logging.getLogger("archiwista.services.pins")


@dataclass(frozen=True, slots=True)
class SkippedVersion:
    """A version a request named that was not pinned, with why."""

    store: str
    version: str
    reason: SkipReason


@dataclass(frozen=True, slots=True)
class PinResult:
    """What a pin request did.

    Attributes
    ----------
    project : str
        The project's key after the change.
    group : str
        The group's name as the file holds it.
    pinned : int
        Versions added to the group.
    already : int
        Versions the group pinned already (also a version named twice).
    skipped : tuple[SkippedVersion, ...]
        Versions not pinned, in the request's order.
    state : {"open", "closed"}
        The group's state after the request.
    """

    project: str
    group: str
    pinned: int
    already: int
    skipped: tuple[SkippedVersion, ...]
    state: SetState


def group_name(name: str) -> str:
    """Return a group's name as the file writes it, else refuse it.

    Raises
    ------
    InvalidChangeError
        1 to ``MAX_GROUP_NAME_CHARS`` characters after NFC and trimming, no
        control character and no ``/`` (reason ``invalid_group_name``).
    """
    cleaned = clean_name(name)
    if (
        not 1 <= len(cleaned) <= MAX_GROUP_NAME_CHARS
        or "/" in cleaned
        or any(unicodedata.category(char) == "Cc" for char in cleaned)
    ):
        raise InvalidChangeError(
            message("project.group_name_invalid", group=name),
            reason="invalid_group_name",
            details={"group": name},
        )
    return cleaned


def find_group(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return the JSON object of a group, its name compared case-folded."""
    wanted = name.casefold()
    for item in data.get("groups", []):
        if isinstance(item, dict) and str(item.get("name", "")).casefold() == wanted:
            return item
    return None


def group_taken(project: str, name: str) -> ConflictError:
    """Return the refusal of a group name the project holds (``group_exists``)."""
    return ConflictError(
        message("project.group_exists", project=project, group=name),
        reason="group_exists",
        details={"group": name},
    )


def group_missing(project: str, name: str) -> NotFoundError:
    """Return the refusal of a group the project does not have (``group_not_found``)."""
    return NotFoundError(
        message("project.group_not_found", project=project, group=name),
        reason="group_not_found",
        details={"group": name},
    )


def require_open(group: Mapping[str, Any]) -> None:
    """Refuse a change of a group's JSON object unless the set is open."""
    if group_state(group) != "open":
        raise set_closed(str(group["name"]))


def set_producers(group: Mapping[str, Any]) -> list[str]:
    """Return the producers of a group's JSON object: a plan's, else its pins'."""
    origin = group["origin"]
    if origin.get("kind") == "plan":
        return [str(origin["producer"])]
    return list(dict.fromkeys(str(pin["producer"]) for pin in group["pins"]))


def require_producer(
    group: Mapping[str, Any], producer: str, *, call: bool = False
) -> None:
    """Apply D12: an open set holds the data of the producer of its first call or pin.

    A pin of a producer the set holds no data of is refused, and a call of
    a producer other than every one of the set's (a local set of several
    producers takes no call).

    Raises
    ------
    ConflictError
        ``set_producer``, with the set's producers and the one refused.
    """
    held = set_producers(group)
    if held and (held != [producer] if call else producer not in held):
        raise _other_producer(str(group["name"]), held, producer)


def _other_producer(name: str, held: Sequence[str], producer: str) -> ConflictError:
    """Return the refusal of another producer's data in a set (``set_producer``)."""
    return ConflictError(
        message(
            "project.set_producer",
            group=name,
            producers=", ".join(held),
            producer=producer,
        ),
        reason="set_producer",
        details={"group": name, "producers": list(held), "producer": producer},
    )


def require_calls_room(count: int) -> None:
    """Refuse more calls than a group holds (``too_many_calls``)."""
    if count > MAX_GROUP_CALLS:
        raise InvalidChangeError(
            message("project.too_many_calls", count=count, limit=MAX_GROUP_CALLS),
            reason="too_many_calls",
            details={"count": count, "limit": MAX_GROUP_CALLS},
        )


def pin_local(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    group: str,
    new: bool,
    source: SelectionSource | None,
    versions: Sequence[tuple[str, str]] | None,
    query: "SlotFilters | None",
    actor: Principal,
    visible: ProjectVisibility,
    open_set: bool = False,
) -> PinResult:
    """Pin versions the index holds into a group of a project.

    Parameters
    ----------
    registry, settings, queries, index_path, authorizer
        The producers (a ``bbox`` of ``query``, the project's area), the
        configured stores and project directories, the index and the
        decisions over the state database.
    key : str
        The project (``/projects/{project}``).
    group : str
        The group's name.
    new : bool
        A new group (``True``), else an open group the project has, of
        either origin (into a ``plan`` group the pins get ``calls`` ``[]``).
    source : {"local_state", "catalog", "file"} or None
        Where the versions were chosen; recorded with ``query`` in the
        origin's ``selections``. ``None`` with no versions: an empty draft.
    versions : sequence of (store, version) or None
        The versions by store and path.
    query : SlotFilters or None
        The query of ``GET /slots`` whose rows' versions are pinned; with
        neither, a new open group without pins (an empty draft).
    actor : Principal
        Who pins (``pinned_by``, the log).
    visible : ProjectVisibility
        Projects ``actor`` sees.
    open_set : bool, optional
        A new group is left open (a set in the making); else it is written
        closed with its closing, unless every version was skipped.

    Returns
    -------
    PinResult
        What was pinned, already pinned and skipped, and the group's state.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees; no group ``group`` (``new``
        false, ``group_not_found``); a store that is not configured.
    PermissionDeniedError
        ``actor`` may not change the project.
    InvalidChangeError
        A name breaking the rule (``invalid_group_name``); more than
        ``MAX_GROUP_PINS`` versions (``too_many_pins``, ``details.count``).
    ConflictError
        A taken name (``group_exists``), a closed group (``set_closed``), a
        version of another producer than an open group's (``set_producer``),
        a version of another store than the project's (``other_store``) or a
        project store matching no configured one (``unknown_store``).
    IndexQueryError, SourceStateError
        ``query`` is refused as ``GET /slots`` refuses it.
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    ValueError
        Neither ``versions`` nor ``query`` for anything but a new open group.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    name = group_name(group)
    if versions is not None:
        chosen = list(dict.fromkeys(versions))
    elif query is not None:
        chosen = _rows(queries, settings, registry, query, visible)
    elif new and open_set:
        chosen = []
    else:
        raise ValueError("versions or query is required")
    _require_few(len(chosen))
    candidates, skipped = _resolve(queries, chosen)
    roots: dict[tuple[str, str], str] = {}
    for fact in candidates:
        config = settings.store(fact.store)
        root = None if config is None else config.roots().get(fact.producer)
        if config is None or root is None:
            raise NotFoundError(message("api.store_not_configured", store=fact.store))
        roots.setdefault(
            (fact.store, fact.producer),
            written_root(root, directory, relative=bool(config.path_aliases)),
        )
    selection: dict[str, Any] | None = None
    if source is not None and (versions is not None or query is not None):
        selection = {"from": source}
        if query is not None:
            selection["query"] = query.model_dump(mode="json", exclude_none=True)
    moment = format_time(datetime.now(UTC).replace(microsecond=0))
    counts = {"pinned": 0, "already": 0}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, name)
        if new and found is not None:
            raise group_taken(project.key, str(found["name"]))
        if not new and found is None:
            raise group_missing(project.key, name)
        if found is not None:
            require_open(found)
        target = found or {
            "name": name,
            "state": "open",
            "origin": {"kind": "local", "selections": []},
            "pins": [],
        }
        if found is not None or open_set:
            _require_one_producer(target, candidates)
        stores = _project_stores(data, directory, settings)
        pins: list[dict[str, Any]] = target["pins"]
        held = {(item["producer"], item["version"]) for item in pins}
        by_hand = target["origin"].get("kind") == "plan"
        added: list[dict[str, Any]] = []
        for fact in candidates:
            _require_store(data, stores, fact, roots[fact.store, fact.producer])
            if (fact.producer, fact.path) in held:
                counts["already"] += 1
                continue
            held.add((fact.producer, fact.path))
            pin = _pin_json(fact, moment, actor.id)
            if by_hand:
                pin["calls"] = []
            added.append(pin)
        _require_few(len(pins) + len(added))
        pins.extend(added)
        counts["pinned"] = len(added)
        if selection is not None and (added or found is None):
            target["origin"].setdefault("selections", []).append(selection)
        if found is None:
            if pins and not open_set:
                seal_group(target, closed_at=moment, closed_by=actor.id)
            data.setdefault("groups", []).append(target)

    document = change_project_file(directory, change)
    _keep_calls(registry, settings, queries, index_path, candidates)
    written = next(item for item in document.groups if _same(item.name, name))
    details: dict[str, object] = {
        "group": written.name,
        "from": source,
        "pins": counts["pinned"],
        "already": counts["already"],
        "skipped": len(skipped),
    }
    if new:
        details["open"] = written.state == "open"
    authorizer.state.record(actor, "project.pin", project.access_key, details=details)
    return PinResult(
        project=record_changed(registry, settings, index_path, directory),
        group=written.name,
        pinned=counts["pinned"],
        already=counts["already"],
        skipped=tuple(skipped),
        state=written.state,
    )


def _require_one_producer(
    group: Mapping[str, Any], candidates: Sequence[VersionFacts]
) -> None:
    """Refuse versions of another producer than an open set's (D12).

    A new set's producer is that of its first version.
    """
    held = set_producers(group)
    for fact in candidates:
        if not held:
            held = [fact.producer]
        elif fact.producer not in held:
            raise _other_producer(str(group["name"]), held, fact.producer)


def unpin(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    group: str,
    pins: Sequence[tuple[str, str]] | None,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Remove pins of a project's group, or the whole group; return its key.

    ``pins`` names them by producer and version (a pin the group does not
    hold is ignored); only an open group loses pins. ``None`` removes the
    group, open or closed. Logged as ``project.unpin`` with the group and
    the pins removed.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or no group ``group``
        (``group_not_found``).
    PermissionDeniedError
        ``actor`` may not change the project.
    ConflictError
        Pins of a closed group (``set_closed``).
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    removed: list[dict[str, str]] = []
    named: list[str] = []

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if found is None:
            raise group_missing(project.key, group)
        if pins is not None:
            require_open(found)
        named.append(str(found["name"]))
        held: list[dict[str, Any]] = found["pins"]
        wanted = None if pins is None else set(pins)
        kept = []
        for item in held:
            if wanted is None or (item["producer"], item["version"]) in wanted:
                removed.append(
                    {"producer": item["producer"], "version": item["version"]}
                )
            else:
                kept.append(item)
        if wanted is None:
            data["groups"].remove(found)
        else:
            found["pins"] = kept

    change_project_file(directory, change)
    details: dict[str, object] = {"group": named[0], "pins": removed}
    if pins is None:
        details["group_removed"] = True
    authorizer.state.record(actor, "project.unpin", project.access_key, details=details)
    return record_changed(registry, settings, index_path, directory)


def remove_call(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    group: str,
    call: int,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Remove a call of an open ``plan`` group with the pins only it pinned.

    ``call`` is the call's place in ``origin.calls`` (from 0). It leaves
    every pin's ``calls`` and the higher places shift down; a pin whose
    ``calls`` becomes empty that way goes, while a pin added by hand
    (``[]``) and a pin of another call too stay. Removing the last call
    makes the group ``local`` again (its ``selections`` kept, the pins'
    ``calls`` gone). Logged as ``project.unpin`` with the call and the pins
    removed; returns the project's key.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, no group ``group``
        (``group_not_found``), or no call ``call`` (``call_not_found``).
    PermissionDeniedError
        ``actor`` may not change the project.
    ConflictError
        A closed group (``set_closed``); a group holding a pin without
        ``calls``, written before the sets had states, which belongs to all
        its calls (``pins_without_calls``: a re-pin writes them).
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    named: list[str] = []
    removed: list[dict[str, str]] = []
    removed_call: dict[str, Any] = {}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if found is None:
            raise group_missing(project.key, group)
        require_open(found)
        name = str(found["name"])
        origin: dict[str, Any] = found["origin"]
        calls: list[Any] = origin.get("calls", []) if origin["kind"] == "plan" else []
        if not 0 <= call < len(calls):
            raise NotFoundError(
                message("project.call_not_found", group=name, call=call),
                reason="call_not_found",
                details={"group": name, "call": call},
            )
        if any(pin.get("calls") is None for pin in found["pins"]):
            raise ConflictError(
                message("project.pins_without_calls", group=name),
                reason="pins_without_calls",
                details={"group": name},
                hint=message("fix.pins_without_calls"),
            )
        named.append(name)
        removed_call.update(calls.pop(call), call=call)
        kept: list[dict[str, Any]] = []
        for pin in found["pins"]:
            places: list[int] = pin["calls"]
            left = [place - (place > call) for place in places if place != call]
            if places and not left:
                removed.append({"producer": pin["producer"], "version": pin["version"]})
                continue
            pin["calls"] = left
            kept.append(pin)
        found["pins"] = kept
        if not calls:
            origin.pop("producer", None)
            origin.pop("calls", None)
            origin["kind"] = "local"
            origin.setdefault("selections", [])
            for pin in kept:
                pin.pop("calls", None)

    change_project_file(directory, change)
    authorizer.state.record(
        actor,
        "project.unpin",
        project.access_key,
        details={"group": named[0], "call": removed_call, "pins": removed},
    )
    return record_changed(registry, settings, index_path, directory)


def close_set(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    jobs: "JobSupervisor",
    key: str,
    *,
    group: str,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Close an open set („Zamknij zestaw”); return the project's key.

    The pins' states are the index's, from the last scan (A-ADR-049
    decision 5): nothing is hashed. Under the file's lock the set must
    still be open and hold exactly the pins the index judged ``ok``; then
    ``state`` becomes ``closed`` with ``closed_at`` (now), ``closed_by``
    (``actor``) and ``pins_sha256`` (``pins_digest`` of its pins). Logged
    as ``project.set_close`` with the group, the number of pins and the
    digest.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or no group ``group``
        (``group_not_found``).
    PermissionDeniedError
        ``actor`` may not change the project.
    ConflictError
        In this order: a closed set (``set_closed``); a job that writes into
        it waits or runs (``set_job_active``, ``details.job``): a
        ``download`` pinning into it or a ``project_repin`` of it; no pin
        (``set_empty``); a pin whose state is not ``ok`` (``set_pins_not_ok``,
        ``details.counts`` by state and the first ``MAX_LISTED_PINS`` in
        ``details.pins``).
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    record = queries.project(project.key, visible=ALL_PROJECTS)
    groups = () if record is None else record.groups
    indexed = next((item for item in groups if _same(item.name, group)), None)
    if indexed is None:
        raise group_missing(project.key, group)
    if indexed.state != "open":
        raise set_closed(indexed.name)
    running = jobs.active_set_job(project.key, indexed.name)
    if running is not None:
        raise ConflictError(
            message(
                "project.set_job_active",
                group=indexed.name,
                kind=label("job.kind", running.kind),
                state=label("job.state", running.state),
            ),
            reason="set_job_active",
            details={
                "group": indexed.name,
                "job": {"id": running.id, "kind": running.kind, "state": running.state},
            },
        )
    if not indexed.pins:
        raise _set_empty(indexed.name)
    _require_ok(
        indexed.name,
        [(pin.producer, pin.version, pin.state) for pin in indexed.pins],
    )
    ok = {(pin.producer, pin.version, pin.sha256) for pin in indexed.pins}
    moment = format_time(datetime.now(UTC).replace(microsecond=0))
    sealed: dict[str, Any] = {}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if found is None:
            raise group_missing(project.key, group)
        require_open(found)
        if not found["pins"]:
            raise _set_empty(str(found["name"]))
        # Pins the index has not judged (the file changed since it was read).
        _require_ok(
            str(found["name"]),
            [
                (
                    str(pin["producer"]),
                    str(pin["version"]),
                    "ok"
                    if (pin["producer"], pin["version"], pin["sha256"]) in ok
                    else "unknown",
                )
                for pin in found["pins"]
            ],
        )
        digest = seal_group(found, closed_at=moment, closed_by=actor.id)
        sealed.update(group=found["name"], pins=len(found["pins"]), pins_sha256=digest)

    change_project_file(directory, change)
    authorizer.state.record(
        actor, "project.set_close", project.access_key, details=dict(sealed)
    )
    return record_changed(registry, settings, index_path, directory)


def reopen_set(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    authorizer: Authorizer,
    key: str,
    *,
    group: str,
    actor: Principal,
    visible: ProjectVisibility,
) -> str:
    """Open a closed set for editing („Otwórz do edycji”); return the project's key.

    ``state`` becomes ``open`` and ``closed_at``, ``closed_by`` and
    ``pins_sha256`` go; a set without ``state`` (written before the sets
    had states) is opened alike. Logged as ``project.set_open`` with the
    group and the members of the closing it ends (``None`` without them).

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or no group ``group``
        (``group_not_found``).
    PermissionDeniedError
        ``actor`` may not change the project.
    ConflictError
        The set is open already (``set_open``).
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    ended: dict[str, Any] = {}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if found is None:
            raise group_missing(project.key, group)
        name = str(found["name"])
        if group_state(found) == "open":
            raise ConflictError(
                message("project.set_open", group=name),
                reason="set_open",
                details={"group": name},
            )
        ended.update(group=name, **unseal_group(found))

    change_project_file(directory, change)
    authorizer.state.record(
        actor, "project.set_open", project.access_key, details=dict(ended)
    )
    return record_changed(registry, settings, index_path, directory)


def _set_empty(name: str) -> ConflictError:
    """Return the refusal of closing a set without a pin (``set_empty``)."""
    return ConflictError(
        message("project.set_empty", group=name),
        reason="set_empty",
        details={"group": name},
    )


def _require_ok(name: str, pins: Sequence[tuple[str, str, str]]) -> None:
    """Refuse closing a set with a pin whose state is not ``ok`` (``set_pins_not_ok``).

    ``pins`` are ``(producer, version, state)``; the refusal counts the
    pins by state and lists the first ``MAX_LISTED_PINS``.
    """
    bad = [pin for pin in pins if pin[2] != "ok"]
    if not bad:
        return
    counts = {
        state: sum(1 for pin in bad if pin[2] == state) for state in _NOT_OK_STATES
    }
    raise ConflictError(
        message(
            "project.set_pins_not_ok",
            group=name,
            count=len(bad),
            missing=counts["missing"],
            mismatch=counts["sha256_mismatch"],
            unknown=counts["unknown"],
        ),
        reason="set_pins_not_ok",
        details={
            "group": name,
            "counts": counts,
            "pins": [
                {"producer": producer, "version": version, "state": state}
                for producer, version, state in bad[:MAX_LISTED_PINS]
            ],
        },
        hint=message("fix.set_pins_not_ok"),
    )


def pin_mode(pin: Mapping[str, object]) -> PinMode:
    """Return how a download's ``params.pin`` pins: ``add``, ``open`` or ``new``."""
    if pin.get("add") is True:
        return "add"
    if pin.get("open") is True:
        return "open"
    return "new"


def check_plan_pin(
    settings: AppSettings,
    queries: IndexQueries,
    authorizer: Authorizer,
    *,
    project: str,
    group: str,
    producer: str,
    store: str,
    actor: Principal,
    visible: ProjectVisibility,
    mode: PinMode = "new",
    calls: int = 1,
) -> dict[str, object]:
    """Check the ``pin`` of a download before its job exists; return the job's.

    Parameters
    ----------
    settings, queries, authorizer
        The configured stores and project directories, the index and the
        decisions over the state database.
    project, group : str
        The project and the group's name.
    producer, store : str
        The download's producer and configured store.
    actor : Principal
        Who asks.
    visible : ProjectVisibility
        Projects ``actor`` sees.
    mode : {"new", "open", "add"}, optional
        A new group written closed, a new group left open, or the open
        group ``group`` the download's calls and pins are added to.
    calls : int, optional
        The download's calls: an open group holds at most
        ``MAX_GROUP_CALLS`` together.

    Returns
    -------
    dict[str, object]
        ``project`` (its key), ``group`` (the name as the file holds or will
        hold it) and ``add`` or ``open`` (``True``) but for ``new``: the
        job's ``params.pin``.

    Raises
    ------
    NotFoundError
        No project ``project`` ``actor`` sees; ``add`` and no group
        ``group`` (``group_not_found``).
    PermissionDeniedError
        ``actor`` may not change the project.
    InvalidChangeError
        The name breaks the rule (``invalid_group_name``); ``add`` beyond
        ``MAX_GROUP_CALLS`` calls (``too_many_calls``).
    ConflictError
        ``new`` or ``open`` and the project holds a group of the name
        (``group_exists``); ``add`` and a closed group (``set_closed``) or
        one of another producer (``set_producer``); the project names
        another store of ``producer`` (``other_store``) or one matching no
        configured store (``unknown_store``).
    ProjectFileError
        The file is invalid or of a newer format.
    """
    ref = changed_project(queries, authorizer, project, actor=actor, visible=visible)
    directory = project_directory(ref, settings)
    name = group_name(group)
    data = read_project_json(directory)
    project_document.parse_document(data)
    found = find_group(data, name)
    if mode == "add":
        if found is None:
            raise group_missing(ref.key, name)
        require_open(found)
        require_producer(found, producer, call=True)
        require_calls_room(_held_calls(found) + calls)
        name = str(found["name"])
    elif found is not None:
        raise group_taken(ref.key, str(found["name"]))
    stores = _project_stores(data, directory, settings)
    if producer in stores:
        probe = VersionFacts(store, "", producer, None, None, None, None, None, True)
        _require_store(data, stores, probe, "")
    checked: dict[str, object] = {"project": ref.key, "group": name}
    if mode != "new":
        checked[mode] = True
    return checked


def pin_download(
    settings: AppSettings,
    index_path: Path,
    geo: GeoAdapter | None,
    *,
    pin: Mapping[str, object],
    store: str,
    calls: Sequence[CommandCall],
    files: Sequence[Mapping[str, Any]],
    positions: Sequence[tuple[str, int]],
    account: str,
    areas: Path,
) -> dict[str, object]:
    """Write the pins of a download that succeeded into its group (decision 9).

    A new group (``pin`` without ``add``) is a ``plan`` group of the
    download's calls, written closed with its closing unless ``open`` or
    without any pin; with ``add`` the calls are appended to the open group's
    (a ``local`` one becomes ``plan``: its hand pins get ``calls`` ``[]``,
    its requests stay in ``origin.selections``) and its pins added. Each
    pin names the places of the calls whose run or kept plan holds it,
    offset by the calls the group held; a version the group pins already
    gains them and keeps its ``pinned_at`` and ``pinned_by``.

    Parameters
    ----------
    settings : AppSettings
        The configured stores and project directories.
    index_path : Path
        The local index, read after the download's rescan.
    geo : GeoAdapter or None
        Coordinate operations: the project's area read into the index.
    pin : Mapping[str, object]
        The job's ``params.pin``: ``project``, ``group`` and ``add`` or
        ``open``.
    store : str
        The download's configured store.
    calls : Sequence[CommandCall]
        The download's calls, in their order.
    files : Sequence[Mapping[str, Any]]
        ``files[]`` of the download's summary: each pinned by its
        ``version_path``, ``sha256``, ``size_bytes``, ``label`` and ``unit``
        (``content_sha256`` from the index) for its ``call``; one without a
        ``version_path`` as a position.
    positions : Sequence[tuple[str, int]]
        Standard paths of the kept plans' positions with their call's
        place: those not in ``files`` are pinned to the current version the
        index holds there.
    account : str
        The job's actor (``pinned_by``, ``closed_by``).
    areas : Path
        Where the areas' GeoJSON files are (``AppPaths.areas_dir``): an
        option naming one names the project's ``obszary/<area id>.geojson``
        in the group, relative to the project directory
        (``copy_area_geojson``).

    Returns
    -------
    dict[str, object]
        The summary's ``pin``: ``project``, ``group``, ``pins`` (the pins
        added), ``already`` (the versions the group pinned already),
        ``state`` (the group's after the change) and ``not_pinned``
        (``[{path, reason}]``, reason ``not_in_store``).

    Raises
    ------
    ArchiwistaError
        The project is gone; the name was taken meanwhile, or the open
        group was closed or removed (``set_closed``, ``group_not_found``);
        the store is another one; the lock is held, or the file cannot be
        written.
    """
    project, group = str(pin["project"]), str(pin["group"])
    mode = pin_mode(pin)
    producer = calls[0].producer
    versioned = [item for item in files if item.get("version_path")]
    by_path = {str(item["path"]): str(item["version_path"]) for item in versioned}
    rest = [
        (str(item["path"]), int(item["call"]))
        for item in files
        if not item.get("version_path")
    ]
    candidates: dict[str, VersionFacts] = {}
    places: dict[str, set[int]] = {}
    not_pinned: dict[str, dict[str, str]] = {}
    with IndexQueries(index_path) as queries:
        record = queries.project(project, visible=ALL_PROJECTS)
        if record is None:
            raise NotFoundError(message("project.not_found", project=project))
        indexed = queries.version_facts(store, list(by_path.values()))
        for item in versioned:
            version = str(item["version_path"])
            content = indexed.get(version)
            candidates.setdefault(
                version,
                VersionFacts(
                    store=store,
                    path=version,
                    producer=producer,
                    sha256=str(item["sha256"]),
                    content_sha256=None if content is None else content.content_sha256,
                    size_bytes=int(item["size_bytes"]),
                    unit=item.get("unit"),
                    label=item.get("label"),
                    present=True,
                ),
            )
            places.setdefault(version, set()).add(int(item["call"]))
        for path, place in [*positions, *rest]:
            if path in by_path:
                places[by_path[path]].add(place)
                continue
            current = queries.current_version_at(store, path)
            if current is None or current.sha256 is None:
                not_pinned.setdefault(path, {"path": path, "reason": "not_in_store"})
                continue
            candidates.setdefault(current.path, current)
            places.setdefault(current.path, set()).add(place)
    directory = project_directory(record.project, settings)
    config = settings.store(store)
    root = None if config is None else config.roots().get(producer)
    if config is None or root is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    written = written_root(root, directory, relative=bool(config.path_aliases))
    moment = format_time(datetime.now(UTC).replace(microsecond=0))
    origin_calls = [
        {
            "command": call.command,
            "options": _project_options(call.options, directory, areas),
        }
        for call in calls
    ]
    outcome: dict[str, object] = {}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if mode != "add" and found is not None:
            raise group_taken(project, str(found["name"]))
        if mode == "add":
            if found is None:
                raise group_missing(project, group)
            require_open(found)
            require_producer(found, producer, call=True)
        target = found or {
            "name": group,
            "state": "open",
            "origin": {"kind": "plan", "producer": producer, "calls": []},
            "pins": [],
        }
        _plan_origin(target, producer)
        offset = _held_calls(target)
        require_calls_room(offset + len(origin_calls))
        target["origin"]["calls"].extend(origin_calls)
        stores = _project_stores(data, directory, settings)
        for fact in candidates.values():
            _require_store(data, stores, fact, written)
        pins: list[dict[str, Any]] = target["pins"]
        held = {(item["producer"], item["version"]): item for item in pins}
        added: list[dict[str, Any]] = []
        already = 0
        for version, fact in candidates.items():
            numbers = sorted(offset + place for place in places[version])
            item = held.get((fact.producer, version))
            if item is not None:
                already += 1
                # A pin of the calls as a whole (no member) holds these too.
                if item.get("calls") is not None:
                    item["calls"] = sorted({*item["calls"], *numbers})
                continue
            new = _pin_json(fact, moment, account)
            new["calls"] = numbers
            added.append(new)
        _require_few(len(pins) + len(added))
        pins.extend(added)
        if found is None:
            if mode == "new" and pins:
                seal_group(target, closed_at=moment, closed_by=account)
            data.setdefault("groups", []).append(target)
        outcome.update(pins=len(added), already=already, state=group_state(target))

    change_project_file(directory, change)
    with IndexWriter(index_path) as writer:
        record_project(writer, directory, stores=settings.stores, geo=geo)
    return {
        "project": project,
        "group": group,
        **outcome,
        "not_pinned": list(not_pinned.values()),
    }


def _held_calls(group: Mapping[str, Any]) -> int:
    """Return the number of calls a group's JSON object holds (``local``: none)."""
    origin = group["origin"]
    return len(origin.get("calls", [])) if origin.get("kind") == "plan" else 0


def _plan_origin(group: dict[str, Any], producer: str) -> None:
    """Make a ``local`` group's origin ``plan`` for its first call.

    Its requests stay in ``selections`` and its pins, added by hand, get
    ``calls`` ``[]``; a ``plan`` group is left as it is.
    """
    origin: dict[str, Any] = group["origin"]
    if origin.get("kind") == "plan":
        return
    others = {
        name: value
        for name, value in origin.items()
        if name not in ("kind", "producer", "calls", "selections")
    }
    selections = origin.get("selections", [])
    origin.clear()
    origin.update(
        kind="plan", producer=producer, calls=[], selections=selections, **others
    )
    for pin in group["pins"]:
        pin["calls"] = []


def _project_options(
    options: Mapping[str, object], directory: Path, areas: Path
) -> dict[str, object]:
    """Return a call's options, an area's GeoJSON as the project's file.

    An option naming a GeoJSON of ``areas`` (``area_geojson_id``) names the
    project's ``obszary/<area id>.geojson`` (``copy_area_geojson``), relative
    to the project directory, so the group's calls hold wherever the project
    lies; the other options stay as they are.
    """
    return {
        name: (
            value
            if area_geojson_id(value, areas) is None
            else copy_area_geojson(directory, Path(str(value)))
        )
        for name, value in options.items()
    }


def _same(left: str, right: str) -> bool:
    return left.casefold() == right.casefold()


def _require_few(count: int) -> None:
    """Refuse more versions than a group holds (``too_many_pins``)."""
    limit = project_document.MAX_GROUP_PINS
    if count > limit:
        raise InvalidChangeError(
            message("project.too_many_pins", count=count, limit=limit),
            reason="too_many_pins",
            details={"count": count, "limit": limit},
        )


def _rows(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    query: "SlotFilters",
    visible: ProjectVisibility,
) -> list[tuple[str, str]]:
    """Return the versions of a query's rows through every page.

    At most ``MAX_GROUP_PINS + 1`` rows are read: one more is refused
    anyway. A row without a version (a slot without a current one) is no
    version and is left out.
    """
    found: list[tuple[str, str]] = []
    limit = project_document.MAX_GROUP_PINS
    for store, version in _pages(queries, settings, registry, query, visible):
        if len(found) > limit:
            break
        if version is not None:
            found.append((store, version))
    return list(dict.fromkeys(found))


def _pages(
    queries: IndexQueries,
    settings: AppSettings,
    registry: PluginRegistry,
    query: "SlotFilters",
    visible: ProjectVisibility,
) -> Iterator[tuple[str, str | None]]:
    """Yield the store and version of each row of every page of ``query``."""
    # The API's catalog imports the services: imported here, where it is used.
    from archiwista.api.models import CatalogFilters
    from archiwista.api.slots import search_slots
    from archiwista.index.types import MAX_PAGE_LIMIT

    cursor: str | None = None
    while True:
        filters = CatalogFilters(
            **query.model_dump(), limit=MAX_PAGE_LIMIT, cursor=cursor
        )
        page = search_slots(queries, settings, registry, filters, visible=visible)
        for row in page.items:
            yield row.store, None if row.version is None else row.version.path
        cursor = page.next_cursor
        if cursor is None:
            return


def _resolve(
    queries: IndexQueries, chosen: Sequence[tuple[str, str]]
) -> tuple[list[VersionFacts], list[SkippedVersion]]:
    """Return the versions to pin and the skipped ones, in the request's order."""
    facts: dict[tuple[str, str], VersionFacts] = {}
    for store in dict.fromkeys(store for store, _ in chosen):
        paths = [path for name, path in chosen if name == store]
        for path, fact in queries.version_facts(store, paths).items():
            facts[(store, path)] = fact
    candidates: list[VersionFacts] = []
    skipped: list[SkippedVersion] = []
    for store, path in chosen:
        found = facts.get((store, path))
        if found is None or not found.present:
            skipped.append(SkippedVersion(store, path, "missing"))
        elif found.sha256 is None or found.size_bytes is None:
            skipped.append(SkippedVersion(store, path, "no_sha256"))
        else:
            candidates.append(found)
    return candidates, skipped


def _project_stores(
    data: dict[str, Any], directory: Path, settings: AppSettings
) -> dict[str, str | None]:
    """Return the configured store each producer's entry of the file matches."""
    return {
        item["producer"]: match_store(
            item["root"], directory, item["producer"], settings.stores
        )
        for item in data.get("stores", [])
        if isinstance(item, dict)
    }


def _require_store(
    data: dict[str, Any],
    stores: dict[str, str | None],
    fact: VersionFacts,
    root: str,
) -> None:
    """Apply D-7: name the producer's store at its first pin, refuse another one.

    Raises
    ------
    ConflictError
        The project's store of the producer matches no configured store
        (``unknown_store``), or is another one (``other_store``).
    """
    if fact.producer not in stores:
        data.setdefault("stores", []).append({"producer": fact.producer, "root": root})
        stores[fact.producer] = fact.store
        return
    store = stores[fact.producer]
    if store is None:
        raise ConflictError(
            message("project.unknown_store", producer=fact.producer),
            reason="unknown_store",
            details={"producer": fact.producer},
        )
    if store != fact.store:
        raise ConflictError(
            message(
                "project.other_store",
                producer=fact.producer,
                store=store,
                version_store=fact.store,
            ),
            reason="other_store",
            details={"store": store, "producer": fact.producer},
        )


def _keep_calls(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    facts: Sequence[VersionFacts],
) -> None:
    """Keep the producer's call of each pinned version in the index (D-10).

    Offline: ``command_for_version`` of the versions whose answer the index
    does not keep for the installed producer. A producer without the
    capability, or one that refuses otherwise than D5, leaves its versions
    unknown: a job asks again.
    """
    paths: dict[tuple[str, str], list[str]] = {}
    for fact in facts:
        paths.setdefault((fact.store, fact.producer), []).append(fact.path)
    with IndexWriter(index_path) as writer:
        for (store, producer), chosen in paths.items():
            config = settings.store(store)
            root = None if config is None else config.roots().get(producer)
            if root is None:
                continue
            try:
                version_calls(
                    version_commands(registry, producer),
                    registry.state(producer).package_version or "",
                    queries,
                    writer,
                    store=store,
                    root=root,
                    paths=chosen,
                )
            except ArchiwistaError as error:
                logger.info(
                    "The calls of %d pinned versions of %s were not kept: %s",
                    len(chosen),
                    producer,
                    error,
                )


def _pin_json(fact: VersionFacts, moment: str, account: str) -> dict[str, Any]:
    """Return a pin of the file for an indexed version."""
    pin: dict[str, Any] = {
        "producer": fact.producer,
        "version": fact.path,
        "sha256": fact.sha256,
    }
    if fact.content_sha256 is not None:
        pin["content_sha256"] = fact.content_sha256
    pin.update(
        size_bytes=fact.size_bytes,
        unit=fact.unit,
        label=fact.label,
        pinned_at=moment,
        pinned_by=account,
    )
    return pin
