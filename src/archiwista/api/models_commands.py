"""Models of the producers' commands (plan of 2026-10-25, A1; SPEC 9.2; ADR-034).

``CommandList`` answers ``GET /commands`` and ``archiwista commands list``: the
commands of the producers' catalogs with their options, the summary and the
description in the language of the request. ``CommandCallItem`` is one call of
a command: the answer of ``POST /commands/parse`` and ``/validate`` and the
body of ``/format``, whose answer is ``CommandLine``, the producer's command
line of the call. The store root is never an option of a call: ``validate``
takes the id of a configured store (``ValidateRequest.store``), and the root a
pasted line names stays in ``run`` (ADR-034, decision 2). The request models
refuse unknown members (``400 validation_error``).
"""

from collections.abc import Iterable
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from archiwista.sources import (
    CommandCall,
    CommandChoice,
    CommandInfo,
    CommandOption,
    CommandWrites,
    OptionType,
    PathRole,
)

_PRODUCT_OPTION: dict[str, Any] = {
    "name": "product",
    "type": "string",
    "required": True,
    "description": "Product.",
    "choices": [
        {"value": "nmt", "meaning": "Digital terrain model (bare earth); PL and CZ."},
        {"value": "laz", "meaning": "LIDAR point cloud; PL and CZ."},
    ],
    "default": None,
    "minimum": None,
    "maximum": None,
    "items": None,
    "group": None,
    "path_role": None,
}
_GEOMETRY_OPTION: dict[str, Any] = {
    "name": "geometry",
    "type": "string",
    "required": False,
    "description": (
        "Vector file (SHP or GPKG): PL sheets and LAZ tiles that intersect its"
        " features. Give exactly one of `sheet`, `bbox`, `geometry`."
    ),
    "choices": [],
    "default": None,
    "minimum": None,
    "maximum": None,
    "items": None,
    "group": "area",
    "path_role": "input",
}
_OPTIONS: dict[str, Any] = {
    "product": "nmt",
    "sheet": "N-34-130-D-d-2-4",
    "resolution": "1m",
    "vertical_crs": "EVRF2007",
}
_LINE = (
    "kartograf elevation download --product nmt --sheet N-34-130-D-d-2-4"
    " --resolution 1m --vertical-crs EVRF2007 --root ./data"
)
_COMMAND_EXAMPLE: dict[str, Any] = {
    "producer": "kartograf",
    "command": "elevation download",
    "group": "elevation",
    "summary": (
        "Download NMT, NMPT, LAZ or contours as sheets, tiles or one WCS cutout"
    ),
    "description": (
        "Fetches the DTM (NMT), DSM (NMPT), LAZ point clouds or CZ contours of"
        " GUGiK (PL) and CUZK (CZ) into the versioned store. Never overwrites:"
        " new content is a new version."
    ),
    "options": [_PRODUCT_OPTION, _GEOMETRY_OPTION],
    "read_only": False,
    "writes": "add",
    "network": True,
    "check": True,
    "store": True,
    "examples": [_LINE],
}
_CALL_EXAMPLE: dict[str, Any] = {
    "producer": "kartograf",
    "command": "elevation download",
    "options": _OPTIONS,
    "run": {"root": "./data"},
}


