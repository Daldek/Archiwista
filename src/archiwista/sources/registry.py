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
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

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
from archiwista.messages import lookup, message, with_detail
from archiwista.sources.protocol import DefaultRootAdapter, SourceAdapter
from archiwista.sources.types import (
    DefaultRoot,
    SourceContext,
    SourceState,
    SourceStatus,
)

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "archiwista.sources"
APP_DISTRIBUTION = "archiwista"


class PluginRegistry(Protocol):
    """Producer plugins as the application reads them: states and adapters.

    ``SourceRegistry`` implements it; tests stand in small fakes. It extends
    the settings' ``SourceRegistryView`` (``states``, ``probe``) with the
    adapters that answer requests needing a producer.
    """

    def producers(self) -> tuple[str, ...]:
        """Return the registered producer ids."""
        ...

    def states(self) -> tuple[SourceState, ...]:
        """Return the state of every registered plugin, ordered by producer."""
        ...

    def state(self, producer: str) -> SourceState:
        """Return one plugin's state (``not_installed`` when unregistered)."""
        ...

    def adapter(self, producer: str) -> SourceAdapter:
        """Return an available plugin's adapter or raise ``SourceStateError``."""
        ...

    def probe(self, producer: str, root: Path) -> SourceState:
        """Probe a producer directory, or return the plugin's unavailable state."""
        ...


def app_requirement(package: str) -> Requirement | None:
    """Return Archiwista's own unconditional requirement on a package.

    Parameters
    ----------
    package : str
        Distribution name, e.g. ``"kartograf"``.

    Returns
    -------
    Requirement or None
        The requirement of the installed ``archiwista`` metadata: a direct
        reference to the producer's tag or commit while it has no release
        (REL-5.1, REL-5.3), a version range afterwards; ``None`` when
        Archiwista requires the package only through an extra or not at all.
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


def install_requirement(producer: str) -> str:
    """Return the pip requirement that installs a supported producer package.

    Parameters
    ----------
    producer : str
        Producer id, e.g. ``"kartograf"``.

    Returns
    -------
    str
        Archiwista's own dependency on a core producer, e.g.
        ``"kartograf@ git+https://github.com/Daldek/Kartograf@<commit>"``;
        otherwise the Archiwista extra named after the producer, e.g.
        ``"archiwista[imgw]"``.
    """
    requirement = app_requirement(producer)
    if requirement is not None:
        return str(requirement)
    return f"{APP_DISTRIBUTION}[{producer}]"


def source_fix(state: SourceState) -> str:
    """Return the instruction that makes an unavailable source work.

    Parameters
    ----------
    state : SourceState
        A state other than ``available``.

    Returns
    -------
    str
        Reinstalling the plugin for ``error``, otherwise installing a
        supported version of the producer package (``install_requirement``).
    """
    if state.status == "error":
        return message("fix.plugin_error", producer=state.producer)
    return message("fix.install", requirement=install_requirement(state.producer))


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
        detail = message("plugin.package_missing", package=package)
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
        unknown = message("doctor.unknown")
        text: str = message(
            "source.incompatible_producer",
            producer=state.producer,
            version=state.package_version or unknown,
            supported=state.supported_versions or unknown,
        )
        return SourceIncompatibleError(with_detail(text, state.detail), state=state)
    text = with_detail(
        message("source.unavailable_producer", producer=state.producer),
        lookup(f"source.status_{state.status}", ""),
    )
    return SourceUnavailableError(with_detail(text, state.detail), state=state)


def read_default_root(registry: PluginRegistry, producer: str) -> DefaultRoot | None:
    """Return a producer's default store root, ``None`` when it has none to report.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins.
    producer : str
        Producer id, e.g. ``"kartograf"``.

    Returns
    -------
    DefaultRoot or None
        What the adapter's ``default_root`` reports. ``None`` when the plugin is
        not available, its adapter has no such capability
        (``DefaultRootAdapter``) or reading it failed (logged): the root is an
        offer, so a faulty plugin must not stop the caller.
    """
    try:
        adapter = registry.adapter(producer)
    except SourceStateError:
        return None
    if not isinstance(adapter, DefaultRootAdapter):
        return None
    try:
        return adapter.default_root()
    except Exception:  # an offer only: a faulty plugin must not stop the caller
        logger.exception("Reading the default root of producer %s failed", producer)
        return None


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
            ``root`` (``status``, ``detail``, ``reason`` and ``hint``);
            ``error`` when the adapter's probe raised.
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
            reason=found.reason,
            hint=found.hint,
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
            detail = message("plugin.unregistered")
            return _Plugin(SourceState(producer, "not_installed", detail=detail))
        if len(points) > 1:
            values = ", ".join(sorted(point.value for point in points))
            detail = message("plugin.duplicate", values=values)
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
            detail = message("plugin.module_missing", module=error.name)
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
        detail = message("plugin.not_adapter")
        return _Plugin(SourceState(producer, "error", detail=detail))
    if adapter.producer != producer:
        detail = message("plugin.wrong_producer", declared=adapter.producer)
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
