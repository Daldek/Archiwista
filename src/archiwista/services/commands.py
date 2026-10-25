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
"""

from pathlib import Path

from archiwista.config import AppSettings
from archiwista.errors import (
    CommandRequestError,
    NotFoundError,
    PathOutsideRootError,
    SourceStateError,
    UnsupportedError,
)
from archiwista.messages import message
from archiwista.sources import ActionAdapter, CommandCall, CommandInfo
from archiwista.sources.registry import PluginRegistry


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
    for option in info.options:
        if option.path_role is not None and option.name in call.options:
            raise PathOutsideRootError(
                message("command.path_option", option=option.name),
                hint=message("command.path_option_hint"),
                details={"option": option.name},
            )
    root = store_root(settings, store, call) if info.store else None
    checked = adapter.validate(call.command, call.options, root=root)
    return CommandCall(call.producer, call.command, checked)


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