class CommandChoiceItem(BaseModel):
    """A value an option allows, with what it means in the producer's words."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [_PRODUCT_OPTION["choices"][0]]}
    )

    value: str | int = Field(description="The value in the JSON form of a call.")
    meaning: str = Field(description="What it stands for.")

    @classmethod
    def of(cls, choice: CommandChoice) -> Self:
        """Return the model of a value of an option."""
        return cls(value=choice.value, meaning=choice.meaning)


class CommandOptionItem(BaseModel):
    """One option of a command, as a call gives it in `options`."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [_PRODUCT_OPTION, _GEOMETRY_OPTION]}
    )

    name: str = Field(description="Key of the option in `options`, snake_case.")
    type: OptionType = Field(description="JSON type of its value.")
    required: bool = Field(description="Whether a call without it is refused.")
    description: str = Field(
        description=(
            "What it is, in the producer's words: in the language of the request"
            " when the producer has it, else English."
        )
    )
    choices: list[CommandChoiceItem] = Field(
        description="The values it allows; empty when it takes any."
    )
    default: Any = Field(
        description=(
            "The JSON value the producer uses when a call leaves the option out;"
            " null for none."
        )
    )
    minimum: int | float | None = Field(description="Lower bound of a number.")
    maximum: int | float | None = Field(description="Upper bound of a number.")
    items: OptionType | None = Field(description="Type of the items of an `array`.")
    group: str | None = Field(
        description=(
            "Group of mutually exclusive options it belongs to (`area`: a sheet, a"
            " box or a geometry file); the description says whether one is required."
        )
    )
    path_role: PathRole | None = Field(
        description=(
            "`input` or `output`: its value is a file path the command reads or"
            " writes. `POST /commands/validate` refuses such an option (`403`,"
            " `path_outside_root`): the producer would open the path on the server."
        )
    )

    @classmethod
    def of(cls, option: CommandOption) -> Self:
        """Return the model of an option of a command."""
        return cls(
            name=option.name,
            type=option.type,
            required=option.required,
            description=option.description,
            choices=[CommandChoiceItem.of(choice) for choice in option.choices],
            default=option.default,
            minimum=option.minimum,
            maximum=option.maximum,
            items=option.items,
            group=option.group,
            path_role=option.path_role,
        )


class CommandItem(BaseModel):
    """A command of a producer's catalog: its options and what a run does."""

    model_config = ConfigDict(json_schema_extra={"examples": [_COMMAND_EXAMPLE]})

    producer: str = Field(description="Producer id (`GET /sources`).")
    command: str = Field(
        description="The producer's name of the command, `<group> <verb>`."
    )
    group: str = Field(description="Its group (`elevation`).")
    summary: str = Field(
        description=(
            "What it does, one sentence: in the language of the request when the"
            " producer has it, else English."
        )
    )
    description: str = Field(
        description="When to use it, when not and its main limit; the same language."
    )
    options: list[CommandOptionItem] = Field(
        description=(
            "The options of a call, in the producer's order. The store root and"
            " the flags of a run are none of them: a call names the store by its"
            " id (`store` of `POST /commands/validate`), and a line gives the"
            " flags beside the options (`run`)."
        )
    )
    read_only: bool = Field(
        description="A run changes nothing: no store, project or cache."
    )
    writes: CommandWrites = Field(
        description="What a run does to files: `none`, `add`, `replace` or `delete`."
    )
    network: bool = Field(description="A run uses the network.")
    check: bool = Field(
        description="The producer plans a run without effects (a check of the plan)."
    )
    store: bool = Field(
        description=(
            "The command works on a store: a call is checked with the directory of"
            " a configured store, never with a producer's default root."
        )
    )
    examples: list[str] = Field(
        description="Complete command lines of the producer (`POST /commands/parse`)."
    )

    @classmethod
    def of(cls, info: CommandInfo) -> Self:
        """Return the model of a command of a catalog."""
        return cls(
            producer=info.producer,
            command=info.command,
            group=info.group,
            summary=info.summary,
            description=info.description,
            options=[CommandOptionItem.of(option) for option in info.options],
            read_only=info.read_only,
            writes=info.writes,
            network=info.network,
            check=info.check,
            store=info.store,
            examples=list(info.examples),
        )


class CommandList(BaseModel):
    """Commands of the producers' catalogs, by producer id, each in its order."""

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"items": [_COMMAND_EXAMPLE]}]}
    )

    items: list[CommandItem] = Field(
        description=(
            "Without `producer`, the commands of every producer whose plugin is"
            " available and offers them; the others are left out (`GET /sources`"
            " says why)."
        )
    )

    @classmethod
    def of(cls, infos: Iterable[CommandInfo]) -> Self:
        """Return the model of the commands of catalogs."""
        return cls(items=[CommandItem.of(info) for info in infos])


class CommandsQuery(BaseModel):
    """The producer of `GET /commands`."""

    model_config = ConfigDict(extra="forbid")

    producer: str | None = Field(
        default=None,
        description=(
            "Only this producer's commands: one whose plugin is not available"
            " answers `503`, one that offers no commands `422 unsupported`."
        ),
    )


