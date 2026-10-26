"""Producer-neutral source adapter interfaces: reads, and commands as data.

A plugin is an entry point of the ``archiwista.sources`` group naming a
factory (``SourceFactory``) that receives a ``SourceContext`` and returns a
``SourceAdapter``. Segments (and the description of segments), the current
version of a slot, their parts, coordinate operations, link confirmation,
sheet grids, the default store root, the producer's commands with the
availability at the source and the changes of a project's manifest are
optional capabilities: a producer without them still satisfies
``SourceAdapter``.
"""

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from archiwista.sources.types import (
    ActionPlan,
    ActionProgress,
    ActionResult,
    AvailabilityNotice,
    AvailabilityReport,
    CommandCall,
    CommandInfo,
    DefaultRoot,
    EntryMeta,
    Footprint,
    GeoJSONGeometry,
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
class SegmentDescriptionAdapter(Protocol):
    """Optional capability: the producer describes the segments its entries carry.

    For a producer whose entries name a segment (a dataset, a product) but
    that cannot read one segment on its own: the scan describes each segment
    it met, and a job that asks for one segment of it is refused
    (``unsupported``). A ``SegmentedAdapter`` has it too.
    """

    def describe_segment(self, segment: str) -> SourceSegment:
        """Describe a segment: product, country, and a human-readable name."""
        ...


@runtime_checkable
class SegmentedAdapter(SegmentDescriptionAdapter, Protocol):
    """Optional capability: a store split into independently scanned segments."""

    def segments(self, root: Path) -> tuple[str, ...]:
        """List the segments; their scans together equal one unscoped scan."""
        ...


@runtime_checkable
class CurrentVersionAdapter(Protocol):
    """Optional capability: the producer names the current version of a slot.

    For a producer without links, whose slots carry its own key
    (``SourceEntry.slot_key``): which version of a slot is the current one is
    the producer's decision, taken by reading the slot's versions. The scan
    asks for the slots it touched, once at the end of a pass.
    """

    def current_version(self, root: Path, slot_key: str) -> Path | None:
        """Return the current version of a slot, relative to the store.

        ``None`` when the slot has no current version: it has no version, or
        one of its versions is broken (an older one is never chosen in its
        place).

        Raises
        ------
        SourceUnavailableError
            The system cannot read the store.
        ProducerError
            The producer rejected the store or the key.
        """
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

    def gdal_operation(self) -> str:
        """Return the same operation as a PROJ pipeline for GDAL.

        Passed as ``COORDINATE_OPERATION`` (e.g. to
        ``rasterio.warp.reproject``), it makes GDAL move pixels with exactly
        this operation instead of one GDAL would choose itself. GDAL hands
        coordinates over in the authoritative axis order of both CRSs, so
        the pipeline swaps the axes of a northing-first CRS.
        """
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


@runtime_checkable
class DefaultRootAdapter(Protocol):
    """Optional capability: the directory the producer uses when no store is named."""

    def default_root(self) -> DefaultRoot:
        """Return the producer's default store root and where it comes from.

        A report only: Archiwista names the store in every call, so it never
        uses this directory itself. The producer may read the whole directory
        to size it, so ask for an answer a person waits for, never on a poll.
        """
        ...


@runtime_checkable
class ActionAdapter(Protocol):
    """Optional capability: the producer's commands as data (SPEC 12.2 KB-1 to KB-5).

    The catalog, the reading of a command line, the check of a call and the
    command line of a call: what the forms, the plan window and an agent need
    before anything runs (plan of 2026-10-25, A1). None of them uses the
    network or writes. A call the producer refuses raises ``ProducerError`` with
    the producer's registry code, its text and hint, and the names it gives
    (``details.option``, ``details.options``, ``details.allowed``). The
    availability at the source (A2) and the plan of a run (A4) ask the network
    and write only the producer's metadata cache, which the adapter keeps in its
    ``cache_dir``; the run itself (A5) writes the store through the producer.
    """

    def commands(self) -> tuple[CommandInfo, ...]:
        """Return the producer's catalog in its order, texts in the call's language."""
        ...

    def parse(self, line: str) -> CommandCall:
        """Read a command line as the producer's own command line reads it."""
        ...

    def validate(
        self, command: str, options: Mapping[str, object], *, root: Path | None
    ) -> Mapping[str, object]:
        """Check a call without network and without writing.

        ``root`` is the store root of a command that works on a store
        (``CommandInfo.store``): the configured store's, given to the producer
        in the call; such a command with ``None`` is a program error
        (``ValueError``) and never reaches the producer, whose default root
        would stand in. A command on no store ignores it. Returns the options
        as the producer reads them.
        """
        ...

    def format(self, call: CommandCall) -> str:
        """Return the producer's command line of a call; ``parse`` reads it back."""
        ...

    def availability_products(self) -> tuple[str, ...]:
        """Return the products whose availability at the source it reports."""
        ...

    def availability(
        self,
        product: str,
        *,
        area: GeoJSONGeometry,
        countries: tuple[str, ...],
        force: bool = False,
        on_notice: Callable[[AvailabilityNotice], None] | None = None,
    ) -> AvailabilityReport:
        """Ask the source what it has for an area: years, variants, sheets.

        Uses the network (SPEC 6.3). ``area`` is the WGS84 polygon of the area
        and ``countries`` the countries it meets (``AreaRecord``); the adapter
        expresses them as its producer reads an area. The producer's metadata
        cache stands for its answers of the last days; ``force`` asks the
        source again. ``on_notice`` receives each notice when it is said.

        Raises
        ------
        ProducerError
            The producer refused the request (an unknown product, an area
            outside its countries) or the source failed.
        """
        ...

    def check(
        self,
        command: str,
        options: Mapping[str, object],
        *,
        root: Path,
        on_notice: Callable[[AvailabilityNotice], None] | None = None,
    ) -> ActionPlan:
        """Plan a run of a command on a store without its effects (SPEC 12.2 KB-5).

        The producer compares what the store at ``root`` holds with what the
        source has now: nothing is downloaded or written but the producer's
        metadata cache. ``root`` is the configured store's root, never the
        producer's default one; ``on_notice`` receives each notice when it is
        said. A position the source could not tell about is ``check_failed``,
        the others are planned all the same.

        Raises
        ------
        ProducerError
            The producer refused the call (an unknown command, an invalid
            option, a store it cannot write) or the whole check failed.
        UnsupportedError
            The command has no plan of a store (reason ``no_plan``).
        """
        ...

    def run(
        self,
        command: str,
        options: Mapping[str, object],
        *,
        root: Path,
        plan: ActionPlan | None = None,
        on_progress: Callable[[ActionProgress], None] | None = None,
        on_notice: Callable[[AvailabilityNotice], None] | None = None,
    ) -> ActionResult:
        """Run a command in the store at ``root`` (SPEC 12.2 KB-5).

        The producer writes the store: it publishes each version whole, so an
        interrupt (``KeyboardInterrupt``, which the run lets through) leaves no
        part of a version. ``root`` is the configured store's root, never the
        producer's default one, and the run writes no plain file. ``plan``, a
        plan ``check`` made of the same call, runs that plan: only its positions
        to download, and a position whose source changed since the plan fails
        as ``conflict`` with the reason ``stale_plan``. Without a plan the
        versions the store holds are kept. ``on_progress`` and ``on_notice``
        receive each event when it happens. A unit that fails is an item of
        the result, not an error.

        Raises
        ------
        ProducerError
            The producer refused the call (an unknown command, an invalid
            option or plan, a store it cannot write) or failed as a whole.
        BrokenContractError
            The producer reported a file outside the store, or a plain one
            (``written``, ``replaced``).
        """
        ...

    def scope(self, path: str) -> ScanScope:
        """Return what a scan reads to see the file at ``path`` again.

        ``path`` is a file's standard path below the store root (``/``-
        separated): the ``path`` of an ``ActionFile`` or a ``PlanEntry``.
        The scope names its segment and its one unit (``ScanScope.units``),
        so a scan of it reads that file's slot and nothing else.

        Raises
        ------
        ValueError
            ``path`` is not the place of a file of the producer's store.
        """
        ...


@runtime_checkable
class ProjectActionAdapter(Protocol):
    """Optional capability: change a project's manifest (SPEC 4.7, 9.2; ADR-039).

    Create a project bound to a store, add a task (a data command of the
    producer's catalog with its options) and remove one. Each call is the
    producer's own: it writes the manifest under the producer's lock and
    refuses what the producer's command line refuses, as ``ProducerError``
    with the producer's code, text and ``details.option``. None uses the
    network or writes the store; the store's files of a removed task stay.
    """

    def create_project(self, directory: Path, *, root: Path, relative: bool) -> None:
        """Create the project's manifest in ``directory`` for the store at ``root``.

        ``root`` is the configured store's directory, never the producer's
        default root. ``relative`` writes it relative to the project directory
        (a share mounted under other paths on other computers, SPEC 4.6 point
        7), else as the absolute path. A missing ``directory`` is created; a
        project that exists already is refused and left as it is.
        """
        ...

    def add_project_task(
        self,
        directory: Path,
        *,
        name: str,
        command: str,
        options: Mapping[str, object],
    ) -> None:
        """Add the task ``name``: ``command`` with ``options`` in their JSON form.

        Checked without the network, as the producer checks the command before
        its first request; nothing is downloaded.
        """
        ...

    def remove_project_task(self, directory: Path, *, name: str) -> None:
        """Remove the task ``name`` with its pins; its files stay in the store."""
        ...
