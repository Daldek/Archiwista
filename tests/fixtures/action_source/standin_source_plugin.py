"""Stand-in producer plugin of the action tests: commands called as IMGWTools'.

Tests register it the way production plugins are registered: they put this
directory, holding its ``*.dist-info/entry_points.txt``, on ``sys.path``. Its
producer (``standin_producer``) takes the store root as ``options["root"]``,
as IMGWTools does; the adapter keeps the root out of the producer-neutral
options, in ``CommandCall.run["root"]`` and in the ``root`` of ``validate``,
as the Kartograf adapter does with a producer that takes it by name beside
the options. Its availability takes the area, its countries and ``refresh``
among the options too, and so do its plan and its run of a call the store
root. Its store is the files a run fetched, ``<kind>/<station>/<file>``: each
file a version of its own slot, its station the unit a scan reads it by. A
plan is narrowed (``narrow``) by the ``file`` of its items.
"""

from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Literal, cast

import standin_producer  # type: ignore[import-not-found]

from archiwista.errors import ProducerError
from archiwista.messages import current_language
from archiwista.sources import (
    PLAN_TODO,
    ActionFile,
    ActionItem,
    ActionPlan,
    ActionProgress,
    ActionResult,
    AvailabilityNotice,
    AvailabilityReport,
    CommandCall,
    CommandChoice,
    CommandInfo,
    CommandOption,
    CommandWrites,
    EntryMeta,
    Footprint,
    GeoJSONGeometry,
    OptionType,
    PathRole,
    PlanEntry,
    PlanStatus,
    ProjectInfo,
    RunStatus,
    ScanScope,
    SourceAdapter,
    SourceContext,
    SourceEntry,
    SourceState,
)
from archiwista.sources.registry import check_package, source_error

PRODUCER = "standin"
PACKAGE = "standin-producer"
SUPPORTED_VERSIONS = ">=2,<3"
SCHEMAS = ("standin-meta/1",)
# The path role of the store root among the producer's options (DEV-19.1).
ROOT = "root"


