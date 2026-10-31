"""Pinning into a project's groups (A-ADR-049 decisions 7, 8 and 9).

``pin_local`` adds versions the index holds to a ``local`` group of a project
file: a new group, or one the project has. The versions are named (a store
and a path: older ones too) or chosen by the query of ``GET /slots`` (the
versions of its rows, through every page). Their ``sha256``,
``content_sha256``, size, unit and label come from the index: no network, no
producer. A version that is not present or has no ``sha256`` is skipped with
its reason; one the group pins already is counted. The first pin of a
producer names the project's store of that producer; a pin from another
store, or while the project's store matches no configured one, is refused.
``unpin`` removes pins of a group, or the whole group. Both need
``project.write``, write the file under its lock
(``archiwista.projects.change_project_file``), log ``project.pin`` or
``project.unpin`` and record the project in the index at once. ``pin_local``
also keeps the producer's call of each version it pinned in the index
(``version_calls``, A-ADR-049 D-10), so the card knows which pins a job can
check, restore and re-pin.

A download of the plan window that names ``pin`` (decision 9) is checked
before its job exists by ``check_plan_pin`` (the project, its name and its
store), and its worker writes the ``plan`` group with ``pin_download`` when
the job succeeded.
"""

import logging
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

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
from archiwista.messages import message
from archiwista.projects import (
    MAX_GROUP_NAME_CHARS,
    SelectionSource,
    change_project_file,
    clean_name,
    format_time,
    read_project_json,
)
from archiwista.projects import document as project_document
from archiwista.services.commands import version_calls, version_commands
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

type SkipReason = Literal["missing", "no_sha256"]

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
    """

    project: str
    group: str
    pinned: int
    already: int
    skipped: tuple[SkippedVersion, ...]


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
    source: SelectionSource,
    versions: Sequence[tuple[str, str]] | None,
    query: "SlotFilters | None",
    actor: Principal,
    visible: ProjectVisibility,
) -> PinResult:
    """Pin versions the index holds into a local group of a project.

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
        A new group (``True``), else a local group the project has.
    source : {"local_state", "catalog", "file"}
        Where the versions were chosen; recorded with ``query``.
    versions : sequence of (store, version) or None
        The versions by store and path.
    query : SlotFilters or None
        The query of ``GET /slots`` whose rows' versions are pinned.
    actor : Principal
        Who pins (``pinned_by``, the log).
    visible : ProjectVisibility
        Projects ``actor`` sees.

    Returns
    -------
    PinResult
        What was pinned, already pinned and skipped.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees; no group ``group`` (``new``
        false); a store that is not configured.
    PermissionDeniedError
        ``actor`` may not change the project.
    InvalidChangeError
        A name breaking the rule (``invalid_group_name``); more than
        ``MAX_GROUP_PINS`` versions (``too_many_pins``, ``details.count``).
    ConflictError
        A taken name (``group_exists``), a ``plan`` group
        (``group_origin_plan``), a version of another store than the
        project's (``other_store``) or a project store matching no configured
        one (``unknown_store``).
    IndexQueryError, SourceStateError
        ``query`` is refused as ``GET /slots`` refuses it.
    ProjectFileError, ProjectLockedError, ProjectFileWriteError
        As for every change of the file.
    """
    project = changed_project(queries, authorizer, key, actor=actor, visible=visible)
    directory = project_directory(project, settings)
    name = group_name(group)
    if versions is not None:
        chosen = list(dict.fromkeys(versions))
    elif query is not None:
        chosen = _rows(queries, settings, registry, query, visible)
    else:
        raise ValueError("versions or query is required")
    _require_few(len(chosen))
    candidates, skipped = _resolve(queries, chosen)
    roots: dict[str, str] = {}
    for fact in candidates:
        config = settings.store(fact.store)
        root = None if config is None else config.roots().get(fact.producer)
        if config is None or root is None:
            raise NotFoundError(message("api.store_not_configured", store=fact.store))
        roots.setdefault(
            fact.store,
            written_root(root, directory, relative=bool(config.path_aliases)),
        )
    selection: dict[str, Any] = {"from": source}
    if query is not None:
        selection["query"] = query.model_dump(mode="json", exclude_none=True)
    moment = format_time(datetime.now(UTC).replace(microsecond=0))
    counts = {"pinned": 0, "already": 0}

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, name)
        if new and found is not None:
            raise group_taken(project.key, str(found["name"]))
        if not new and found is None:
            raise NotFoundError(
                message("project.group_not_found", project=project.key, group=name)
            )
        if found is not None and found["origin"].get("kind") != "local":
            raise ConflictError(
                message("project.group_origin_plan", group=found["name"]),
                reason="group_origin_plan",
                details={"group": found["name"]},
            )
        target = found or {
            "name": name,
            "origin": {"kind": "local", "selections": []},
            "pins": [],
        }
        stores = _project_stores(data, directory, settings)
        pins: list[dict[str, Any]] = target["pins"]
        held = {(item["producer"], item["version"]) for item in pins}
        added: list[dict[str, Any]] = []
        for fact in candidates:
            _require_store(data, stores, fact, roots[fact.store])
            if (fact.producer, fact.path) in held:
                counts["already"] += 1
                continue
            held.add((fact.producer, fact.path))
            added.append(_pin_json(fact, moment, actor.id))
        _require_few(len(pins) + len(added))
        pins.extend(added)
        counts["pinned"] = len(added)
        if added or found is None:
            target["origin"]["selections"].append(selection)
        if found is None:
            data.setdefault("groups", []).append(target)

    document = change_project_file(directory, change)
    _keep_calls(registry, settings, queries, index_path, candidates)
    written = next(item for item in document.groups if _same(item.name, name))
    authorizer.state.record(
        actor,
        "project.pin",
        project.access_key,
        details={
            "group": written.name,
            "from": source,
            "pins": counts["pinned"],
            "already": counts["already"],
            "skipped": len(skipped),
        },
    )
    return PinResult(
        project=record_changed(registry, settings, index_path, directory),
        group=written.name,
        pinned=counts["pinned"],
        already=counts["already"],
        skipped=tuple(skipped),
    )


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
    hold is ignored); ``None`` removes the group. Logged as
    ``project.unpin`` with the group and the pins removed.

    Raises
    ------
    NotFoundError
        No project ``key`` ``actor`` sees, or no group ``group``.
    PermissionDeniedError
        ``actor`` may not change the project.
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
            raise NotFoundError(
                message("project.group_not_found", project=project.key, group=group)
            )
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
) -> dict[str, str]:
    """Check the ``pin`` of a download before its job exists; return the job's.

    Returns
    -------
    dict[str, str]
        ``project`` (its key) and ``group`` (the name as the file will hold
        it): the job's ``params.pin``.

    Raises
    ------
    NotFoundError
        No project ``project`` ``actor`` sees.
    PermissionDeniedError
        ``actor`` may not change the project.
    InvalidChangeError
        The name breaks the rule (``invalid_group_name``).
    ConflictError
        The project holds a group of the name (``group_exists``), or names
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
    if found is not None:
        raise group_taken(ref.key, str(found["name"]))
    stores = _project_stores(data, directory, settings)
    if producer in stores:
        probe = VersionFacts(store, "", producer, None, None, None, None, None, True)
        _require_store(data, stores, probe, "")
    return {"project": ref.key, "group": name}


