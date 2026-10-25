"""The availability at the source: refusals, coverage labels and store badges."""

from archiwista.messages import Text

MESSAGES = {
    "product_unsupported": Text(
        (
            'The source {producer} checks no availability of "{product}"; it checks:'
            " {allowed}."
        ),
        "Źródło {producer} nie sprawdza dostępności „{product}”; sprawdza: {allowed}.",
    ),
    "none": Text(
        'Area "{area}" has no report of the availability of "{product}" by {producer}.',
        "Obszar „{area}” nie ma raportu dostępności „{product}” od {producer}.",
    ),
    # The coverage labels of SPEC 6.4 and their parts.
    "label_full": Text("complete", "pełne"),
    "label_full_campaigns": Text("complete · {campaigns}", "pełne · {campaigns}"),
    "label_partial": Text("partial · {percent}%", "częściowe · {percent}%"),
    "label_partial_below_one": Text("partial · <1%", "częściowe · <1%"),
    "label_partial_unmeasured": Text("partial", "częściowe"),
    "label_no_data": Text("no data", "brak danych"),
    "label_part": Text("{label} · {part}", "{label} · {part}"),
    "campaigns_one": Text("{count} campaign", "{count} kampania"),
    "campaigns_few": Text("{count} campaigns", "{count} kampanie"),
    "campaigns_many": Text("{count} campaigns", "{count} kampanii"),
    "partial_sheets_one": Text("{count} partial sheet", "{count} ark. niepełny"),
    "partial_sheets_few": Text("{count} partial sheets", "{count} ark. niepełne"),
    "partial_sheets_many": Text("{count} partial sheets", "{count} ark. niepełnych"),
    "missing_sheets_one": Text(
        "{count} sheet without a file", "{count} ark. bez pliku"
    ),
    "missing_sheets_few": Text(
        "{count} sheets without a file", "{count} ark. bez pliku"
    ),
    "missing_sheets_many": Text(
        "{count} sheets without a file", "{count} ark. bez pliku"
    ),
    "other_variants_one": Text("+{count} variant", "+{count} wariant"),
    "other_variants_few": Text("+{count} variants", "+{count} warianty"),
    "other_variants_many": Text("+{count} variants", "+{count} wariantów"),
    # The store badge.
    "local_all": Text("downloaded", "pobrane"),
    "local_some": Text("downloaded {units}/{of}", "pobrane {units}/{of}"),
    "local_none": Text("not downloaded", "niepobrane"),
}
