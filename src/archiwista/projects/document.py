"""The project file ``archiwista-project/1``: its members and their rules.

A project of Archiwista (A-ADR-049) is a directory holding
``archiwista-project.json`` (``PROJECT_FILE``): UTF-8 JSON of the schema
``archiwista-project/1``, written only by Archiwista on a person's command
(``archiwista.projects.files``), an open format that is read without
Archiwista. ``parse_document`` reads its JSON object as decisions 1 and 2
rule it: a member it does not know is ignored (and kept by a writer),
``archiwista-project/<n>`` with ``n`` above 1 is a project in a newer format
(``unsupported_project_schema``), and anything else outside a rule is an
invalid file (``invalid_project_file``), refused with the JSON pointer
(RFC 6901) of the member and the rule it breaks (``invalid_file``,
``rule_text``). Names are NFC without surrounding white space
(``clean_name``); group names are unique in a project compared case-folded.
``document_json``, ``group_json``, ``store_json``, ``area_json`` and
``pin_json`` give the members a writer sets.

A group is a set („zestaw”) in one of two states (A-ADR-049 erratum 6):
``open``, a set in the making whose content changes, or ``closed``, a frozen
one; a group without ``state`` is closed. Archiwista closes a set by writing
``closed_at``, ``closed_by`` and ``pins_sha256`` (``pins_digest`` of its
pins) together (``seal_group``) and opens it by removing them
(``unseal_group``). A ``plan`` group's pin may name the calls whose runs
pinned it (``calls``, ``[]`` for a pin added by hand), and its origin may
hold the hand pins' ``selections``.
"""

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PureWindowsPath
from typing import Any, Literal, get_args

from archiwista.errors import ProjectFileError
from archiwista.messages import message, with_detail
from archiwista.sources.types import CommandCall

PROJECT_FILE = "archiwista-project.json"
PROJECT_SCHEMA = "archiwista-project/1"
LOCK_NAME = ".archiwista-project.lock"
AREAS_DIR = "obszary"
EXPORTS_DIR = "eksport"
MAX_GROUP_PINS = 10_000
MAX_PROJECT_FILE_BYTES = 32 * 1024**2
MAX_NAME_CHARS = 200
MAX_DESCRIPTION_CHARS = 2_000
MAX_GROUP_NAME_CHARS = 80
# The calls of one job (``jobs.supervisor.MAX_JOB_CALLS``): a plan group
# keeps the calls of the run that downloaded it.
MAX_GROUP_CALLS = 1_000

type SelectionSource = Literal["local_state", "catalog", "file"]
type OriginKind = Literal["plan", "local"]
# A set in the making (``open``) or a frozen one (``closed``); no member: closed.
type SetState = Literal["open", "closed"]

SELECTION_SOURCES: tuple[SelectionSource, ...] = ("local_state", "catalog", "file")
SET_STATES: tuple[SetState, ...] = get_args(SetState.__value__)
# The members Archiwista writes together when it closes a set.
CLOSED_MEMBERS = ("closed_at", "closed_by", "pins_sha256")
# The order of a group's members as Archiwista writes them; members it does
# not know follow.
_GROUP_ORDER = ("name", "state", *CLOSED_MEMBERS, "origin", "pins")
# How every time of the file is written: UTC, whole seconds.
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_SCHEMA = re.compile(r"archiwista-project/([1-9][0-9]{0,8})")
_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PRODUCER = re.compile(r"[a-z][a-z0-9_]{0,31}")


@dataclass(frozen=True, slots=True)
class AreaRef:
    """A project's area: its GeoJSON file and the SHA-256 of its bytes.

    Attributes
    ----------
    path : str
        Relative to the project directory, ``/``-separated, below
        ``obszary/`` (``AREAS_DIR``).
    sha256 : str
        Of the file's bytes as Archiwista wrote them.
    """

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class StoreRoot:
    """The store of one producer's pins, as the project names it.

    Attributes
    ----------
    producer : str
        Producer id.
    root : str
        The producer's directory of a configured store as written when it
        was added: relative to the project directory, or absolute.
    """

    producer: str
    root: str


