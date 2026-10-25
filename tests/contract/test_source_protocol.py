"""Contract checks for third-party read-only source adapters."""

from collections.abc import Iterator
from pathlib import Path

from archiwista.sources import (
    DefaultRootAdapter,
    EntryMeta,
    Footprint,
    GeoAdapter,
    LinkCheckAdapter,
    PartitionedAdapter,
    ProjectInfo,
    ScanScope,
    SegmentedAdapter,
    SheetGridAdapter,
    SourceAdapter,
    SourceContext,
    SourceEntry,
    SourceFactory,
    SourceState,
)


class MinimalSource:
    """A producer without any notion of sheets or Cartographer layout."""

    producer = "external"
    package = "external"
    supported_versions = ">=1,<2"
    schemas: tuple[str, ...] = ("external-meta/1",)

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

    def footprint(self, entry: SourceEntry, *, network: bool = False) -> Footprint:
        """Report unavailable location instead of inventing coordinates."""
        return Footprint(location="none", reason="no_source")

    def read_project(self, path: Path) -> ProjectInfo:
        """Read the producer's existing project."""
        return ProjectInfo(producer=self.producer, store="demo", path=path, name="demo")

    def project_status(self, path: Path) -> ProjectInfo:
        """Read the existing project's status."""
        return self.read_project(path)


def load_minimal(context: SourceContext) -> SourceAdapter:
    """Plugin factory of the minimal producer."""
    return MinimalSource()


def test_source_protocol_does_not_require_optional_capabilities() -> None:
    """A producer without segments, CRSs, links or sheets is still a source."""
    factory: SourceFactory = load_minimal

    adapter = factory(SourceContext(cache_dir=Path("cache")))

    assert isinstance(adapter, SourceAdapter)
    for capability in (
        SegmentedAdapter,
        PartitionedAdapter,
        GeoAdapter,
        LinkCheckAdapter,
        DefaultRootAdapter,
        SheetGridAdapter,
    ):
        assert not isinstance(adapter, capability)
