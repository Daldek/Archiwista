"""Read-only, producer-neutral source adapter interfaces.

A plugin is an entry point of the ``archiwista.sources`` group naming a
factory (``SourceFactory``) that receives a ``SourceContext`` and returns a
``SourceAdapter``. Segments, their parts, coordinate operations, link
confirmation and sheet grids are optional capabilities: a producer without
them still satisfies ``SourceAdapter``.
"""

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from archiwista.sources.types import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ScanScope,
    SheetGrid,
    SourceContext,
    SourceEntry,
    SourcePartition,
    SourceSegment,
    SourceState,
)

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

type FloatArray = NDArray[np.float64]


@runtime_checkable
class SourceAdapter(Protocol):
    """Expose producer store reads without revealing producer-specific APIs."""

    producer: str
    package: str
    supported_versions: str
    schemas: tuple[str, ...]

    def probe(self, root: Path) -> SourceState:
        """Report the producer and store contract state for a root."""
        ...

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Yield versions, links, full sheets, and problems for a scan."""
        ...

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Read metadata for one entry using only the producer's API."""
        ...

    def footprint(self, entry: SourceEntry, *, network: bool = False) -> Footprint:
        """Return a WGS84 geometry or an explicit missing-location reason.

        Without ``network`` no request leaves the process; unit outlines
        then come only from the adapter's local cache.
        """
        ...

    def read_project(self, path: Path) -> ProjectInfo:
        """Read an existing project without modifying its manifest."""
        ...

    def project_status(self, path: Path) -> ProjectInfo:
        """Read the current status of an existing project."""
        ...


type SourceFactory = Callable[[SourceContext], SourceAdapter]


@runtime_checkable
class SheetGridAdapter(Protocol):
    """Optional capability for producers with named geographic sheets."""

    def sheet_grid(
        self, area: tuple[float, float, float, float], system: str, scale: str
    ) -> SheetGrid:
        """Find sheets or report that sheet grids are unsupported."""
        ...


@runtime_checkable
class SegmentedAdapter(Protocol):
    """Optional capability: a store split into independently scanned segments."""

    def segments(self, root: Path) -> tuple[str, ...]:
        """List the segments; their scans together equal one unscoped scan."""
        ...

    def describe_segment(self, segment: str) -> SourceSegment:
        """Describe a segment: product, country, and a human-readable name."""
        ...


@runtime_checkable
class PartitionedAdapter(Protocol):
    """Optional capability: a segment read in disjoint parts, in parallel."""

    def partitions(
        self, root: Path, segment: str, known_versions: Mapping[str, tuple[str, ...]]
    ) -> tuple[SourcePartition, ...]:
        """Split a segment into parts whose scans together equal its scan.

        ``known_versions`` (as in ``ScanScope``) weighs the parts; a segment
        that is gone has none.
        """
        ...


class CoordinateTransformer(Protocol):
    """A pinned coordinate operation, safe to share between threads."""

    @property
    def description(self) -> str:
        """Name of the operation, e.g. for the provenance of a result."""
        ...

    @property
    def accuracy_m(self) -> float:
        """Declared accuracy of the operation in metres."""
        ...

    def transform(
        self, xs: FloatArray, ys: FloatArray
    ) -> tuple[FloatArray, FloatArray]:
        """Transform coordinates given and returned in x (east), y (north) order."""
        ...


@runtime_checkable
class GeoAdapter(Protocol):
    """Optional capability: the producer's coordinate operations and countries."""

    def transformer(self, src_crs: str, dst_crs: str) -> CoordinateTransformer:
        """Return the producer's pinned operation between two CRSs."""
        ...

    def countries(
        self, bbox_wgs84: tuple[float, float, float, float]
    ) -> tuple[str, ...]:
        """Return codes of the producer's countries intersecting a WGS84 box."""
        ...


@runtime_checkable
class LinkCheckAdapter(Protocol):
    """Optional capability: confirm on demand which version a link holds."""

    def confirm_link(self, entry: SourceEntry) -> Path | None:
        """Return the confirmed version path relative to the store, or ``None``."""
        ...