def pin_download(
    settings: AppSettings,
    index_path: Path,
    geo: GeoAdapter | None,
    *,
    pin: Mapping[str, object],
    store: str,
    calls: Sequence[CommandCall],
    files: Sequence[Mapping[str, Any]],
    positions: Sequence[str],
    account: str,
) -> dict[str, object]:
    """Write the ``plan`` group of a download that succeeded (decision 9).

    Parameters
    ----------
    settings : AppSettings
        The configured stores and project directories.
    index_path : Path
        The local index, read after the download's rescan.
    geo : GeoAdapter or None
        Coordinate operations: the project's area read into the index.
    pin : Mapping[str, object]
        The job's ``params.pin``: ``project`` and ``group``.
    store : str
        The download's configured store.
    calls : Sequence[CommandCall]
        The download's calls, in their order: the group's origin.
    files : Sequence[Mapping[str, Any]]
        ``files[]`` of the download's summary: each pinned by its
        ``version_path``, ``sha256``, ``size_bytes``, ``label`` and ``unit``
        (``content_sha256`` from the index); one without a ``version_path``
        as a position.
    positions : Sequence[str]
        Standard paths of the kept plans' positions: those not in ``files``
        are pinned to the current version the index holds there.
    account : str
        The job's actor (``pinned_by``).

    Returns
    -------
    dict[str, object]
        The summary's ``pin``: ``project``, ``group``, ``pins`` (the count
        written) and ``not_pinned`` (``[{path, reason}]``, reason
        ``not_in_store``).

    Raises
    ------
    ArchiwistaError
        The project is gone, the name was taken meanwhile, the store is
        another one, the lock is held, or the file cannot be written.
    """
    project, group = str(pin["project"]), str(pin["group"])
    producer = calls[0].producer
    versioned = [item for item in files if item.get("version_path")]
    done = {str(item["path"]) for item in versioned}
    rest = [str(item["path"]) for item in files if not item.get("version_path")]
    candidates: dict[str, VersionFacts] = {}
    not_pinned: list[dict[str, str]] = []
    with IndexQueries(index_path) as queries:
        record = queries.project(project, visible=ALL_PROJECTS)
        if record is None:
            raise NotFoundError(message("project.not_found", project=project))
        indexed = queries.version_facts(
            store, [str(item["version_path"]) for item in versioned]
        )
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
        for path in dict.fromkeys([*positions, *rest]):
            if path in done:
                continue
            current = queries.current_version_at(store, path)
            if current is None or current.sha256 is None:
                not_pinned.append({"path": path, "reason": "not_in_store"})
                continue
            candidates.setdefault(current.path, current)
    directory = project_directory(record.project, settings)
    config = settings.store(store)
    root = None if config is None else config.roots().get(producer)
    if config is None or root is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    written = written_root(root, directory, relative=bool(config.path_aliases))
    moment = format_time(datetime.now(UTC).replace(microsecond=0))

    def change(data: dict[str, Any]) -> None:
        found = find_group(data, group)
        if found is not None:
            raise group_taken(project, str(found["name"]))
        stores = _project_stores(data, directory, settings)
        for fact in candidates.values():
            _require_store(data, stores, fact, written)
        data.setdefault("groups", []).append(
            {
                "name": group,
                "origin": {
                    "kind": "plan",
                    "producer": producer,
                    "calls": [
                        {"command": call.command, "options": dict(call.options)}
                        for call in calls
                    ],
                },
                "pins": [
                    _pin_json(fact, moment, account) for fact in candidates.values()
                ],
            }
        )

    change_project_file(directory, change)
    with IndexWriter(index_path) as writer:
        record_project(writer, directory, stores=settings.stores, geo=geo)
    return {
        "project": project,
        "group": group,
        "pins": len(candidates),
        "not_pinned": not_pinned,
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
