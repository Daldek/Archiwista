"""Read-only, producer-neutral source adapter interfaces."""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from archiwista.sources.types import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ScanScope,
    SheetGrid,
    SourceEntry,
    SourceState,
)


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

    def footprint(self, entry: SourceEntry) -> Footprint:
        """Return a WGS84 geometry or an explicit missing-location reason."""
        ...

    def read_project(self, path: Path) -> ProjectInfo:
        """Read an existing project without modifying its manifest."""
        ...

    def project_status(self, path: Path) -> ProjectInfo:
        """Read the current status of an existing project."""
        ...


@runtime_checkable
class SheetGridAdapter(Protocol):
    """Optional capability for producers with named geographic sheets."""

    def sheet_grid(
        self, area: tuple[float, float, float, float], system: str, scale: str
    ) -> SheetGrid:
        """Find sheets or report that sheet grids are unsupported."""
        ...
