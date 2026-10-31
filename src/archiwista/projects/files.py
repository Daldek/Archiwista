"""The project file on the disk: reading it, and changing it under its lock.

Archiwista writes a project's directory only on a person's command
(A-ADR-049 decisions 3 and 4, SPEC 10.1): the project file, the area files
in ``obszary/`` and the exports in ``zestawy/`` (``exports``, through
``_write_atomic``). A share gives no reliable byte-range
locks (SPEC 4.6), so every change of the project file takes the lock
``.archiwista-project.lock``, a directory made with ``os.mkdir`` beside the
file (atomic on a local disk and on SMB), with its owner (``<host>_<pid>``
and the time) written inside for the person who finds it. A lock held by
another writer is waited for (``LOCK_WAIT_S``), then the change is refused
(``ProjectLockedError``); Archiwista removes only its own lock, never
another's. Under the lock ``change_project_file`` reads the file again,
applies one change to its JSON object (members it does not know stay),
validates the result, writes it beside the file under a name of its own,
``fsync``s it, replaces the file with ``os.replace`` and ``fsync``s the
directory where the platform allows: a failed write leaves the file whole.
The area files are written the same way, without the lock: a file of
another area has another name, and one of the same name and content is kept.

``archiwista.areas`` imports the index, which reads project files, so it is
imported where an area file is read.
"""

import hashlib
import json
import logging
import os
import secrets
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from archiwista.errors import (
    PathOutsideRootError,
    ProjectAreaError,
    ProjectFileError,
    ProjectFileWriteError,
    ProjectLockedError,
)
from archiwista.messages import message, with_detail
from archiwista.projects.document import (
    AREAS_DIR,
    LOCK_NAME,
    MAX_PROJECT_FILE_BYTES,
    PROJECT_FILE,
    AreaRef,
    ProjectDocument,
    document_json,
    format_time,
    invalid_file,
    parse_document,
)
from archiwista.sandbox import owner_alive, process_owner
from archiwista.sources.types import GeoJSONGeometry

if TYPE_CHECKING:
    from archiwista.index.types import AreaRecord

# How long a change waits for a lock another writer holds, and how often it
# looks again.
LOCK_WAIT_S = 5.0
LOCK_POLL_S = 0.1
# The file inside a lock naming who holds it.
LOCK_OWNER = "owner"

type ProjectChange = Callable[[dict[str, Any]], None]
type AreaState = Literal["missing", "changed", "invalid"]

logger = logging.getLogger(__name__)