@dataclass(frozen=True, slots=True)
class Selection:
    """A request that added pins to a local group: a record, never run again.

    Attributes
    ----------
    source : {"local_state", "catalog", "file"}
        Where the request chose its versions (the JSON member ``from``).
    query : Mapping[str, object] or None
        The parameters of ``GET /slots`` that chose them; ``None`` for
        ``file``.
    """

    source: SelectionSource
    query: Mapping[str, object] | None


@dataclass(frozen=True, slots=True)
class PlanOrigin:
    """A group of the data the plan window downloaded: the runs' calls.

    Attributes
    ----------
    producer : str
        Producer of the calls and of every pin of the group.
    calls : tuple[CommandCall, ...]
        The calls of the runs in their order, 1 to ``MAX_GROUP_CALLS``.
    selections : tuple[Selection, ...]
        The requests that added the hand pins of an open set holding calls.
    """

    producer: str
    calls: tuple[CommandCall, ...]
    selections: tuple[Selection, ...] = ()

    kind: Literal["plan"] = field(default="plan", init=False)


@dataclass(frozen=True, slots=True)
class LocalOrigin:
    """A group of versions the store already held when they were pinned.

    Attributes
    ----------
    selections : tuple[Selection, ...]
        The requests that added its pins, in their order.
    """

    selections: tuple[Selection, ...] = ()

    kind: Literal["local"] = field(default="local", init=False)


@dataclass(frozen=True, slots=True)
class Pin:
    """A version a group pins: its file relative to the store and its SHA-256.

    Attributes
    ----------
    producer : str
        Producer of the version.
    version : str
        The version's file relative to the producer's directory of the
        store, ``/``-separated (never a standard path).
    sha256 : str
        Of the version's bytes.
    content_sha256 : str or None
        The canonical content's digest when the version's metadata has one.
    size_bytes : int
        The file's size.
    unit, label : str or None
        The version's unit and label, ``None`` when it has none.
    pinned_at : datetime
        When it was pinned (UTC, whole seconds).
    pinned_by : str
        The account that pinned it (``local`` for the local owner).
    calls : tuple[int, ...] or None
        A ``plan`` group's pin: the ascending places in ``origin.calls`` of
        the calls whose runs pinned it, ``()`` for a pin added by hand;
        ``None`` without the member (a local group's pin, or one written
        before the sets had states, which belongs to the calls as a whole).
    """

    producer: str
    version: str
    sha256: str
    content_sha256: str | None
    size_bytes: int
    unit: str | None
    label: str | None
    pinned_at: datetime
    pinned_by: str
    calls: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class PinGroup:
    """A named group of pins with the origin of its versions.

    Attributes
    ----------
    name : str
        1 to ``MAX_GROUP_NAME_CHARS`` characters, no control character, no
        ``/``; unique in the project compared case-folded.
    origin : PlanOrigin or LocalOrigin
        ``plan`` (a download of the plan window) or ``local`` (versions the
        store held).
    pins : tuple[Pin, ...]
        At most ``MAX_GROUP_PINS``; a version once.
    state : {"open", "closed"}
        A set in the making or a frozen one (no member: ``closed``).
    closed_at, closed_by, pins_sha256 : datetime, str, str or None
        When and by whom Archiwista closed the set, and ``pins_digest`` of
        its pins then; all three or none, none on an open set.
    """

    name: str
    origin: PlanOrigin | LocalOrigin
    pins: tuple[Pin, ...] = ()
    state: SetState = "closed"
    closed_at: datetime | None = None
    closed_by: str | None = None
    pins_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectDocument:
    """What a project file holds (A-ADR-049 decision 1).

    Attributes
    ----------
    name : str
        1 to ``MAX_NAME_CHARS`` characters after NFC and trimming, no
        control character.
    description : str
        At most ``MAX_DESCRIPTION_CHARS`` characters; ``""`` when left out.
    created_at : datetime
        When the project was created (UTC, whole seconds).
    created_by : str
        The account that created it (``local`` for the local owner).
    area : AreaRef or None
        The project's area file.
    stores : tuple[StoreRoot, ...]
        At most one per producer.
    groups : tuple[PinGroup, ...]
        In the order people see them.
    """

    name: str
    description: str
    created_at: datetime
    created_by: str
    area: AreaRef | None = None
    stores: tuple[StoreRoot, ...] = ()
    groups: tuple[PinGroup, ...] = ()


