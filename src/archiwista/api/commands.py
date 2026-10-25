"""The producers' commands over HTTP (plan of 2026-10-25, A1; SPEC 9.2; ADR-034).

``GET /commands`` lists the commands of the producers' catalogs, ``POST
/commands/parse`` reads a pasted command line into a call, ``POST
/commands/validate`` checks a call without the network and ``POST
/commands/format`` writes the producer's command line of a call. The routes
translate only: ``archiwista.services.commands`` does the work, and
``archiwista commands`` calls the same functions. A session is all they need:
nothing here uses the network or writes.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from archiwista.api.dependencies import plugin_registry, settings_service
from archiwista.api.errors import PROBLEM_MEDIA_TYPE, problem_example, problem_responses
from archiwista.api.models_commands import (
    CommandCallItem,
    CommandLine,
    CommandList,
    CommandsQuery,
    ParseRequest,
    ValidateRequest,
)
from archiwista.auth import Principal
from archiwista.config import SettingsService
from archiwista.messages import message
from archiwista.security import current_principal
from archiwista.services import commands as command_service
from archiwista.sources.registry import PluginRegistry

router = APIRouter(tags=["commands"])

_Principal = Annotated[Principal, Depends(current_principal)]
_Registry = Annotated[PluginRegistry, Depends(plugin_registry)]
_Settings = Annotated[SettingsService, Depends(settings_service)]


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
) -> CommandCallItem:
    """Check a call of a command of a producer's catalog without the network.

    A command that works on a store (`store` of `GET /commands`) is checked
    with the producer's directory of the configured store `store` names,
    never with the producer's default root: without `store` it is `400`
    (`store_required`), a store without a directory of the producer `400`
    (`store_without_producer`), an unknown one `404`. An option that is a file
    path (`path_role`) is `403` (`path_outside_root`, `details.option`): the
    producer would open it on the server. A command outside the catalog is
    `400` (`unknown_command`). The producer's refusal is `400
    validation_error` with its own text and hint and the option in
    `details.option`. The answer is the call with the options as the producer
    reads them; `run` is empty.
    """
    call = command_service.validate_command(
        registry, settings.get(), body.call(), store=body.store
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
