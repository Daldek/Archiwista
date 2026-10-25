"""Kartograf source plugin: the only package that imports ``kartograf``.

The factory compares the installed Kartograf with the range the adapter
reads (``SUPPORTED_VERSIONS``) before importing it, so a Kartograf without
the store API is reported as ``incompatible`` with both versions rather than
as an import error.
"""

from archiwista.sources import SourceAdapter, SourceContext
from archiwista.sources.registry import check_package, source_error

PRODUCER = "kartograf"
PACKAGE = "kartograf"
# The Kartograf versions the adapter reads (PEP 440). Archiwista's own
# requirement on Kartograf is a commit or tag (REL-5.3), so it cannot hold
# the range. While the commit is pinned the range starts at the development
# version of the pending release (REL-5.6): PEP 440 sorts ``0.8.0.dev0``
# below ``0.8.0``. The release pull request narrows it to ``>=0.8.0,<0.9``.
SUPPORTED_VERSIONS = ">=0.8.0.dev0,<0.9"
SCHEMAS = ("kartograf-meta/1", "kartograf-project/1", "kartograf-store/1")


def load(context: SourceContext) -> SourceAdapter:
    """Create the Kartograf adapter (``archiwista.sources`` entry point).

    Parameters
    ----------
    context : SourceContext
        ``cache_dir`` keeps the local memory of unit outlines.

    Returns
    -------
    SourceAdapter
        The adapter, also implementing every optional capability.

    Raises
    ------
    SourceUnavailableError
        Kartograf is not installed.
    SourceIncompatibleError
        The installed Kartograf is outside ``SUPPORTED_VERSIONS``.
    """
    state = check_package(PRODUCER, PACKAGE, SUPPORTED_VERSIONS, SCHEMAS)
    if state.status != "available":
        raise source_error(state)
    from archiwista.adapter.kartograf.adapter import KartografAdapter

    return KartografAdapter(context, supported_versions=SUPPORTED_VERSIONS)