def clean_name(text: str) -> str:
    """Return a name as the file keeps it: NFC without surrounding white space."""
    return unicodedata.normalize("NFC", text).strip()


def format_time(moment: datetime) -> str:
    """Return a time as the file writes it: UTC, ``YYYY-MM-DDTHH:MM:SSZ``."""
    return moment.astimezone(UTC).strftime(TIME_FORMAT)


def invalid_file(
    pointer: str, rule: str, detail: str | None = None
) -> ProjectFileError:
    """Return the refusal of a file that breaks ``rule`` at ``pointer``.

    Parameters
    ----------
    pointer : str
        JSON pointer of the member (RFC 6901); ``""`` for the whole file.
    rule : str
        The rule it breaks: an entry ``project.rule_<rule>`` of the catalog.
    detail : str or None, optional
        The system's or the JSON reader's own text, appended and kept as
        ``details["detail"]``.
    """
    details = {"pointer": pointer, "rule": rule}
    if detail:
        details["detail"] = detail
    return ProjectFileError(rule_text(pointer, rule, detail), details=details)


def rule_text(pointer: str, rule: str, detail: str | None = None) -> str:
    """Return the text of a file that breaks ``rule`` at ``pointer``.

    Also how the index's problem of an invalid project is read back, in the
    language of each request (``invalid_file`` takes the same values).
    """
    name = message(f"project.rule_{rule}")
    if pointer:
        text = message("project.invalid_member", pointer=pointer, rule=name)
    else:
        text = message("project.invalid_file", rule=name)
    return with_detail(text, detail)


def unsupported_schema(schema: str) -> ProjectFileError:
    """Return the refusal of a project file of a newer format ``schema``."""
    return ProjectFileError(
        message("project.unsupported_schema", schema=schema),
        reason="unsupported_project_schema",
        details={"schema": schema},
        hint=message("fix.unsupported_project_schema"),
    )


def read_name(data: Mapping[str, object]) -> str | None:
    """Return the ``name`` of a file's JSON object when it keeps its rule.

    For a file of a newer format, which is listed with its name when it has
    one (A-ADR-049 decision 2).
    """
    try:
        return _name(data, "/name", "name", MAX_NAME_CHARS)
    except ProjectFileError:
        return None


def parse_document(data: object) -> ProjectDocument:
    """Read a project file's JSON value by the rules of ``archiwista-project/1``.

    Members the rules do not name are ignored.

    Parameters
    ----------
    data : object
        The file's JSON value.

    Returns
    -------
    ProjectDocument
        The project, its names NFC and trimmed.

    Raises
    ------
    ProjectFileError
        ``unsupported_project_schema`` for ``archiwista-project/<n>`` with
        ``n`` above 1; ``invalid_project_file`` with the pointer and the rule
        of the first member that breaks one.
    """
    root = _object(data, "")
    schema = root.get("schema")
    if schema != PROJECT_SCHEMA:
        found = _SCHEMA.fullmatch(schema) if isinstance(schema, str) else None
        if found is not None and int(found[1]) > 1:
            raise unsupported_schema(str(schema))
        raise invalid_file("/schema", "required" if schema is None else "schema")
    name = _name(root, "/name", "name", MAX_NAME_CHARS)
    description = root.get("description", "")
    if not isinstance(description, str):
        raise invalid_file("/description", "description")
    description = clean_name(description)
    if len(description) > MAX_DESCRIPTION_CHARS:
        raise invalid_file("/description", "description")
    return ProjectDocument(
        name=name,
        description=description,
        created_at=_time(root, "/created_at"),
        created_by=_account(root, "/created_by"),
        area=_area(root.get("area")),
        stores=_stores(_array(root, "/stores")),
        groups=_groups(_array(root, "/groups")),
    )


