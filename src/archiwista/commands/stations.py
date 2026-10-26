"""``archiwista stations``: the stations of the station catalogs (plan I6, I8).

``stations list [options]`` pages the stations as ``GET /stations`` does; its
options are generated from ``StationListFilters``, the route's query model:
one option per parameter, of the same name, validated by the same model (a
repeatable parameter is a repeatable option). ``stations timeline [options]``
is a page of the stations of one dataset with each variable year by year, as
``GET /stations/timeline`` gives it (the options of
``StationTimelineListFilters``; a person reads a strip of year cells per
variable). ``stations show CODE`` is the card of ``GET /stations/{code}``,
with the options of ``StationLookup``, ``stations series CODE`` the chart of
``GET /stations/{code}/series`` (the options of ``StationChartQuery``; a
person reads the range, the points with a value, the gaps and the markers)
and ``stations datasets`` the datasets of ``GET /stations/datasets``. Each
calls the function behind its route without HTTP: ``--json`` prints the
route's model, a refusal the route's problem as the ``archiwista-error/1``
document (``503`` while IMGWTools is not available becomes its exit code).
Nothing here uses the network or writes.
"""

import argparse
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TextIO, get_origin

from pydantic import BaseModel, ValidationError

from archiwista.api.models import IndexAnswer
from archiwista.api.models_stations import (
    ChartVariable,
    StationCard,
    StationChart,
    StationChartQuery,
    StationDatasetItem,
    StationDatasetsQuery,
    StationItem,
    StationList,
    StationListFilters,
    StationLookup,
    StationSeriesItem,
    StationTimelineItem,
    StationTimelineListFilters,
    StationTimelinePage,
    TimelineSeries,
    YearCell,
    YearSpan,
)
from archiwista.api.stations import (
    station_card,
    station_chart,
    station_datasets,
    station_list,
    station_timeline_page,
)
from archiwista.commands import Commands, add_parser
from archiwista.config import (
    AppPaths,
    AppSettings,
    ConfigStore,
    SettingsValidationError,
)
from archiwista.error_document import (
    Problem,
    describe,
    exception_problem,
    refuse,
    validation_problem,
)
from archiwista.errors import ArchiwistaError
from archiwista.index import IndexQueries, IndexUnsupportedError
from archiwista.messages import label, language, message, plural_form, with_detail
from archiwista.sources.registry import PluginRegistry

COMMANDS = frozenset({"stations"})

# What an action prints: the route's model with ``--json``, else text for people.
type _Output = tuple[BaseModel, str]
type _Action = Callable[
    [argparse.Namespace, AppSettings, PluginRegistry, IndexQueries], _Output
]

# A year of the Timeline in a line of text, by its cell (SPEC 6.7).
_CELLS: dict[YearCell, str] = {
    "full": "█",
    "fraction": "▒",
    "none": "·",
    "unknown": "?",
}
# The help of an option of ``stations series`` whose meaning differs there.
_SERIES_HELP = {
    "dataset": "cli.stations_chart_dataset_help",
    "variable": "cli.stations_chart_variable_help",
}


class _InvalidOptions(Exception):
    """Options the query model refuses (``400 validation_error``)."""

    def __init__(self, problem: Problem) -> None:
        super().__init__(problem.detail)
        self.problem = problem


def add_commands(commands: Commands) -> None:
    """Add ``archiwista stations`` with its actions (see the module).

    Parameters
    ----------
    commands : argparse._SubParsersAction
        Subcommands of the ``archiwista`` parser.
    """
    text = message("cli.stations_help")
    parser = commands.add_parser("stations", help=text, description=text)
    actions = parser.add_subparsers(
        dest="action", required=True, metavar=message("metavar.action")
    )
    listing = add_parser(actions, "list", "cli.stations_list_help")
    _options(listing, StationListFilters)
    timeline = add_parser(actions, "timeline", "cli.stations_timeline_help")
    _options(timeline, StationTimelineListFilters)
    shown = add_parser(actions, "show", "cli.stations_show_help")
    shown.add_argument(
        "code", metavar=message("metavar.code"), help=message("cli.stations_code_help")
    )
    _options(shown, StationLookup)
    series = add_parser(actions, "series", "cli.stations_series_help")
    series.add_argument(
        "code", metavar=message("metavar.code"), help=message("cli.stations_code_help")
    )
    _options(series, StationChartQuery, _SERIES_HELP)
    datasets = add_parser(actions, "datasets", "cli.stations_datasets_help")
    _options(datasets, StationDatasetsQuery)


