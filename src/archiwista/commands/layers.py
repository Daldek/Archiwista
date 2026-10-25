"""``archiwista layers``: the layers of a product for people and AI agents.

``archiwista layers --store S --product P [--area-id A] [--segment G]
[--group year|campaign] [--json]`` (plan v0.2, decision 11) prints the
``LayerSet`` that ``GET /local-layers`` answers, after the same view refresh
of the area's slots. ``--thumbnail KLUCZ --output PLIK.png [--size N]
[--style STYL]`` also writes the layer's thumbnail (``GET
/local-layers/thumbnail.png``), drawn by a render process of the command
into the preview cache the server uses, so an agent that sees images looks
at a year without HTTP. Everything runs as the owner of the installation
(``LOCAL_OWNER``) through ``archiwista.services.layers``. No job supervisor
runs, so no ``preview`` job is submitted or named: a layer whose previews a
server is building shows ``needs_build``, and its thumbnail what is ready.
"""

import argparse
import asyncio
import sqlite3
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

from pydantic import ValidationError

from archiwista.api.models_layers import LayerSet, LayersQuery, LayerThumbnailQuery
from archiwista.auth import LOCAL_OWNER
from archiwista.commands import Commands, add_parser
from archiwista.commands.previews import LocalPreviews, local_previews
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsService,
    SettingsValidationError,
)
from archiwista.error_document import (
    describe,
    exception_problem,
    fail,
    refuse,
    validation_problem,
)
from archiwista.errors import ArchiwistaError
from archiwista.index import IndexUnsupportedError
from archiwista.messages import message, with_detail
from archiwista.services.layers import layer_images, layer_thumbnail, read_local_layers
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"layers"})
# Side of the thumbnail ``--output`` writes, as ``archiwista preview``.
DEFAULT_SIZE = 512


def add_commands(commands: Commands) -> None:
    """Add ``archiwista layers`` (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    layers = add_parser(commands, "layers", "cli.layers_help")
    layers.add_argument(
        "--store",
        required=True,
        metavar=message("metavar.store"),
        help=message("cli.layers_store_help"),
    )
    layers.add_argument(
        "--product",
        required=True,
        metavar=message("metavar.product"),
        help=message("cli.layers_product_help"),
    )
    layers.add_argument(
        "--area-id",
        metavar=message("metavar.area"),
        help=message("cli.layers_area_help"),
    )
    layers.add_argument(
        "--segment", metavar="SEGMENT", help=message("cli.layers_segment_help")
    )
    layers.add_argument(
        "--group",
        choices=("year", "campaign"),
        default="year",
        help=message("cli.layers_group_help"),
    )
    layers.add_argument(
        "--thumbnail",
        metavar=message("metavar.key"),
        help=message("cli.layers_thumbnail_help"),
    )
    layers.add_argument(
        "--size",
        type=int,
        default=DEFAULT_SIZE,
        metavar=message("metavar.side"),
        help=message("cli.layers_size_help"),
    )
    layers.add_argument(
        "--style",
        metavar=message("metavar.style"),
        help=message("cli.preview_style_help"),
    )
    layers.add_argument(
        "--output",
        type=Path,
        metavar=message("metavar.png_file"),
        help=message("cli.layers_output_help"),
    )


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run ``archiwista layers``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``layers``.
    paths : AppPaths
        Configuration file, local index and preview cache.
    registry : PluginRegistry
        Producer plugins: the store's producer and the pinned operations.
    out, err : TextIO
        The ``LayerSet`` (as JSON with ``--json``); a refusal's Polish message
        and its ``archiwista-error/1`` document go to ``err``.

    Returns
    -------
    int
        ``0`` on success; a refusal (the query, a thumbnail that cannot be
        written, ``--thumbnail`` without ``--output``, unusable settings, index
        or preview cache) returns the exit code of its registry code.
    """
    if (args.thumbnail is None) != (args.output is None):
        return fail(
            err,
            "validation_error",
            message("cli.layers_output_required"),
            reason="usage",
        )
    try:
        query = LayersQuery(
            store=args.store,
            product=args.product,
            area_id=args.area_id,
            segment=args.segment,
            group=args.group,
        )
        image = None
        if args.thumbnail is not None:
            image = LayerThumbnailQuery(
                **query.model_dump(),
                layer=args.thumbnail,
                size=args.size,
                style=args.style,
            )
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        return refuse(validation_problem(located), err)
    with ExitStack() as stack:
        try:
            settings = SettingsService(ConfigStore(paths.config_file), registry).get()
            previews = stack.enter_context(local_previews(paths, settings))
        except (
            SettingsValidationError,
            IndexUnsupportedError,
            OSError,
            sqlite3.Error,
        ) as error:
            return refuse(
                exception_problem(
                    error, with_detail(message("cli.layers_failed"), str(error))
                ),
                err,
            )
        try:
            return _layers(
                args, query, image, previews, settings, paths, registry, out, err
            )
        except ArchiwistaError as error:
            return refuse(describe(error), err)


def _layers(
    args: argparse.Namespace,
    query: LayersQuery,
    image: LayerThumbnailQuery | None,
    previews: LocalPreviews,
    settings: AppSettings,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Print the layers, after writing a layer's thumbnail when asked to."""
    cache = previews.pool.cache
    found = read_local_layers(
        previews.queries,
        settings,
        registry,
        paths.index_file,
        query,
        principal=LOCAL_OWNER,
        cache=cache,
    )
    if image is not None:
        images = layer_images(
            previews.queries, settings, registry, image, image.layer, cache=cache
        )
        drawn = asyncio.run(
            layer_thumbnail(
                previews.pool, images, style=image.style, size=image.size, v=None
            )
        )
        assert drawn.data is not None  # asked without If-None-Match
        try:
            args.output.write_bytes(drawn.data)
        except OSError as error:
            return refuse(
                exception_problem(
                    error, with_detail(message("cli.layers_failed"), str(error))
                ),
                err,
            )
        text = message(
            "cli.layers_written",
            layer=image.layer,
            path=args.output,
            size=image.size,
            style=image.style or images.default_style or "–",
        )
        err.write(text + "\n")
    out.write((found.model_dump_json() if args.json else _text(found)) + "\n")
    return 0


def _text(found: LayerSet) -> str:
    area = (
        message("cli.layers_whole_store")
        if found.area is None
        else (found.area.name or found.area.id)
    )
    lines = [
        message(
            "cli.layers_heading",
            store=found.store,
            product=found.product,
            count=len(found.layers),
            area=area,
        )
    ]
    if found.stale_reason is not None:
        lines.append(message("cli.layers_stale", reason=found.stale_reason))
    for layer in found.layers:
        lines.append(
            message(
                "cli.layers_layer",
                key=layer.key,
                title=layer.title,
                subtitle=layer.subtitle,
                versions=layer.versions_count,
                units=layer.units_count,
            )
        )
        lines.append(
            message("cli.layers_formats", formats=", ".join(layer.variant.formats))
        )
        if layer.coverage is not None:
            lines.append(message("cli.layers_coverage", label=layer.coverage.label))
        preview = layer.preview
        if preview is not None:
            job = (
                ""
                if preview.job is None
                else message("cli.layers_preview_job", job=preview.job.id)
            )
            lines.append(
                message(
                    "cli.layers_preview",
                    ready=preview.ready,
                    total=preview.total,
                    state=message(f"preview.state_{preview.state}"),
                    job=job,
                )
            )
    return "\n".join(lines)
