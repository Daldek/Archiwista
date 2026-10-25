"""Fake producer library of the action tests, called the way IMGWTools is.

Its catalog (``list_commands``, ``command_schema``) has two commands. A command
that works on a store takes the store root as an option of the call,
``options["root"]`` (path role ``root``), as IMGWTools does, where Kartograf
takes it by name beside the options. ``validate_command`` returns the options
as the library reads them (texts trimmed, a value of a choice in lower case),
``format_command`` writes the canonical line of a call and ``parse_command``
reads a line back. Each of these three appends its call to ``CALLS`` with the
options it received, so a test can tell what Archiwista passed.
"""

import shlex
from collections.abc import Mapping

__version__ = "2.0.0"
PROGRAM = "standin"

CALLS: list[tuple[str, str, dict[str, object]]] = []

_COMMANDS: dict[str, dict[str, object]] = {
    "series fetch": {
        "summary": "Fetch the daily series of one station into the store.",
        "summary_pl": "Pobierz serię dobową jednej stacji do magazynu.",
        "writes": "add",
        "network": True,
        "check": True,
        "options": [
            {
                "name": "station",
                "type": "string",
                "required": True,
                "description": "Station code.",
            },
            {
                "name": "kind",
                "type": "string",
                "required": False,
                "enum": ["hydro", "meteo"],
                "description": "Kind of the station.",
            },
            {
                "name": "area",
                "type": "string",
                "required": False,
                "path_role": "input",
                "description": "Vector file of the area whose stations are fetched.",
            },
            {
                "name": "root",
                "type": "string",
                "required": True,
                "path_role": "root",
                "description": "Store root.",
            },
        ],
        "examples": [
            "standin series fetch --station 150160180 --kind hydro --root /data/standin"
        ],
    },
    "stations list": {
        "summary": "List the stations of one kind.",
        "summary_pl": "Wypisz stacje jednego rodzaju.",
        "writes": "none",
        "network": False,
        "check": False,
        "options": [
            {
                "name": "kind",
                "type": "string",
                "required": True,
                "enum": ["hydro", "meteo"],
                "description": "Kind of the stations.",
            }
        ],
        "examples": ["standin stations list --kind meteo"],
    },
}


class ValidationError(Exception):
    """A call the library refuses; ``option`` names the option at fault."""

    code = "validation_error"

    def __init__(self, message: str, *, option: str | None = None) -> None:
        super().__init__(message)
        self.option = option


def list_commands() -> list[str]:
    """Return the names of the commands, in the order of the catalog."""
    return list(_COMMANDS)


def command_schema(command: str) -> dict[str, object]:
    """Return the description of one command."""
    if command not in _COMMANDS:
        raise ValidationError(f"unknown command {command!r}", option="command")
    return _COMMANDS[command]


def validate_command(
    command: str, /, *, options: Mapping[str, object]
) -> dict[str, object]:
    """Check a call; return its options as the library reads them."""
    CALLS.append(("validate_command", command, dict(options)))
    return _checked(command, options)


def format_command(command: str, /, *, options: Mapping[str, object]) -> str:
    """Return the canonical line of a call: its options in the catalog's order."""
    CALLS.append(("format_command", command, dict(options)))
    checked = _checked(command, options)
    words = [PROGRAM, *command.split()]
    for name, value in checked.items():
        words += [f"--{name.replace('_', '-')}", str(value)]
    return shlex.join(words)


def parse_command(line: str) -> tuple[str, dict[str, object]]:
    """Read a command line into its command and its options (texts)."""
    CALLS.append(("parse_command", line, {}))
    words = shlex.split(line)
    if words[:1] == [PROGRAM]:
        del words[0]
    command = " ".join(words[:2])
    command_schema(command)
    options: dict[str, object] = {}
    flags = words[2:]
    while flags:
        flag = flags.pop(0)
        if not flag.startswith("--") or not flags:
            raise ValidationError(f"expected --<option> <value>, got {flag!r}")
        options[flag[2:].replace("-", "_")] = flags.pop(0)
    return command, options


def _checked(command: str, options: Mapping[str, object]) -> dict[str, object]:
    """Return the options of a valid call in the catalog's order, normalised."""
    declared = {
        str(option["name"]): option
        for option in _options(command_schema(command)["options"])
    }
    for name in options:
        if name not in declared:
            raise ValidationError(f"unknown option {name!r}", option=name)
    checked: dict[str, object] = {}
    for name, option in declared.items():
        if name not in options:
            if option["required"]:
                raise ValidationError(f"option {name!r} is required", option=name)
            continue
        value = str(options[name]).strip()
        allowed = option.get("enum")
        if isinstance(allowed, list):
            value = value.lower()
            if value not in allowed:
                raise ValidationError(
                    f"{name} is one of {', '.join(allowed)}, not {value!r}", option=name
                )
        checked[name] = value
    return checked


def _options(value: object) -> list[dict[str, object]]:
    """Return the option entries of a command's description."""
    assert isinstance(value, list)
    return value
