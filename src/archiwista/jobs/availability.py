"""Whether a store directory can be read now, before a job relies on it.

A producer's probe may find an empty directory a valid, empty store; for a
store the index holds entries of, an empty directory is a share that is not
mounted (SPEC 4.4, 4.6). Jobs and the scheduler then leave the index as it
is.
"""

import os
from pathlib import Path

from archiwista.messages import message, with_detail
from archiwista.sources import SourceState


def unreachable_detail(state: SourceState, root: Path, *, indexed: bool) -> str | None:
    """Return why a store directory cannot be read now, ``None`` when it can.

    Parameters
    ----------
    state : SourceState
        The producer's probe of ``root``.
    root : Path
        The producer directory of the store.
    indexed : bool
        Whether the index holds entries of the store: then an empty
        directory counts as unavailable.

    Returns
    -------
    str or None
        Description of the cause, a catalog message.
    """
    if state.status != "available":
        text = message("store.unreadable", path=root)
        return with_detail(text, state.detail)
    if indexed and _empty(root):
        return message("scan.store_empty", path=root)
    return None


def _empty(root: Path) -> bool:
    """Whether a directory lists nothing; one that cannot be listed counts."""
    try:
        with os.scandir(root) as entries:
            return next(entries, None) is None
    except OSError:
        return True
