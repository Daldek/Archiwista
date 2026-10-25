"""The report of ``archiwista doctor``."""

from archiwista.messages import Text

MESSAGES = {
    "title": Text(
        "Archiwista — diagnostics",
        "Archiwista — diagnostyka",
    ),
    "level_ok": Text(
        "OK",
        "OK",
    ),
    "level_warning": Text(
        "WARNING",
        "UWAGA",
    ),
    "level_error": Text(
        "ERROR",
        "BŁĄD",
    ),
    "fix": Text(
        "Fix: {fix}",
        "Naprawa: {fix}",
    ),
    "summary": Text(
        "Result: errors {errors}, warnings {warnings}.",
        "Wynik: błędy {errors}, ostrzeżenia {warnings}.",
    ),
    "config_ok": Text(
        "Configuration: {path}",
        "Konfiguracja: {path}",
    ),
    "config_absent": Text(
        "Configuration file {path} is missing — Archiwista runs with default settings",
        "Brak pliku konfiguracji {path} — Archiwista działa na ustawieniach domyślnych",
    ),
    "no_stores": Text(
        "No store is configured",
        "Nie skonfigurowano żadnego magazynu",
    ),
    "source_available": Text(
        (
            "Plugin {producer}: version {version} (supported {supported}; schemas:"
            " {schemas})"
        ),
        (
            "Wtyczka {producer}: wersja {version} (wspierane {supported}; schematy:"
            " {schemas})"
        ),
    ),
    "source_not_installed": Text(
        "Plugin {producer}: the producer package is not installed",
        "Wtyczka {producer}: pakiet producenta nie jest zainstalowany",
    ),
    "source_incompatible": Text(
        (
            "Plugin {producer}: installed version {version} is incompatible"
            " (supported: {supported}; schemas: {schemas})"
        ),
        (
            "Wtyczka {producer}: zainstalowana wersja {version} jest niezgodna"
            " (wspierane {supported}; schematy: {schemas})"
        ),
    ),
    "source_error": Text(
        "Plugin {producer}: loading error",
        "Wtyczka {producer}: błąd ładowania",
    ),
    "source_unregistered": Text(
        'Plugin {producer} is not registered, but store "{store}" uses it',
        "Wtyczka {producer} nie jest zarejestrowana, a używa jej magazyn „{store}”",
    ),
    "store_ok": Text(
        'Store "{store}" ({producer}, {kind}): {path}',
        "Magazyn „{store}” ({producer}, {kind}): {path}",
    ),
    "project_dir_ok": Text(
        "Projects directory: {path}",
        "Katalog projektów: {path}",
    ),
    "data_dir_ok": Text(
        "Local data (index, cache, jobs): {path}",
        "Dane lokalne (indeks, pamięć, zadania): {path}",
    ),
    "data_dir_open": Text(
        (
            "Local data {path} is accessible to other accounts on this computer"
            " (permissions {mode}): index, areas, accounts and job logs."
        ),
        (
            "Dane lokalne {path} są dostępne dla innych kont tego komputera"
            " (uprawnienia {mode}): indeks, obszary, konta i dzienniki zadań."
        ),
    ),
    "data_dir_unwritable": Text(
        "No write permission to the local data directory: {path}",
        "Brak prawa zapisu do katalogu danych lokalnych: {path}",
    ),
    "port_ok": Text(
        "Port {port} on 127.0.0.1 is free",
        "Port {port} na 127.0.0.1 jest wolny",
    ),
    "port_busy": Text(
        "Port {port} on 127.0.0.1 is in use (Archiwista may already be running)",
        "Port {port} na 127.0.0.1 jest zajęty (może działać już Archiwista)",
    ),
    "unknown": Text(
        "no data",
        "brak danych",
    ),
}