class CommandCallItem(BaseModel):
    """A call of a producer's command: its options and what goes beside them."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [_CALL_EXAMPLE]}
    )

    producer: str = Field(description="Producer id.")
    command: str = Field(description="Command of the producer's catalog.")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The options in the JSON form of the catalog (`options` of `GET"
            " /commands`): a box as four numbers, a list as a list."
        ),
    )
    run: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "What a command line gives beside the options: the store root and the"
            " flags of a run, by the names of the data-output convention where it"
            " has them (`root`, `output_dir`, `check`, `force`, `upgrade`, `plan`)"
            " and by the producer's otherwise. Empty in the answer of `validate`."
        ),
    )

    @classmethod
    def of(cls, call: CommandCall) -> Self:
        """Return the model of a call."""
        return cls(
            producer=call.producer,
            command=call.command,
            options=dict(call.options),
            run=dict(call.run),
        )

    def call(self) -> CommandCall:
        """Return the call this model describes."""
        return CommandCall(self.producer, self.command, self.options, self.run)


class ParseRequest(BaseModel):
    """A command line of a producer to read into a call (`POST /commands/parse`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"producer": "kartograf", "line": _LINE}]},
    )

    producer: str = Field(description="Producer id.")
    line: str = Field(description="The command line, as a person pastes it.")


class ValidateRequest(BaseModel):
    """A call to check without the network (`POST /commands/validate`)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "producer": "kartograf",
                    "command": "elevation download",
                    "options": _OPTIONS,
                    "store": "zespol",
                }
            ]
        },
    )

    producer: str = Field(description="Producer id.")
    command: str = Field(description="Command of the producer's catalog.")
    options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The options in the JSON form of the catalog; no option that is a file"
            " path (`path_role`)."
        ),
    )
    store: str | None = Field(
        default=None,
        description=(
            "Id of the configured store whose directory of the producer a command"
            " that works on a store (`store` of `GET /commands`) is checked with;"
            " not used for another command."
        ),
    )

    def call(self) -> CommandCall:
        """Return the call to check."""
        return CommandCall(self.producer, self.command, self.options)


class CommandLine(BaseModel):
    """The producer's command line of a call (`POST /commands/format`)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "producer": "kartograf",
                    "command": "elevation download",
                    "line": _LINE,
                }
            ]
        }
    )

    producer: str = Field(description="Producer id.")
    command: str = Field(description="Command of the producer's catalog.")
    line: str = Field(
        description=(
            "The canonical line of the call, which `POST /commands/parse` reads"
            " back into the same call."
        )
    )

    @classmethod
    def of(cls, call: CommandCall, line: str) -> Self:
        """Return the model of the command line of a call."""
        return cls(producer=call.producer, command=call.command, line=line)


class VersionCommand(BaseModel):
    """The call that selects a stored version again (A-ADR-049 D-10)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "producer": "kartograf",
                    "command": "elevation download",
                    "options": {**_OPTIONS, "year": 2022, "all_campaigns": True},
                    "line": (
                        "kartograf elevation download --product nmt --sheet"
                        " N-34-130-D-d-2-4 --resolution 1m --vertical-crs EVRF2007"
                        " --year 2022 --all-campaigns --root /mnt/nas/kartograf"
                    ),
                }
            ]
        }
    )

    producer: str = Field(description="Producer id.")
    command: str = Field(description="Command of the producer's catalog.")
    options: dict[str, Any] = Field(
        description=(
            "Its options in the JSON form of the producer's catalog, with every"
            " option that chooses the version pinned; never the store root."
        )
    )
    line: str | None = Field(
        description=(
            "The producer's command line of the call in the store's producer"
            " directory; null for a producer without commands."
        )
    )

    @classmethod
    def of(cls, call: CommandCall, line: str | None) -> Self:
        """Return the model of a version's call and its line."""
        return cls(
            producer=call.producer,
            command=call.command,
            options=dict(call.options),
            line=line,
        )
