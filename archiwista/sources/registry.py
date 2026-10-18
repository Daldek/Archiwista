"""Producer plugin registry: lazy entry points with explicit source states.

Plugins are entry points of the ``archiwista.sources`` group, found in the
installed distribution metadata (``*.dist-info/entry_points.txt``). A plugin
is imported and its factory called only when its state or adapter is first
needed, one plugin at a time. A missing producer package, an unsupported
version or schema, or any error while loading becomes that plugin's
``SourceState`` instead of an exception, so a faulty plugin never stops the
process and the other plugins keep working.
"""

import importlib.metadata
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from archiwista.config import AppPaths
from archiwista.errors import (
    SourceIncompatibleError,
    SourceStateError,
    SourceUnavailableError,
)
from archiwista.messages import MESSAGES, with_detail
from archiwista.sources.protocol import SourceAdapter
from archiwista.sources.types import SourceContext, SourceState, SourceStatus

ENTRY_POINT_GROUP = "archiwista.sources"
APP_DISTRIBUTION = "archiwista"


def app_requirement(package: str) -> Requirement | None:
    """Return Archiwista's own unconditional requirement on a package.

    Parameters
    ----------
    package : str
        Distribution name, e.g. ``"kartograf"``.

    Returns
    -------
    Requirement or None
        The requirement of the installed ``archiwista`` metadata, e.g.
        ``kartograf<0.9,>=0.8.0``; ``None`` when Archiwista requires the
        package only through an extra or not at all.
    """
    try:
        lines = importlib.metadata.requires(APP_DISTRIBUTION) or []
    except importlib.metadata.PackageNotFoundError:
        return None
    wanted = canonicalize_name(package)
    for line in lines:
        requirement = Requirement(line)
        if requirement.marker is None and canonicalize_name(requirement.name) == wanted:
            return requirement
    return None


def check_package(
    producer: str, package: str, supported_versions: str, schemas: tuple[str, ...]
) -> SourceState:
    """Compare the installed producer package with a plugin's supported range.

    Parameters
    ----------
    producer : str
        Producer id reported in the state.
    package : str
        Distribution of the producer library, e.g. ``"kartograf"``.
    supported_versions : str
        PEP 440 range, e.g. ``">=0.8.0,<0.9"``.
    schemas : tuple[str, ...]
        Schemas the plugin reads, reported in the state.

    Returns
    -------
    SourceState
        ``available``; ``not_installed`` without a distribution of
        ``package``; ``incompatible`` for an installed version outside the
        range; ``error`` for a malformed range or version.
    """
    state = SourceState(
        producer,
        "available",
        supported_versions=supported_versions,
        schemas=schemas,
    )
    try:
        installed = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        detail = MESSAGES["plugin_package_missing"].format(package=package)
        return replace(state, status="not_installed", detail=detail)
    state = replace(state, package_version=installed)
    try:
        supported = SpecifierSet(supported_versions).contains(
            Version(installed), prereleases=True
        )
    except (InvalidSpecifier, InvalidVersion) as error:
        return replace(state, status="error", detail=str(error))
    return state if supported else replace(state, status="incompatible")


def source_error(state: SourceState) -> SourceStateError:
    """Return the error that reports a source which is not available.

    Parameters
    ----------
    state : SourceState
        A state other than ``available``.

    Returns
    -------
    SourceStateError
        ``SourceIncompatibleError`` for ``incompatible``, otherwise
        ``SourceUnavailableError``; both carry ``state``.
    """
    if state.status == "incompatible":
        unknown = MESSAGES["doctor_unknown"]
        message = MESSAGES["source_incompatible_producer"].format(
            producer=state.producer,
            version=state.package_version or unknown,
            supported=state.supported_versions or unknown,
        )
        return SourceIncompatibleError(with_detail(message, state.detail), state=state)
    message = with_detail(
        MESSAGES["source_unavailable_producer"].format(producer=state.producer),
        MESSAGES.get(f"source_status_{state.status}"),
    )
    return SourceUnavailableError(with_detail(message, state.detail), state=state)


@dataclass(frozen=True, slots=True)
class _Plugin:
    state: SourceState
    adapter: SourceAdapter | None = None