def document_json(document: ProjectDocument) -> dict[str, Any]:
    """Return the JSON object of a project file holding ``document``."""
    return {
        "schema": PROJECT_SCHEMA,
        "name": document.name,
        "description": document.description,
        "created_at": format_time(document.created_at),
        "created_by": document.created_by,
        "area": None if document.area is None else area_json(document.area),
        "stores": [store_json(store) for store in document.stores],
        "groups": [group_json(group) for group in document.groups],
    }


def area_json(area: AreaRef) -> dict[str, Any]:
    """Return the member ``area`` of a project file."""
    return {"path": area.path, "sha256": area.sha256}


def store_json(store: StoreRoot) -> dict[str, Any]:
    """Return an entry of the member ``stores`` of a project file."""
    return {"producer": store.producer, "root": store.root}


def group_json(group: PinGroup) -> dict[str, Any]:
    """Return an entry of the member ``groups`` of a project file.

    A closed set Archiwista did not close (one written before the sets had
    states) is written without ``state``, as it was read.
    """
    selections = [selection_json(item) for item in group.origin.selections]
    origin: dict[str, Any]
    if isinstance(group.origin, PlanOrigin):
        origin = {
            "kind": "plan",
            "producer": group.origin.producer,
            "calls": [
                {"command": call.command, "options": dict(call.options)}
                for call in group.origin.calls
            ],
        }
        if selections:
            origin["selections"] = selections
    else:
        origin = {"kind": "local", "selections": selections}
    data: dict[str, Any] = {"name": group.name}
    if group.state == "open" or group.pins_sha256 is not None:
        data["state"] = group.state
    if (
        group.closed_at is not None
        and group.closed_by is not None
        and group.pins_sha256 is not None
    ):
        data.update(
            closed_at=format_time(group.closed_at),
            closed_by=group.closed_by,
            pins_sha256=group.pins_sha256,
        )
    data.update(origin=origin, pins=[pin_json(pin) for pin in group.pins])
    return data


def selection_json(selection: Selection) -> dict[str, Any]:
    """Return an entry of the member ``selections`` of an origin."""
    if selection.query is None:
        return {"from": selection.source}
    return {"from": selection.source, "query": dict(selection.query)}


def pin_json(pin: Pin) -> dict[str, Any]:
    """Return an entry of the member ``pins`` of a group."""
    data: dict[str, Any] = {
        "producer": pin.producer,
        "version": pin.version,
        "sha256": pin.sha256,
    }
    if pin.content_sha256 is not None:
        data["content_sha256"] = pin.content_sha256
    data.update(
        size_bytes=pin.size_bytes,
        unit=pin.unit,
        label=pin.label,
        pinned_at=format_time(pin.pinned_at),
        pinned_by=pin.pinned_by,
    )
    if pin.calls is not None:
        data["calls"] = list(pin.calls)
    return data


def pins_digest(pins: Iterable[tuple[str, str, str]]) -> str:
    r"""Return the digest of a set's pins, its ``pins_sha256`` (A-ADR-049 erratum 6).

    The lowercase hexadecimal SHA-256 of the UTF-8 bytes of the lines
    ``<producer>\t<version>\t<sha256>\n``, one per pin, sorted by producer
    and version by code point, the three texts exactly as the file holds
    them (none can hold a tab or a line feed: ``_PRODUCER``, ``_relative``,
    ``_SHA256``). Only the pins' identity counts: their calls, times, labels
    and the set's origin do not. The writers and the index compute it here.

    Parameters
    ----------
    pins : Iterable[tuple[str, str, str]]
        ``(producer, version, sha256)`` of each pin, in any order.

    Returns
    -------
    str
        64 lowercase hexadecimal digits.
    """
    digest = hashlib.sha256()
    for producer, version, sha256 in sorted(pins, key=lambda pin: (pin[0], pin[1])):
        digest.update(f"{producer}\t{version}\t{sha256}\n".encode())
    return digest.hexdigest()


def group_state(group: Mapping[str, object]) -> SetState:
    """Return the state of a group's JSON object: ``closed`` without the member."""
    return "open" if group.get("state") == "open" else "closed"


def group_digest(group: Mapping[str, Any]) -> str:
    """Return ``pins_digest`` of the pins of a group's JSON object."""
    return pins_digest(
        (str(pin["producer"]), str(pin["version"]), str(pin["sha256"]))
        for pin in group.get("pins", [])
    )


