"""Coverage labels of the series of stations (SPEC 4.8.4, A-ADR-021)."""

from archiwista.messages import Text

MESSAGES = {
    "label_continuous": Text("continuous · {years}", "ciągły · {years}"),
    "label_gaps": Text(
        "gaps {percent}% · longest {gap}",
        "luki {percent}% · najdł. {gap}",
    ),
    "label_gaps_below_one": Text(
        "gaps <1% · longest {gap}",
        "luki <1% · najdł. {gap}",
    ),
    "label_partial": Text("partial · {years}", "częściowy · {years}"),
    "label_partial_from": Text("partial · from {year}", "częściowy · od {year}"),
    "label_partial_to": Text("partial · to {year}", "częściowy · do {year}"),
    "label_partial_gaps": Text(
        "{label} · gaps {percent}%",
        "{label} · luki {percent}%",
    ),
    "label_partial_gaps_below_one": Text(
        "{label} · gaps <1%",
        "{label} · luki <1%",
    ),
    "label_no_data": Text("no data", "brak danych"),
    "label_no_data_only": Text(
        "no data (only {variables})",
        "brak danych (tylko {variables})",
    ),
    "label_unknown": Text("unknown", "nieznane"),
    "label_unknown_years": Text(
        "{label} · unknown: {years}",
        "{label} · nieznane: {years}",
    ),
    "years_one": Text("{count} year", "{count} rok"),
    "years_few": Text("{count} years", "{count} lata"),
    "years_many": Text("{count} years", "{count} lat"),
    "unit_day_one": Text("{count} day", "{count} dzień"),
    "unit_day_few": Text("{count} days", "{count} dni"),
    "unit_day_many": Text("{count} days", "{count} dni"),
    "unit_month_one": Text("{count} month", "{count} miesiąc"),
    "unit_month_few": Text("{count} months", "{count} miesiące"),
    "unit_month_many": Text("{count} months", "{count} miesięcy"),
    "year_type_hydrological": Text("hydrological", "hydrologiczne"),
    "year_type_calendar": Text("calendar", "kalendarzowe"),
}
