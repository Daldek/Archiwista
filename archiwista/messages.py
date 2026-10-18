"""Polish user-facing messages shared across the command line and server."""

from types import MappingProxyType

MESSAGES = MappingProxyType(
    {
        "cli_description": "Archiwista — przeglądarka lokalnego magazynu danych.",
        "source_unavailable": "Źródło danych jest niedostępne.",
        "source_incompatible": "Wersja źródła danych jest niezgodna.",
        "store_unavailable": "Magazyn danych jest niedostępny.",
    }
)
