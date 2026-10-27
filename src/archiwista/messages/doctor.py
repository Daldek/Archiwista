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
    "setting_retired": Text(
        (
            "Configuration {path} holds {key}, which Archiwista no longer reads:"
            " it is ignored"
        ),
        (
            "Konfiguracja {path} zawiera {key}, którego Archiwista już nie czyta:"
            " jest pomijane"
        ),
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
    "default_root": Text(
        "Plugin {producer}: default store root {path} ({origin}; {state})",
        (
            "Wtyczka {producer}: domyślny katalog główny magazynu {path}"
            " ({origin}; {state})"
        ),
    ),
    "default_root_default": Text(
        "under the data directory",
        "w katalogu danych",
    ),
    "default_root_env": Text(
        "variable {name}",
        "zmienna {name}",
    ),
    "default_root_dotenv": Text(
        "variable {name} in a .env file",
        "zmienna {name} w pliku .env",
    ),
    "default_root_file": Text(
        "{name} of nogat.toml",
        "{name} w pliku nogat.toml",
    ),
    "default_root_absent": Text(
        "does not exist",
        "nie istnieje",
    ),
    "default_root_unmarked": Text(
        "exists, without a store marker",
        "istnieje, bez znacznika magazynu",
    ),
    "default_root_marked": Text(
        "a store with its marker",
        "magazyn ze znacznikiem",
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
    "team_origin": Text(
        "Team mode: people open {origin}",
        "Tryb zespołu: ludzie otwierają {origin}",
    ),
    "team_tls": Text(
        "Team mode: TLS in the server, certificate {cert} and key {key} load as a pair",
        (
            "Tryb zespołu: TLS w serwerze, certyfikat {cert} i klucz {key} wczytują"
            " się jako para"
        ),
    ),
    "team_key_open": Text(
        (
            "The TLS key {path} is accessible to other accounts on this computer"
            " (permissions {mode})"
        ),
        (
            "Klucz TLS {path} jest dostępny dla innych kont tego komputera"
            " (uprawnienia {mode})"
        ),
    ),
    "team_proxies": Text(
        "Team mode: trusted reverse proxies {proxies}",
        "Tryb zespołu: zaufane serwery pośredniczące {proxies}",
    ),
    "team_admins": Text(
        "Team mode: administrators who can sign in: {ids}",
        "Tryb zespołu: administratorzy, którzy mogą się zalogować: {ids}",
    ),
    "state_outdated": Text(
        (
            "The state database {path} is from an older Archiwista: the server's"
            " next start brings it up to date; check the administrators after that"
        ),
        (
            "Baza stanu {path} pochodzi ze starszej Archiwisty: następne"
            " uruchomienie serwera ją uaktualni; potem sprawdź administratorów"
        ),
    ),
    "state_unreadable": Text(
        "Cannot read the state database {path}",
        "Nie można odczytać bazy stanu {path}",
    ),
}
