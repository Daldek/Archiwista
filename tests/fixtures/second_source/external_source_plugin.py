"""Second producer plugin of the plugin tests; not a production IMGW source.

Tests register it the way production plugins are registered: they put this
directory, holding its ``*.dist-info/entry_points.txt``, on ``sys.path``. The
store is deliberately unlike Kartograf's: a flat directory of ``*.csv``
files without segments, sheets or links.
"""

from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import external_producer  # type: ignore[import-not-found]

from archiwista.sources import (
    EntryMeta,
    Footprint,
    ProjectInfo,
    ScanScope,
    SourceAdapter,
    SourceContext,
    SourceEntry,
    SourceState,
)
from archiwista.sources.registry import check_package, source_error

PRODUCER = "external"
PACKAGE = "external-producer"
SUPPORTED_VERSIONS = ">=1,<2"
SCHEMAS = ("external-meta/1",)


class ExternalAdapter:
    """Read a flat directory of ``*.csv`` files written by the producer."""

    producer = PRODUCER
    package = PACKAGE
    supported_versions = SUPPORTED_VERSIONS
    schemas: tuple[str, ...] = SCHEMAS

    def __init__(self, context: SourceContext) -> None:
        self.cache_dir = context.cache_dir

    def probe(self, root: Path) -> SourceState:
        """Accept an existing directory; fail loudly on a missing one.

        A directory named ``unmarked`` is refused with a reason and a hint.
        """
        if not root.is_dir():
            raise FileNotFoundError(root)
        if root.name == "unmarked":
            return SourceState(
                self.producer,
                "incompatible",
                store=str(root),
                detail="brak znacznika",
                reason="no_marker",
                hint=f"external init --root {root}",
            )
        return SourceState(self.producer, "available", store=str(root))

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Yield every ``*.csv`` file as an immutable version."""
        for path in sorted(root.glob("*.csv")):
            relative = path.relative_to(root)
            yield SourceEntry(
                producer=self.producer,
                store=str(root),
                relative_path=relative,
                kind="version",
                version_path=relative,
            )

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Describe a file by its name only."""
        return EntryMeta(
            producer=self.producer,
            store=entry.store,
            relative_path=entry.relative_path,
            label=entry.relative_path.stem,
        )

    def footprint(self, entry: SourceEntry, *, network: bool = False) -> Footprint:
        """Report that the producer has no location for its files."""
        return Footprint(location="none", reason="no_source")

    def read_project(self, path: Path) -> ProjectInfo:
        """Describe a project directory without a manifest."""
        return ProjectInfo(
            producer=self.producer, store=str(path), path=path, name=path.name
        )

    def project_status(self, path: Path) -> ProjectInfo:
        """Report the project as read."""
        return self.read_project(path)


def load(context: SourceContext) -> SourceAdapter:
    """Create the adapter, refusing a producer that writes another schema."""
    if external_producer.SCHEMA not in SCHEMAS:
        state = check_package(PRODUCER, PACKAGE, SUPPORTED_VERSIONS, SCHEMAS)
        detail = f"schemat {external_producer.SCHEMA} nie jest wspierany"
        raise source_error(replace(state, status="incompatible", detail=detail))
    return ExternalAdapter(context)


def load_failing(context: SourceContext) -> SourceAdapter:
    """Fail like a broken plugin."""
    raise RuntimeError("uszkodzona wtyczka")


def load_not_adapter(context: SourceContext) -> object:
    """Return something that is not a source adapter."""
    return object()
