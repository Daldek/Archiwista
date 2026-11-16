"""The marker of a generated Kartograf store (DEV-19.13, ADR-031).

A Kartograf store is a root with ``kartograf-store.json``; Archiwista refuses a
root that has the layout and no marker. The generators of this package write
stores by hand (the 0.8 API has no offline writer of versions at scale), so
each one marks its new root first, through Kartograf's own ``init_store``, the
way the first write of Kartograf into a new root does.
"""

from datetime import UTC, datetime
from pathlib import Path

from kartograf import StoreInit, init_store

# Before every download of the generated stores (2025 and 2026), and the same for
# every store: two stores of one seed stay equal.
MARKED_AT = datetime(2024, 12, 31, tzinfo=UTC)


def mark_store(root: Path) -> StoreInit:
    """Write the marker of a new store root, before its first file.

    Parameters
    ----------
    root : Path
        Missing or empty directory; created when missing.

    Returns
    -------
    StoreInit
        The marker Kartograf wrote (``marker`` is its path).
    """
    return init_store(root, created_at=MARKED_AT)