class SourceRegistry:
    """Producer plugins registered in the ``archiwista.sources`` entry points.

    Parameters
    ----------
    entry_points : Iterable[importlib.metadata.EntryPoint]
        Plugin entry points; their names are producer ids and their values
        name a factory ``load(context: SourceContext) -> SourceAdapter``.
    cache_dir : Path
        Local cache root; each plugin owns ``cache_dir / <producer>``.

    Notes
    -----
    Thread-safe: a plugin is loaded once, under a lock, on first use.
    """

    def __init__(
        self,
        entry_points: Iterable[importlib.metadata.EntryPoint],
        *,
        cache_dir: Path,
    ) -> None:
        grouped: dict[str, list[importlib.metadata.EntryPoint]] = {}
        for point in entry_points:
            grouped.setdefault(point.name, []).append(point)
        self._points = grouped
        self._cache_dir = cache_dir
        self._plugins: dict[str, _Plugin] = {}
        self._lock = threading.Lock()

    def producers(self) -> tuple[str, ...]:
        """Return the registered producer ids without loading any plugin."""
        return tuple(sorted(self._points))

    def states(self) -> tuple[SourceState, ...]:
        """Return the state of every registered plugin, ordered by producer."""
        return tuple(self.state(producer) for producer in self.producers())

    def state(self, producer: str) -> SourceState:
        """Return one plugin's state, loading the plugin on first use.

        An unregistered producer is ``not_installed``.
        """
        return self._plugin(producer).state

    def adapter(self, producer: str) -> SourceAdapter:
        """Return the adapter of an available plugin.

        Parameters
        ----------
        producer : str
            Producer id, e.g. ``"kartograf"``.

        Returns
        -------
        SourceAdapter
            The plugin's adapter, created once.

        Raises
        ------
        SourceUnavailableError
            The plugin is not registered, its producer package is missing,
            or loading it failed.
        SourceIncompatibleError
            The installed producer version or schema is unsupported.
        """
        plugin = self._plugin(producer)
        if plugin.adapter is None:
            raise source_error(plugin.state)
        return plugin.adapter

    def probe(self, producer: str, root: Path) -> SourceState:
        """Probe a producer directory, or return the plugin's unavailable state.

        Parameters
        ----------
        producer : str
            Producer id.
        root : Path
            The producer directory of a store.

        Returns
        -------
        SourceState
            The plugin's versions and schemas with the adapter's verdict on
            ``root``; ``error`` when the adapter's probe raised.
        """
        plugin = self._plugin(producer)
        store = str(root)
        if plugin.adapter is None:
            return replace(plugin.state, store=store)
        try:
            found = plugin.adapter.probe(root)
        except Exception as error:  # a faulty plugin must not stop the caller
            return replace(
                plugin.state, status="error", store=store, detail=_describe(error)
            )
        return replace(
            plugin.state,
            status=found.status,
            store=found.store or store,
            detail=found.detail,
        )

    def _plugin(self, producer: str) -> _Plugin:
        with self._lock:
            plugin = self._plugins.get(producer)
            if plugin is None:
                plugin = self._plugins[producer] = self._load(producer)
            return plugin

    def _load(self, producer: str) -> _Plugin:
        points = self._points.get(producer, [])
        if not points:
            detail = MESSAGES["plugin_unregistered"]
            return _Plugin(SourceState(producer, "not_installed", detail=detail))
        if len(points) > 1:
            values = ", ".join(sorted(point.value for point in points))
            detail = MESSAGES["plugin_duplicate"].format(values=values)
            return _Plugin(SourceState(producer, "error", detail=detail))
        point = points[0]
        context = SourceContext(cache_dir=self._cache_dir / producer)
        try:
            adapter = point.load()(context)
        except SourceStateError as error:
            return _Plugin(_failed_state(producer, error))
        except ModuleNotFoundError as error:
            if error.name is None or _within(error.name, point.module):
                return _Plugin(SourceState(producer, "error", detail=_describe(error)))
            detail = MESSAGES["plugin_module_missing"].format(module=error.name)
            return _Plugin(SourceState(producer, "not_installed", detail=detail))
        except Exception as error:  # a faulty plugin must not stop the process
            return _Plugin(SourceState(producer, "error", detail=_describe(error)))
        return _checked(producer, adapter)


def load_registry(*, cache_dir: Path | None = None) -> SourceRegistry:
    """Discover the installed producer plugins without loading them.

    Parameters
    ----------
    cache_dir : Path or None, optional
        Local cache root, by default ``<user_data_dir>/cache``.

    Returns
    -------
    SourceRegistry
        Registry of the ``archiwista.sources`` entry points.
    """
    points = importlib.metadata.entry_points(group=ENTRY_POINT_GROUP)
    return SourceRegistry(points, cache_dir=cache_dir or AppPaths.default().cache_dir)


def _checked(producer: str, adapter: object) -> _Plugin:
    """Accept a factory's result only as an adapter of this producer."""
    if not isinstance(adapter, SourceAdapter):
        detail = MESSAGES["plugin_not_adapter"]
        return _Plugin(SourceState(producer, "error", detail=detail))
    if adapter.producer != producer:
        detail = MESSAGES["plugin_wrong_producer"].format(declared=adapter.producer)
        return _Plugin(SourceState(producer, "error", detail=detail))
    state = check_package(
        producer, adapter.package, adapter.supported_versions, tuple(adapter.schemas)
    )
    return _Plugin(state, adapter if state.status == "available" else None)


def _failed_state(producer: str, error: SourceStateError) -> SourceState:
    """Return the state a factory reported by raising, under the registered name."""
    if error.state is not None:
        return replace(error.state, producer=producer)
    status: SourceStatus = (
        "incompatible"
        if isinstance(error, SourceIncompatibleError)
        else "not_installed"
    )
    return SourceState(producer, status, detail=str(error))


def _within(module: str, plugin_module: str) -> bool:
    """Whether a missing module belongs to the plugin's own top-level package."""
    return module.partition(".")[0] == plugin_module.partition(".")[0]


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"
