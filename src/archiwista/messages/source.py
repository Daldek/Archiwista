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
