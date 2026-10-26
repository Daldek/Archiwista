"""Stations and the coverage of their series for people and agents (SPEC 4.8.4).

The index gives a coverage label as structure (`SeriesLabel`); this module
writes its text in the language of the context, for the API and the command
line alike.
"""

from archiwista.index import GapRun, SeriesLabel, YearRange
from archiwista.index.series import MAX_UNKNOWN_RANGES
from archiwista.messages import message, plural_form
from archiwista.sources import TimeUnit


def series_label_text(label: SeriesLabel, *, time_unit: TimeUnit) -> str:
    """Return a coverage label for a person, in the language of the context.

    "ciągły · 1951–2025", "luki 3% · najdł. 1981.06.02–1982.12.31",
    "częściowy · od 1972 · luki 12%", "brak danych (tylko H)" and "nieznane"
    in Polish (SPEC 4.8.4), with "· nieznane: 2011–2025" when some years of
    the range are not known (at most two ranges, else "· nieznane: 15 lat").
    A label names one year as one; a gap is written in days ``RRRR.MM.DD``,
    or in months ``RRRR.MM`` for monthly and half-year characteristics.

    Parameters
    ----------
    label : SeriesLabel
        The label of a variable.
    time_unit : TimeUnit
        The unit of the dataset's series.
    """
    if label.state == "unknown":
        return message("series.label_unknown")
    text: str
    if label.state == "no_data":
        if label.only:
            variables = ", ".join(label.only)
            text = message("series.label_no_data_only", variables=variables)
        else:
            text = message("series.label_no_data")
    else:
        text = _valued_text(label, time_unit)
    if label.unknown_years:
        years = _unknown_text(label)
        text = message("series.label_unknown_years", label=text, years=years)
    return text


def _valued_text(label: SeriesLabel, time_unit: TimeUnit) -> str:
    """Write the label of a variable with a value in a known year of the range."""
    valued = label.valued or (0, 0)
    known = label.known or valued
    if label.state == "continuous":
        return message("series.label_continuous", years=_years(valued))
    if label.state == "gaps":
        gap = _gap_text(label.longest_gap, time_unit)
        if label.below_one:
            return message("series.label_gaps_below_one", gap=gap)
        return message("series.label_gaps", percent=label.percent, gap=gap)
    if valued[0] > known[0] and valued[1] < known[1]:
        text = message("series.label_partial", years=_years(valued))
    elif valued[0] > known[0]:
        text = message("series.label_partial_from", year=valued[0])
    else:
        text = message("series.label_partial_to", year=valued[1])
    if label.below_one:
        return message("series.label_partial_gaps_below_one", label=text)
    if label.percent:
        return message("series.label_partial_gaps", label=text, percent=label.percent)
    return text


def _years(years: YearRange) -> str:
    """``1951–2025``, or one year alone."""
    first, last = years
    return str(first) if first == last else f"{first}–{last}"


def _gap_text(gap: GapRun | None, time_unit: TimeUnit) -> str:
    """``1981.06.02–1982.12.31`` (``RRRR.MM`` for characteristics), or one unit."""
    if gap is None:
        return ""
    form = "%Y.%m.%d" if time_unit == "day" else "%Y.%m"
    start, end = gap.start.strftime(form), gap.end.strftime(form)
    return start if start == end else f"{start}–{end}"


def _unknown_text(label: SeriesLabel) -> str:
    """Write the unknown years of the range: up to two ranges, else their count."""
    if len(label.unknown_years) <= MAX_UNKNOWN_RANGES:
        return ", ".join(_years(years) for years in label.unknown_years)
    count = label.unknown_count
    return message(f"series.years_{plural_form(count)}", count=count)
