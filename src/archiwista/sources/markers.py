"""Store marker file names of the Nogat producers and their data roots (DEV-19.12).

Every producer's store root holds a marker ``<tool>-store.json`` (schema
``<tool>-store/1``). A tool judges another tool's store by this file name
alone and imports nothing from it (DEV-19.12, DEV-19.14): so do Archiwista's
adapters when they refuse a foreign directory, and the settings when they
refuse a store nested in another one. The list is the one of Nogat's
DEV §19.

Obserwator keeps what it builds in a data root of its own beside its store
root, the raw root (Obserwator ADR-017): the marker ``obserwator-data.json``
(``obserwator-data/1``) and the trees ``series/``, ``stations/`` and
``analyses/``. A path of such a producer lies in its data root when its first
part is one of those trees (Obserwator ADR-017 D6), else in its store root;
the settings name the data root in the field ``<producer>_data`` of a store
(A-ADR-056).
"""

import os
from collections.abc import Mapping
from pathlib import Path, PurePath
from types import MappingProxyType

STORE_MARKERS: Mapping[str, str] = MappingProxyType(
    {
        "kartograf": "kartograf-store.json",
        "obserwator": "obserwator-store.json",
    }
)
"""Marker file name of the store root by producer id."""

DATA_MARKERS: Mapping[str, str] = MappingProxyType(
    {"obserwator": "obserwator-data.json"}
)
"""Marker file name of the data root by producer id, for a producer with one."""

DATA_TREES: Mapping[str, frozenset[str]] = MappingProxyType(
    {"obserwator": frozenset({"series", "stations", "analyses"})}
)
"""The first parts of the paths that lie in a producer's data root."""

NESTING_DEPTH = 2
"""Levels below a directory that ``store_below`` looks into.

A store that was put into another store's tree lies in one of its first levels
(the products and segments of Kartograf, the trees and datasets of Obserwator),
which are a few dozen directories; the slots below them are tens of thousands.
The producer's own writer looks at the whole tree before it writes.
"""

_MARKERS = (*STORE_MARKERS.values(), *DATA_MARKERS.values())


def data_field(producer: str) -> str:
    """Return the settings field of a producer's data root (``obserwator_data``)."""
    return f"{producer}_data"


def field_producer(field: str) -> str:
    """Return the producer of a store's directory field (``obserwator_data``)."""
    for producer in DATA_MARKERS:
        if field == data_field(producer):
            return producer
    return field


def directory_field(producer: str, path: str | PurePath) -> str:
    """Return the settings field of the directory a producer's path lies in.

    Parameters
    ----------
    producer : str
        Producer id.
    path : str or PurePath
        A path relative to the producer's directories, as the index keeps it
        (parts joined by ``/``).

    Returns
    -------
    str
        ``<producer>_data`` for a path in a tree of its data root
        (``DATA_TREES``), else the producer id: its store root.
    """
    trees = DATA_TREES.get(producer)
    if trees is None:
        return producer
    text = path if isinstance(path, str) else path.as_posix()
    if text.partition("/")[0] in trees:
        return data_field(producer)
    return producer


def foreign_markers(producer: str) -> tuple[str, ...]:
    """Return the marker file names of every producer but ``producer``."""
    return tuple(
        name
        for markers in (STORE_MARKERS, DATA_MARKERS)
        for key, name in markers.items()
        if key != producer
    )


def marker_in(directory: Path) -> str | None:
    """Return the name of the store marker a directory holds, ``None`` without one.

    A store root and a data root are both stores here: no root of a producer
    nests in another (DEV-19.14). A directory that cannot be read holds none
    as far as anyone can tell.
    """
    for name in _MARKERS:
        if os.path.isfile(directory / name):
            return name
    return None


def store_around(path: Path) -> tuple[Path, str] | None:
    """Return the nearest ancestor of ``path`` that holds a store marker.

    Parameters
    ----------
    path : Path
        A directory, normally after ``realpath``; its own marker does not count.

    Returns
    -------
    tuple[Path, str] or None
        The ancestor and the marker file name found in it.
    """
    for ancestor in path.parents:
        name = marker_in(ancestor)
        if name is not None:
            return ancestor, name
    return None


def store_below(path: Path, *, depth: int = NESTING_DEPTH) -> tuple[Path, str] | None:
    """Return a directory below ``path`` that holds a store marker.

    The directories are searched level by level, in name order, down to
    ``depth`` levels (``NESTING_DEPTH``); symbolic links are not followed.

    Parameters
    ----------
    path : Path
        A directory, normally after ``realpath``; its own marker does not count.
    depth : int, default ``NESTING_DEPTH``
        How many levels below ``path`` to look into.

    Returns
    -------
    tuple[Path, str] or None
        The first directory found and the marker file name found in it.
    """
    level = [path]
    for _ in range(depth):
        below: list[Path] = []
        for directory in level:
            for child in _directories(directory):
                name = marker_in(child)
                if name is not None:
                    return child, name
                below.append(child)
        level = below
    return None


def _directories(path: Path) -> list[Path]:
    """List the subdirectories of ``path`` by name, not the links."""
    try:
        with os.scandir(path) as entries:
            found = [
                Path(entry.path)
                for entry in entries
                if entry.is_dir(follow_symlinks=False)
            ]
    except OSError:
        return []
    return sorted(found)