def seal_group(group: dict[str, Any], *, closed_at: str, closed_by: str) -> str:
    """Close a group's JSON object as Archiwista closes a set; return its digest.

    Writes ``state`` ``closed`` with ``closed_at``, ``closed_by`` and
    ``pins_sha256`` (``pins_digest`` of its pins), in the members' order.
    """
    digest = group_digest(group)
    group.update(
        state="closed", closed_at=closed_at, closed_by=closed_by, pins_sha256=digest
    )
    _in_order(group)
    return digest


def unseal_group(group: dict[str, Any]) -> dict[str, Any]:
    """Open a group's JSON object; return the members of the closing it ends.

    ``closed_at``, ``closed_by`` and ``pins_sha256`` go (each ``None`` in the
    answer when the set had none) and ``state`` becomes ``open``.
    """
    ended = {name: group.pop(name, None) for name in CLOSED_MEMBERS}
    group["state"] = "open"
    _in_order(group)
    return ended


def _in_order(group: dict[str, Any]) -> None:
    """Put a group's members in the order Archiwista writes them; unknown ones last."""
    order = {name: place for place, name in enumerate(_GROUP_ORDER)}
    items = sorted(group.items(), key=lambda item: order.get(item[0], len(order)))
    group.clear()
    group.update(items)


def _pointer(base: str, *parts: object) -> str:
    """Return the JSON pointer of a member below ``base`` (RFC 6901 escapes)."""
    escaped = (str(part).replace("~", "~0").replace("/", "~1") for part in parts)
    return "/".join((base, *escaped))


