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
        (
            "the directory holds other files and no Kartograf store — point to the"
            " store root, the directory that holds {marker}"
        ),
        (
            "w katalogu są inne pliki, a nie magazyn Kartografa — wskaż katalog"
            " główny magazynu, czyli ten z plikiem {marker}"
        ),
    ),
    "no_marker": Text(
        "the directory has the layout of a Kartograf store but no {marker}",
        "katalog ma układ magazynu Kartografa, ale nie ma pliku {marker}",
    ),
    "obserwator_no_marker": Text(
        (
            "the directory has the layout of an Obserwator store but no"
            " obserwator-store.json marker — mark the store with: {hint}"
        ),
        (
            "w katalogu jest układ magazynu Obserwatora, ale brak znacznika"
            " obserwator-store.json — zaznacz magazyn poleceniem: {hint}"
        ),
    ),
    "obserwator_unsupported_marker": Text(
        (
            "the obserwator-store.json marker is not supported: schema {found}, this"
            " version of Archiwista reads {expected}"
        ),
        (
            "znacznik obserwator-store.json nie jest obsługiwany: schemat {found}, ta"
            " wersja Archiwisty czyta {expected}"
        ),
    ),
    "obserwator_foreign_store": Text(
        (
            "the directory holds the marker {marker}: it is the store of another"
            " producer, not of Obserwator"
        ),
        (
            "w katalogu jest znacznik {marker}: to magazyn innego producenta, nie"
            " Obserwatora"
        ),
    ),
    "obserwator_not_store": Text(
        (
            "this is not the root of an Obserwator store — point to the directory that"
            " holds obserwator-store.json"
        ),
        (
            "to nie jest katalog główny magazynu Obserwatora — wskaż katalog z plikiem"
            " obserwator-store.json"
        ),
    ),
    "obserwator_catalog": Text(
        "Station catalog of {provider}",
        "Katalog stacji {provider}",
    ),
    "obserwator_series_unit": Text(
        (
            "The series of {dataset} are kept by the unit {unit}, which Archiwista"
            " cannot measure (day, month or half-year)."
        ),
        (
            "Szeregi {dataset} mają jednostkę {unit}, której Archiwista nie umie"
            " zmierzyć (dzień, miesiąc albo półrocze)."
        ),
    ),
    "obserwator_series_station": Text(
        "The station {station} has no series in the version {version}.",
        "Stacja {station} nie ma szeregu w wersji {version}.",
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
