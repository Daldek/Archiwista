"""The two roots of an Obserwator fixture store (Obserwator ADR-017, A-ADR-056).

Obserwator keeps a store in two directories: the raw root
(``obserwator-store.json``) of the archives and station sources that its
``store sync`` downloads, and the data root (``obserwator-data.json``) of the
series, station catalogs and analyses it builds from them. A fixture store of
the tests is one directory that holds both, ``raw/`` and ``data/``, so that a
test copies it whole; its settings name each root in its own field. A path of
the store lies in the root of its first part, as Archiwista indexes it.
"""

from pathlib import Path, PurePath
from typing import TypedDict

RAW = "raw"
DATA = "data"
# The trees of the data root (Obserwator ADR-017 D6); every other path is raw.
DATA_TREES = frozenset({"series", "stations", "analyses"})


class StoreFields(TypedDict):
    """The settings fields of Obserwator's two roots in a store."""

    obserwator: Path
    obserwator_data: Path


def raw_root(store: Path) -> Path:
    """Return the raw root of a fixture store."""
    return store / RAW


def data_root(store: Path) -> Path:
    """Return the data root of a fixture store."""
    return store / DATA


def store_fields(store: Path) -> StoreFields:
    """Return the settings fields of a fixture store's roots.

    ``StoreConfig(id=..., name=..., **store_fields(store), kind=...)`` names the
    raw root in ``obserwator`` and the data root in ``obserwator_data``.
    """
    return StoreFields(obserwator=raw_root(store), obserwator_data=data_root(store))


def root_of(store: Path, path: str | PurePath) -> Path:
    """Return the root of a fixture store that a store path lies in.

    Parameters
    ----------
    store : Path
        The fixture store, the directory of ``raw/`` and ``data/``.
    path : str or PurePath
        A path of the store as the index keeps it, relative to its root.

    Returns
    -------
    Path
        The data root for ``series/``, ``stations/`` and ``analyses/``, else the
        raw root.
    """
    first = PurePath(path).parts[0]
    return data_root(store) if first in DATA_TREES else raw_root(store)
