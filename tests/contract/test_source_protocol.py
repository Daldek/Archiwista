"""Contract checks for third-party read-only source adapters."""

from collections.abc import Iterator
from pathlib import Path

from archiwista.sources import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ScanScope,
    SheetGridAdapter,
    SourceAdapter,
    SourceEntry,
    SourceState,
)


class MinimalSource:
    """A producer without any notion of sheets or Cartographer layout."""

    producer = "external"
    package = "external"
    supported_versions = ">=1,<2"
    schemas = ("external-meta/1",)

    def probe(self, root: Path) -> SourceState:
        """Report a readable store."""
        return SourceState(producer=self.producer, status="available")

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Expose an empty store."""
        return iter(())

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Read the producer's metadata."""
        return EntryMeta(
            producer=self.producer, store=entry.store, relative_path=entry.relative_path
        )

    def footprint(self, entry: SourceEntry) -> Footprint:
        """Report unavailable location instead of inventing coordinates."""
        return Footprint(location="none", reason="no_source")

    def read_project(self, path: Path) -> ProjectInfo:
        """Read the producer's existing project."""
        return ProjectInfo(producer=self.producer, store="demo", path=path, name="demo")

    def project_status(self, path: Path) -> ProjectInfo:
        """Read the existing project's status."""
        return self.read_project(path)


def test_source_protocol_does_not_require_a_sheet_grid() -> None:
    """Non-spatial producers can be registered without sheet support."""
    adapter = MinimalSource()

    assert isinstance(adapter, SourceAdapter)
    assert not isinstance(adapter, SheetGridAdapter)