class StandinAdapter:
    """Commands of the stand-in producer and the files its runs fetched."""

    producer = PRODUCER
    package = PACKAGE
    supported_versions = SUPPORTED_VERSIONS
    schemas: tuple[str, ...] = SCHEMAS

    def __init__(self, context: SourceContext) -> None:
        self.cache_dir = context.cache_dir

    def probe(self, root: Path) -> SourceState:
        """Accept an existing directory."""
        if root.is_dir():
            return SourceState(self.producer, "available", store=str(root))
        return SourceState(self.producer, "error", store=str(root))

    def iter_entries(
        self, root: Path, *, scope: ScanScope | None = None
    ) -> Iterator[SourceEntry]:
        """Yield each fetched file as a version; a scope's units are stations."""
        units = None if scope is None or scope.units is None else set(scope.units)
        for path in sorted(root.glob("*/*/*")):
            relative = path.relative_to(root)
            station = relative.parts[1]
            if not path.is_file() or (units is not None and station not in units):
                continue
            label = path.read_text(encoding="utf-8").strip().rpartition(",")[2]
            meta = EntryMeta(
                producer=self.producer,
                store=str(root),
                relative_path=relative,
                label=label,
                unit=station,
            )
            yield SourceEntry(
                producer=self.producer,
                store=str(root),
                relative_path=relative,
                kind="version",
                version_path=relative,
                meta=meta,
            )

    def read_meta(self, entry: SourceEntry) -> EntryMeta:
        """Describe an entry by its path only."""
        return EntryMeta(
            producer=self.producer, store=entry.store, relative_path=entry.relative_path
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

    def commands(self) -> tuple[CommandInfo, ...]:
        """Return the producer's catalog; the root is no option of a call."""
        polish = current_language() == "pl"
        return tuple(
            _info(name, standin_producer.command_schema(name), polish=polish)
            for name in standin_producer.list_commands()
        )

    def parse(self, line: str) -> CommandCall:
        """Read a line; its ``--root`` goes beside the options."""
        try:
            command, options = standin_producer.parse_command(line)
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error
        run = {ROOT: options.pop(ROOT)} if ROOT in options else {}
        return CommandCall(PRODUCER, str(command), options, run)

    def validate(
        self, command: str, options: Mapping[str, object], *, root: Path | None
    ) -> Mapping[str, object]:
        """Check a call, the store root as ``options["root"]`` of a store command."""
        given = dict(options)
        try:
            if _works_on_store(standin_producer.command_schema(command)):
                if root is None:
                    raise ValueError(f"{command} works on a store: give its root")
                given[ROOT] = str(root)
            checked = dict(standin_producer.validate_command(command, options=given))
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error
        checked.pop(ROOT, None)
        return cast(Mapping[str, object], checked)

    def format(self, call: CommandCall) -> str:
        """Return the producer's line; the root of ``run`` is its ``--root``."""
        given = dict(call.options)
        if ROOT in call.run:
            given[ROOT] = call.run[ROOT]
        try:
            return str(standin_producer.format_command(call.command, options=given))
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error

    def availability_products(self) -> tuple[str, ...]:
        """Return the products the producer reports the availability of."""
        return tuple(standin_producer.AVAILABILITY_PRODUCTS)

    def availability(
        self,
        product: str,
        *,
        area: GeoJSONGeometry,
        countries: tuple[str, ...],
        force: bool = False,
        on_notice: Callable[[AvailabilityNotice], None] | None = None,
    ) -> AvailabilityReport:
        """Ask the fake source; the area, countries and ``force`` are options."""

        def notice(level: Literal["info", "warning"], code: str, text: str) -> None:
            if on_notice is not None:
                on_notice(AvailabilityNotice(level, code, text))

        options = {"area": area, "countries": list(countries), "refresh": force}
        try:
            document = standin_producer.check_availability(
                product, options=options, on_notice=notice
            )
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error
        return AvailabilityReport.from_json({**document, "producer": PRODUCER})

    def check(
        self,
        command: str,
        options: Mapping[str, object],
        *,
        root: Path,
        on_notice: Callable[[AvailabilityNotice], None] | None = None,
    ) -> ActionPlan:
        """Plan a call of the fake source; the store root is ``options["root"]``."""

        def notice(level: Literal["info", "warning"], code: str, text: str) -> None:
            if on_notice is not None:
                on_notice(AvailabilityNotice(level, code, text))

        try:
            document = standin_producer.check_command(
                command, options={**options, ROOT: str(root)}, on_notice=notice
            )
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error
        return ActionPlan(
            producer=PRODUCER,
            command=command,
            schema=str(document["schema"]),
            root=str(document["root"]),
            checked_at=datetime.fromisoformat(str(document["checked_at"])),
            entries=tuple(_plan_entry(item) for item in document["items"]),
            notices=tuple(AvailabilityNotice(**item) for item in document["notices"]),
            document=document,
        )

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
        """Run a call; the store root is ``options["root"]``, a plan its document."""

        def notice(level: Literal["info", "warning"], code: str, text: str) -> None:
            if on_notice is not None:
                on_notice(AvailabilityNotice(level, code, text))

        def progress(current: int, total: int, unit: str, status: str) -> None:
            if on_progress is not None:
                on_progress(ActionProgress(current, total, unit, status))

        try:
            document = standin_producer.run_command(
                command,
                options={**options, ROOT: str(root)},
                plan=None if plan is None else dict(plan.document),
                on_progress=progress,
                on_notice=notice,
            )
        except standin_producer.ValidationError as error:
            raise _refusal(error) from error
        return ActionResult(
            producer=PRODUCER,
            command=command,
            root=str(document["root"]),
            status=cast(RunStatus, document["status"]),
            files=tuple(ActionFile(**item) for item in document["files"]),
            items=tuple(ActionItem(**item) for item in document["items"]),
            notices=tuple(AvailabilityNotice(**item) for item in document["notices"]),
            schema=str(document["schema"]),
        )

    def scope(self, path: str) -> ScanScope:
        """Return the station of a file ``<kind>/<station>/<file>``: its unit."""
        parts = PurePosixPath(path).parts
        if len(parts) != 3:
            raise ValueError(f"{path!r} is no file of a stand-in store")
        return ScanScope(units=(parts[1],))

    def narrow(self, plan: ActionPlan, paths: Collection[str]) -> ActionPlan:
        """Return the plan without the items to download whose ``file`` is not kept."""
        kept = frozenset(paths)

        def keeps(status: object, path: object) -> bool:
            return status not in PLAN_TODO or path in kept

        items = cast(list[dict[str, object]], plan.document["items"])
        return replace(
            plan,
            entries=tuple(e for e in plan.entries if keeps(e.status, e.path)),
            document={
                **plan.document,
                "items": [i for i in items if keeps(i["status"], i["file"])],
            },
        )


def _info(name: str, spec: dict[str, object], *, polish: bool) -> CommandInfo:
    """Return the producer-neutral description of one command."""
    options = cast(list[dict[str, object]], spec["options"])
    return CommandInfo(
        producer=PRODUCER,
        command=name,
        group=name.partition(" ")[0],
        summary=str(spec["summary_pl" if polish else "summary"]),
        description=str(spec["summary_pl" if polish else "summary"]),
        options=tuple(_option(option) for option in options if option["name"] != ROOT),
        read_only=spec["writes"] == "none",
        writes=cast(CommandWrites, spec["writes"]),
        network=bool(spec["network"]),
        check=bool(spec["check"]),
        store=_works_on_store(spec),
        examples=tuple(cast(list[str], spec["examples"])),
    )


def _option(option: dict[str, object]) -> CommandOption:
    """Return the producer-neutral description of one option."""
    choices = cast(list[str], option.get("enum", []))
    return CommandOption(
        name=str(option["name"]),
        type=cast(OptionType, option["type"]),
        required=bool(option["required"]),
        description=str(option["description"]),
        choices=tuple(CommandChoice(value, value) for value in choices),
        path_role=cast(PathRole | None, option.get("path_role")),
    )


def _works_on_store(spec: object) -> bool:
    """Whether a command takes the store root among its options."""
    options = cast(list[dict[str, object]], cast(dict[str, object], spec)["options"])
    return any(option.get("path_role") == ROOT for option in options)


def _plan_entry(item: dict[str, object]) -> PlanEntry:
    """Return the producer-neutral position of one item of the fake plan."""
    size = item["bytes"]
    return PlanEntry(
        path=str(item["file"]),
        unit=str(item["station"]),
        status=cast(PlanStatus, item["status"]),
        local_label=cast(str | None, item["local"]),
        available_label=cast(str | None, item["source"]),
        size_bytes=None if size is None else int(cast(int, size)),
        error=cast(str | None, item.get("error")),
    )


def _refusal(error: Exception) -> ProducerError:
    """Return the producer's refusal of a call as Archiwista's error."""
    option = getattr(error, "option", None)
    return ProducerError(
        PACKAGE,
        type(error).__name__,
        str(error),
        code=str(getattr(error, "code", "validation_error")),
        details={} if option is None else {"option": option},
    )


def load(context: SourceContext) -> SourceAdapter:
    """Create the adapter of an installed, supported stand-in producer."""
    state = check_package(PRODUCER, PACKAGE, SUPPORTED_VERSIONS, SCHEMAS)
    if state.status != "available":
        raise source_error(state)
    return StandinAdapter(context)
