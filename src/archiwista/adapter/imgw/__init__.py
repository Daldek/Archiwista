"""IMGWTools source plugin: the only package that imports ``imgwtools``.

One plugin reads both providers of the package, IMGW-PIB and ČHMÚ: a store
of IMGWTools holds the files of both, so a dataset (``pl.imgw.hydro_daily``,
``cz.chmi.hydro_daily``) is what tells them apart. The factory compares the
installed IMGWTools with the range the adapter reads (``SUPPORTED_VERSIONS``)
before importing it, so a missing or unsupported package is a state of this
source (``not_installed``, ``incompatible``) and the others keep working.

The package never imports ``pyarrow``: reading a store needs no Parquet file,
only the JSON documents of its versions. Archiwista's requirement on IMGWTools
is the extra ``archiwista[imgw]`` (A-ADR-024).
"""

from archiwista.sources import SourceAdapter, SourceContext
from archiwista.sources.registry import check_package, source_error

PRODUCER = "imgw"
PACKAGE = "imgwtools"
# The IMGWTools versions the adapter reads (PEP 440). Archiwista's own
# requirement on IMGWTools is a commit or tag (REL-5.3), so it cannot hold
# the range.
SUPPORTED_VERSIONS = ">=3.0.0,<4"
# The contracts of the store: the marker, the sidecar, the series index and
# the project manifest (IMGWTools ADR-007).
SCHEMAS = ("imgw-store/1", "imgw-meta/1", "imgw-series/1", "imgw-project/1")


def load(context: SourceContext) -> SourceAdapter:
    """Create the IMGWTools adapter (``archiwista.sources`` entry point).

    Parameters
    ----------
    context : SourceContext
        Local resources of the plugin; the adapter keeps no cache.

    Returns
    -------
    SourceAdapter
        The adapter; it implements the source interface and no optional
        capability.

    Raises
    ------
    SourceUnavailableError
        IMGWTools is not installed.
    SourceIncompatibleError
        The installed IMGWTools is outside ``SUPPORTED_VERSIONS``.
    """
    state = check_package(PRODUCER, PACKAGE, SUPPORTED_VERSIONS, SCHEMAS)
    if state.status != "available":
        raise source_error(state)
    from archiwista.adapter.imgw.adapter import ImgwAdapter

    return ImgwAdapter(supported_versions=SUPPORTED_VERSIONS)