def read_project_json(directory: Path) -> dict[str, Any]:
    """Return the JSON object of a project file, before its rules are checked.

    Parameters
    ----------
    directory : Path
        The project directory.

    Raises
    ------
    ProjectFileError
        ``invalid_project_file`` with the rule ``unreadable`` (no file, no
        permission), ``too_large`` (over ``MAX_PROJECT_FILE_BYTES``),
        ``invalid_json`` (no UTF-8 JSON) or ``object`` (no JSON object).
    """
    try:
        with open(directory / PROJECT_FILE, "rb") as file:
            content = file.read(MAX_PROJECT_FILE_BYTES + 1)
    except OSError as error:
        raise invalid_file("", "unreadable", error.strerror or str(error)) from None
    if len(content) > MAX_PROJECT_FILE_BYTES:
        raise invalid_file("", "too_large")
    try:
        data = json.loads(content.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise invalid_file("", "invalid_json", str(error)) from None
    if not isinstance(data, dict):
        raise invalid_file("", "object")
    return data


def read_project_file(directory: Path) -> ProjectDocument:
    """Read a project file by the rules of ``archiwista-project/1``.

    Parameters
    ----------
    directory : Path
        The project directory.

    Raises
    ------
    ProjectFileError
        ``invalid_project_file`` (``read_project_json``, ``parse_document``)
        or ``unsupported_project_schema``.
    """
    return parse_document(read_project_json(directory))


@contextmanager
def project_lock(directory: Path, *, wait_s: float = LOCK_WAIT_S) -> Iterator[Path]:
    """Hold the lock of a project's file while the block runs.

    Parameters
    ----------
    directory : Path
        The project directory, which holds the lock.
    wait_s : float, optional
        How long a lock held by another writer is waited for.

    Yields
    ------
    Path
        The lock, removed when the block ends.

    Raises
    ------
    ProjectLockedError
        Another writer held the lock past ``wait_s``: the lock, its owner and
        whether that owner is a process of this computer that has ended.
    ProjectFileWriteError
        The lock could not be made (a read-only share, no space).
    """
    lock = directory / LOCK_NAME
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise _locked(lock) from None
            time.sleep(LOCK_POLL_S)
        except OSError as error:
            raise _write_failed(directory / PROJECT_FILE, error) from error
    try:
        try:
            owner = f"{process_owner()} {format_time(datetime.now(UTC))}\n"
            (lock / LOCK_OWNER).write_text(owner, encoding="utf-8")
        except OSError as error:
            raise _write_failed(directory / PROJECT_FILE, error) from error
        yield lock
    finally:
        _release(lock)


def change_project_file(
    directory: Path,
    change: ProjectChange | None = None,
    *,
    create: ProjectDocument | None = None,
    wait_s: float = LOCK_WAIT_S,
) -> ProjectDocument:
    """Apply one change to a project file under its lock; return the result.

    Parameters
    ----------
    directory : Path
        The project directory; it must exist.
    change : callable or None, optional
        Changes the file's JSON object in place; members it does not touch,
        unknown ones too, stay as they were.
    create : ProjectDocument or None, optional
        Write a new file holding this project (then ``change``, if given).
    wait_s : float, optional
        How long a lock held by another writer is waited for.

    Returns
    -------
    ProjectDocument
        The project as the file now holds it.

    Raises
    ------
    ProjectFileError
        The file is invalid (``invalid_project_file``) or of a newer format
        (``unsupported_project_schema``): Archiwista never writes over a file
        it cannot read; the result breaks a rule; or ``create`` is given and
        a project file exists (``project_exists``).
    ProjectLockedError
        Another writer held the lock past ``wait_s``.
    ProjectFileWriteError
        The lock or the file could not be written; the file stays as it was.
    """
    path = directory / PROJECT_FILE
    with project_lock(directory, wait_s=wait_s):
        if create is not None:
            if os.path.lexists(path):
                raise ProjectFileError(
                    message("project.exists", path=directory), reason="project_exists"
                )
            data = document_json(create)
        else:
            data = read_project_json(directory)
            parse_document(data)
        if change is not None:
            change(data)
        document = parse_document(data)
        content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
        if len(content) > MAX_PROJECT_FILE_BYTES:
            raise invalid_file("", "too_large")
        _write_atomic(path, content)
    return document


def area_file_bytes(area: "AreaRecord") -> bytes:
    """Return the GeoJSON file of an area as a project keeps it (RFC 7946).

    A ``FeatureCollection`` of one feature: the area's geometry in WGS84 with
    the properties ``name``, ``source``, ``area_km2`` and ``countries``.
    """
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "name": area.name,
                    "source": area.source,
                    "area_km2": area.area_km2,
                    "countries": list(area.countries),
                },
                "geometry": area.geometry,
            }
        ],
    }
    return (json.dumps(collection, ensure_ascii=False) + "\n").encode()


def write_area_file(directory: Path, area: "AreaRecord") -> AreaRef:
    """Write an area into the project's ``obszary/`` as ``<area id>.geojson``.

    The file is written under a name of its own and moved into place; one of
    the same name and content is kept as it is. No other file is touched.

    Parameters
    ----------
    directory : Path
        The project directory.
    area : AreaRecord
        An area of the index.

    Returns
    -------
    AreaRef
        Its path relative to the project directory and the SHA-256 of its
        bytes, for the project file.

    Raises
    ------
    PathOutsideRootError
        ``obszary/`` leads out of the project directory (a symbolic link).
    ProjectFileWriteError
        The file could not be written.
    """
    content = area_file_bytes(area)
    name = f"{area.id}.geojson"
    ref = AreaRef(
        path=f"{AREAS_DIR}/{name}", sha256=hashlib.sha256(content).hexdigest()
    )
    target = directory / AREAS_DIR / name
    try:
        target.parent.mkdir(exist_ok=True)
        inside = target.parent.resolve().is_relative_to(directory.resolve())
    except OSError as error:
        raise _write_failed(target, error) from error
    if not inside:
        raise PathOutsideRootError(message("ref.path_outside_root", path=target.parent))
    with suppress(OSError):
        if target.is_file() and target.read_bytes() == content:
            return ref
    _write_atomic(target, content)
    return ref


