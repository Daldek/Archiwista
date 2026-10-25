"""Producer plugins and their adapters."""

from archiwista.messages import Text

MESSAGES = {
    "unavailable": Text(
        "The data source is unavailable.",
        "Źródło danych jest niedostępne.",
    ),
    "unavailable_producer": Text(
        "Data source {producer} is unavailable",
        "Źródło danych {producer} jest niedostępne",
    ),
    "incompatible_producer": Text(
        (
            "Data source {producer} is incompatible: installed version {version},"
            " supported {supported}"
        ),
        (
            "Źródło danych {producer} jest niezgodne: zainstalowana wersja {version},"
            " wspierane {supported}"
        ),
    ),
    "kartograf_not_store": Text(
        "no directory is a Kartograf segment — point to the --output directory (data/)",
        "żaden katalog nie jest segmentem Kartografa — wskaż katalog --output (data/)",
    ),
    "imgw_no_marker": Text(
        (
            "the directory has the layout of an IMGWTools store but no imgw-store.json"
            " marker — mark the store with: {hint}"
        ),
        (
            "w katalogu jest układ magazynu IMGWTools, ale brak znacznika"
            " imgw-store.json — zaznacz magazyn poleceniem: {hint}"
        ),
    ),
    "imgw_unsupported_marker": Text(
        (
            "the imgw-store.json marker is not supported: schema {found}, this version"
            " of Archiwista reads {expected}"
        ),
        (
            "znacznik imgw-store.json nie jest obsługiwany: schemat {found}, ta wersja"
            " Archiwisty czyta {expected}"
        ),
    ),
    "imgw_foreign_store": Text(
        (
            "the directory holds the marker {marker}: it is the store of another"
            " producer, not of IMGWTools"
        ),
        (
            "w katalogu jest znacznik {marker}: to magazyn innego producenta, nie"
            " IMGWTools"
        ),
    ),
    "imgw_not_store": Text(
        (
            "this is not the root of an IMGWTools store — point to the directory that"
            " holds imgw-store.json"
        ),
        (
            "to nie jest katalog główny magazynu IMGWTools — wskaż katalog z plikiem"
            " imgw-store.json"
        ),
    ),
    "schema_unknown": Text(
        "unknown",
        "nieznany",
    ),
    "status_not_installed": Text(
        "producer package is not installed",
        "pakiet producenta nie jest zainstalowany",
    ),
    "status_incompatible": Text(
        "incompatible version or schema",
        "niezgodna wersja albo schemat",
    ),
    "status_error": Text(
        "plugin error",
        "błąd wtyczki",
    ),
}
