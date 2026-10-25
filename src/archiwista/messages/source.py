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
