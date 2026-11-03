"""Store marker file names of the Nogat producers (DEV-19.12).

Every producer's store root holds a marker ``<tool>-store.json`` (schema
``<tool>-store/1``). A tool judges another tool's store by this file name
alone and imports nothing from it (DEV-19.12, DEV-19.14): so do Archiwista's
adapters when they refuse a foreign directory, and the settings when they
refuse a store nested in another one. The list is the one of Nogat's
DEV §19.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

STORE_MARKERS: Mapping[str, str] = MappingProxyType(
    {
        "kartograf": "kartograf-store.json",
        "imgw": "imgw-store.json",
    }
)
"""Marker file name by producer id."""

NESTING_DEPTH = 2
"""Levels below a directory that ``store_below`` looks into.

A store that was put into another store's tree lies in one of its first levels
(the products and segments of Kartograf, the trees and datasets of IMGWTools),
which are a few dozen directories; the slots below them are tens of thousands.
The producer's own writer looks at the whole tree before it writes.
"""


def foreign_markers(producer: str) -> tuple[str, ...]:
    """Return the marker file names of every producer but ``producer``."""
    return tuple(name for key, name in STORE_MARKERS.items() if key != producer)


def marker_in(directory: Path) -> str | None:
    """Return the name of the store marker a directory holds, ``None`` without one.

    A directory that cannot be read holds none as far as anyone can tell.
    """
    for name in STORE_MARKERS.values():
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
