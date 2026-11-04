"""Obserwator source plugin: the only package that imports ``obserwator``.

One plugin reads both providers of the package, IMGW-PIB and ČHMÚ: a store
of Obserwator holds the files of both, so a dataset (``pl.imgw.hydro_daily``,
``cz.chmi.hydro_daily``) is what tells them apart. The factory compares the
installed Obserwator with the range the adapter reads (``SUPPORTED_VERSIONS``)
before importing it, so a missing or unsupported package is a state of this
source (``not_installed``, ``incompatible``) and the others keep working.

The package never imports ``pyarrow``: reading a store needs no Parquet file,
only the JSON documents of its versions. Archiwista's requirement on Obserwator
is the extra ``archiwista[obserwator]`` (A-ADR-024).
"""

from archiwista.sources import SourceAdapter, SourceContext
from archiwista.sources.registry import check_package, source_error

PRODUCER = "obserwator"
PACKAGE = "obserwator"
# The Obserwator versions the adapter reads (PEP 440). Archiwista's own
# requirement on Obserwator is a commit or tag (REL-5.3), so it cannot hold
# the range.
SUPPORTED_VERSIONS = ">=3.0.0,<4"
# The contracts of the store: the marker, the sidecar and the series index
# (Obserwator ADR-007).
SCHEMAS = ("obserwator-store/1", "obserwator-meta/1", "obserwator-series/1")


def load(context: SourceContext) -> SourceAdapter:
    """Create the Obserwator adapter (``archiwista.sources`` entry point).

    Parameters
    ----------
    context : SourceContext
        Local resources of the plugin; the adapter keeps no cache.

    Returns
    -------
    SourceAdapter
        The adapter; it implements the source interface, the description of
        the segments its entries name and the current version of a slot.

    Raises
    ------
    SourceUnavailableError
        Obserwator is not installed.
    SourceIncompatibleError
        The installed Obserwator is outside ``SUPPORTED_VERSIONS``.
    """
    state = check_package(PRODUCER, PACKAGE, SUPPORTED_VERSIONS, SCHEMAS)
    if state.status != "available":
        raise source_error(state)
    from archiwista.adapter.obserwator.adapter import ObserwatorAdapter

    return ObserwatorAdapter(supported_versions=SUPPORTED_VERSIONS)
