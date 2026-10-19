"""``archiwista compare REF REF`` (plan v0.2, decision 11; step 10).

Compares the metadata of two objects as ``GET /compare`` does, by calling
``services.compare.compare`` without HTTP as the owner of the installation:
``--json`` prints the route's ``Comparison``, without it the sides and one
line per field, a differing one marked with ``*``.
"""

import argparse
from typing import TextIO

from archiwista.api.errors import service_problem
from archiwista.api.models_compare import CompareValue, Comparison
from archiwista.auth import LOCAL_OWNER
from archiwista.auth.authorize import Authorizer
from archiwista.commands import Commands, add_parser, refuse
from archiwista.config import AppPaths, ConfigStore, SettingsValidationError
from archiwista.errors import ArchiwistaError, StateError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import MESSAGES, with_detail
from archiwista.services.compare import compare
from archiwista.sources.registry import PluginRegistry
from archiwista.state import StateStore

COMMANDS = frozenset({"compare"})


def add_commands(commands: Commands) -> None:
    """Add ``compare`` to the subcommands of ``archiwista``."""
    parser = add_parser(commands, "compare", "cli_compare_help")
    parser.add_argument("a", metavar="REF", help=MESSAGES["cli_compare_ref_help"])
    parser.add_argument("b", metavar="REF", help=MESSAGES["cli_compare_ref_help"])


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
        err.write(with_detail(MESSAGES["cli_compare_failed"], str(error)) + "\n")
        return 1
    with queries:
        try:
            comparison = compare(queries, args.a, args.b, visible=visible)
        except ArchiwistaError as error:
            problem = service_problem(error)
            if problem is None:
                raise
            return refuse(problem, out, err, as_json=args.json)
    text = comparison.model_dump_json() if args.json else _text(comparison)
    out.write(text + "\n")
    return 0


def _text(comparison: Comparison) -> str:
    lines = [
        MESSAGES["cli_compare_side"].format(side=name, title=side.title, ref=side.ref)
        for name, side in (("A", comparison.a), ("B", comparison.b))
    ]
    if comparison.same_content:
        lines.append(MESSAGES["cli_compare_same_content"])
    lines += [
        MESSAGES["cli_compare_row"].format(
            mark="*" if row.differs else " ",
            label=row.label,
            a=_value(row.a),
            b=_value(row.b),
        )
        for row in comparison.rows
    ]
    differs = sum(row.differs for row in comparison.rows)
    lines.append(
        MESSAGES["cli_compare_summary"].format(
            differs=differs, total=len(comparison.rows)
        )
    )
    return "\n".join(lines)


def _value(value: CompareValue) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return MESSAGES[f"cli_compare_{str(value).lower()}"]
    return str(value)
