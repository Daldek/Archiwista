"""The producers' commands over HTTP (plan of 2026-10-25, A1; SPEC 9.2; ADR-034).

``GET /commands`` lists the commands of the producers' catalogs, ``POST
/commands/parse`` reads a pasted command line into a call, ``POST
/commands/validate`` checks a call without the network, ``POST
/commands/format`` writes the producer's command line of a call and ``POST
/commands/area`` gives a call an area of Archiwista (A-ADR-049 erratum 5). The
routes translate only: ``archiwista.services.commands`` does the work, and
``archiwista commands`` calls the same functions. A session is all they need:
nothing here uses the network, and only ``area`` writes, the area's GeoJSON in
Archiwista's data.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from archiwista.api.dependencies import (
    app_paths,
    index_queries,
    plugin_registry,
    settings_service,
)
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.models_commands import (
    AreaRequest,
    CommandAreaItem,
    CommandCallItem,
    CommandLine,
    CommandList,
    CommandsQuery,
    ParseRequest,
    ValidateRequest,
)
from archiwista.auth import Principal
from archiwista.config import AppPaths, SettingsService
from archiwista.index import IndexQueries
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import commands as command_service
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["commands"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]
_Paths = Annotated[AppPaths, Depends(app_paths)]
_Queries = Annotated[IndexQueries, Depends(index_queries)]


def _responses(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """Return a route's problems, with the ``422`` of a producer without commands."""
    responses = problem_responses(*statuses)
    responses[422] = {
        "description": (
            "`unsupported` (reason `no_commands`): the producer's plugin offers no"
            " commands."
        ),
        "content": {
            PROBLEM_MEDIA_TYPE: {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"},
                "example": problem_example(
                    "unsupported",
                    message("command.no_commands", "en", producer="imgw"),
                    reason="no_commands",
                ),
            }
        },
    }
    return responses


def _area_responses() -> dict[int | str, dict[str, Any]]:
    """Return the problems of ``POST /commands/area``: the ``422`` of no area too."""
    responses = _responses(400, 404, 503)
    responses[422]["description"] = (
        "`unsupported`: the producer's plugin offers no commands (reason"
        " `no_commands`) or takes no area of Archiwista (`no_area_commands`), or"
        " the command takes no area (`no_area_option`)."
    )
    responses[422]["content"][PROBLEM_MEDIA_TYPE]["example"] = problem_example(
        "unsupported",
        message("command.no_area_option", "en", command="store overview"),
        reason="no_area_option",
    )
    return responses


@router.get("/commands", response_model=CommandList, responses=_responses(400, 503))
def list_commands(
    query: Annotated[CommandsQuery, Query()],
    principal: _Principal,
    registry: _Registry,
) -> CommandList:
    """List the commands of the producers' catalogs with their options.

    Without `producer`, the commands of every producer whose plugin is
    available and offers commands, by producer id and each in the producer's
    order; the others are left out (`GET /sources` says why). With it, only
    that producer's: one whose plugin is not available answers `503`
    (`source_unavailable`, `details.source` and the fix), one that offers no
    commands `422 unsupported`. The summaries and descriptions are in the
    language of `Accept-Language` when the producer has it. Nothing here uses
    the network.
    """
    found = command_service.list_commands(registry, producer=query.producer)
    return CommandList.of(found)


@router.post(
    "/commands/parse", response_model=CommandCallItem, responses=_responses(400, 503)
)
def parse_command(
    body: ParseRequest, principal: _Principal, registry: _Registry
) -> CommandCallItem:
    """Read a pasted command line of a producer into a call.

    The answer has the command, its `options` in the JSON form of the catalog
    and `run`: what the line gives beside the options (`root`, `check`,
    `force`, ...). The producer's parser decides: a mistake of the line is
    `400 validation_error` with the producer's own text and hint, the option
    in `details.option` and `details.reason` `kartograf_error` for Kartograf.
    Nothing is checked against a store.
    """
    call = command_service.parse_command(registry, body.producer, body.line)
    return CommandCallItem.of(call)


@router.post(
    "/commands/validate",
    response_model=CommandCallItem,
    responses=_responses(400, 403, 404, 503),
)
def validate_command(
    body: ValidateRequest,
    principal: _Principal,
    registry: _Registry,
    settings: _Settings,
    paths: _Paths,
) -> CommandCallItem:
    """Check a call of a command of a producer's catalog without the network.

    A command that works on a store (`store` of `GET /commands`) is checked
    with the producer's directory of the configured store `store` names,
    never with the producer's default root: without `store` it is `400`
    (`store_required`), a store without a directory of the producer `400`
    (`store_without_producer`), an unknown one `404`. An option that is a file
    path (`path_role`) is `403` (`path_outside_root`, `details.option`): the
    producer would open it on the server; an input naming an area's GeoJSON
    Archiwista wrote, as the command lines of `/availability` do,
    is none. A command outside the catalog is `400` (`unknown_command`). The
    producer's refusal is `400 validation_error` with its own text and hint
    and the option in `details.option`. The answer is the call with the
    options as the producer reads them; `run` is empty.
    """
    call = command_service.validate_command(
        registry, settings.get(), body.call(), store=body.store, areas=paths.areas_dir
    )
    return CommandCallItem.of(call)


@router.post(
    "/commands/format", response_model=CommandLine, responses=_responses(400, 503)
)
def format_command(
    body: CommandCallItem, principal: _Principal, registry: _Registry
) -> CommandLine:
    """Write the producer's command line of a call (`kartograf …`).

    The line is the producer's canonical one, and `POST /commands/parse` reads
    it back into the same call; `run` gives what goes beside the options
    (`root`, `check`, ...). The call is not checked against the catalog's
    rules: a command or an option the producer does not know, an option also
    given in `run` or a value of a wrong form is `400 validation_error` with
    the producer's own text.
    """
    call = body.call()
    return CommandLine.of(call, command_service.format_command(registry, call))


@router.post(
    "/commands/area", response_model=CommandAreaItem, responses=_area_responses()
)
def apply_command_area(
    body: AreaRequest,
    principal: _Principal,
    registry: _Registry,
    queries: _Queries,
    paths: _Paths,
) -> CommandAreaItem:
    """Give a call an area of Archiwista in place of the area it names.

    For a pasted command run on a project's area, or on any area of `/areas`
    (A-ADR-049 erratum 5). The options that choose an area go (a sheet, a box,
    a file, a TERYT code…) and the area takes their place: as the command's
    geometry file when it has one (`way` `geometry`: the path of the area's
    GeoJSON Archiwista keeps, which `validate` and the jobs accept), else as
    the box that encloses it (`way` `bbox`: the producer may select data
    outside the area). A country the command needs with an area and the call
    does not give is the area's. The answer is the call, its line without a
    store root and the replaced options; nothing is checked against a store
    (`POST /commands/validate` does). An unknown area is `404`; a command
    outside the catalog `400` (`unknown_command`); a command that takes no
    area `422 unsupported` (`no_area_option`), as is a producer without
    commands (`no_commands`) or without areas (`no_area_commands`).
    """
    found = command_service.command_with_area(
        registry, queries, body.call(), area_id=body.area_id, areas=paths.areas_dir
    )
    return CommandAreaItem.of(found)
