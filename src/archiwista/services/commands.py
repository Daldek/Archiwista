"""Producers' commands as data for every interface (plan of 2026-10-25, A1).

``list_commands`` gathers the catalogs of the producers whose adapter offers
its commands (``ActionAdapter``); ``parse_command``, ``validate_command`` and
``format_command`` go to the adapter of the producer a request names. A
producer whose plugin is not available refuses its own commands only
(``SourceUnavailableError``, ``SourceIncompatibleError``), and one without
the capability refuses them as ``unsupported``.

``validate_command`` checks a command of the producer's catalog only. It names
the root of the configured store for a command that works on a store, never
the producer's default root (Decision 1 of the plan), and refuses an option of
the request that is a file path: the producer would open that file in this
process (SPEC 10.1). Nothing here uses the network or writes.

``version_command`` gives the call that selects a stored version again
(A-ADR-049 D-10, ``VersionCommandAdapter``) and its command line with the
store's root; ``version_calls`` asks the producer only for versions whose
answer of the installed producer the index does not keep (``version_calls``)
and keeps the new answers, a refusal ``command_not_rebuildable`` with its text.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from archiwista.auth import ProjectVisibility
from archiwista.config import AppSettings
from archiwista.errors import (
    CommandRequestError,
    NotFoundError,
    PathOutsideRootError,
    SourceStateError,
    UnsupportedError,
)
from archiwista.index import IndexQueries, IndexWriter, VersionCall
from archiwista.messages import message
from archiwista.sources import (
    ActionAdapter,
    CommandCall,
    CommandInfo,
    VersionCommandAdapter,
)
from archiwista.sources.registry import PluginRegistry

# The reason of a version whose call its producer cannot rebuild (A-ADR-049 D5).
NOT_REBUILDABLE = "command_not_rebuildable"
# The name of the store root beside the options of a call (``CommandCall.run``).
_ROOT = "root"


@dataclass(frozen=True, slots=True)
class VersionCommand:
    """The call that selects a stored version again, and its command line.

    ``line`` is the producer's line of the call with the store's root
    (``ActionAdapter.format``); ``None`` for a producer without commands.
    """

    call: CommandCall
    line: str | None


def list_commands(
    registry: PluginRegistry, *, producer: str | None = None
) -> tuple[CommandInfo, ...]:
    """Return the commands of the producers' catalogs.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins.
    producer : str or None, optional
        Only this producer's commands. Without it, those of every producer
        whose plugin is available and offers commands, in the order of the
        producer ids; the others are left out (``GET /sources`` says why).

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The plugin of ``producer`` is not available.
    UnsupportedError
        ``producer`` offers no commands.
    ProducerError
        The producer failed to describe its catalog.
    """
    if producer is not None:
        return actions(registry, producer).commands()
    found: list[CommandInfo] = []
    for name in registry.producers():
        try:
            adapter = registry.adapter(name)
        except SourceStateError:
            continue
        if isinstance(adapter, ActionAdapter):
            found.extend(adapter.commands())
    return tuple(found)


def parse_command(registry: PluginRegistry, producer: str, line: str) -> CommandCall:
    """Read a command line of ``producer`` into a call.

    Raises
    ------
    ProducerError
        The producer's parser refused the line (``validation_error``).
    SourceUnavailableError, SourceIncompatibleError, UnsupportedError
        As ``actions``.
    """
    return actions(registry, producer).parse(line)


def validate_command(
    registry: PluginRegistry,
    settings: AppSettings,
    call: CommandCall,
    *,
    store: str | None = None,
) -> CommandCall:
    """Check a call of a command of a producer's catalog without network.

    Parameters
    ----------
    registry : PluginRegistry
        Producer plugins.
    settings : AppSettings
        The configured stores.
    call : CommandCall
        The producer, the command and the options; ``run`` is not checked.
    store : str or None, optional
        Id of the configured store whose producer directory a command that
        works on a store (``CommandInfo.store``) is checked with; not used for
        another command.

    Returns
    -------
    CommandCall
        The call with the options as the producer reads them.

    Raises
    ------
    CommandRequestError
        The command is not in the producer's catalog (reason
        ``unknown_command``), or works on a store and ``store`` is missing
        (``store_required``) or has no directory of the producer
        (``store_without_producer``).
    NotFoundError
        ``store`` is not configured.
    PathOutsideRootError
        An option that is a file path is given (``details.option``).
    ProducerError
        The producer refused the call (``validation_error``, its text and
        ``details.option``).
    SourceUnavailableError, SourceIncompatibleError, UnsupportedError
        As ``actions``.
    """
    adapter = actions(registry, call.producer)
    return checked_call(
        adapter, settings, command_info(adapter, call), call, store=store
    )


def checked_call(
    adapter: ActionAdapter,
    settings: AppSettings,
    info: CommandInfo,
    call: CommandCall,
    *,
    store: str | None,
) -> CommandCall:
    """Check a call of the catalog's command ``info`` (``validate_command``).

    Raises
    ------
    PathOutsideRootError
        An option that is a file path is given (``details.option``).
    CommandRequestError, NotFoundError
        As ``store_root``, for a command that works on a store.
    ProducerError
        The producer refused the call.
    """
    refuse_path_options(info, call.options)
    root = store_root(settings, store, call) if info.store else None
    checked = adapter.validate(call.command, call.options, root=root)
    return CommandCall(call.producer, call.command, checked)


def refuse_path_options(info: CommandInfo, options: Mapping[str, object]) -> None:
    """Refuse an option of the command ``info`` that is a file path.

    The producer would open the file in this process (SPEC 10.1).

    Raises
    ------
    PathOutsideRootError
        An option with a ``path_role`` is given (``details.option``).
    """
    for option in info.options:
        if option.path_role is not None and option.name in options:
            raise PathOutsideRootError(
                message("command.path_option", option=option.name),
                hint=message("command.path_option_hint"),
                details={"option": option.name},
            )


def format_command(registry: PluginRegistry, call: CommandCall) -> str:
    """Return the producer's command line of a call; it reads back into the call.

    Raises
    ------
    ProducerError
        The producer refused the call (``validation_error``).
    SourceUnavailableError, SourceIncompatibleError, UnsupportedError
        As ``actions``.
    """
    return actions(registry, call.producer).format(call)


def actions(registry: PluginRegistry, producer: str) -> ActionAdapter:
    """Return the adapter of a producer that offers its commands.

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available (``missing_dependency``).
    UnsupportedError
        Its adapter offers no commands (reason ``no_commands``).
    """
    adapter = registry.adapter(producer)
    if not isinstance(adapter, ActionAdapter):
        raise UnsupportedError(
            message("command.no_commands", producer=producer), reason="no_commands"
        )
    return adapter


def command_info(adapter: ActionAdapter, call: CommandCall) -> CommandInfo:
    """Return the catalog's entry of the command a call names.

    Raises
    ------
    CommandRequestError
        The producer's catalog has no such command (reason
        ``unknown_command``, the catalog's commands in ``details.allowed``).
    """
    catalog = adapter.commands()
    for info in catalog:
        if info.command == call.command:
            return info
    raise CommandRequestError(
        message("command.unknown", producer=call.producer, command=call.command),
        reason="unknown_command",
        details={"option": "command", "allowed": [info.command for info in catalog]},
    )


def store_root(settings: AppSettings, store: str | None, call: CommandCall) -> Path:
    """Return the producer directory of the configured store a call names.

    Raises
    ------
    CommandRequestError
        ``store`` is ``None`` (reason ``store_required``) or has no directory
        of the call's producer (``store_without_producer``).
    NotFoundError
        ``store`` is not configured.
    """
    if store is None:
        raise CommandRequestError(
            message("command.store_required", command=call.command),
            reason="store_required",
            details={"option": "store"},
        )
    config = settings.store(store)
    if config is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    root = config.roots().get(call.producer)
    if root is None:
        raise CommandRequestError(
            message(
                "command.store_without_producer", store=store, producer=call.producer
            ),
            reason="store_without_producer",
            details={"option": "store"},
        )
    return root


def version_command(
    registry: PluginRegistry,
    settings: AppSettings,
    queries: IndexQueries,
    index_path: Path,
    store: str,
    version: str,
) -> VersionCommand:
    """Return the call of the indexed version ``version`` of ``store`` and its line.

    Offline: the answer the index keeps for the installed producer, else the
    producer's (``command_for_version``), which is kept.

    Raises
    ------
    NotFoundError
        ``store`` is not configured or the index has no such version.
    UnsupportedError
        The producer's adapter gives no calls of versions (reason
        ``no_commands``), or cannot rebuild this one (``command_not_rebuildable``,
        the producer's text).
    ProducerError
        The producer refused otherwise (a missing or invalid sidecar).
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available.
    """
    config = settings.store(store)
    if config is None:
        raise NotFoundError(message("api.store_not_configured", store=store))
    detail = queries.version(store, version, visible=ProjectVisibility())
    root = None if detail is None else config.roots().get(detail.segment.producer)
    if detail is None or root is None:
        raise NotFoundError(
            message("api.version_unknown", version=version, store=store)
        )
    producer = detail.segment.producer
    adapter = version_commands(registry, producer)
    with IndexWriter(index_path) as writer:
        answer = version_calls(
            adapter,
            registry.state(producer).package_version or "",
            queries,
            writer,
            store=store,
            root=root,
            paths=(version,),
        )[version]
    if answer.call is None:
        raise not_rebuildable(producer, version, answer.refusal or "")
    line = None
    if isinstance(adapter, ActionAdapter):
        rooted = replace(answer.call, run={**answer.call.run, _ROOT: str(root)})
        line = adapter.format(rooted)
    return VersionCommand(answer.call, line)


def version_commands(registry: PluginRegistry, producer: str) -> VersionCommandAdapter:
    """Return the adapter of a producer that gives the calls of stored versions.

    Raises
    ------
    SourceUnavailableError, SourceIncompatibleError
        The producer's plugin is not available (``missing_dependency``).
    UnsupportedError
        Its adapter gives no calls of versions (reason ``no_commands``).
    """
    adapter = registry.adapter(producer)
    if not isinstance(adapter, VersionCommandAdapter):
        raise UnsupportedError(
            message("command.no_commands", producer=producer), reason="no_commands"
        )
    return adapter


def version_calls(
    adapter: VersionCommandAdapter,
    producer_version: str,
    queries: IndexQueries,
    writer: IndexWriter,
    *,
    store: str,
    root: Path,
    paths: Collection[str],
) -> dict[str, VersionCall]:
    """Return the answer for the call of each version at ``paths`` of ``store``.

    The index's answers of ``producer_version`` stand; each other version is
    asked of the producer once (``command_for_version`` below ``root``, the
    store's producer directory) and its answer is kept: the call, or the
    producer's text of a ``command_not_rebuildable`` refusal. The answers
    asked before another refusal are kept all the same.

    Raises
    ------
    ProducerError, UnsupportedError
        The producer refused a version otherwise than ``command_not_rebuildable``.
    """
    known = queries.version_calls(store, paths, producer_version)
    asked: list[VersionCall] = []
    try:
        for path in sorted(set(paths) - known.keys()):
            try:
                call = adapter.command_for_version(path, root=root)
            except UnsupportedError as error:
                if error.details.get("reason") != NOT_REBUILDABLE:
                    raise
                asked.append(VersionCall(path, producer_version, refusal=error.message))
            else:
                asked.append(VersionCall(path, producer_version, call=call))
    finally:
        if asked:
            writer.write_version_calls(store, asked)
    return known | {answer.version_path: answer for answer in asked}


def not_rebuildable(producer: str, version: str, text: str) -> UnsupportedError:
    """Return the refusal of a version whose call the producer cannot rebuild."""
    return UnsupportedError(
        text,
        reason=NOT_REBUILDABLE,
        details={"producer": producer, "version": version},
        hint=message("fix.command_not_rebuildable"),
    )
