"""Polish user-facing messages shared across the command line and server.

``MESSAGES`` holds the general texts and, one line each, the dictionaries of
single features (``archiwista.texts``); a key defined twice stops the import.
"""

from collections.abc import Mapping
from types import MappingProxyType

from archiwista.texts.compare import COMPARE_MESSAGES
from archiwista.texts.layers import LAYER_MESSAGES
from archiwista.texts.owndata import OWN_DATA_MESSAGES
from archiwista.texts.previews import PREVIEW_MESSAGES


def merge_messages(*dictionaries: Mapping[str, str]) -> MappingProxyType[str, str]:
    """Return the texts of all dictionaries as one read-only mapping.

    Raises
    ------
    ValueError
        A key appears in two dictionaries.
    """
    merged: dict[str, str] = {}
    for dictionary in dictionaries:
        twice = merged.keys() & dictionary.keys()
        if twice:
            raise ValueError(f"message keys defined twice: {sorted(twice)}")
        merged.update(dictionary)
    return MappingProxyType(merged)


MESSAGES = merge_messages(
    {
        "cli_description": "Archiwista — przeglądarka lokalnego magazynu danych.",
        "cli_doctor_help": "Sprawdza instalację, wtyczki źródeł, magazyny i port.",
        # Local server, sessions and access protection (step 8).
        "cli_serve_help": (
            "Uruchamia serwer Archiwisty na 127.0.0.1 i otwiera przeglądarkę."
        ),
        "cli_serve_host_help": "adres nasłuchu; bez trybu zespołu tylko 127.0.0.1",
        "cli_serve_port_help": "port (domyślnie z ustawień; 0 — dowolny wolny)",
        "cli_serve_no_browser_help": "nie otwieraj przeglądarki, tylko wypisz adres",
        "cli_serve_access_log_help": (
            "włącz dziennik dostępu (wartości token= są w nim ukryte)"
        ),
        "cli_token_help": (
            "Wystawia jednorazowy adres sesji agenta, ważny 5 min (albo kończy"
            " sesje agentów: --revoke-all)."
        ),
        "cli_token_port_help": "port serwera w adresie (domyślnie z ustawień)",
        "cli_token_json_help": "wypisz JSON jak odpowiedź POST /api/v1/session/tokens",
        "cli_token_revoke_all_help": (
            "zakończ wszystkie sesje agentów i unieważnij niewykorzystane tokeny"
        ),
        "cli_port_invalid": "port musi być liczbą od {minimum} do 65535",
        "serve_host_refused": (
            "Odmowa uruchomienia na adresie {host}: bez trybu zespołu Archiwista"
            " nasłuchuje wyłącznie na {loopback}."
        ),
        "serve_failed": "Nie można uruchomić Archiwisty",
        "serve_port_unavailable": "Nie można nasłuchiwać na {host}:{port}",
        "serve_started": (
            "Archiwista działa. Otwórz w przeglądarce:\n  {url}\n"
            "Adres zawiera jednorazowy token ważny {minutes} min; kolejny wystawia"
            " „archiwista token”. Zatrzymanie: Ctrl+C."
        ),
        "serve_launch_link": "Otwórz Archiwistę",
        "token_failed": "Nie można wystawić tokenu",
        "token_issued": (
            "Jednorazowy adres sesji agenta (etykieta {label}), ważny {minutes} min"
            " (do {time}). Przekaż go agentowi albo otwórz w przeglądarce; sesja"
            " agenta trwa najwyżej {hours} h."
        ),
        "token_revoked": (
            "Sesje agentów zakończone; unieważnione niewykorzystane tokeny agentów:"
            " {count}. Nowa sesja agenta wymaga nowego tokenu („archiwista token”)."
        ),
        "permission_session_tokens": (
            "Sesja agenta nie wystawia tokenów kolejnych sesji; token dla agenta"
            " wystawia właściciel („archiwista token”) albo jego przeglądarka."
        ),
        "api_title_invalid_host": "Niedozwolony adres serwera",
        "api_title_session_required": "Wymagana sesja",
        "api_title_csrf_rejected": "Żądanie odrzucone",
        "api_title_validation_error": "Niepoprawne dane żądania",
        "api_title_not_found": "Nie znaleziono",
        "api_title_permission_denied": "Brak uprawnień",
        "api_title_conflict": "Konflikt",
        "api_title_request_too_large": "Za duże żądanie",
        "api_request_too_large": "Treść żądania przekracza limit {limit}.",
        "api_invalid_host": (
            "Archiwista przyjmuje tylko żądania na adres 127.0.0.1:{port}"
            " albo localhost:{port}."
        ),
        "api_session_required": (
            "Brak ważnej sesji. Otwórz adres wypisany przez „archiwista serve”"
            " albo wystaw nowy poleceniem „archiwista token”."
        ),
        "api_token_rejected": (
            "Token jest nieznany, wygasł albo został już użyty. Wystaw nowy"
            " poleceniem „archiwista token”."
        ),
        "api_session_ended": (
            "Sesja zakończyła się: konto jest wyłączone albo usunięte, albo"
            " właściciel zakończył sesje agentów („archiwista token --revoke-all”)."
            " Otwórz nową sesję."
        ),
        "api_cross_site": "Żądanie wysłane z innej strony zostało odrzucone.",
        "api_origin_missing": (
            "Przeglądarka nie podała nagłówka Origin przy żądaniu zmieniającym stan."
        ),
        "api_csrf_missing": (
            "Brak nagłówka X-Archiwista-CSRF z tokenem CSRF sesji (csrf_token"
            " z odpowiedzi POST /api/v1/session); wymaga go każde żądanie /api."
        ),
        "api_csrf_mismatch": (
            "Nagłówek X-Archiwista-CSRF nie pasuje do tokenu CSRF tej sesji."
        ),
        "api_validation_error": "Niepoprawne dane żądania: {fields}.",
        "api_interface_missing": "Pliki interfejsu nie są zainstalowane.",
        "path_outside_root": (
            "Ścieżka „{path}” wychodzi poza katalog magazynu albo projektu."
        ),
        "source_unavailable": "Źródło danych jest niedostępne.",
        "source_incompatible": "Wersja źródła danych jest niezgodna.",
        "store_unavailable": "Magazyn danych jest niedostępny.",
        # Read API: errors, catalog, map and projects (step 9a).
        "api_title_method_not_allowed": "Niedozwolona metoda",
        "api_title_path_outside_root": "Ścieżka poza magazynem",
        "api_title_store_unavailable": "Magazyn niedostępny",
        "api_title_source_unavailable": "Źródło danych niedostępne",
        "api_title_source_incompatible": "Niezgodne źródło danych",
        "api_title_kartograf_error": "Błąd Kartografa",
        "api_title_imgwtools_error": "Błąd IMGWTools",
        "api_title_producer_error": "Błąd biblioteki producenta",
        "api_title_http_error": "Błąd żądania",
        "api_title_internal_error": "Błąd serwera",
        "api_route_not_found": "Nie ma takiego zasobu.",
        "api_method_not_allowed": "Metoda {method} nie jest dostępna dla {path}.",
        "api_internal_error": (
            "Wewnętrzny błąd serwera; szczegóły są w dzienniku „archiwista serve”."
        ),
        "api_source_problem": "{message}. Naprawa: {fix}",
        "api_store_not_configured": "Nie ma magazynu „{store}” w ustawieniach.",
        "api_store_unknown": "Nie ma magazynu „{store}” w ustawieniach ani w indeksie.",
        "api_slot_unknown": "Indeks nie zna pliku „{slot}” w magazynie „{store}”.",
        "api_version_unknown": (
            "Indeks nie zna wersji „{version}” w magazynie „{store}”."
        ),
        "api_sidecar_missing": (
            "Wersja „{version}” w magazynie „{store}” nie ma czytelnego sidecara."
        ),
        "api_request_unknown": (
            "Indeks nie zna plików zadania producenta „{parent_request}”."
        ),
        "api_area_unknown": "Nie ma obszaru „{area}”.",
        "api_area_and_bbox": (
            "Podaj obszar (area_id) albo prostokąt (bbox), nie oba naraz."
        ),
        "api_bbox_invalid": "bbox to cztery liczby: min_x,min_y,max_x,max_y.",
        "api_years_invalid": (
            "years to rok albo zakres lat: 2023, 2020-2023, 2020- albo -2023."
        ),
        "api_no_geo_source": (
            "Żadne dostępne źródło danych nie przelicza współrzędnych obszaru."
        ),
        "api_too_many_sheets": (
            "Widok obejmuje około {count} arkuszy w skali {scale}, a najwyżej"
            " {limit} — przybliż mapę albo wybierz mniej szczegółową skalę."
        ),
        "api_project_store_unavailable": (
            "Magazyn „{store}” projektu „{project}” jest niedostępny, a żaden skan"
            " nie sprawdził jeszcze projektu."
        ),
        # Areas and local coverage (step 9c).
        "api_title_area_too_large": "Za duży plik obszaru",
        "api_title_area_unreadable": "Nie można odczytać obszaru",
        "api_title_area_too_complex": "Zbyt złożony obszar",
        "area_body_too_large": (
            "Treść żądania ma ponad {limit_mb} MB, a tyle najwyżej może mieć"
            " obszar albo jego plik."
        ),
        "area_archive_too_large": (
            "Archiwum po rozpakowaniu miałoby {size_mb} MB, a najwyżej {limit_mb} MB"
            " — odrzucone przed rozpakowaniem."
        ),
        "area_format_unknown": (
            "Nieznany format pliku obszaru. Wczytaj GeoJSON, GeoPackage albo"
            " Shapefile spakowany do ZIP (pliki .shp, .shx, .dbf i .prj)."
        ),
        "area_archive_broken": "Nie można odczytać archiwum ZIP: {detail}",
        "area_archive_unsafe": (
            "Archiwum zawiera człon „{member}” wychodzący poza swój katalog"
            " — odrzucone przed rozpakowaniem."
        ),
        "area_archive_link": (
            "Archiwum zawiera dowiązanie symboliczne „{member}” — odrzucone przed"
            " rozpakowaniem."
        ),
        "area_archive_encrypted": "Archiwum zawiera zaszyfrowany człon „{member}”.",
        "area_archive_duplicate": "Archiwum zawiera dwa razy człon „{member}”.",
        "area_archive_members": "Archiwum ma {count} członów, a najwyżej {limit}.",
        "area_shapefile_missing": "Archiwum nie zawiera pliku .shp.",
        "area_shapefile_parts": (
            "Shapefile „{layer}” w archiwum nie ma plików {parts} (potrzebne są"
            " .shp, .shx, .dbf i .prj)."
        ),
        "area_layers_many": (
            "Plik ma kilka warstw z geometrią ({names}) — wybierz jedną"
            " (parametr layer)."
        ),
        "area_layer_unknown": (
            "Plik nie ma warstwy „{layer}” z geometrią (są: {names})."
        ),
        "area_layers_none": "Plik nie ma żadnej warstwy z geometrią.",
        "area_crs_missing": (
            "Plik nie podaje układu współrzędnych (np. brak pliku .prj), więc nie"
            " wiadomo, gdzie leży obszar."
        ),
        "area_crs_not_named": (
            "Plik GeoJSON podaje układ współrzędnych inaczej niż nazwą (np. jako"
            " odnośnik „link” lub „url”), a Archiwista nie pobiera definicji"
            " układów z sieci. Podaj układ nazwą (człon crs typu „name”, np."
            " EPSG:2180) albo zapisz plik w WGS84 (bez członu crs)."
        ),
        "area_no_polygon": (
            "Plik nie zawiera wielokątów, a obszar musi mieć powierzchnię."
        ),
        "area_not_polygonal": (
            "Plik zawiera geometrie inne niż wielokąty ({types}), a obszar może"
            " składać się tylko z wielokątów."
        ),
        "area_read_failed": "Nie można odczytać pliku obszaru: {detail}",
        "area_read_timeout": (
            "Odczyt pliku obszaru trwał ponad {seconds} s i został przerwany."
        ),
        "area_reader_crashed": (
            "Proces odczytu pliku obszaru zakończył się bez odpowiedzi (kod"
            " wyjścia {code})."
        ),
        "area_too_many_vertices": (
            "Obszar ma {vertices} wierzchołków, a najwyżej {limit}. Uprość go"
            " w programie GIS — Archiwista nie upraszcza geometrii."
        ),
        "area_too_long": (
            "Krawędzie obszaru mają łącznie {length}°, a najwyżej {limit}° — obszar"
            " jest zbyt rozległy, żeby go zmierzyć."
        ),
        "area_empty": "Obszar nie ma powierzchni.",
        "local_coverage_percent": "lokalnie {percent}% obszaru",
        "local_coverage_below_one": "lokalnie <1% obszaru",
        "local_coverage_no_planar_crs": (
            "lokalnie bez procentu: kraj bez układu płaskiego"
        ),
        "local_coverage_empty_area": "lokalnie bez procentu: obszar bez powierzchni",
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
        "settings_basemap_vector": (
            "podkład wektorowy wskazuje adres TileJSON, bez {z}, {x} i {y}"
        ),
        "settings_default_visibility": "dozwolone wartości: public, private",
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
        "doctor_data_dir_open": (
            "Dane lokalne {path} są dostępne dla innych kont tego komputera"
            " (uprawnienia {mode}): indeks, obszary, konta i dzienniki zadań."
        ),
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
        "fix_data_dir_open": (
            "uruchom „archiwista serve” (zamyka katalog do 0700) albo: chmod 700 {path}"
        ),
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
        # Store scans and view refreshes (step 6a).
        "scan_store_empty": (
            "Magazyn {path} jest pusty, a indeks zawiera jego pliki — udział może"
            " być niepodłączony; indeks pozostaje bez zmian"
        ),
        "scan_footprints_failed": (
            "Plików bez wyznaczonego obrysu: {count} — ponowna próba przy"
            " następnym skanie. Komunikat producenta: {detail}"
        ),
        "index_outline_not_finite": (
            "Przeliczenie obrysu z układu {crs} do WGS84 nie dało skończonych"
            " współrzędnych"
        ),
        "refresh_view_timeout": (
            "Odświeżenie widoku przekroczyło {seconds} s — wynik pochodzi z indeksu"
        ),
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
        # Permission model: accounts, groups, project access (step 8b).
        "permission_project_view": "Brak dostępu do tego projektu.",
        "permission_project_share": (
            "Udostępnienie projektu zmienia tylko jego właściciel albo administrator."
        ),
        "permission_users_manage": "Zarządzanie kontami wymaga roli administratora.",
        "permission_groups_manage": "Zarządzanie grupami wymaga roli administratora.",
        "permission_settings_write": "Zmiana ustawień wymaga roli administratora.",
        "permission_store_write": (
            "Zapis do magazynu wymaga uprawnienia „zapis do magazynu”"
            " (rola store_writer)."
        ),
        "project_not_found": "Nie ma projektu „{project}”.",
        "state_newer": (
            "Baza stanu {path} pochodzi z nowszej wersji Archiwisty (schemat"
            " {version}, ta wersja zna {supported}); zainstaluj nowszą wersję"
            " Archiwisty. Baza pozostaje bez zmian."
        ),
        "state_migration_broken": (
            "Migracja bazy stanu {path} zerwałaby powiązania między tabelami;"
            " baza pozostaje bez zmian."
        ),
        "state_id_pattern": (
            "Niepoprawny identyfikator „{id}”: małe litery, cyfry, „.”, „_” i „-”,"
            " najwyżej 64 znaki, na początku litera albo cyfra."
        ),
        "state_user_id_reserved": (
            "Identyfikator „{id}” jest zarezerwowany dla właściciela lokalnej"
            " instalacji."
        ),
        "state_name_invalid": (
            "Nazwa nie może być pusta ani dłuższa niż {limit} znaków."
        ),
        "state_roles_unknown": "Nieznane role: {roles}. Dostępne: admin, store_writer.",
        "state_visibility_unknown": (
            "Nieznana widoczność „{visibility}”. Dostępne: public, users, group,"
            " private."
        ),
        "state_entries_users": (
            "Widoczność „users” wymaga listy osób (co najmniej jednej) i nie"
            " przyjmuje grup."
        ),
        "state_entries_group": (
            "Widoczność „group” wymaga listy grup (co najmniej jednej) i nie"
            " przyjmuje osób."
        ),
        "state_entries_none": (
            "Widoczność „{visibility}” nie przyjmuje listy osób ani grup."
        ),
        "state_user_exists": "Konto „{id}” już istnieje.",
        "state_group_exists": "Grupa „{id}” już istnieje.",
        "state_user_not_found": "Nie ma konta „{id}”.",
        "state_group_not_found": "Nie ma grupy „{id}”.",
        "state_users_unknown": "Nieznane konta: {ids}.",
        "state_groups_unknown": "Nieznane grupy: {ids}.",
        "state_import_not_empty": (
            "Baza stanu {path} nie jest pusta: kopię można odtworzyć tylko do"
            " pustej bazy (bez kont, grup, wpisów projektów i dziennika)."
        ),
        "state_import_inconsistent": "Kopia bazy stanu jest niespójna: {detail}",
        "state_import_not_json": "Plik nie jest poprawnym JSON: {detail}",
        "state_import_schema": (
            "Plik nie jest kopią bazy stanu {expected} (schemat: {found})."
        ),
        "state_import_invalid": "Kopia bazy stanu ma niepoprawne pola: {fields}.",
        "role_admin": "administrator",
        "role_store_writer": "zapis do magazynu",
        "visibility_public": "publiczny (wszyscy)",
        "visibility_users": "wybrane osoby",
        "visibility_group": "członkowie wybranych grup",
        "visibility_private": "prywatny (tylko właściciel)",
        "cli_users_help": "Konta osób i ich role (tylko administrator).",
        "cli_users_list_help": "Wypisuje konta z rolami i grupami.",
        "cli_users_add_help": "Zakłada konto (w v0.1 bez hasła i logowania).",
        "cli_users_roles_help": "Ustawia role konta (bez ról — zwykły użytkownik).",
        "cli_users_remove_help": (
            "Usuwa konto z grup i list udostępnienia, a potem samo konto."
        ),
        "cli_user_id_help": "identyfikator konta, np. anna.nowak",
        "cli_name_help": "nazwa wyświetlana (domyślnie identyfikator)",
        "cli_role_help": (
            "rola: admin (administrator) albo store_writer (zapis do magazynu)"
        ),
        "cli_groups_help": "Grupy osób, np. działy (tylko administrator).",
        "cli_groups_list_help": "Wypisuje grupy z członkami.",
        "cli_groups_add_help": "Zakłada grupę.",
        "cli_groups_members_help": (
            "Ustawia członków grupy (zastępuje dotychczasowych)."
        ),
        "cli_groups_remove_help": "Usuwa grupę i wpisy projektów, które ją wskazują.",
        "cli_group_id_help": "identyfikator grupy, np. hydro",
        "cli_member_help": "identyfikator konta członka",
        "cli_share_help": (
            "Pokazuje albo ustawia, kto widzi projekt (właściciel projektu"
            " albo administrator)."
        ),
        "cli_project_help": "identyfikator projektu, jak w /api/v1/projects/{id}",
        "cli_visibility_help": (
            "public — wszyscy, users — wybrane osoby (--user), group — członkowie"
            " grup (--group), private — tylko właściciel; bez tej opcji polecenie"
            " tylko pokazuje udostępnienie"
        ),
        "cli_share_user_help": "osoba, która widzi projekt (z --visibility users)",
        "cli_share_group_help": (
            "grupa, której członkowie widzą projekt (z --visibility group)"
        ),
        "cli_owner_help": "nowy właściciel projektu (identyfikator konta)",
        "cli_share_needs_visibility": (
            "Podaj --visibility, aby zmienić udostępnienie projektu."
        ),
        "cli_json_help": "wypisz JSON jak odpowiedź API",
        "cli_state_help": (
            "Kopia zapasowa bazy stanu (konta, grupy, udostępnienia, dziennik)."
        ),
        "cli_state_export_help": "Zapisuje bazę stanu jako JSON archiwista-state/1.",
        "cli_state_output_help": "plik kopii (domyślnie standardowe wyjście)",
        "cli_state_import_help": "Odtwarza bazę stanu z kopii — tylko do pustej bazy.",
        "cli_state_file_help": "plik zapisany przez „archiwista state export”",
        "cli_state_exported": "Zapisano kopię bazy stanu: {path}",
        "cli_state_imported": (
            "Odtworzono bazę stanu: konta {users}, grupy {groups}, projekty"
            " {projects}, wpisy dziennika {changes}."
        ),
        "cli_state_unreadable": "Nie można odczytać pliku {path}: {detail}",
        "cli_admin_failed": "Nie można wykonać polecenia",
        "cli_no_users": "Brak kont.",
        "cli_no_groups": "Brak grup.",
        "cli_user_line": "{id} — {name}; role: {roles}; grupy: {groups}",
        "cli_user_disabled": " (wyłączone)",
        "cli_group_line": "{id} — {name}; członkowie: {members}",
        "cli_user_removed": "Usunięto konto „{id}”.",
        "cli_group_removed": "Usunięto grupę „{id}”.",
        "cli_access_line": (
            "Projekt „{project}”: {visibility}{entries}; właściciel: {owner}"
        ),
        "cli_access_default": " (widoczność domyślna — projekt nie ma własnego wpisu)",
        "cli_none": "brak",
        # Read commands of the index for people, scripts and agents (step 12).
        "cli_status_help": (
            "Stan Archiwisty: wersje, źródła danych, indeks i magazyny"
            " (jak GET /api/v1/health)."
        ),
        "cli_sources_help": (
            "Wtyczki producentów danych i ich stan (jak GET /api/v1/sources)."
        ),
        "cli_search_help": (
            "Wyszukuje i filtruje katalog plików (jak GET /api/v1/slots, opcje"
            " o tych samych nazwach); kolejna strona: --cursor."
        ),
        "cli_entry_help": (
            "Karta pliku: wszystkie wersje, bieżąca, pełny arkusz, przypięcia"
            " i problemy (jak GET /api/v1/stores/{store}/slots/{slot})."
        ),
        "cli_version_help": (
            "Karta jednej wersji: wartości z indeksu, surowy sidecar i ścieżka"
            " (jak GET /api/v1/stores/{store}/versions/{version})."
        ),
        "cli_projects_help": "Projekty, które widzisz (jak GET /api/v1/projects).",
        "cli_project_card_help": (
            "Karta projektu: zadania, przypięcia i problemy"
            " (jak GET /api/v1/projects/{project})."
        ),
        "cli_store_id_help": "identyfikator magazynu z ustawień, np. zespol",
        "cli_slot_help": "ścieżka slotu w magazynie, jak pole slot wyników search",
        "cli_version_path_help": "ścieżka wersji, jak pole version.path",
        "cli_projects_store_help": "tylko projekty tego magazynu",
        "cli_search_q_help": (
            "szukany tekst; pasować musi każde słowo: godło, TERYT, KU, nazwa"
            " pliku, produkt, etykieta wersji, kampania, początek SHA-256"
        ),
        "cli_search_store_help": "identyfikator magazynu",
        "cli_search_product_help": "produkt, np. nmt",
        "cli_search_country_help": "kod kraju, np. PL",
        "cli_search_years_help": "rok danych: 2023, 2020-2023, 2020- albo -2023",
        "cli_search_unit_help": "dokładny kod jednostki: godło arkusza, TERYT albo KU",
        "cli_search_versions_help": (
            "wiersze: current (bieżące, domyślnie), all, full_sheet, pinned"
            " albo noncurrent_unpinned"
        ),
        "cli_search_status_help": (
            "stan wiersza: ok, missing, no_sidecar, unreadable albo unrecognized"
        ),
        "cli_search_project_help": (
            "tylko wersje przypięte w tym projekcie (klucz z archiwista projects)"
        ),
        "cli_search_location_help": (
            "położenie: any (domyślnie), with (obrys albo cały kraj) albo none"
            " (bez położenia)"
        ),
        "cli_search_area_id_help": "obszar zapisany przez POST /api/v1/areas",
        "cli_search_bbox_help": (
            "prostokąt min_x,min_y,max_x,max_y w układzie z --bbox-crs"
        ),
        "cli_search_bbox_crs_help": (
            "układ współrzędnych --bbox, np. EPSG:2180 (domyślnie EPSG:4326)"
        ),
        "cli_search_limit_help": "liczba wierszy na stronie: 1–200 (domyślnie 50)",
        "cli_search_cursor_help": (
            "next_cursor poprzedniej strony tego samego zapytania"
        ),
        "cli_read_failed": "Nie można odczytać indeksu",
        "cli_status_line": "Archiwista {version}; indeks: schemat {schema}, {size}.",
        "cli_source_line": "Źródło {producer} ({version}): {message}",
        "cli_store_line": (
            "Magazyn „{store}” ({name}): {status}; sloty {slots}, wersje"
            " {versions}, brakujące {missing}, problemy {issues}; indeks z"
            " {indexed_at}; ostatni pełny skan: {full_scan_at}."
        ),
        "cli_store_job": " Zadanie: {kind}, {state}.",
        "cli_store_status_unknown": "jeszcze nie zeskanowany",
        "cli_store_status_available": "dostępny",
        "cli_store_status_unavailable": "niedostępny",
        "cli_stale_line": (
            "Uwaga: magazyn „{store}” jest niedostępny — odpowiedź według"
            " indeksu z {indexed_at}."
        ),
        "cli_never": "nigdy",
        "cli_search_row": "{store}  {slot}  (wersja {label}, rok danych {year})",
        "cli_search_summary": (
            "Wierszy: {count}. Położenie w całym wyniku — obrys: {footprint},"
            " kraj: {country}, brak: {none}."
        ),
        "cli_search_next": "Następna strona: --cursor {cursor}",
        "cli_no_rows": "Brak wyników.",
        "cli_entry_title": "{store}/{slot} — {name}",
        "cli_entry_facts": (
            "Segment: {segment}; jednostka: {unit}; produkt: {product}; kraj:"
            " {country}; stan: {status}."
        ),
        "cli_version_line": "  {path} — {label}, rok danych {year}{marks}",
        "cli_version_current": ", bieżąca",
        "cli_version_full_sheet": ", pełny arkusz",
        "cli_version_missing": ", brak pliku",
        "cli_version_pinned": "; przypięta w: {projects}",
        "cli_version_title": "{store}/{path} (slot {slot})",
        "cli_version_facts": (
            "Etykieta: {label}; rok danych: {year}; rozmiar: {size}; układ:"
            " {crs}; SHA-256: {sha256}."
        ),
        "cli_version_license": "Licencja: {license}; atrybucja: {attribution}.",
        "cli_path_line": "Ścieżka: {path}",
        "cli_problem_line": "Problem: {message} {instruction}",
        "cli_project_line": (
            "{project} — {name}; magazyn: {store}; zadania {tasks}, przypięcia"
            " {pins}, brakujące {missing}."
        ),
        "cli_no_projects": "Brak widocznych projektów.",
        "cli_task_line": "  zadanie {task}: {command}; stan: {status}",
        "cli_pin_line": "  przypięcie {version} (zadanie {task}): {state}",
        # Background jobs, their scheduler and ``archiwista reindex`` (step 6b).
        "job_kind_scan": "skan",
        "job_kind_footprints": "obrysy jednostek",
        "job_kind_link_check": "potwierdzenie dowiązania",
        "job_state_queued": "w kolejce",
        "job_state_running": "trwa",
        "job_state_succeeded": "zakończone",
        "job_state_failed": "błąd",
        "job_state_interrupted": "przerwane",
        "job_state_cancelled": "anulowane",
        "job_store_unknown": "Magazyn „{store}” nie jest skonfigurowany.",
        "job_not_found": "Nie ma zadania „{job}”.",
        "job_conflict": (
            "Magazyn „{store}” ma już zadanie zapisujące indeks: {kind}, {state}"
            " (zadanie {job}). Poczekaj na jego koniec."
        ),
        "job_offline_mode": (
            "Tryb offline jest włączony: obrysy jednostek wymagają sieci, więc"
            " zadanie nie zostało uruchomione."
        ),
        "job_cancelled": "Zadanie anulowano.",
        "job_interrupted_stop": (
            "Archiwistę zatrzymano w trakcie zadania. Można je bezpiecznie ponowić."
        ),
        "job_interrupted_restart": (
            "Proces nadzorujący zadanie zakończył się w trakcie (zatrzymanie albo"
            " awaria). Można je bezpiecznie ponowić."
        ),
        "job_interrupted_signal": (
            "Proces roboczy zadania przerwano z zewnątrz. Można je bezpiecznie ponowić."
        ),
        "job_worker_crashed": (
            "Proces roboczy zadania zakończył się nieoczekiwanie ({status});"
            " szczegóły w dzienniku {log}."
        ),
        "job_status_signal": "sygnał {signal}",
        "job_status_code": "kod wyjścia {code}",
        "job_worker_not_started": "Nie można uruchomić procesu roboczego: {detail}",
        "job_internal_error": (
            "Błąd wewnętrzny Archiwisty ({detail}); szczegóły w dzienniku zadania."
        ),
        "job_footprints_failed": (
            "Plików bez wyznaczonego obrysu jednostki: {count} — spróbuj ponownie"
            " później. Komunikat producenta: {detail}"
        ),
        "job_slot_not_found": "Slotu „{slot}” magazynu „{store}” nie ma w indeksie.",
        "job_link_check_unsupported": "Źródło {producer} nie potwierdza dowiązań.",
        "job_link_mismatch": "{problem}. {fix}",
        "job_link_index_outdated": (
            "Dowiązanie {slot} zawiera wersję {version}, a indeks wskazuje inną —"
            " odśwież magazyn."
        ),
        # Background jobs over HTTP and their event streams (step 9b).
        "api_title_offline_mode": "Tryb offline",
        "cli_reindex_help": (
            "Przebudowuje indeks: pełny skan magazynu (bez --store — wszystkich)"
            " jako zadanie, wykonywane na pierwszym planie."
        ),
        "cli_reindex_store_help": "identyfikator magazynu z ustawień",
        "reindex_failed": "Nie można przebudować indeksu",
        "reindex_no_stores": (
            "Nie skonfigurowano żadnego magazynu — dodaj go w kreatorze po"
            " uruchomieniu „archiwista serve”."
        ),
        "reindex_started": "Magazyn „{store}”: pełny skan, zadanie {job}.",
        "reindex_progress": (
            "Magazyn „{store}”: segmenty {current} z {total}, wpisy {entries}."
        ),
        "reindex_notice": "Magazyn „{store}”: {message}",
        "reindex_cancelling": "Przerywanie zadania {job}…",
        "reindex_succeeded": (
            "Magazyn „{store}”: pełny skan zakończony w {seconds} s — wpisy"
            " {entries}, zapisane wersje {versions}, nowe braki {missing},"
            " usunięte {removed}."
        ),
        "reindex_job_failed": "Magazyn „{store}”: zadanie {job} — {state}: {detail}",
        "reindex_error": "{message} (kod {code})",
    },
    PREVIEW_MESSAGES,
    OWN_DATA_MESSAGES,
    COMPARE_MESSAGES,
    LAYER_MESSAGES,
)


_SENTENCE_ENDS = (".", "!", "?", "…")


def with_detail(message: str, detail: str | None) -> str:
    """Append a producer's or system's own detail text to a Polish message.

    The detail follows a colon. A message that is a whole sentence (a
    preview's reason) stays one: its full stop moves after the detail —
    ``Nie można odczytać pliku: <detail>.``, never ``….: …``.
    """
    if not detail:
        return message
    if not message.endswith("."):
        return MESSAGES["with_detail"].format(message=message, detail=detail)
    sentence = MESSAGES["with_detail"].format(message=message[:-1], detail=detail)
    return sentence if sentence.endswith(_SENTENCE_ENDS) else f"{sentence}."
