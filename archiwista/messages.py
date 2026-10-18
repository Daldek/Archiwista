"""Polish user-facing messages shared across the command line and server."""

from types import MappingProxyType

MESSAGES = MappingProxyType(
    {
        "cli_description": "Archiwista — przeglądarka lokalnego magazynu danych.",
        "cli_doctor_help": "Sprawdza instalację, wtyczki źródeł, magazyny i port.",
        "source_unavailable": "Źródło danych jest niedostępne.",
        "source_incompatible": "Wersja źródła danych jest niezgodna.",
        "store_unavailable": "Magazyn danych jest niedostępny.",
        # Producer plugins and their adapters.
        "source_unavailable_producer": "Źródło danych {producer} jest niedostępne",
        "source_incompatible_producer": (
            "Źródło danych {producer} jest niezgodne: zainstalowana wersja"
            " {version}, wspierane {supported}"
        ),
        "plugin_unregistered": "brak wtyczki tego producenta",
        "plugin_duplicate": "wtyczka zarejestrowana więcej niż raz: {values}",
        "plugin_module_missing": "brak modułu {module}",
        "plugin_package_missing": "brak pakietu {package}",
        "plugin_not_adapter": "fabryka wtyczki nie zwróciła adaptera źródła",
        "plugin_wrong_producer": "adapter wtyczki deklaruje producenta „{declared}”",
        "plugin_range_missing": (
            "Archiwista nie deklaruje wspieranych wersji pakietu {package}"
        ),
        "store_unreadable": "Nie można odczytać magazynu {path}",
        "kartograf_not_store": (
            "żaden katalog nie jest segmentem Kartografa — wskaż katalog --output"
            " (data/)"
        ),
        # Settings validation (code-specific messages).
        "settings_invalid_toml": (
            "Plik konfiguracji {path} nie jest poprawnym TOML: {detail}"
        ),
        "settings_invalid_value": "Niepoprawne ustawienie „{field}”: {detail}",
        "settings_missing": "brak wymaganej wartości",
        "settings_unknown_key": "nieznane ustawienie",
        "settings_not_integer": "oczekiwano liczby całkowitej",
        "settings_not_boolean": "oczekiwano wartości true albo false",
        "settings_not_text": "oczekiwano tekstu",
        "settings_not_list": "oczekiwano listy",
        "settings_too_small": "wartość mniejsza niż {limit}",
        "settings_too_large": "wartość większa niż {limit}",
        "settings_bad_value": "niepoprawna wartość",
        "settings_path_not_absolute": "ścieżka musi być bezwzględna",
        "settings_store_id_pattern": (
            "identyfikator: małe litery, cyfry, „-” i „_”, najwyżej 32 znaki"
        ),
        "settings_empty_text": "wartość nie może być pusta",
        "settings_duplicate_store": "identyfikator magazynu „{value}” powtarza się",
        "settings_duplicate_basemap": "nazwa podkładu „{value}” powtarza się",
        "settings_basemap_url": "adres podkładu musi zaczynać się od http:// albo https://",
        "settings_basemap_xyz": "adres kafli musi zawierać {z}, {x} i {y}",
        "root_missing": (
            "Katalog {producer} magazynu „{store}” nie istnieje"
            " albo udział nie jest podłączony: {path}"
        ),
        "root_not_directory": (
            "Ścieżka {producer} magazynu „{store}” nie jest katalogiem: {path}"
        ),
        "root_unreadable": (
            "Brak uprawnień do odczytu katalogu {producer} magazynu „{store}”: {path}"
        ),
        "root_nested": (
            "Katalog {path} leży wewnątrz katalogu {other}"
            " — katalogi producentów nie mogą być zagnieżdżone"
        ),
        "root_source": (
            "Katalog {producer} magazynu „{store}” nie jest zgodnym magazynem"
            " ({status})"
        ),
        "source_status_not_installed": "pakiet producenta nie jest zainstalowany",
        "source_status_incompatible": "niezgodna wersja albo schemat",
        "source_status_error": "błąd wtyczki",
        "with_detail": "{message}: {detail}",
        "project_dir_missing": "Katalog projektów nie istnieje: {path}",
        "project_dir_not_directory": (
            "Ścieżka katalogu projektów nie jest katalogiem: {path}"
        ),
        "project_dir_unreadable": (
            "Brak uprawnień do odczytu katalogu projektów: {path}"
        ),
        # Doctor report.
        "doctor_title": "Archiwista — diagnostyka",
        "doctor_level_ok": "OK",
        "doctor_level_warning": "UWAGA",
        "doctor_level_error": "BŁĄD",
        "doctor_fix": "Naprawa: {fix}",
        "doctor_summary": "Wynik: błędy {errors}, ostrzeżenia {warnings}.",
        "doctor_config_ok": "Konfiguracja: {path}",
        "doctor_config_absent": (
            "Brak pliku konfiguracji {path} — Archiwista działa na ustawieniach"
            " domyślnych"
        ),
        "doctor_no_stores": "Nie skonfigurowano żadnego magazynu",
        "doctor_source_available": (
            "Wtyczka {producer}: wersja {version} (wspierane {supported};"
            " schematy: {schemas})"
        ),
        "doctor_source_not_installed": (
            "Wtyczka {producer}: pakiet producenta nie jest zainstalowany"
        ),
        "doctor_source_incompatible": (
            "Wtyczka {producer}: zainstalowana wersja {version} jest niezgodna"
            " (wspierane {supported}; schematy: {schemas})"
        ),
        "doctor_source_error": "Wtyczka {producer}: błąd ładowania",
        "doctor_source_unregistered": (
            "Wtyczka {producer} nie jest zarejestrowana, a używa jej magazyn „{store}”"
        ),
        "doctor_store_ok": "Magazyn „{store}” ({producer}, {kind}): {path}",
        "doctor_project_dir_ok": "Katalog projektów: {path}",
        "doctor_data_dir_ok": "Dane lokalne (indeks, pamięć, zadania): {path}",
        "doctor_data_dir_unwritable": (
            "Brak prawa zapisu do katalogu danych lokalnych: {path}"
        ),
        "doctor_port_ok": "Port {port} na 127.0.0.1 jest wolny",
        "doctor_port_busy": (
            "Port {port} na 127.0.0.1 jest zajęty (może działać już Archiwista)"
        ),
        "doctor_unknown": "brak danych",
        "fix_config": (
            "popraw plik konfiguracji {path} albo usuń go i skonfiguruj ponownie."
        ),
        "fix_wizard": "dodaj magazyn w kreatorze po uruchomieniu „archiwista serve”.",
        "fix_install": 'zainstaluj zgodną wersję: pip install "{requirement}"',
        "fix_plugin_error": (
            "zainstaluj ponownie pakiet źródła {producer}; jeśli błąd się powtarza,"
            " zgłoś go razem z treścią powyżej."
        ),
        "fix_reconnect": "podłącz udział albo popraw ścieżkę magazynu w ustawieniach.",
        "fix_not_directory": "wskaż w ustawieniach katalog, a nie plik.",
        "fix_permissions": (
            "nadaj użytkownikowi uruchamiającemu Archiwistę prawo odczytu"
            " i wejścia do katalogu."
        ),
        "fix_nested": "wskaż katalogi producentów, z których żaden nie leży w drugim.",
        "fix_source": (
            "sprawdź, czy wskazano katalog --output producenta i czy jego wersja"
            " jest zgodna."
        ),
        "fix_project_dir": "podłącz katalog albo usuń go z ustawień.",
        "fix_data_dir": "nadaj prawo zapisu do katalogu danych lokalnych.",
        "fix_port": "zmień port w ustawieniach albo zatrzymaj program, który go używa.",
        "store_kind_local": "dysk lokalny",
        "store_kind_share": "udział sieciowy",
        # Local index queries (422 validation_error).
        "index_invalid_cursor": (
            "Kursor nie pasuje do tego zapytania — pobierz listę od pierwszej strony."
        ),
        "index_invalid_limit": "Limit musi być liczbą od 1 do {limit}.",
        "index_invalid_years": "Zakres lat jest odwrócony: od {start} do {end}.",
        "index_invalid_area": (
            "Obszar musi być wielokątem GeoJSON (Polygon albo MultiPolygon)"
            " we współrzędnych WGS84."
        ),
        "index_invalid_bbox": (
            "Widok mapy musi być prostokątem min_lon, min_lat, max_lon, max_lat"
            " w WGS84."
        ),
        "index_invalid_grid": "Siatka agregacji musi mieć od 1 do {limit} kolumn.",
        # Store and project problems: what is wrong and how to fix it (step 7).
        # Archiwista deletes nothing; the fix is a person's decision.
        "problem_missing_sidecar": "Plik bez sidecara: {path}",
        "fix_missing_sidecar": (
            "Pobierz ten plik ponownie poleceniem {producer} — nowa wersja dostanie"
            " sidecar; pozostałość bez sidecara usuń ręcznie po sprawdzeniu."
        ),
        "problem_invalid_sidecar": "Nieczytelny sidecar pliku: {path}",
        "fix_invalid_sidecar": (
            "Sprawdź plik .meta.json obok danych albo pobierz tę wersję ponownie"
            " poleceniem {producer}."
        ),
        "problem_unknown_segment": (
            "Katalog nierozpoznany przez wtyczkę {producer}: {path}"
        ),
        "fix_unknown_segment": (
            "To zwykle dane z wersji deweloperskiej albo nowszej pakietu"
            " {producer}: zaktualizuj pakiet albo pobierz te dane ponownie"
            " do rozpoznanego produktu."
        ),
        "problem_legacy_campaigns": (
            "Katalog kampanie/ ze starszej wersji pakietu {producer} (0.7.x),"
            " nieczytany: {path}"
        ),
        "fix_legacy_campaigns": (
            "Pobierz te dane ponownie bieżącą wersją pakietu {producer}; stary"
            " katalog usuń ręcznie dopiero po sprawdzeniu."
        ),
        "problem_stale_incoming": (
            "Pozostałość przerwanego pobierania starsza niż 24 h: {path}"
        ),
        "fix_stale_incoming": (
            "Pakiet {producer} usuwa ją przy następnym pobieraniu do tego produktu;"
            " jeśli żadne pobieranie nie trwa, możesz usunąć ten katalog ręcznie."
        ),
        "problem_link_mismatch": (
            "Dowiązanie ma inną treść, niż podaje jego sidecar: {path}"
        ),
        "fix_link_mismatch": (
            "Pobierz plik ponownie poleceniem {producer} z aktualizacją, aby"
            " dowiązanie wskazywało właściwą wersję."
        ),
        "problem_orphan_sidecar": (
            "Sidecar dowiązania wskazuje brakującą wersję {version}: {path}"
        ),
        "fix_orphan_sidecar": (
            "Przywróć brakującą wersję z kopii albo pobierz plik ponownie"
            " poleceniem {producer}."
        ),
        "problem_missing_pin": (
            "Przypięty plik nie istnieje w magazynie: {version} (projekt"
            " „{project}”, zadanie {task})"
        ),
        "fix_missing_pin": (
            "Odtwórz przypięte pliki poleceniem „{producer} project download"
            " {task}” w katalogu projektu „{project}”."
        ),
        "problem_pin_sha256_mismatch": (
            "Przypięta wersja ma w magazynie inną treść (SHA-256): {version}"
            " (projekt „{project}”, zadanie {task})"
        ),
        "fix_pin_sha256_mismatch": (
            "Sprawdź pliki projektu poleceniem „{producer} project verify”"
            " w katalogu projektu „{project}”."
        ),
        "problem_invalid_manifest": "Niepoprawny manifest projektu: {detail}",
        "fix_invalid_manifest": (
            "Popraw manifest w katalogu projektu {path} — komunikat pakietu"
            " {producer} wskazuje miejsce błędu."
        ),
        "problem_unknown_store": "Magazyn projektu nieznany: {store_dir}",
        "fix_unknown_store": (
            "Dodaj magazyn w ustawieniach (katalog {store_dir}) albo popraw"
            " ścieżkę magazynu w manifeście projektu."
        ),
        "problem_other": "Problem magazynu ({code}): {path}",
        "fix_other": "Sprawdź to miejsce narzędziami pakietu {producer}.",
    }
)


def with_detail(message: str, detail: str | None) -> str:
    """Append a producer's or system's own detail text to a Polish message."""
    if not detail:
        return message
    return MESSAGES["with_detail"].format(message=message, detail=detail)
