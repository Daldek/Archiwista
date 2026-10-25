"""``archiwista compare REF REF`` (plan v0.2, decision 11; steps 9-10).

Compares the metadata of two objects as ``GET /compare`` does, by calling
``services.compare.compare`` without HTTP as the owner of the installation:
``--json`` prints the route's ``Comparison``, without it the sides, one line
per field, a differing one marked with ``*``, and the layers and fields that
differ (``schema_diff``).
"""

import argparse
from typing import TextIO

from archiwista.api.models_compare import CompareValue, Comparison, SchemaDiff
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser
from archiwista.config import AppPaths, ConfigStore, SettingsValidationError
from archiwista.error_document import describe, exception_problem, refuse
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import message, with_detail
from archiwista.services.compare import compare
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset({"compare"})


def add_commands(commands: Commands) -> None:
    """Add ``compare`` to the subcommands of ``archiwista``."""
    parser = add_parser(commands, "compare", "cli.compare_help")
    parser.add_argument("a", metavar="REF", help=message("cli.compare_ref_help"))
    parser.add_argument("b", metavar="REF", help=message("cli.compare_ref_help"))


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run ``compare``: ``0`` on success, ``1`` on a refusal or a failure."""
    try:
        settings = ConfigStore(paths.config_file).load()
        visible = Authorizer(
            StateStore(paths.state_file), lambda: settings
        ).visible_projects(LOCAL_OWNER)
        queries = IndexQueries(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError, StateError) as error:
        return refuse(
            exception_problem(
                error, with_detail(message("cli.compare_failed"), str(error))
            ),
            err,
        )
    with queries:
        try:
            comparison = compare(queries, args.a, args.b, visible=visible)
        except ArchiwistaError as error:
            return refuse(describe(error), err)
    text = comparison.model_dump_json() if args.json else _text(comparison)
    out.write(text + "\n")
    return 0


def _text(comparison: Comparison) -> str:
    lines: list[str] = [
        message("cli.compare_side", side=name, title=side.title, ref=side.ref)
        for name, side in (("A", comparison.a), ("B", comparison.b))
    ]
    if comparison.same_content:
        lines.append(message("cli.compare_same_content"))
    lines += [
        message(
            "cli.compare_row",
            mark="*" if row.differs else " ",
            label=row.label,
            a=_value(row.a),
            b=_value(row.b),
        )
        for row in comparison.rows
    ]
    if comparison.schema_diff is not None:
        lines += _schema(comparison.schema_diff)
    differs = sum(row.differs for row in comparison.rows)
    lines.append(
        message("cli.compare_summary", differs=differs, total=len(comparison.rows))
    )
    return "\n".join(lines)


def _schema(diff: SchemaDiff) -> list[str]:
    """Lines of the layers and fields that differ; none when the schema matches."""
    lines = [
        *(message("cli.compare_layer_only_a", layer=n) for n in diff.layers_only_a),
        *(message("cli.compare_layer_only_b", layer=n) for n in diff.layers_only_b),
    ]
    for layer in diff.layers:
        fields = [
            *(
                message("cli.compare_field_added", name=f.name, type=f.type)
                for f in layer.fields_added
            ),
            *(
                message("cli.compare_field_removed", name=f.name, type=f.type)
                for f in layer.fields_removed
            ),
            *(
                message(
                    "cli.compare_field_changed",
                    name=f.name,
                    type_a=f.type_a,
                    type_b=f.type_b,
                )
                for f in layer.fields_changed
            ),
        ]
        if fields:
            lines += [message("cli.compare_layer", layer=layer.name), *fields]
    return [message("cli.compare_schema"), *lines] if lines else []


def _value(value: CompareValue) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return message("cli.compare_true" if value else "cli.compare_false")
    return str(value)
