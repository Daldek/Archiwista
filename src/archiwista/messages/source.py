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
            "no directory is a Kartograf segment — point to the store root, the"
            " directory that holds {marker}"
        ),
        (
            "żaden katalog nie jest segmentem Kartografa — wskaż katalog główny"
            " magazynu, czyli ten z plikiem {marker}"
        ),
    ),
    "no_marker": Text(
        "the directory has the layout of a Kartograf store but no {marker}",
        "katalog ma układ magazynu Kartografa, ale nie ma pliku {marker}",
    ),
    "foreign_store": Text(
        (
            "the directory is the root of the {tool} store ({marker}), not of a"
            " Kartograf store"
        ),
        "to katalog główny magazynu {tool} ({marker}), a nie magazynu Kartografa",
    ),
    "unsupported_marker": Text(
        (
            'the marker {marker} has the schema "{found}", Archiwista reads'
            ' "{supported}"'
        ),
        "znacznik {marker} ma schemat „{found}”, Archiwista czyta „{supported}”",
    ),
    "invalid_marker": Text(
        'the marker {marker} is not a JSON document with the schema "{supported}"',
        "znacznik {marker} nie jest dokumentem JSON ze schematem „{supported}”",
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
    "imgw_catalog": Text(
        "Station catalog of {provider}",
        "Katalog stacji {provider}",
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
