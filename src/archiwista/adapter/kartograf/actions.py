"""Kartograf's commands as producer-neutral commands (``ActionAdapter``, SPEC 12.2).

``list_commands`` names every command of Kartograf's catalog in its order and
``command_schema`` describes each. The options of a call are the options of
the schema without what Kartograf takes by name beside them: the store root,
``output_dir`` and the flags of a run are keyword arguments of
``run_command`` and ``check_command``, and ``check`` chooses
``check_command``. ``parse_command``, ``validate_command`` and
``format_command`` read, check and write a call. A refusal keeps
Kartograf's own description of it (``error_report``): its registry code, its
text and hint in the language of the call, and the option it names. None of
this uses the network.
"""

import inspect
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from kartograf import (
    KartografError,
    check_command,
    command_schema,
    error_report,
    format_command,
    list_commands,
    parse_command,
    run_command,
    validate_command,
)

from archiwista.adapter.kartograf import PACKAGE, PRODUCER
from archiwista.errors import ProducerError
from archiwista.messages import current_language
from archiwista.sources import (
    CommandCall,
    CommandChoice,
    CommandInfo,
    CommandOption,
    CommandWrites,
    OptionType,
    PathRole,
)

# The names a call gives beside its options: the keyword arguments of
# ``run_command`` and ``check_command`` (the targets and the flags of a run),
# and ``check``, which chooses ``check_command``.
BESIDE_OPTIONS = frozenset(
    {
        name
        for function in (run_command, check_command)
        for name, parameter in inspect.signature(function).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
    }
    | {"check"}
)
# The ``path_role`` of the store root in Kartograf's schema (DEV-19.1).
_ROOT_ROLE = "root"
_PATH_ROLES: frozenset[str] = frozenset({"input", "output"})


def catalog() -> tuple[CommandInfo, ...]:
    """Return every command of Kartograf's catalog, in its order.

    The summary and the description are Polish when the call's language is
    Polish (``i18n.pl`` of the schema), else English; the descriptions of the
    options and the meanings of their values are Kartograf's English.

    Raises
    ------
    ProducerError
        Kartograf failed to describe its catalog.
    """
    polish = current_language() == "pl"
    try:
        entries = [
            command_schema(row.name).commands[0] for row in list_commands().commands
        ]
    except KartografError as error:
        raise call_error(error) from error
    return tuple(_command_info(entry, polish=polish) for entry in entries)


def parse(line: str) -> CommandCall:
    """Read a command line with the parser of ``kartograf`` (``parse_command``).

    Raises
    ------
    ProducerError
        A mistake of the line: an unknown command or flag, a value outside the
        choices of a flag, a flag without its value (``validation_error``).
    """
    try:
        call = parse_command(line)
    except KartografError as error:
        raise call_error(error) from error
    return CommandCall(PRODUCER, call.command, call.options, call.run)


def validate(
    command: str, options: Mapping[str, object], *, root: Path | None
) -> Mapping[str, object]:
    """Check a call with ``validate_command``, naming the store of a store command.

    Returns the options unchanged: Kartograf reads them as they are.

    Raises
    ------
    ProducerError
        Kartograf refused the call: an unknown command or option, a value of a
        wrong form or outside the allowed values, a broken rule among the
        options (``validation_error``, ``details.option`` or
        ``details.options``).
    ValueError
        A command that works on a store without its root: the default root of
        Kartograf would stand in, so the call never reaches Kartograf.
    """
    try:
        schema = command_schema(command)
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    store = _works_on_store(schema.commands[0])
    if store and root is None:
        raise ValueError(f"{command} works on a store: give its root")
    try:
        if store:
            validate_command(command, options, root=root)
        else:
            validate_command(command, options)
    except KartografError as error:
        raise call_error(error, command=command, given=options) from error
    return dict(options)


def format_line(call: CommandCall) -> str:
    """Return the canonical ``kartograf …`` line of a call (``format_command``).

    Raises
    ------
    ProducerError
        An unknown command, an option the command does not have, one in both
        the options and the flags of a run, or a value of a wrong form
        (``validation_error``).
    """
    try:
        return format_command(call.command, call.options, run=call.run)
    except KartografError as error:
        raise call_error(error, command=call.command, given=call.options) from error


def call_error(
    error: KartografError,
    *,
    command: str | None = None,
    given: Mapping[str, object] | None = None,
) -> ProducerError:
    """Return Kartograf's description of an error as the error of Archiwista.

    ``error_report`` gives Kartograf's registry code, its text and hint in the
    language of the call (the hint's example follows the command and the
    options given), and its details: what it names (``option``, ``options``,
    ``allowed``) and its own ``reason``.
    """
    report = error_report(error, command=command, given=given, lang=current_language())
    return ProducerError(
        PACKAGE,
        type(error).__name__,
        report.message,
        code=report.code,
        hint=report.hint,
        details=report.details,
    )


def _command_info(entry: Any, *, polish: bool) -> CommandInfo:
    """Convert one command of ``kartograf-commands/1``."""
    effects = entry.effects
    return CommandInfo(
        producer=PRODUCER,
        command=entry.name,
        group=entry.name.partition(" ")[0],
        summary=entry.i18n.pl.summary if polish else entry.summary,
        description=entry.i18n.pl.description if polish else entry.description,
        options=tuple(
            _option(option)
            for option in entry.options
            if option.name not in BESIDE_OPTIONS
        ),
        read_only=effects.read_only,
        writes=cast(CommandWrites, effects.writes),
        network=effects.network,
        check=entry.check is not None,
        store=_works_on_store(entry),
        examples=tuple(example.call for example in entry.examples),
    )


def _option(option: Any) -> CommandOption:
    """Convert one option of a command's schema."""
    role = option.path_role
    return CommandOption(
        name=option.name,
        type=cast(OptionType, option.type),
        required=option.required,
        description=option.description,
        choices=tuple(
            CommandChoice(choice.value, choice.meaning) for choice in option.enum or ()
        ),
        default=option.default,
        minimum=option.minimum,
        maximum=option.maximum,
        items=cast(OptionType | None, option.items),
        group=option.one_of,
        path_role=cast(PathRole, role) if role in _PATH_ROLES else None,
    )


def _works_on_store(entry: Any) -> bool:
    """Whether a command takes the store root (an option with that path role)."""
    return any(option.path_role == _ROOT_ROLE for option in entry.options)