def read_project_area(directory: Path, ref: AreaRef) -> GeoJSONGeometry:
    """Return the geometry of a project's area file, as the project records it.

    The file is read as JSON only (no GDAL), at most
    ``areas.AREA_BODY_LIMIT_BYTES``, and must hold the bytes of
    ``ref.sha256``. Its polygon is checked by ``areas.area_from_geometry``.

    Parameters
    ----------
    directory : Path
        The project directory.
    ref : AreaRef
        The project file's ``area``.

    Raises
    ------
    ProjectAreaError
        State ``missing`` (no file), ``changed`` (other bytes) or
        ``invalid`` (unreadable, a link out of the project directory, over
        the limit, no ``FeatureCollection`` of one polygon feature).
    """
    from archiwista.areas import AREA_BODY_LIMIT_BYTES

    path = directory / ref.path
    try:
        real = path.resolve(strict=True)
        if not real.is_relative_to(directory.resolve(strict=True)):
            raise _area_error(path, "invalid")
        with open(real, "rb") as file:
            content = file.read(AREA_BODY_LIMIT_BYTES + 1)
    except (FileNotFoundError, NotADirectoryError):
        raise _area_error(path, "missing") from None
    except OSError:
        raise _area_error(path, "invalid") from None
    if len(content) > AREA_BODY_LIMIT_BYTES:
        raise _area_error(path, "invalid")
    if hashlib.sha256(content).hexdigest() != ref.sha256:
        raise _area_error(path, "changed")
    try:
        data = json.loads(content.decode("utf-8"), parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise _area_error(path, "invalid") from None
    features = data.get("features") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or len(features) != 1
        or not isinstance(features[0], dict)
    ):
        raise _area_error(path, "invalid")
    geometry = features[0].get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in (
        "Polygon",
        "MultiPolygon",
    ):
        raise _area_error(path, "invalid")
    return geometry


def _no_constant(name: str) -> None:
    """Refuse ``NaN`` and the infinities, which JSON does not have."""
    raise ValueError(f"{name} is not JSON")


def _area_error(path: Path, state: AreaState) -> ProjectAreaError:
    return ProjectAreaError(message(f"project.area_{state}", path=path), state=state)


def _locked(lock: Path) -> ProjectLockedError:
    """Return the refusal of a change while another writer holds ``lock``."""
    owner = _lock_owner(lock)
    ended = owner is not None and not owner_alive(owner)
    if owner is None:
        text = message(
            "project.file_locked",
            owner=message("project.lock_owner_unknown"),
            lock=lock,
        )
    elif ended:
        text = message("project.file_locked_ended", owner=owner, lock=lock)
    else:
        text = message("project.file_locked", owner=owner, lock=lock)
    return ProjectLockedError(
        text,
        lock=str(lock),
        hint=message("fix.project_locked", lock=lock),
        owner=owner,
        owner_ended=ended,
    )


def _lock_owner(lock: Path) -> str | None:
    """Return the owner a lock names, ``None`` when it names none (yet)."""
    try:
        words = (lock / LOCK_OWNER).read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        return None
    return words[0] if words else None


def _release(lock: Path) -> None:
    """Remove a lock this process made; one it cannot remove is left and logged."""
    with suppress(FileNotFoundError):
        (lock / LOCK_OWNER).unlink()
    try:
        os.rmdir(lock)
    except OSError as error:
        logger.warning("cannot remove the project lock %s: %s", lock, error)


def _write_atomic(path: Path, content: bytes) -> None:
    """Write ``content`` beside ``path`` under a name of its own, then move it.

    Raises
    ------
    ProjectFileWriteError
        Writing or moving failed; ``path`` is as it was and the temporary
        file is gone.
    """
    temp = path.with_name(f".{path.name}.{process_owner()}_{secrets.token_hex(4)}.tmp")
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    except OSError as error:
        with suppress(OSError):
            temp.unlink()
        raise _write_failed(path, error) from error
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    """Flush a directory's entries to the disk where the platform allows it."""
    if sys.platform == "win32":  # pragma: no cover - directories cannot be opened
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        with suppress(OSError):  # a share that cannot flush a directory
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_failed(path: Path, error: OSError) -> ProjectFileWriteError:
    return ProjectFileWriteError(
        with_detail(
            message("project.file_write_failed", path=path),
            error.strerror or str(error),
        ),
        hint=message("fix.project_file_write_failed", path=path.parent),
    )
