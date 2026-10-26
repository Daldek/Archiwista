"""Scanning stores."""

from archiwista.messages import Text

MESSAGES = {
    "store_empty": Text(
        (
            "Store {path} is empty, but the index contains its files — the share may"
            " be disconnected; the index remains unchanged"
        ),
        (
            "Magazyn {path} jest pusty, a indeks zawiera jego pliki — udział może być"
            " niepodłączony; indeks pozostaje bez zmian"
        ),
    ),
    "footprints_failed": Text(
        (
            "Files without a determined footprint: {count} — will retry at the next"
            " scan. Producer message: {detail}"
        ),
        (
            "Plików bez wyznaczonego obrysu: {count} — ponowna próba przy następnym"
            " skanie. Komunikat producenta: {detail}"
        ),
    ),
    "stations_unreadable": Text(
        (
            "The station catalog of {provider} ({path}) cannot be read; its stations"
            " are not in the index until a scan reads it. Producer message: {detail}"
        ),
        (
            "Nie można odczytać katalogu stacji {provider} ({path}); jego stacji nie"
            " ma w indeksie, dopóki skan go nie odczyta. Komunikat producenta:"
            " {detail}"
        ),
    ),
}
