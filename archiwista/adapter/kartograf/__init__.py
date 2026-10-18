"""Kartograf source plugin: the only package that imports ``kartograf``.

The factory compares the installed Kartograf with Archiwista's own pin
before importing it, so a Kartograf without the store API is reported as
``incompatible`` with both versions rather than as an import error.
"""

from archiwista.errors import ArchiwistaError
from archiwista.messages import MESSAGES
from archiwista.sources import SourceAdapter, SourceContext
from archiwista.sources.registry import app_requirement, check_package, source_error

PRODUCER = "kartograf"
PACKAGE = "kartograf"
SCHEMAS = ("kartograf-meta/1", "kartograf-project/1")


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
        The installed Kartograf is outside Archiwista's pinned range.
    """
    requirement = app_requirement(PACKAGE)
    if requirement is None:
        raise ArchiwistaError(MESSAGES["plugin_range_missing"].format(package=PACKAGE))
    supported = str(requirement.specifier)
    state = check_package(PRODUCER, PACKAGE, supported, SCHEMAS)
    if state.status != "available":
        raise source_error(state)
    from archiwista.adapter.kartograf.adapter import KartografAdapter

    return KartografAdapter(context, supported_versions=supported)