def main(
    args: argparse.Namespace,
    paths: AppPaths,
    registry: PluginRegistry,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run an action of ``archiwista stations``; return the exit status.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments of ``stations`` (``action`` names the action).
    paths : AppPaths
        Configuration file and local index.
    registry : PluginRegistry
        Producer plugins: the source of the stations, a ``bbox`` in another CRS.
    out, err : TextIO
        The route's model (as JSON with ``--json``) or the text for a person;
        a refusal's message and its ``archiwista-error/1`` document go to
        ``err``.

    Returns
    -------
    int
        ``0`` on success; a refusal returns the exit code of its registry code.
    """
    try:
        settings = ConfigStore(paths.config_file).load()
        queries = IndexQueries(paths.index_file)
    except (SettingsValidationError, IndexUnsupportedError) as error:
        return refuse(
            exception_problem(
                error, with_detail(message("cli.stations_failed"), str(error))
            ),
            err,
        )
    with queries:
        try:
            model, text = _ACTIONS[args.action](args, settings, registry, queries)
        except _InvalidOptions as error:
            return refuse(error.problem, err)
        except ArchiwistaError as error:
            return refuse(describe(error), err)
    out.write((model.model_dump_json() if args.json else text) + "\n")
    return 0


def query_of[Model: BaseModel](model: type[Model], args: argparse.Namespace) -> Model:
    """Return the route's query of the given options.

    Options left out keep the model's defaults, as parameters left out of the
    URL do; values are validated by the model as the route validates them, so
    a refusal is the same ``400 validation_error`` problem.

    Raises
    ------
    _InvalidOptions
        The model refuses a value.
    """
    values = {
        name: getattr(args, name)
        for name in model.model_fields
        if getattr(args, name, None) is not None
    }
    try:
        with language("en"):  # the error document that reports a refusal is English
            return model.model_validate(values)
    except ValidationError as error:
        located = ({**item, "loc": ("query", *item["loc"])} for item in error.errors())
        raise _InvalidOptions(validation_problem(located)) from None


def _options(
    parser: argparse.ArgumentParser,
    model: type[BaseModel],
    helps: Mapping[str, str] | None = None,
) -> None:
    """Add an option for each parameter of a query model, of the same name.

    A parameter read by an alias (``from``) is the option of the alias; its
    help is ``cli.stations_<field>_help`` unless ``helps`` names another.
    """
    for name, field in model.model_fields.items():
        option = "--" + (field.alias or name).replace("_", "-")
        help_text = message((helps or {}).get(name, f"cli.stations_{name}_help"))
        if get_origin(field.annotation) is list:
            parser.add_argument(option, dest=name, action="append", help=help_text)
        else:
            parser.add_argument(option, dest=name, help=help_text)


def _list(
    args: argparse.Namespace,
    settings: AppSettings,
    registry: PluginRegistry,
    queries: IndexQueries,
) -> _Output:
    found = station_list(
        queries, settings, registry, query_of(StationListFilters, args)
    )
    lines: list[str] = []
    for item in found.items:
        lines.append(_station_line(item))
        lines.extend(_series_line(series) for series in item.series)
    if not lines:
        lines.append(message("cli.stations_none"))
    return found, _with_stale(found, [*lines, *_page_end(found)])


def _timeline(
    args: argparse.Namespace,
    settings: AppSettings,
    registry: PluginRegistry,
    queries: IndexQueries,
) -> _Output:
    found = station_timeline_page(
        queries, settings, registry, query_of(StationTimelineListFilters, args)
    )
    lines: list[str] = []
    for item in found.items:
        lines.append(_station_line(item))
        for series in item.series:
            lines.extend(_timeline_lines(series))
    if lines:
        lines.append(message("cli.station_timeline_legend", **_CELLS))
    else:
        lines.append(message("cli.stations_none"))
    return found, _with_stale(found, [*lines, *_page_end(found)])


def _show(
    args: argparse.Namespace,
    settings: AppSettings,
    registry: PluginRegistry,
    queries: IndexQueries,
) -> _Output:
    card = station_card(
        queries, settings, registry, args.code, query_of(StationLookup, args)
    )
    return card, _card_text(card)


def _series(
    args: argparse.Namespace,
    settings: AppSettings,
    registry: PluginRegistry,
    queries: IndexQueries,
) -> _Output:
    chart = station_chart(
        queries, settings, registry, args.code, query_of(StationChartQuery, args)
    )
    return chart, _chart_text(chart)


def _datasets(
    args: argparse.Namespace,
    settings: AppSettings,
    registry: PluginRegistry,
    queries: IndexQueries,
) -> _Output:
    found = station_datasets(
        queries, settings, registry, query_of(StationDatasetsQuery, args)
    )
    lines = [_dataset_line(item) for item in found.items]
    if not lines:
        lines.append(message("cli.station_datasets_none"))
    return found, _with_stale(found, lines)


_ACTIONS: dict[str, _Action] = {
    "list": _list,
    "timeline": _timeline,
    "show": _show,
    "series": _series,
    "datasets": _datasets,
}


# Text.


def _station_line(item: StationItem | StationTimelineItem) -> str:
    river = (
        message(
            "cli.station_river", river=item.river, code=_value(item.hydrographic_code)
        )
        if item.river is not None
        else ""
    )
    place = ""
    if item.location.kind == "none":
        place = message("cli.station_unlocated", reason=_reason(item.location.reason))
    elif item.location.on_boundary:
        place = message("cli.station_on_boundary")
    return message(
        "cli.station_line",
        code=item.code,
        name=_value(item.name),
        kind=_value(item.kind),
        provider=item.provider,
        store=item.store,
        river=river,
        place=place,
    )


def _page_end(found: StationList | StationTimelinePage) -> list[str]:
    """Write the counts of a page of stations and the cursor of the next one."""
    counts = found.counts
    lines: list[str] = [
        message(
            "cli.stations_summary",
            count=len(found.items),
            located=counts.located,
            boundary=counts.boundary,
            unlocated=counts.unlocated,
            hidden=counts.hidden,
        )
    ]
    if found.next_cursor is not None:
        lines.append(message("cli.search_next", cursor=found.next_cursor))
    return lines


def _series_line(series: StationSeriesItem) -> str:
    labels = "; ".join(
        message("cli.station_label", key=key, label=variable.label)
        for key, variable in series.coverage.items()
    )
    return message(
        "cli.station_series",
        dataset=series.dataset,
        series=_value(series.series),
        year_type=label("series.year_type", series.year_type),
        years=_years(series.years),
        labels=labels,
    )


def _timeline_lines(series: TimelineSeries) -> list[str]:
    """Write a series' heading, then each variable's strip of years and label."""
    width = max((len(variable.key) for variable in series.variables), default=0)
    lines: list[str] = [
        message(
            "cli.station_timeline_series",
            dataset=series.dataset,
            series=_value(series.series),
            year_type=label("series.year_type", series.year_type),
            years=_years(series.years),
        )
    ]
    lines.extend(
        message(
            "cli.station_timeline_variable",
            key=variable.key.ljust(width),
            years="".join(_CELLS[year["cell"]] for year in variable.years),
            label=variable.label,
        )
        for variable in series.variables
    )
    return lines


def _card_text(card: StationCard) -> str:
    item = card.station
    location = item.location
    lines: list[str] = [
        message(
            "cli.station_title",
            code=item.code,
            name=_value(item.name),
            provider=item.provider,
            store=item.store,
        ),
        message(
            "cli.station_facts",
            kind=_value(item.kind),
            river=_value(item.river),
            river_code=_value(item.hydrographic_code),
            active=_active(item.active),
            established=_value(item.established_year),
            gauge_zero=_value(item.gauge_zero_m),
            river_km=_value(item.river_km),
        ),
    ]
    if location.kind == "point":
        lines.append(
            message(
                "cli.station_located",
                lon=_value(location.lon),
                lat=_value(location.lat),
                source=_value(location.source),
                uncertainty=_value(location.uncertainty_m),
                catalog=_value(item.catalog),
            )
        )
    else:
        lines.append(
            message(
                "cli.station_no_location",
                reason=_reason(location.reason),
                catalog=_value(item.catalog),
            )
        )
    for series in item.series:
        lines.append(
            message(
                "cli.station_series_title",
                dataset=series.dataset,
                series=_value(series.series),
                year_type=label("series.year_type", series.year_type),
                years=_years(series.years),
                file=series.file,
            )
        )
        lines.extend(
            message(
                "cli.station_variable",
                key=key,
                unit=variable.unit,
                label=variable.label,
                complete=variable.complete_years,
            )
            for key, variable in series.coverage.items()
        )
        if series.attribution is not None:
            lines.append(
                message(
                    "cli.station_attribution",
                    license=_value(series.license),
                    attribution=series.attribution,
                )
            )
    return _with_stale(card, lines)


def _chart_text(chart: StationChart) -> str:
    """Write a chart's series, range, and each variable's points, gaps, markers."""
    lines: list[str] = [
        message(
            "cli.station_chart_title",
            code=chart.code,
            dataset=chart.dataset,
            series=_value(chart.series),
            year_type=label("series.year_type", chart.year_type),
            file=chart.file,
        )
    ]
    if chart.first is None or chart.last is None:
        lines.append(message("cli.station_chart_empty"))
    else:
        lines.append(
            message(
                "cli.station_chart_values"
                if chart.interval == 1
                else "cli.station_chart_simplified",
                start=chart.first,
                end=chart.last,
                units=_units(chart.units, chart.time_unit),
                interval=_units(chart.interval, chart.time_unit),
            )
        )
    for variable in chart.variables:
        lines.extend(_chart_variable_lines(variable, chart.time_unit))
    if chart.attribution is not None:
        lines.append(
            message(
                "cli.station_attribution",
                license=_value(chart.license),
                attribution=chart.attribution,
            )
        )
    return _with_stale(chart, lines)


def _chart_variable_lines(variable: ChartVariable, time_unit: str) -> list[str]:
    """Write a variable's count of points with a value, its gaps and markers."""
    lines: list[str] = [
        message(
            "cli.station_chart_variable",
            key=variable.key,
            unit=variable.unit,
            valued=sum(point["mean"] is not None for point in variable.points),
            points=len(variable.points),
            gaps=len(variable.gaps),
            markers=len(variable.markers),
        )
    ]
    lines.extend(
        message(
            "cli.station_chart_gap",
            start=gap.first,
            end=gap.last,
            units=_units(gap.units, time_unit),
        )
        for gap in variable.gaps
    )
    for marker in variable.markers:
        if marker["kind"] == "accumulated":
            lines.append(
                message(
                    "cli.station_chart_accumulated",
                    day=marker["t"],
                    value=marker["value"],
                )
            )
        else:
            lines.append(
                message(
                    "cli.station_chart_extreme",
                    kind=label("cli.station_marker", marker["kind"]),
                    period=label("cli.station_period", marker["period"] or "annual"),
                    day=marker["t"],
                    value=marker["value"],
                )
            )
    return lines


def _units(count: int, time_unit: str) -> str:
    """Return a count of days or months for a person ("14 dni")."""
    return message(f"series.unit_{time_unit}_{plural_form(count)}", count=count)


def _dataset_line(item: StationDatasetItem) -> str:
    variables = ", ".join(
        message("cli.station_dataset_variable", key=variable.key, unit=variable.unit)
        for variable in item.variables
    )
    return message(
        "cli.station_dataset_line",
        dataset=item.dataset,
        name=_value(item.name),
        provider=item.provider,
        kind=_value(item.kind),
        store=item.store,
        series=_value(item.series),
        year_type=label("series.year_type", item.year_type),
        years=_years(item.years),
        variables=variables or message("cli.none"),
    )


def _years(years: YearSpan | None) -> str:
    if years is None:
        return message("cli.none")
    first, last = years.first, years.last
    return str(first) if first == last else f"{first}–{last}"


def _reason(reason: str | None) -> str:
    return (
        message("cli.none") if reason is None else label("cli.station_reason", reason)
    )


def _active(active: bool | None) -> str:
    if active is None:
        return message("cli.none")
    return label("cli.station_active", "true" if active else "false")


def _with_stale(answer: IndexAnswer, lines: list[str]) -> str:
    notes = [
        message("cli.stale_line", store=item.store, indexed_at=_time(item.indexed_at))
        for item in answer.stale_stores
    ]
    return "\n".join([*lines, *notes])


def _value(value: object) -> str:
    return message("cli.none") if value is None else str(value)


def _time(value: datetime | None) -> str:
    if value is None:
        return message("cli.never")
    return value.astimezone().strftime("%Y-%m-%d %H:%M")