def _object(value: object, pointer: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise invalid_file(pointer, "object")
    return value


def _array(parent: Mapping[str, object], pointer: str) -> list[object]:
    value = parent.get(pointer.rsplit("/", 1)[-1])
    if value is None:
        raise invalid_file(pointer, "required")
    if not isinstance(value, list):
        raise invalid_file(pointer, "array")
    return value


def _member(parent: Mapping[str, object], pointer: str) -> object:
    """Return a required member (the last part of ``pointer``) of ``parent``."""
    name = pointer.rsplit("/", 1)[-1]
    if name not in parent:
        raise invalid_file(pointer, "required")
    return parent[name]


def _plain(text: str) -> bool:
    """Whether a text holds no control character."""
    return not any(unicodedata.category(char) == "Cc" for char in text)


def _name(parent: Mapping[str, object], pointer: str, rule: str, limit: int) -> str:
    value = _member(parent, pointer)
    if not isinstance(value, str):
        raise invalid_file(pointer, rule)
    name = clean_name(value)
    if not 1 <= len(name) <= limit or not _plain(name):
        raise invalid_file(pointer, rule)
    return name


def _time(parent: Mapping[str, object], pointer: str) -> datetime:
    value = _member(parent, pointer)
    if not isinstance(value, str) or _TIME.fullmatch(value) is None:
        raise invalid_file(pointer, "time")
    try:
        return datetime.strptime(value, TIME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        raise invalid_file(pointer, "time") from None


def _account(parent: Mapping[str, object], pointer: str) -> str:
    value = _member(parent, pointer)
    if not isinstance(value, str) or not value or not _plain(value):
        raise invalid_file(pointer, "account")
    return value


def _sha256(parent: Mapping[str, object], pointer: str) -> str:
    value = _member(parent, pointer)
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise invalid_file(pointer, "sha256")
    return value


def _producer(parent: Mapping[str, object], pointer: str) -> str:
    value = _member(parent, pointer)
    if not isinstance(value, str) or _PRODUCER.fullmatch(value) is None:
        raise invalid_file(pointer, "producer")
    return value


def _text(parent: Mapping[str, object], pointer: str) -> str | None:
    value = _member(parent, pointer)
    if value is None:
        return None
    if not isinstance(value, str) or not _plain(value):
        raise invalid_file(pointer, "text")
    return value


def _relative(path: str) -> bool:
    """Whether ``path`` is relative, ``/``-separated and without ``..``.

    A Windows drive or UNC anchor (``C:/x``, ``C:x``) is refused as
    :func:`archiwista.paths.indexed_path` refuses it.
    """
    parts = path.split("/")
    return (
        _plain(path)
        and "\\" not in path
        and not PureWindowsPath(path).anchor
        and all(part not in ("", ".", "..") for part in parts)
    )


def _area(value: object) -> AreaRef | None:
    if value is None:
        return None
    area = _object(value, "/area")
    path = _member(area, "/area/path")
    if not (
        isinstance(path, str) and path.startswith(f"{AREAS_DIR}/") and _relative(path)
    ):
        raise invalid_file("/area/path", "area_path")
    return AreaRef(path=path, sha256=_sha256(area, "/area/sha256"))


def _stores(items: list[object]) -> tuple[StoreRoot, ...]:
    stores: list[StoreRoot] = []
    for index, item in enumerate(items):
        base = _pointer("/stores", index)
        store = _object(item, base)
        producer = _producer(store, f"{base}/producer")
        if any(known.producer == producer for known in stores):
            raise invalid_file(f"{base}/producer", "store_unique")
        root = _member(store, f"{base}/root")
        if not isinstance(root, str) or not root or not _plain(root):
            raise invalid_file(f"{base}/root", "root")
        stores.append(StoreRoot(producer=producer, root=root))
    return tuple(stores)


def _groups(items: list[object]) -> tuple[PinGroup, ...]:
    groups: list[PinGroup] = []
    taken: set[str] = set()
    for index, item in enumerate(items):
        base = _pointer("/groups", index)
        group = _object(item, base)
        name = _name(group, f"{base}/name", "group_name", MAX_GROUP_NAME_CHARS)
        if "/" in name:
            raise invalid_file(f"{base}/name", "group_name")
        if name.casefold() in taken:
            raise invalid_file(f"{base}/name", "group_unique")
        taken.add(name.casefold())
        pointer = f"{base}/origin"
        origin = _origin(_object(_member(group, pointer), pointer), pointer)
        pins = _pins(_array(group, f"{base}/pins"), f"{base}/pins", origin)
        state, closed_at, closed_by, digest = _closing(group, base)
        groups.append(
            PinGroup(
                name=name,
                origin=origin,
                pins=pins,
                state=state,
                closed_at=closed_at,
                closed_by=closed_by,
                pins_sha256=digest,
            )
        )
    return tuple(groups)


def _closing(
    group: Mapping[str, object], base: str
) -> tuple[SetState, datetime | None, str | None, str | None]:
    """Return a group's state and the members of its closing, if it has them.

    ``state`` is ``open`` or ``closed`` (``set_state``), ``closed`` when left
    out; ``closed_at``, ``closed_by`` and ``pins_sha256`` are all three or
    none, and none on an open set (``set_closed_members``).
    """
    given = group.get("state", "closed")
    state = next((known for known in SET_STATES if known == given), None)
    if state is None:
        raise invalid_file(f"{base}/state", "set_state")
    present = [name for name in CLOSED_MEMBERS if name in group]
    if not present:
        return state, None, None, None
    if state == "open":
        raise invalid_file(f"{base}/{present[0]}", "set_closed_members")
    missing = [name for name in CLOSED_MEMBERS if name not in group]
    if missing:
        raise invalid_file(f"{base}/{missing[0]}", "set_closed_members")
    return (
        state,
        _time(group, f"{base}/closed_at"),
        _account(group, f"{base}/closed_by"),
        _sha256(group, f"{base}/pins_sha256"),
    )


def _origin(origin: Mapping[str, object], base: str) -> PlanOrigin | LocalOrigin:
    kind = origin.get("kind")
    if kind == "plan":
        producer = _producer(origin, f"{base}/producer")
        items = _array(origin, f"{base}/calls")
        if not 1 <= len(items) <= MAX_GROUP_CALLS:
            raise invalid_file(f"{base}/calls", "calls")
        calls: list[CommandCall] = []
        for index, item in enumerate(items):
            pointer = _pointer(f"{base}/calls", index)
            call = _object(item, pointer)
            command = _member(call, f"{pointer}/command")
            if not isinstance(command, str) or not command or not _plain(command):
                raise invalid_file(f"{pointer}/command", "command")
            options = _object(_member(call, f"{pointer}/options"), f"{pointer}/options")
            calls.append(CommandCall(producer, command, dict(options)))
        selections: tuple[Selection, ...] = ()
        if origin.get("selections") is not None:
            selections = _selections(origin, f"{base}/selections")
        return PlanOrigin(producer=producer, calls=tuple(calls), selections=selections)
    if kind == "local":
        return LocalOrigin(selections=_selections(origin, f"{base}/selections"))
    raise invalid_file(f"{base}/kind", "required" if kind is None else "origin")


def _selections(origin: Mapping[str, object], base: str) -> tuple[Selection, ...]:
    """Return the requests an origin records (its member ``selections``)."""
    selections: list[Selection] = []
    for index, item in enumerate(_array(origin, base)):
        pointer = _pointer(base, index)
        selection = _object(item, pointer)
        given = _member(selection, f"{pointer}/from")
        source = next((known for known in SELECTION_SOURCES if known == given), None)
        if source is None:
            raise invalid_file(f"{pointer}/from", "selection")
        query = selection.get("query")
        # A request that named its versions has no query: always `file`,
        # and `local_state` for the year layer the map shows.
        if source == "file" and query is not None:
            raise invalid_file(f"{pointer}/query", "query")
        if query is None and source != "catalog":
            selections.append(Selection(source=source, query=None))
            continue
        if not isinstance(query, dict):
            raise invalid_file(f"{pointer}/query", "query")
        selections.append(Selection(source=source, query=dict(query)))
    return tuple(selections)


def _pins(
    items: list[object], base: str, origin: PlanOrigin | LocalOrigin
) -> tuple[Pin, ...]:
    if len(items) > MAX_GROUP_PINS:
        raise invalid_file(base, "pins")
    pins: list[Pin] = []
    seen: set[tuple[str, str]] = set()
    for index, item in enumerate(items):
        pointer = _pointer(base, index)
        pin = _object(item, pointer)
        producer = _producer(pin, f"{pointer}/producer")
        if isinstance(origin, PlanOrigin) and producer != origin.producer:
            raise invalid_file(f"{pointer}/producer", "plan_producer")
        version = _member(pin, f"{pointer}/version")
        if not isinstance(version, str) or not _relative(version):
            raise invalid_file(f"{pointer}/version", "version")
        if (producer, version) in seen:
            raise invalid_file(f"{pointer}/version", "pin_unique")
        seen.add((producer, version))
        content = None
        if pin.get("content_sha256") is not None:
            content = _sha256(pin, f"{pointer}/content_sha256")
        size = _member(pin, f"{pointer}/size_bytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise invalid_file(f"{pointer}/size_bytes", "size")
        calls = None
        if pin.get("calls") is not None:
            calls = _pin_calls(pin["calls"], f"{pointer}/calls", origin)
        pins.append(
            Pin(
                producer=producer,
                version=version,
                sha256=_sha256(pin, f"{pointer}/sha256"),
                content_sha256=content,
                size_bytes=size,
                unit=_text(pin, f"{pointer}/unit"),
                label=_text(pin, f"{pointer}/label"),
                pinned_at=_time(pin, f"{pointer}/pinned_at"),
                pinned_by=_account(pin, f"{pointer}/pinned_by"),
                calls=calls,
            )
        )
    return tuple(pins)


def _pin_calls(
    value: object, pointer: str, origin: PlanOrigin | LocalOrigin
) -> tuple[int, ...]:
    """Return the places of a pin's calls (``pin_calls``).

    Only a ``plan`` group's pin names calls: ascending distinct places of
    ``origin.calls``, ``[]`` for a pin added by hand.
    """
    if not isinstance(origin, PlanOrigin) or not isinstance(value, list):
        raise invalid_file(pointer, "pin_calls")
    places: list[int] = []
    for item in value:
        if (
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 0 <= item < len(origin.calls)
            or (places and item <= places[-1])
        ):
            raise invalid_file(pointer, "pin_calls")
        places.append(item)
    return tuple(places)
